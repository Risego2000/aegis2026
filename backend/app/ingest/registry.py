"""Async scheduler for every ingestion pipeline.

Each source is an independent asyncio task with its own cadence, its own
exponential backoff and its own health record — one flaky upstream never blocks
the rest of the platform. This is deliberately not a heavyweight queue: at
free-tier scale (thousands of items / 15 min) in-process asyncio + bounded
concurrency is the cheapest correct design.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..config import settings
from ..fence.engine import GeofenceEngine
from ..live import AIRCRAFT, AIR, VESSELS, LiveLayer
from ..livehub import HUB
from ..models import Event, EventRecord
from ..storage.base import Store
from . import adsb, air, ais, cameras, dgt, emsc, eonet, firms, gdacs, gdelt, gtfs, ioda, nws, satellites, trains, usgs
from .client import Fetcher

log = logging.getLogger("aegis.registry")


@dataclass
class Ingestor:
    name: str
    interval: float
    kind: str                      # "events" | "positions" | "internal"
    runner: Callable[[], Awaitable[Any]]
    layer: LiveLayer | None = None
    enabled: bool = True
    # live status
    last_run: float = 0.0
    last_ok: bool = True
    last_message: str = "pendiente"
    last_items: int = 0
    last_duration_ms: int = 0
    runs: int = 0
    failures: int = 0
    task: asyncio.Task | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "interval_s": self.interval,
            "kind": self.kind,
            "last_run": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_run)) if self.last_run else None
            ),
            "ok": self.last_ok,
            # `active` distingue "falla" de "no configurada" (p. ej. FIRMS sin clave)
            "active": self.enabled,
            "message": self.last_message,
            "items": self.last_items,
            "duration_ms": self.last_duration_ms,
            "runs": self.runs,
            "failures": self.failures,
            "next_run_s": max(
                0, round(self.interval - (time.time() - self.last_run), 1)
            ) if self.last_run else 0,
            **self.meta,
        }


class Registry:
    def __init__(self, store: Store, engine: GeofenceEngine, fetcher: Fetcher):
        self.store = store
        self.engine = engine
        self.fetcher = fetcher
        self.ingestors: dict[str, Ingestor] = {}
        self._tasks: list[asyncio.Task] = []
        self._ais_queue: asyncio.Queue | None = None
        # almacén de analista (watchlists/casos/posiciones); lo inyecta main.py
        self.extras = None
        self.started_at = time.time()

    # ------------------------------------------------------------------ #
    def build(self) -> None:
        add = self._register

        if settings.enable_usgs:
            add(Ingestor("usgs", settings.usgs_interval, "events", self._run_usgs,
                         meta={"source": "USGS", "url": "earthquake.usgs.gov",
                               "description": f"Sismos globales M4.5+ ({settings.usgs_feed})"}))
        if settings.enable_gdacs:
            add(Ingestor("gdacs", settings.gdacs_interval, "events", self._run_gdacs,
                         meta={"source": "GDACS", "url": "gdacs.org",
                               "description": "Desastres naturales + polígonos de área"}))
        if settings.enable_gdelt:
            add(Ingestor("gdelt", settings.gdelt_interval, "events", self._run_gdelt,
                         meta={"source": "GDELT 2.0", "url": "gdeltproject.org",
                               "description": "Eventos CAMEO geolocalizados cada 15 min"}))
        if settings.enable_adsb:
            add(Ingestor("adsb", settings.adsb_interval, "positions", self._run_adsb,
                         layer=AIRCRAFT,
                         meta={"source": "adsb.lol", "url": "adsb.lol",
                               "description": "Telemetría ADS-B (12 regiones de vigilancia)"}))
        if settings.enable_adsb:
            add(Ingestor("adsb-mil", 60, "positions", self._run_military,
                         meta={"source": "adsb.fi (mil)", "url": "opendata.adsb.fi/api/v2/mil",
                               "description": "Aeronaves militares y de Estado en todo el mundo"}))
        if settings.enable_ais:
            mode = "aisstream.io" if settings.aisstream_key else (
                "digitraffic.fi" if settings.enable_digitraffic else "deshabilitado"
            )
            add(Ingestor("ais", settings.ais_interval, "positions", self._run_ais,
                         layer=VESSELS, enabled=bool(settings.aisstream_key or settings.enable_digitraffic),
                         meta={"source": "AIS", "url": "aisstream.io",
                               "description": f"Posiciones marítimas ({mode})",
                               "mode": mode}))
        if settings.enable_firms:
            add(Ingestor("firms", settings.firms_interval, "events", self._run_firms,
                         enabled=True,   # los CSV globales de NASA son abiertos: sin clave
                         meta={"source": "NASA FIRMS", "url": "firms.modaps.eosdis.nasa.gov",
                               "description": "Focos térmicos VIIRS/MODIS (CSV globales; MAP_KEY opcional)",
                               "needs_key": False,
                               "key_optional": True,
                               "mode": "area-api" if settings.firms_map_key else "csv-global"}))
        if settings.enable_eonet:
            add(Ingestor("eonet", settings.eonet_interval, "events", self._run_eonet,
                         meta={"source": "NASA EONET", "url": "eonet.gsfc.nasa.gov",
                               "description": "Eventos naturales curados (fuegos, tormentas, volcanes, hielo)"}))
        if settings.enable_emsc:
            add(Ingestor("emsc", settings.emsc_interval, "events", self._run_emsc,
                         meta={"source": "EMSC", "url": "seismicportal.eu",
                               "description": "Sismos M2.5+ en Europa, Mediterráneo y Oriente Medio"}))
        if settings.enable_nws:
            add(Ingestor("nws", settings.nws_interval, "events", self._run_nws,
                         meta={"source": "NOAA / NWS", "url": "api.weather.gov",
                               "description": "Avisos meteorológicos severos activos (EE. UU.)"}))
        if settings.enable_ioda:
            add(Ingestor("ioda", settings.ioda_interval, "events", self._run_ioda,
                         meta={"source": "IODA · Georgia Tech", "url": "ioda.inetintel.cc.gatech.edu",
                               "description": "Cortes de internet medidos (BGP + sondas + telescopio), sin clave"}))
        if settings.enable_cameras:
            add(Ingestor("cameras", settings.cameras_interval, "internal", self._run_cameras,
                         meta={"source": "Cámaras públicas", "url": "tfl.gov.uk · dot.ca.gov · nyctmc.org · digitraffic.fi",
                               "description": "Cámaras de tráfico y meteorológicas abiertas (4 redes, ~5.000)"}))
        if settings.enable_dgt:
            add(Ingestor("dgt", settings.dgt_interval, "events", self._run_dgt,
                         meta={"source": "DGT", "url": "nap.dgt.es (DATEX II)",
                               "description": "Incidencias de tráfico en tiempo real: accidentes, obras, cortes y restricciones"}))
        if settings.enable_trains:
            add(Ingestor("trains", settings.trains_interval, "positions", self._run_trains,
                         meta={"source": "Renfe + FGC + Amtrak",
                               "url": "gtfsrt.renfe.com · dadesobertes.fgc.cat · amtraker.com",
                               "description": "Trenes en vivo: Renfe (Cercanías, AVE, Avlo, Alvia, MD), FGC y Amtrak"}))
        if settings.enable_trains:
            add(Ingestor("renfe-avisos", 600, "events", self._run_renfe_alerts,
                         meta={"source": "Renfe", "url": "gtfsrt.renfe.com/alerts.json",
                               "description": "Avisos e incidencias de servicio de Renfe, geolocalizados por línea"}))
        if settings.enable_air:
            add(Ingestor("air", settings.air_interval, "positions", self._run_air,
                         layer=AIR,
                         meta={"source": "Sensor.Community", "url": "sensor.community",
                               "description": "Calidad del aire PM2.5/PM10 (red ciudadana abierta)"}))
        if settings.enable_satellites:
            add(Ingestor("satellites", settings.sat_interval, "internal", self._run_satellites,
                         meta={"source": "Celestrak + SGP4", "url": "celestrak.org",
                               "description": "Catálogo orbital y propagación SGP4"}))

    def _register(self, ingestor: Ingestor) -> None:
        self.ingestors[ingestor.name] = ingestor

    # ------------------------------------------------------------------ #
    # source runners
    # ------------------------------------------------------------------ #
    async def _run_usgs(self) -> list[EventRecord]:
        return await usgs.fetch(self.fetcher)

    async def _run_gdacs(self) -> list[EventRecord]:
        return await gdacs.fetch(self.fetcher)

    async def _run_gdelt(self) -> list[EventRecord]:
        return await gdelt.fetch(self.fetcher)

    async def _run_eonet(self) -> list[EventRecord]:
        return await eonet.fetch(self.fetcher)

    async def _run_emsc(self) -> list[EventRecord]:
        return await emsc.fetch(self.fetcher)

    async def _run_nws(self) -> list[EventRecord]:
        return await nws.fetch(self.fetcher)

    async def _run_firms(self) -> list[EventRecord]:
        return await firms.fetch(self.fetcher)

    async def _run_adsb(self) -> list[dict]:
        return await adsb.fetch(self.fetcher)

    async def _run_ais(self) -> list[dict]:
        if settings.aisstream_key:
            # positions arrive asynchronously over the websocket consumer
            return []
        return await ais.fetch_digitraffic(self.fetcher)

    async def _run_ioda(self) -> list[EventRecord]:
        return await ioda.fetch(self.fetcher)

    async def _run_cameras(self) -> int:
        return await cameras.refresh(self.fetcher)

    async def _run_dgt(self) -> list[EventRecord]:
        return await dgt.refresh(self.fetcher)

    async def _run_trains(self) -> list[dict]:
        index = getattr(self, "gtfs", None)
        return await trains.refresh(self.fetcher, index=index)

    async def _run_military(self) -> list[dict]:
        from . import adsb

        return await adsb.fetch_military(self.fetcher)

    async def _run_renfe_alerts(self) -> list[EventRecord]:
        index = getattr(self, "gtfs", None)
        if index is not None:
            index.alerts = await gtfs.refresh_alerts(self.fetcher)
            return trains.alerts_to_events(index.alerts, index)
        return []

    async def _run_air(self) -> list[dict]:
        return await air.fetch(self.fetcher)

    async def _run_satellites(self) -> int:
        count = await satellites.refresh_tles(self.fetcher)
        satellites.propagate_all()
        return count

    # ------------------------------------------------------------------ #
    async def _loop(self, ing: Ingestor) -> None:
        delay_boost = 1.0
        while True:
            if not ing.enabled:
                # una fuente inactiva (p. ej. FIRMS sin MAP_KEY) no es una fuente
                # "OK": se reporta como tal para no inflar el recuento de salud
                ing.last_ok = False
                ing.last_run = time.time()
                ing.last_message = ing.meta.get("disabled_reason", "inactiva")
                ing.last_items = 0
                await asyncio.sleep(3600)
                continue
            started = time.perf_counter()
            ok, message, items = True, "", 0
            try:
                result = await ing.runner()
                if ing.kind == "events":
                    records: list[EventRecord] = result or []
                    upsert = await self.store.upsert(records)
                    items = len(records)
                    message = f"{upsert.inserted} nuevos · {upsert.merged} fusionados"
                    await self.engine.evaluate_events([self._shim(r) for r in records
                                                       if r.category in ("earthquake", "disaster", "wildfire")])
                    self._watch(records)
                elif ing.kind == "positions":
                    actors = result or []
                    items = len(actors)
                    if ing.layer:
                        ing.layer.upsert_many(actors)
                        await self.engine.update_positions(ing.layer.name, actors)
                    message = f"{items} objetos"
                else:
                    items = int(result or 0)
                    message = f"{items} elementos"
                delay_boost = 1.0
            except Exception as exc:  # noqa: BLE001
                ok = False
                ing.failures += 1
                message = f"{type(exc).__name__}: {exc}"[:400]
                delay_boost = min(6.0, 1.3 ** min(ing.failures, 8))
                log.warning("[%s] %s", ing.name, message)
            duration = int((time.perf_counter() - started) * 1000)

            ing.last_run = time.time()
            ing.last_ok = ok
            ing.last_message = message
            ing.last_items = items
            ing.last_duration_ms = duration
            ing.runs += 1
            await self.store.record_run(ing.name, ok, items, message, duration)

            await asyncio.sleep(ing.interval * delay_boost + random.uniform(0, 1.5))

    def _watch(self, records: list[EventRecord]) -> None:
        """Contrasta los sucesos recién ingeridos con las reglas del analista."""
        if not records or self.extras is None:
            return
        try:
            from ..extras import watch as watch_mod

            watch_mod.evaluate(records, self.extras, HUB)
        except Exception as exc:  # noqa: BLE001 - una regla rota no tumba la ingesta
            log.warning("watchlists: %s", exc)

    def _shim(self, rec: EventRecord) -> Event:
        """Lightweight Event view so the fence engine can react immediately."""
        return Event(
            id=rec.uid, cluster_id=rec.uid, source=rec.source, sources=[rec.source],
            category=rec.category, subtype=rec.subtype, title=rec.title,
            summary=rec.summary, lat=rec.lat, lon=rec.lon, depth_km=rec.depth_km,
            severity=rec.severity, severity_label=rec.severity_label, country=rec.country,
            iso3=rec.iso3, event_time=rec.event_time.isoformat(), first_seen="", updated_at="",
            url=rec.url, mentions=1, sources_count=1, confidence=0.5,
            payload=rec.payload, geometry=rec.geometry,
        )

    # ------------------------------------------------------------------ #
    async def _ais_consumer(self) -> None:
        """Batch aisstream websocket messages into the live layer + fence engine."""
        assert self._ais_queue is not None
        while True:
            batch: list[dict] = []
            deadline = time.time() + 2.0
            while time.time() < deadline:
                try:
                    timeout = max(0.05, deadline - time.time())
                    batch.append(await asyncio.wait_for(self._ais_queue.get(), timeout))
                except asyncio.TimeoutError:
                    break
            if not batch:
                continue
            VESSELS.upsert_many(batch)
            await self.engine.update_positions("vessels", batch)
            ing = self.ingestors.get("ais")
            if ing:
                ing.last_run = time.time()
                ing.last_items = len(batch)
                ing.last_ok = True
                ing.last_message = f"{len(batch)} posiciones AIS (websocket)"

    async def start(self) -> None:
        self.build()
        for ing in self.ingestors.values():
            ing.task = asyncio.create_task(self._loop(ing), name=f"ingest:{ing.name}")
            self._tasks.append(ing.task)
            await asyncio.sleep(0.15)   # stagger cold starts

        if settings.enable_ais and settings.aisstream_key:
            self._ais_queue = asyncio.Queue(maxsize=5000)
            self._tasks.append(asyncio.create_task(ais.stream_aisstream(self._ais_queue)))
            self._tasks.append(asyncio.create_task(self._ais_consumer()))
        log.info("registry started: %s", ", ".join(self.ingestors))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()

    # ------------------------------------------------------------------ #
    async def trigger(self, name: str) -> dict[str, Any]:
        ing = self.ingestors.get(name)
        if not ing:
            return {"ok": False, "error": f"fuente desconocida: {name}"}
        started = time.perf_counter()
        try:
            result = await ing.runner()
            if ing.kind == "events":
                upsert = await self.store.upsert(result or [])
                items = len(result or [])
                msg = f"{upsert.inserted} nuevos · {upsert.merged} fusionados"
                try:
                    by_uid = {str(rec.uid): rec for rec in (result or [])}
                    fresh = []
                    for event_id in upsert.fresh:
                        rec = by_uid.get(str(event_id))
                        if rec is None:
                            continue
                        fresh.append({
                            "id": event_id, "title": rec.title, "category": rec.category,
                            "lat": rec.lat, "lon": rec.lon,
                            "event_time": rec.event_time.isoformat() if rec.event_time else None,
                        })
                    HUB.push_events(fresh)
                except Exception:  # noqa: BLE001 - el canal en vivo nunca rompe la ingesta
                    pass
                self._watch(result or [])
            elif ing.kind == "positions":
                if ing.layer:
                    ing.layer.upsert_many(result or [])
                    await self.engine.update_positions(ing.layer.name, result or [])
                items, msg = len(result or []), f"{len(result or [])} objetos"
            else:
                items, msg = int(result or 0), "ok"
            ing.last_ok = True
            ing.last_message = msg
            ing.last_items = items
            ing.last_run = time.time()
            return {"ok": True, "items": items, "message": msg,
                    "duration_ms": int((time.perf_counter() - started) * 1000)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:400]}

    def status(self) -> dict[str, Any]:
        return {
            "uptime_s": int(time.time() - self.started_at),
            "sources": [ing.status() for ing in self.ingestors.values()],
            "live": {"aircraft": AIRCRAFT.stats(), "vessels": VESSELS.stats()},
        }
