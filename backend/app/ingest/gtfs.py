"""Índice GTFS estático de Renfe: paradas con nombre, destinos e itinerarios.

Los feeds GTFS-Realtime de Renfe dan la posición de cada tren y el `stopId` de
la próxima parada, pero un código (`28065`) no dice nada. Esa información está
en los GTFS estáticos que Renfe publica para descarga:

  · AVE / Largo Recorrido .. https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip   (0,7 MB)
  · Cercanías .............. https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip (15,9 MB)

De ahí se extrae un índice pequeño y ya "cocinado" (index_renfe.json, ~1,5 MB):

  stops   { stop_id: {name, lat, lon, kind} }
  trips   { trip_id: {route, label, headsign, stops: [ids]} }
  routes  { route_id: {short, long, type} }
  alerts  [ {routes:[], text, start, end} ]     ← de gtfsrt.renfe.com/alerts.json

El ZIP de Cercanías (1,8 M de filas de horarios) se descarga **una sola vez**;
después el índice se refresca desde el ZIP pequeño de AVE/LD y los horarios
solo se rehacen si el fichero tiene más de un mes. Así el arranque es de
segundos y el consumo de disco (~1,5 MB) no crece.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Any

from .client import Fetcher

log = logging.getLogger("aegis.gtfs")

LD_ZIP = "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip"
CER_ZIP = "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip"
ALERTS = "https://gtfsrt.renfe.com/alerts.json"

# el ZIP de Cercanías es de 16 MB: se rehace como mucho una vez al mes
CER_MAX_AGE_S = 30 * 24 * 3600

ROUTE_TYPE = {
    "0": "tranvía", "1": "metro", "2": "tren", "3": "autobús",
    "4": "ferry", "5": "teleférico", "6": "aéreo",
}


def index_path(root: Path) -> Path:
    """Índice comprimido con gzip: 5,1 MB en claro → 0,5 MB (carga igual de rápida)."""
    return root / "data" / "index_renfe.json.gz"


async def _download(fetcher: Fetcher, url: str, dest: Path) -> Path | None:
    try:
        blob = await fetcher.get_bytes(url, timeout=180, retries=1)
    except Exception as exc:  # noqa: BLE001
        log.warning("gtfs %s: %s", url, exc)
        return None
    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 1000:
        log.warning("gtfs %s: descarga vacía", url)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(blob))
    return dest


def _rows(zf: zipfile.ZipFile, name: str):
    if name not in zf.namelist():
        return
    with zf.open(name) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))


def _read_ld(zf: zipfile.ZipFile) -> dict[str, Any]:
    """AVE / Largo Recorrido: 1.006 paradas, 6.862 viajes, 57 k horarios."""
    stops: dict[str, dict] = {}
    for r in _rows(zf, "stops.txt"):
        sid = (r.get("stop_id") or "").strip()
        if not sid or (r.get("location_type") or "") == "1":
            continue
        try:
            lat, lon = float(r["stop_lat"]), float(r["stop_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        stops[sid] = {"name": (r.get("stop_name") or sid).strip(), "lat": lat, "lon": lon, "kind": "tren"}

    routes: dict[str, dict] = {}
    for r in _rows(zf, "routes.txt"):
        rid = (r.get("route_id") or "").strip()
        if rid:
            routes[rid] = {
                "short": (r.get("route_short_name") or "").strip(),
                "long": (r.get("route_long_name") or "").strip(),
                "type": ROUTE_TYPE.get((r.get("route_type") or "").strip(), "tren"),
            }

    trips: dict[str, dict] = {}
    for r in _rows(zf, "trips.txt"):
        tid = (r.get("trip_id") or "").strip()
        if not tid:
            continue
        trips[tid] = {
            "route": (r.get("route_id") or "").strip(),
            "label": (r.get("trip_short_name") or "").strip(),
            "headsign": (r.get("trip_headsign") or "").strip(),
            "stops": [],
        }

    order: dict[str, list[tuple[int, str]]] = {}
    for r in _rows(zf, "stop_times.txt"):
        tid = (r.get("trip_id") or "").strip()
        sid = (r.get("stop_id") or "").strip()
        if tid not in trips or not sid:
            continue
        try:
            seq = int(r.get("stop_sequence") or 0)
        except ValueError:
            seq = 0
        order.setdefault(tid, []).append((seq, sid))
    for tid, seqs in order.items():
        seqs.sort()
        trips[tid]["stops"] = [s for _, s in seqs]
        if not trips[tid]["headsign"] and trips[tid]["stops"]:
            last = stops.get(trips[tid]["stops"][-1])
            if last:
                trips[tid]["headsign"] = last["name"]
    return {"stops": stops, "trips": trips, "routes": routes}


def _read_cer(zf: zipfile.ZipFile, stops: dict[str, dict], routes: dict[str, dict]) -> dict[str, dict]:
    """Cercanías: solo las paradas que faltan y los destinos de cada viaje.

    El fichero tiene 1,8 M de horarios: aquí no se guardan itinerarios (un
    cercanías tiene 10-25 paradas y el feed ya trae la siguiente), solo:
      · paradas nuevas (nombre + coordenadas)
      · destino de cada viaje (última parada) para poder decir «va a Alcalá»
    """
    for r in _rows(zf, "stops.txt"):
        sid = (r.get("stop_id") or "").strip()
        if not sid or sid in stops or (r.get("location_type") or "") == "1":
            continue
        try:
            stops[sid] = {
                "name": (r.get("stop_name") or sid).strip(),
                "lat": float(r["stop_lat"]),
                "lon": float(r["stop_lon"]),
                "kind": "tren",
            }
        except (KeyError, TypeError, ValueError):
            continue

    for r in _rows(zf, "routes.txt"):
        rid = (r.get("route_id") or "").strip()
        if rid and rid not in routes:
            routes[rid] = {
                "short": (r.get("route_short_name") or "").strip(),
                "long": (r.get("route_long_name") or "").strip(),
                "type": ROUTE_TYPE.get((r.get("route_type") or "").strip(), "tren"),
            }

    last: dict[str, tuple[int, str]] = {}
    for r in _rows(zf, "stop_times.txt"):
        tid = (r.get("trip_id") or "").strip()
        sid = (r.get("stop_id") or "").strip()
        if not tid or not sid:
            continue
        try:
            seq = int(r.get("stop_sequence") or 0)
        except ValueError:
            continue
        prev = last.get(tid)
        if prev is None or seq > prev[0]:
            last[tid] = (seq, sid)

    trips: dict[str, dict] = {}
    for r in _rows(zf, "trips.txt"):
        tid = (r.get("trip_id") or "").strip()
        if not tid:
            continue
        headsign = (r.get("trip_headsign") or "").strip()
        if not headsign and tid in last:
            sid = last[tid][1]
            headsign = stops.get(sid, {}).get("name", "")
        trips[tid] = {
            "route": (r.get("route_id") or "").strip(),
            "label": (r.get("trip_short_name") or "").strip(),
            "headsign": headsign,
            "stops": [],
        }
    return trips


async def refresh_alerts(fetcher: Fetcher) -> list[dict[str, Any]]:
    """Incidencias de servicio publicadas por Renfe (GTFS-RT alerts)."""
    try:
        data = await fetcher.get_json(ALERTS, timeout=25, retries=1)
    except Exception as exc:  # noqa: BLE001
        log.warning("alertas renfe: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for ent in (data or {}).get("entity") or []:
        alert = ent.get("alert") or {}
        text = ""
        for tr in (alert.get("descriptionText") or {}).get("translation") or []:
            if tr.get("text"):
                text = str(tr["text"]).strip()
                break
        if not text:
            continue
        routes = [
            str((ie.get("routeId") or "")).strip()
            for ie in alert.get("informedEntity") or []
            if ie.get("routeId")
        ]
        period = (alert.get("activePeriod") or [{}])[0]
        try:
            start = int(period.get("start") or 0)
        except (TypeError, ValueError):
            start = 0
        try:
            end = int(period.get("end") or 0)
        except (TypeError, ValueError):
            end = 0
        out.append({"text": text, "routes": routes, "start": start, "end": end})
    return out[:300]


class GtfsIndex:
    """Índice consultable por la API y por la ingesta de trenes."""

    def __init__(self, root: Path):
        self.root = root
        self.stops: dict[str, dict] = {}
        self.trips: dict[str, dict] = {}
        self.routes: dict[str, dict] = {}
        self.alerts: list[dict] = []
        self.built_at: float = 0.0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ util
    def stop_name(self, stop_id: str) -> str:
        return (self.stops.get(str(stop_id or "")) or {}).get("name", "")

    def trip_info(self, trip_id: str) -> dict:
        return self.trips.get(str(trip_id or "")) or {}

    def alert_for(self, route_id: str = "", text: str = "") -> str:
        """Primera incidencia activa que afecte a esa línea."""
        now = time.time()
        for al in self.alerts:
            if al.get("end") and al["end"] < now:
                continue
            if route_id and route_id in (al.get("routes") or []):
                return str(al.get("text") or "")
            if text and text.lower() in str(al.get("text") or "").lower():
                return str(al.get("text") or "")
        return ""

    def stats(self) -> dict[str, Any]:
        return {
            "stops": len(self.stops),
            "trips": len(self.trips),
            "routes": len(self.routes),
            "alerts": len(self.alerts),
            "built_at": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.built_at)) if self.built_at else None
            ),
        }

    # ----------------------------------------------------------------- carga
    def load(self) -> bool:
        path = index_path(self.root)
        plain = self.root / "data" / "index_renfe.json"
        try:
            if path.exists():
                import gzip

                data = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
            elif plain.exists():          # formato anterior sin comprimir
                data = json.loads(plain.read_text(encoding="utf-8"))
            else:
                return False
        except Exception as exc:  # noqa: BLE001
            log.warning("index_renfe ilegible: %s", exc)
            return False
        if data.get("v") == 2:
            strs = data.get("strs") or []
            self.stops = {
                k: {"name": strs[v[0]] if v[0] < len(strs) else "", "lat": v[1], "lon": v[2], "kind": "tren"}
                for k, v in (data.get("stops") or {}).items()
            }
            self.routes = {
                k: {"short": strs[v[0]] if v[0] < len(strs) else "",
                    "long": strs[v[1]] if v[1] < len(strs) else "", "type": "tren"}
                for k, v in (data.get("routes") or {}).items()
            }
            self.trips = {
                k: {"route": strs[v[0]] if v[0] < len(strs) else "",
                    "label": strs[v[1]] if v[1] < len(strs) else "",
                    "headsign": strs[v[2]] if v[2] < len(strs) else "",
                    "stops": v[3] if isinstance(v[3], list) else []}
                for k, v in (data.get("trips") or {}).items()
            }
        else:  # formato antiguo (v1)
            self.stops = data.get("stops") or {}
            self.trips = data.get("trips") or {}
            self.routes = data.get("routes") or {}
        self.built_at = float(data.get("built_at") or 0)
        log.info(
            "índice Renfe: %d paradas · %d viajes · %d líneas",
            len(self.stops), len(self.trips), len(self.routes),
        )
        return True

    def save(self) -> Path:
        """Guarda el índice comprimido (~1/3 del tamaño en claro).

        Las cadenas repetidas (nombres de parada, destinos, líneas) se guardan
        una sola vez en `strs` y las tablas solo llevan índices: 140.000 viajes
        pasan de 13 MB a ~4 MB.
        """
        path = index_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        strs: list[str] = []
        pos: dict[str, int] = {}

        def sid(text: str) -> int:
            text = text or ""
            got = pos.get(text)
            if got is None:
                got = len(strs)
                pos[text] = got
                strs.append(text)
            return got

        stops = {k: [sid(v.get("name", "")), round(float(v.get("lat", 0)), 4),
                     round(float(v.get("lon", 0)), 4)] for k, v in self.stops.items()}
        routes = {k: [sid(v.get("short", "")), sid(v.get("long", ""))] for k, v in self.routes.items()}
        trips = {}
        for tid, t in self.trips.items():
            stops_ids = t.get("stops") or []
            trips[tid] = [sid(t.get("route", "")), sid(t.get("label", "")),
                          sid(t.get("headsign", "")), stops_ids if stops_ids else 0]

        payload = {
            "v": 2,
            "built_at": self.built_at or time.time(),
            "strs": strs,
            "stops": stops,
            "routes": routes,
            "trips": trips,
        }
        import gzip

        tmp = path.with_suffix(".tmp")
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        tmp.write_bytes(gzip.compress(blob, compresslevel=6))
        tmp.replace(path)
        return path

    async def build(self, fetcher: Fetcher, force_cer: bool = False) -> dict[str, Any]:
        """Construye el índice desde los ZIP de Renfe (una vez al mes el de Cercanías)."""
        async with self._lock:
            cache = self.root / "data" / "cache"
            cer_zip = cache / "renfe_cercanias.zip"
            ld_zip = cache / "renfe_ld.zip"

            ld_path = await _download(fetcher, LD_ZIP, ld_zip)
            if not ld_path:
                return {"ok": False, "error": "no se pudo descargar el GTFS de AVE/LD"}
            data = _read_ld(zipfile.ZipFile(ld_path))

            need_cer = force_cer or not cer_zip.exists() or (time.time() - cer_zip.stat().st_mtime) > CER_MAX_AGE_S
            if need_cer:
                log.info("gtfs: descargando Cercanías (16 MB, una vez al mes)…")
                await _download(fetcher, CER_ZIP, cer_zip)
            if cer_zip.exists():
                try:
                    data["trips"].update(_read_cer(zipfile.ZipFile(cer_zip), data["stops"], data["routes"]))
                except Exception as exc:  # noqa: BLE001
                    log.warning("gtfs cercanías ilegible: %s", exc)
                finally:
                    # 16 MB que no hacen falta hasta el mes que viene
                    try:
                        cer_zip.unlink(missing_ok=True)
                    except OSError:
                        pass

            self.stops = data["stops"]
            self.trips = data["trips"]
            self.routes = data["routes"]
            self.built_at = time.time()
            self.alerts = await refresh_alerts(fetcher)
            path = self.save()
            size_mb = path.stat().st_size / 1e6
            log.info(
                "índice Renfe construido: %d paradas · %d viajes · %d líneas · %.1f MB",
                len(self.stops), len(self.trips), len(self.routes), size_mb,
            )
            return {"ok": True, **self.stats(), "size_mb": round(size_mb, 2)}

    async def ensure(self, fetcher: Fetcher) -> dict[str, Any]:
        """Carga el índice del disco; si no existe, lo construye (una vez)."""
        if self.stops or self.load():
            if not self.alerts:
                self.alerts = await refresh_alerts(fetcher)
            return {"ok": True, "cached": True, **self.stats()}
        return await self.build(fetcher)
