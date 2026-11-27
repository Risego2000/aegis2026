"""HTTP + WebSocket surface consumed by the Next.js client."""
from __future__ import annotations

import asyncio
import gzip
import json
import time
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi import Response
from fastapi.responses import JSONResponse

from ..ai.briefing import build_briefing, summary_numbers
from ..ai.providers import probe
from ..config import HOTSPOTS, ROOT, settings
from ..fence.engine import AVAILABLE_RULES
from ..ingest.client import Fetcher
from ..cameras import CAMERAS
from ..live import AIRCRAFT, AIR, SATCAT, TRAINS, VESSELS
from ..models import CATEGORIES, Event
from ..ingest import satellites as sats_mod
from .. import tiles as tiles_mod

# caché de fotogramas: id -> (instante, jpeg) — 3 s de gracia por cámara
_FRAME_CACHE: dict[str, tuple[float, bytes]] = {}

UA = {"User-Agent": "aegis-osint/1.0 (cliente HTTP propio; datos abiertos)"}

router = APIRouter()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _event_json(ev: Event) -> dict[str, Any]:
    """Evento tal y como se sirve a la interfaz: todo el texto en español.

    La traducción se aplica también en lectura (no solo en la ingesta) para que
    ningún titular antiguo llegue en inglés a la pantalla.
    """
    from ..ingest.es import (
        CATEGORIA_ES,
        SEVERIDAD_ES,
        es_region,
        es_titulo_cualquiera,
    )

    data = {k: v for k, v in ev.__dict__.items() if k != "embedding"}
    data["title"] = es_titulo_cualquiera(ev.title, ev.source)
    data["category_label"] = CATEGORIA_ES.get(ev.category, ev.category.title())
    data["severity_label"] = ev.severity_label
    data["severity_text"] = SEVERIDAD_ES.get(ev.severity_label, ev.severity_label)
    data["country_es"] = es_region(ev.country)
    if ev.summary:
        resumen = ev.summary
        if ev.source == "gdelt":
            from ..ingest.es import ROOT_LABELS_ES

            for en, es in ROOT_LABELS_ES.items():
                resumen = resumen.replace(f"({en})", f"({es})")
            resumen = resumen.replace("CAMEO", "CAMEO")
        data["summary"] = resumen
    return data


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw:
        return None
    try:
        parts = [float(x) for x in raw.split(",")]
        if len(parts) != 4:
            return None
        return (parts[0], parts[1], parts[2], parts[3])
    except ValueError:
        return None


def _store(request: Request):
    return request.app.state.store


def _engine(request: Request):
    return request.app.state.engine


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #
@router.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    ai = await probe()
    return {
        "categories": list(CATEGORIES),
        "rules": AVAILABLE_RULES,
        "ai": {"provider": ai.provider, "model": ai.model, "available": ai.available, "detail": ai.detail},
        "sources": {
            "usgs": settings.enable_usgs,
            "gdacs": settings.enable_gdacs,
            "gdelt": settings.enable_gdelt,
            "adsb": settings.enable_adsb,
            "ais": settings.enable_ais,
            "firms": settings.enable_firms and bool(settings.firms_map_key),
            "satellites": settings.enable_satellites,
        },
        "hotspots": {k: {"lat": v[0], "lon": v[1], "radius_nm": v[2]} for k, v in HOTSPOTS.items()},
        "fence_engine": "tile38" if settings.tile38_url else "in-process",
        "storage": _store(request).backend,
    }


@router.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    store = _store(request)
    registry = request.app.state.registry
    engine = _engine(request)
    stats = await store.stats()
    return {
        "status": "ok",
        "storage": stats,
        "ingest": registry.status(),
        "fence": engine.status(),
        "live": {"aircraft": AIRCRAFT.stats(), "vessels": VESSELS.stats(),
                 "satellites": SATCAT.stats(), "air": AIR.stats(),
                 "trains": TRAINS.stats(), "cameras": CAMERAS.stats()},
        "version": request.app.version,
    }


@router.get("/api/stats")
async def stats(request: Request) -> dict[str, Any]:
    store = _store(request)
    runs = await store.runs(limit=24)
    return {
        "storage": await store.stats(),
        "runs": runs,
        "live": {"aircraft": AIRCRAFT.stats(), "vessels": VESSELS.stats(),
                 "satellites": SATCAT.stats(), "air": AIR.stats(),
                 "trains": TRAINS.stats(), "cameras": CAMERAS.stats()},
        "fence": _engine(request).status(),
    }


@router.get("/api/sources")
async def sources(request: Request) -> dict[str, Any]:
    return request.app.state.registry.status()


@router.post("/api/ingest/{name}/run")
async def trigger_ingest(name: str, request: Request) -> dict[str, Any]:
    """Fuerza una ingesta.

    Si `AEGIS_TOKEN` está definido, exige la cabecera `X-Aegis-Token`, y si no
    lo está solo permite llamadas desde la propia máquina: con el túnel
    público, el endpoint quedaba abierto para que cualquiera saturara las
    fuentes.
    """
    token = settings.aegis_token
    if token:
        if request.headers.get("x-aegis-token") != token:
            raise HTTPException(status_code=401, detail="token requerido (cabecera X-Aegis-Token)")
    else:
        client = (request.client.host if request.client else "") or ""
        if client and client not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(
                status_code=403,
                detail="este endpoint solo acepta llamadas locales; define AEGIS_TOKEN para abrirlo bajo tu control",
            )
    result = await request.app.state.registry.trigger(name)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return result


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Prioridad social: ¿este suceso es una amenaza para la población o genera
# alarma social / interés general? Se calcula con lo que el propio dato trae
# (categoría, gravedad, nº de fuentes, menciones y palabras clave del titular).
# No se inventa nada: es una heurística transparente y explicable.
# --------------------------------------------------------------------------- #
_THREAT_TERMS = {
    # amenaza directa para la vida
    "dead": 3, "muert": 3, "fallecid": 3, "killed": 3, "casualt": 3, "víctim": 3,
    "herid": 2, "injured": 2, "damage": 1.5, "daño": 1.5, "destroz": 2,
    "evacuat": 3, "evacuad": 3, "desaloj": 2.5, "desplaz": 2,
    "tsunami": 4, "terremoto": 3, "earthquake": 3, "erupci": 3, "volcán": 3,
    "inundaci": 2.5, "flood": 2.5, "huracán": 3, "huracan": 3, "ciclón": 3,
    "tornado": 3, "tormenta": 2, "sequía": 2, "incendio": 2.5, "fire": 2,
    "explosi": 3, "explosion": 3, "atentado": 4, "attack": 3, "ataque": 3,
    "bomba": 3.5, "bomb": 3, "tiroteo": 3.5, "shooting": 3.5, "rehén": 3,
    "guerra": 3, "war": 2.5, "ofensiva": 3, "misil": 3, "drone": 2,
    "ciberataque": 2.5, "cyberattack": 2.5, "colapso": 2.5, "apagón": 2,
    "blackout": 2, "huelga": 1.5, "protesta": 1.5, "disturbio": 2, "riot": 2.5,
    "toque de queda": 3, "curfew": 3, "confinamiento": 3, "lockdown": 3,
    "emergencia": 2.5, "emergency": 2.5, "alerta": 2, "alert": 1.5, "aviso": 1.5,
}
_THREAT_ROJO = {"atentado", "tiroteo", "tsunami", "muert", "fallecid", "killed",
                "evacuat", "evacuad", "bomba", "toque de queda", "curfew", "misil"}
_ALARM_CATS = {"earthquake": 3.0, "disaster": 3.0, "wildfire": 2.5,
               "conflict": 2.8, "protest": 1.6, "military": 2.4,
               "traffic": 1.2, "transporte": 0.8, "transport": 0.8,
               "economy": 0.9, "diplomacy": 0.6, "news": 0.5}


def social_priority(ev: Any) -> dict[str, Any]:
    """Puntuación 0-10 de amenaza/alarma social, con su motivo en español."""
    title = f"{getattr(ev, 'title', '') or ''} {getattr(ev, 'subtype', '') or ''}".lower()
    summary = (getattr(ev, "summary", "") or "").lower()
    cat = (getattr(ev, "category", "") or "").lower()

    puntos = _ALARM_CATS.get(cat, 0.5)
    motivos: list[str] = []
    if puntos >= 2.4:
        motivos.append(cat)

    hits = 0.0
    rojo = False
    for term, peso in _THREAT_TERMS.items():
        if term in title or term in summary:
            hits += peso
            if term in _THREAT_ROJO:
                rojo = True
    hits = min(hits, 5.0)

    # gravedad declarada por la fuente (escala 1-5) y su etiqueta
    sev = getattr(ev, "severity", None)
    sev_label = (getattr(ev, "severity_label", "") or "").lower()
    sev_pts = 0.0
    if sev_label in ("red", "critical"):
        sev_pts += 2.0
    elif sev_label in ("orange",):
        sev_pts += 1.4
    elif sev_label in ("yellow", "high"):
        sev_pts += 0.8
    if sev is not None:
        try:
            sev_pts += min(float(sev), 6.0) * 0.18
        except (TypeError, ValueError):
            pass

    # corroboración: más fuentes o menciones ⇒ interés general
    corrobor = min((getattr(ev, "sources_count", 1) or 1) - 1, 3) * 0.7 + \
               min((getattr(ev, "mentions", 1) or 1) - 1, 40) * 0.03

    # escala suave: evita que media docena de titulares se peguen todos al 10
    # (puntuación bruta 6 → 6,3 · 12 → 8,6 · 24 → 9,8)
    bruto = puntos + hits + sev_pts + corrobor
    total = round(10.0 * (1.0 - pow(2.718281828, -bruto / 6.0)), 1)
    if rojo and total < 6.0:
        total = 6.0
    nivel = "crítica" if total >= 7.5 else "alta" if total >= 5.5 else \
            "media" if total >= 3.5 else "baja"
    if not motivos and hits == 0:
        motivos.append("sin indicios de amenaza")
    return {"score": total, "level": nivel, "reasons": motivos[:3],
            "population_threat": total >= 5.5, "alarm": total >= 3.5}


@router.get("/api/events/priority")
async def events_priority(
    request: Request,
    bbox: str | None = Query(None, description="w,s,e,n"),
    categories: str | None = Query(None),
    hours: float = Query(24.0, ge=0.1, le=24 * 30),
    min_score: float = Query(3.5, ge=0, le=10),
    limit: int = Query(400, ge=1, le=2000),
) -> dict[str, Any]:
    """Sucesos que amenazan a la población o generan alarma, ya ordenados.

    Es la vista que un centro de crisis miraría primero: mismo dato que el
    mapa, pero priorizado y con el motivo de la prioridad escrito.
    """
    store = _store(request)
    box = _parse_bbox(bbox)
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    events = await store.query_bbox(
        box or (-180.0, -85.0, 180.0, 85.0), categories=cats, since_hours=hours, limit=3000,
    )
    items = []
    for ev in events:
        pr = social_priority(ev)
        if pr["score"] < min_score:
            continue
        props = _event_json(ev)
        props.pop("payload", None)
        props.pop("geometry", None)
        props["priority"] = pr
        items.append(props)
    items.sort(key=lambda x: (x["priority"]["score"], x.get("first_seen") or ""), reverse=True)
    return {
        "count": len(items),
        "considered": len(events),
        "hours": hours,
        "min_score": min_score,
        "levels": {
            "crítica": sum(1 for i in items if i["priority"]["level"] == "crítica"),
            "alta": sum(1 for i in items if i["priority"]["level"] == "alta"),
            "media": sum(1 for i in items if i["priority"]["level"] == "media"),
            "baja": sum(1 for i in items if i["priority"]["level"] == "baja"),
        },
        "events": items[:limit],
        "server_time": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/api/events")
async def list_events(
    request: Request,
    bbox: str | None = Query(None, description="w,s,e,n"),
    categories: str | None = Query(None, description="coma-separadas"),
    hours: float = Query(24.0, ge=0.1, le=24 * 30),
    limit: int = Query(6000, ge=1, le=20000),
    q: str | None = None,
    sources: str | None = Query(None, description="coma-separadas: desglose por fuente"),
    full: bool = Query(False, description="incluye el payload de origen en cada evento"),
    since: str | None = Query(None, description="ISO-8601: solo eventos vistos después (refresco incremental)"),
) -> dict[str, Any]:
    store = _store(request)
    box = _parse_bbox(bbox)
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    srcs = [c.strip() for c in sources.split(",") if c.strip()] if sources else None
    events = await store.query_bbox(
        box or (-180.0, -85.0, 180.0, 85.0), categories=cats, since_hours=hours, limit=limit,
        search=q, sources=srcs,
    )
    if since:
        # refresco incremental: el cliente manda la marca del último evento que
        # tiene y solo recibe lo aparecido después (evita repintar 1,4 MB cada 20 s)
        from datetime import datetime

        try:
            mark = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            mark = None
        if mark is not None:
            kept = []
            for ev in events:
                try:
                    seen = datetime.fromisoformat((ev.first_seen or "").replace("Z", "+00:00"))
                except ValueError:
                    kept.append(ev)
                    continue
                if seen >= mark:
                    kept.append(ev)
            events = kept

    if since and events:
        # el incremental se pinta delante: lo más nuevo primero
        events = sorted(events, key=lambda e: (e.first_seen or ""), reverse=True)

    features = []
    for ev in events:
        geometry = ev.geometry or {"type": "Point", "coordinates": [ev.lon, ev.lat]}
        props = _event_json(ev)
        props.pop("lat")
        props.pop("lon")
        props.pop("geometry")
        if not full:
            # el mapa solo necesita lo justo para pintar y agrupar: el payload
            # completo se sirve en /api/events/{id} al abrir la ficha
            props.pop("payload", None)
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    return {
        "type": "FeatureCollection",
        "count": len(features),
        "bbox": box,
        "hours": hours,
        "numbers": summary_numbers(events),
        # marca de agua que el cliente devuelve como ?since= en el refresco
        "server_time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(
            timespec="seconds"
        ),
        "features": features,
    }


@router.get("/api/export/events")
async def export_events(
    request: Request,
    bbox: str | None = Query(None, description="w,s,e,n"),
    categories: str | None = None,
    hours: float = Query(24.0, ge=0.1, le=24 * 30),
    limit: int = Query(8000, ge=1, le=20000),
    q: str | None = None,
    fmt: str = Query("csv", pattern="^(csv|geojson)$"),
) -> Response:
    """Descarga de los sucesos visibles en CSV o GeoJSON.

    CSV con separador `;` (y BOM) para que Excel en español lo abra sin tocar
    nada; GeoJSON listo para QGIS. Los mismos filtros que la capa del mapa.
    """
    import csv
    import io as _io

    store = _store(request)
    box = _parse_bbox(bbox)
    cats = [c.strip() for c in categories.split(",") if c.strip()] if categories else None
    events = await store.query_bbox(
        box or (-180.0, -85.0, 180.0, 85.0), categories=cats, since_hours=hours, limit=limit, search=q,
    )
    from ..ingest.es import CATEGORIA_ES, SEVERIDAD_ES

    stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%dT%H%MZ")

    if fmt == "geojson":
        feats = []
        for ev in events:
            props = _event_json(ev)
            props.pop("payload", None)
            feats.append({
                "type": "Feature",
                "geometry": ev.geometry or {"type": "Point", "coordinates": [ev.lon, ev.lat]},
                "properties": props,
            })
        payload = {"type": "FeatureCollection", "count": len(feats), "features": feats}
        return Response(
            content=__import__("json").dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            media_type="application/geo+json",
            headers={"Content-Disposition": f'attachment; filename="aegis-eventos-{stamp}.geojson"'},
        )

    buf = _io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["id", "fecha", "categoria", "categoria_es", "titulo", "resumen",
                     "lat", "lon", "pais", "fuente", "gravedad", "severidad", "url"])
    for ev in events:
        writer.writerow([
            ev.id, ev.event_time, ev.category, CATEGORIA_ES.get(ev.category, ev.category),
            ev.title, (ev.summary or "")[:500], ev.lat, ev.lon, ev.country or "", ev.source,
            ev.severity if ev.severity is not None else "", SEVERIDAD_ES.get(ev.severity_label, ev.severity_label),
            ev.url or "",
        ])
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="aegis-eventos-{stamp}.csv"'},
    )


@router.get("/api/events/{event_id}")
async def get_event(event_id: str, request: Request) -> dict[str, Any]:
    store = _store(request)
    event = await store.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="evento no encontrado")
    return {
        "event": _event_json(event),
        "mentions": await store.mentions(event_id, limit=30),
    }


@router.get("/api/events/{event_id}/nearby")
async def nearby(
    event_id: str,
    request: Request,
    radius_km: float = Query(150.0, ge=1, le=2000),
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, Any]:
    """ST_DWithin-style proximity: which settlements/infrastructure sit inside
    the impact radius of this event."""
    store = _store(request)
    event = await store.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="evento no encontrado")
    hits = await store.nearby(event.lat, event.lon, radius_km * 1000.0, limit=limit)
    total_pop = sum(h.population for h in hits)
    return {
        "event_id": event_id,
        "center": {"lat": event.lat, "lon": event.lon},
        "radius_km": radius_km,
        "query": "ST_DWithin(geom, point, radius) -- GiST / R-Tree index backed",
        "count": len(hits),
        "population_exposed": total_pop,
        "hits": [h.__dict__ for h in hits],
    }


# --------------------------------------------------------------------------- #
# live layers
# --------------------------------------------------------------------------- #
def _live_layer(kind: str):
    """Mapea el nombre de capa de la URL a su LiveLayer."""
    return {
        "aircraft": AIRCRAFT,
        "vessels": VESSELS,
        "ships": VESSELS,
        "boats": VESSELS,
        "air": AIR,
        "aire": AIR,
        "trains": TRAINS,
        "trenes": TRAINS,
        "train": TRAINS,
    }.get(kind)


@router.get("/api/live/aircraft/refresh")
async def live_aircraft_refresh(request: Request, lat: float, lon: float, radius: int = 250) -> dict:
    """Refresco a la carta del tráfico aéreo de la zona visible.

    El cliente lo llama al mover el mapa (con freno) para que las aeronaves de
    la vista tengan posiciones recién sondeadas y se vean volar de verdad.
    """
    from ..ingest import adsb as adsb_ingest

    fetcher = getattr(request.app.state, "fetcher", None) or Fetcher()
    try:
        n = await adsb_ingest.focus(fetcher, lat, lon, radius)
    except Exception as exc:  # noqa: BLE001 - el fallo de un sondeo no rompe la API
        raise HTTPException(status_code=502, detail=f"adsb focus: {exc}") from exc
    return {"ok": True, "updated": n, "count": len(AIRCRAFT.items),
            "lat": lat, "lon": lon, "radius": radius}


@router.get("/api/live/aircraft")
async def live_aircraft(bbox: str | None = None, limit: int = Query(20000, le=40000)) -> dict[str, Any]:
    data = AIRCRAFT.geojson(_parse_bbox(bbox), limit)
    data["stats"] = AIRCRAFT.stats()
    return data


@router.get("/api/live/vessels")
async def live_vessels(bbox: str | None = None, limit: int = Query(20000, le=40000)) -> dict[str, Any]:
    data = VESSELS.geojson(_parse_bbox(bbox), limit)
    data["stats"] = VESSELS.stats()
    return data


@router.get("/api/live/air")
async def live_air(bbox: str | None = None, limit: int = Query(20000, le=40000)) -> dict[str, Any]:
    """Calidad del aire: un elemento por sensor con su última lectura."""
    data = AIR.geojson(_parse_bbox(bbox), limit)
    data["stats"] = AIR.stats()
    return data


# --------------------------------------------------------------------------- #
# fotografía del elemento (avión / buque)
# --------------------------------------------------------------------------- #
APP_STATE: dict[str, Any] = {}
_GTFS_FALLBACK = None
_PHOTO_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_PHOTO_TTL = 6 * 3600
# Planespotters exige un User-Agent con contacto identificable (403 si no).
_PHOTO_UA = "AEGIS-OSINT/1.0 (+https://github.com/aegis-osint)"



async def _commons_photo(fetcher: Fetcher, query: str, note: str = "") -> dict[str, Any] | None:
    """Primera foto real de Wikimedia Commons para una búsqueda concreta."""
    from urllib.parse import quote as _q

    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=search&gsrnamespace=6&gsrlimit=3"
           f"&gsrsearch={_q(query)}"
           "&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=520")
    try:
        data = await fetcher.get_json(url, retries=1, timeout=20)
    except Exception:  # noqa: BLE001 - sin foto no pasa nada
        return None
    pages = ((data or {}).get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        thumb = info.get("thumburl") or info.get("url")
        if not thumb:
            continue
        meta = info.get("extmetadata") or {}
        artist = (meta.get("Artist") or {}).get("value") or "Wikimedia Commons"
        artist = __import__("re").sub(r"<[^>]+>", "", artist).strip()[:80]
        return {
            "url": thumb,
            "proxy": "/api/media/img?url=" + _q(thumb, safe=""),
            "credit": artist,
            "link": info.get("descriptionurl") or "",
            "source": "Wikimedia Commons",
            "note": note,
        }
    return None


@router.get("/api/events/{event_id}/photo")
async def event_photo(request: Request, event_id: str) -> dict[str, Any]:
    """Imagen real asociada a un suceso, elegida por su propia fuente.

    · FIRMS    → fotograma del satélite que detectó el foco (Esri World Imagery,
                 la misma escena que vio el sensor, sin clave): es la imagen
                 más fiel que existe del incendio.
    · EONET    → la imagen oficial del propio evento (NASA).
    · GDACS    → mapa de situación del ciclón/terremoto (JRC).
    · resto    → si el suceso trae URL y la página publica og:image, se usa esa
                 (la foto del medio que informó); si no, no se inventa nada.
    """
    from urllib.parse import quote

    store = _store(request)
    ev = await store.get(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="suceso no encontrado")
    payload = ev.payload or {}
    photo: dict[str, Any] | None = None

    if ev.source == "firms":
        z = 11
        url = ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
               "MapServer/tile/{z}/{y}/{x}")
        # tesela Esri que contiene el punto (Esri no publica teselas por lat/lon,
        # así que se calcula el índice WebMercator estándar)
        import math

        n = 2 ** z
        xt = int((ev.lon + 180.0) / 360.0 * n)
        yt = int((1.0 - math.log(math.tan(math.radians(ev.lat)) + 1 / math.cos(math.radians(ev.lat))) / math.pi) / 2.0 * n)
        tile = url.format(z=z, x=xt, y=yt)
        photo = {
            "url": "/api/tile/img?url=" + quote(tile, safe=""),
            "proxy": "/api/tile/img?url=" + quote(tile, safe=""),
            "credit": f"Esri World Imagery · detectado por {payload.get('satellite', 'VIIRS')}",
            "link": ev.url or "",
            "source": "imagen de satélite",
            "note": "escena satelital del punto donde el sensor vio el foco",
        }

    elif ev.source == "eonet":
        img = payload.get("image") or payload.get("images")
        if isinstance(img, list):
            img = img[0] if img else None
        if img:
            photo = {
                "url": str(img), "proxy": "/api/media/img?url=" + quote(str(img), safe=""),
                "credit": "NASA EONET", "link": ev.url or "",
                "source": "NASA", "note": "imagen oficial del evento",
            }

    elif ev.source in ("gdelt", "nws", "usgs", "emsc", "gdacs"):
        og = await _og_image(request, ev.url or "")
        if og:
            photo = og

    if photo is None and ev.url:
        og = await _og_image(request, ev.url)
        if og:
            photo = og
    return {"photo": photo}


async def _og_image(request: Request, page_url: str) -> dict[str, Any] | None:
    """Lee `og:image` de la página del suceso (la foto que publicó el medio)."""
    import re as _re
    from urllib.parse import quote, urlparse

    page_url = (page_url or "").strip()
    if not page_url.startswith("http"):
        return None
    key = f"og:{page_url}"
    now = time.time()
    hit = _PHOTO_CACHE.get(key)
    if hit and now - hit[0] < _PHOTO_TTL:
        return hit[1]
    fetcher = getattr(request.app.state, "fetcher", None) or Fetcher()
    photo = None
    try:
        text = await fetcher.get_text(page_url, retries=0, timeout=12)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        try:
            raw = await fetcher.get_bytes(page_url, retries=0, timeout=12)  # type: ignore[attr-defined]
            text = raw[:200000].decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            text = ""
    if text:
        m = _re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', text)
        if not m:
            m = _re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', text)
        if m:
            src = m.group(1)
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}{src}"
            photo = {
                "url": src,
                "proxy": "/api/media/img?url=" + quote(src, safe=""),
                "credit": urlparse(page_url).netloc,
                "link": page_url,
                "source": urlparse(page_url).netloc,
                "note": "imagen publicada con la noticia",
            }
    _PHOTO_CACHE[key] = (now, photo)
    return photo


@router.get("/api/tile/img")
async def tile_img(request: Request, url: str = Query(...)) -> Response:
    """Tesela de imagen satelital servida por nuestro dominio (sin claves)."""
    allowed = ("server.arcgisonline.com", "services.arcgisonline.com", "basemaps.cartocdn.com")
    host = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).netloc
    if host not in allowed:
        raise HTTPException(status_code=403, detail="host no permitido")
    fetcher = getattr(request.app.state, "fetcher", None) or Fetcher()
    key = url
    now = time.time()
    hit = _IMG_CACHE.get(key)
    if hit and now - hit[0] < _IMG_TTL:
        return Response(content=hit[1], media_type=hit[2], headers={"Cache-Control": "public, max-age=86400"})
    try:
        body, ctype = await fetcher.get_bytes(url, retries=1, timeout=20), "image/jpeg"  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"tesela no disponible: {exc}")
    _IMG_CACHE[key] = (now, body, ctype)
    return Response(content=body, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/api/media/photo")
async def media_photo(request: Request, kind: str, id: str) -> dict[str, Any]:
    """Fotografía real del aparato concreto (no una genérica del modelo).

    · aeronave → Planespotters por ICAO24 (hex) y, si no hay, por matrícula.
    · buque      → Wikimedia Commons buscando por nombre + IMO/MMSI, y se marca
                   siempre como «foto de archivo» porque el AIS no publica
                   imágenes del casco.

    El resultado se cachea 6 h: las fotos de un aparato no cambian.
    """
    from urllib.parse import quote

    key = f"{kind}:{id}"
    now = time.time()
    hit = _PHOTO_CACHE.get(key)
    if hit and now - hit[0] < _PHOTO_TTL:
        return {"photo": hit[1], "cached": True}

    fetcher = getattr(request.app.state, "fetcher", None) or Fetcher()
    photo: dict[str, Any] | None = None

    if kind in ("aircraft", "plane"):
        actor = AIRCRAFT.items.get(id) or {}
        hexcode = (str(actor.get("id") or id) or "").strip().lower()
        reg = str(actor.get("registration") or "").strip()
        for path in ([f"hex/{hexcode}"] if len(hexcode) == 6 else []) + ([f"reg/{reg}"] if reg else []):
            try:
                data = await fetcher.get_json(
                    f"https://api.planespotters.net/pub/photos/{path}",
                    retries=1, timeout=20, headers={"User-Agent": _PHOTO_UA},
                )
            except Exception:  # noqa: BLE001 - sin foto no pasa nada
                continue
            photos = (data or {}).get("photos") or []
            if not photos:
                continue
            first = photos[0]
            thumb = (first.get("thumbnail_large") or {}).get("src") or (first.get("thumbnail") or {}).get("src")
            if not thumb:
                continue
            photo = {
                "url": thumb,
                "proxy": "/api/media/img?url=" + quote(thumb, safe=""),
                "credit": first.get("photographer") or "Planespotters",
                "link": first.get("link") or "",
                "source": "Planespotters.net",
                "note": "",
            }
            break

    elif kind in ("vessels", "ships", "boats"):
        actor = VESSELS.items.get(id) or {}
        name = str(actor.get("name") or actor.get("label") or "").strip()
        if name:
            query = f"{name} ship".replace(" ", "+")
            url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
                   "&generator=search&gsrnamespace=6&gsrlimit=3"
                   f"&gsrsearch={quote(query)}"
                   "&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=520")
            try:
                data = await fetcher.get_json(url, retries=1, timeout=20)
            except Exception:  # noqa: BLE001
                data = {}
            pages = ((data or {}).get("query") or {}).get("pages") or {}
            for page in pages.values():
                info = (page.get("imageinfo") or [{}])[0]
                thumb = info.get("thumburl") or info.get("url")
                if not thumb:
                    continue
                meta = info.get("extmetadata") or {}
                artist = (meta.get("Artist") or {}).get("value") or "Wikimedia Commons"
                artist = __import__("re").sub(r"<[^>]+>", "", artist).strip()[:80]
                photo = {
                    "url": thumb,
                    "proxy": "/api/media/img?url=" + quote(thumb, safe=""),
                    "credit": artist,
                    "link": info.get("descriptionurl") or "",
                    "source": "Wikimedia Commons",
                    "note": "foto de archivo: el AIS no publica imagen del buque",
                }
                break

    elif kind in ("trains", "train"):
        actor = TRAINS.items.get(id) or {}
        net = str(actor.get("network") or "")
        line = str(actor.get("line_label") or actor.get("line") or actor.get("route_name") or "").strip()
        # Se busca el material concreto cuando se sabe (serie del tren), si no
        # el tipo de servicio: «AVE» o «Cercanías Madrid» dan fotos reales del
        # modelo que circula, nunca una imagen inventada.
        if net == "amtrak":
            query = f"Amtrak {line} train".strip()
        elif "ave" in line.lower() or "avlo" in line.lower():
            query = "Renfe AVE Serie 103 train"
        elif "alvia" in line.lower():
            query = "Renfe Alvia train"
        elif "regional" in line.lower() or "media" in line.lower():
            query = "Renfe Media Distancia tren"
        else:
            query = f"Renfe Cercanías {line} tren".replace("  ", " ").strip()
        photo = await _commons_photo(fetcher, query, note="foto de archivo del material rodante")

    elif kind in ("satellites", "sat"):
        actor = SATCAT.sats.get(str(id)) or {}
        name = str(actor.get("name") or actor.get("norad_name") or id).strip()
        photo = await _commons_photo(fetcher, f"{name} satellite", note="foto de archivo del satélite")

    elif kind in ("cameras", "camera"):
        actor = CAMERAS.get(id)
        if actor:
            photo = {
                "url": f"/api/cameras/{__import__('urllib.parse', fromlist=['quote']).quote(id, safe='')}/frame",
                "proxy": f"/api/cameras/{__import__('urllib.parse', fromlist=['quote']).quote(id, safe='')}/frame",
                "credit": str(actor.get("network_label") or actor.get("network") or "cámara pública"),
                "link": str(actor.get("url") or ""),
                "source": "fotograma en vivo",
                "note": "imagen actual de la cámara",
            }

    _PHOTO_CACHE[key] = (now, photo)
    if len(_PHOTO_CACHE) > 800:
        for stale in sorted(_PHOTO_CACHE, key=lambda k: _PHOTO_CACHE[k][0])[:300]:
            _PHOTO_CACHE.pop(stale, None)
    return {"photo": photo, "cached": False}


# hosts de los bancos de fotos: el proxy solo sirve desde estos
_PHOTO_HOSTS = (
    "plnspttrs.net", "planespotters.net",
    "wikimedia.org", "wikipedia.org",
)
_IMG_CACHE: dict[str, tuple[float, bytes, str]] = {}
_IMG_TTL = 24 * 3600
_IMG_MAX_BYTES = 3 * 1024 * 1024


@router.get("/api/media/img")
async def media_img(request: Request, url: str) -> Response:
    """Sirve una fotografía de un banco abierto, cacheada en memoria.

    Hace falta un proxy porque los bancos de fotos bloquean el *hotlinking* y
    porque así la imagen viaja por el mismo origen que la app (sin CORS ni
    referrer del usuario). Solo se permiten los hosts de la lista blanca.
    """
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _PHOTO_HOSTS):
        raise HTTPException(status_code=400, detail="host de imagen no permitido")

    now = time.time()
    hit = _IMG_CACHE.get(url)
    if hit and now - hit[0] < _IMG_TTL:
        return Response(content=hit[1], media_type=hit[2],
                        headers={"Cache-Control": "public, max-age=86400"})

    fetcher = getattr(request.app.state, "fetcher", None) or Fetcher()
    try:
        resp = await fetcher.get_bytes(url, headers={"User-Agent": _PHOTO_UA}, timeout=25)
    except TypeError:
        # el fetcher antiguo no tiene get_bytes: se usa httpx directo
        import httpx

        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": _PHOTO_UA})
            r.raise_for_status()
            resp = r.content
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"no se pudo descargar la imagen: {exc}") from exc

    if not isinstance(resp, (bytes, bytearray)):
        resp = getattr(resp, "content", b"")
    data = bytes(resp)
    if not data or len(data) > _IMG_MAX_BYTES:
        raise HTTPException(status_code=502, detail="imagen vacía o demasiado grande")
    mime = _image_mime(data) or "image/jpeg"

    _IMG_CACHE[url] = (now, data, mime)
    if len(_IMG_CACHE) > 120:
        for stale in sorted(_IMG_CACHE, key=lambda k: _IMG_CACHE[k][0])[:40]:
            _IMG_CACHE.pop(stale, None)
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "public, max-age=86400"})


# --------------------------------------------------------------------------- #
# canal en vivo (un solo flujo para toda la app)
# --------------------------------------------------------------------------- #
@router.get("/api/stream")
async def api_stream(request: Request):
    """SSE: `hello` al conectar, `update` cuando cambia una capa, `event` con
    los sucesos nuevos, `alert` con las alertas del motor y `ping` cada 15 s."""
    from fastapi.responses import StreamingResponse
    from ..livehub import stream

    return StreamingResponse(
        stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/api/links")
async def links_health() -> dict[str, Any]:
    """Estado de los enlaces públicos según el guardián externo."""
    import json as _json

    path = ROOT / "data" / "health_links.json"
    if not path.exists():
        return {"links": {}, "note": "el guardián aún no ha pasado (scripts/guardian.py)"}
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"links": {}, "note": "estado ilegible"}


@router.get("/api/trains/index")
async def trains_index() -> dict[str, Any]:
    """Salud del índice GTFS de Renfe (paradas, viajes, avisos activos)."""
    idx = _train_index()
    data = idx.stats()
    data["alerts_sample"] = [a.get("text", "")[:160] for a in (idx.alerts or [])[:5]]
    return data


@router.get("/api/poll")
async def api_poll(request: Request, since: int = Query(0, ge=0), wait: int = Query(18, ge=0, le=25)) -> dict[str, Any]:
    """Long-polling del canal en vivo (atraviesa cualquier proxy; ver api/stream.py)."""
    from .stream import api_poll as _poll

    return await _poll(request, since, wait)


@router.get("/api/stream/stats")
async def api_stream_stats() -> dict[str, Any]:
    from ..livehub import HUB

    return HUB.stats()


@router.get("/api/live/trains")
async def live_trains(bbox: str | None = None, limit: int = Query(20000, le=40000)) -> dict[str, Any]:
    """Trenes de Renfe en vivo (GTFS-RT). Vacío cuando no hay servicio."""
    data = TRAINS.geojson(_parse_bbox(bbox), limit)
    data["stats"] = TRAINS.stats()
    return data


@router.get("/api/live/satellites")
async def live_satellites() -> dict[str, Any]:
    sats_mod.propagate_all()
    data = SATCAT.geojson()
    data["stats"] = SATCAT.stats()
    return data


# --------------------------------------------------------------------------- #
# cámaras públicas abiertas
# --------------------------------------------------------------------------- #
@router.get("/api/cameras")
async def cameras_list(
    bbox: str | None = None,
    network: str | None = Query(None, description="tfl | caltrans | nyc | digitraffic"),
    limit: int = Query(20000, le=40000),
    request: Request = None,  # type: ignore[assignment]
    gzip_level: int = Query(6, ge=0, le=9, include_in_schema=False),
) -> Response:
    """Catálogo de cámaras abiertas como GeoJSON, con el recuento por red.

    Se sirve comprimido: son ~8 800 cámaras y el JSON sin comprimir rozaba los
    5 MB (y se pide cada 20 s). Con gzip baja a ~500 KB sin tocar el formato:
    el navegador lo descomprime solo.
    """
    import gzip as _gzip
    import json as _json

    data = CAMERAS.geojson(_parse_bbox(bbox), network, limit)
    data["stats"] = CAMERAS.stats()
    raw = _json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # Solo se comprime si el cliente lo anuncia (navegadores y curl --compressed).
    # Herramientas sin negociación (scripts, smoke) reciben el JSON tal cual.
    acepta = "gzip" if request is not None else ""
    if request is not None:
        acepta = request.headers.get("accept-encoding", "")
    if "gzip" in acepta and len(raw) > 1024:
        return Response(
            content=_gzip.compress(raw, gzip_level),
            media_type="application/json",
            headers={
                "Content-Encoding": "gzip",
                "Cache-Control": "public, max-age=20",
                "Vary": "Accept-Encoding",
            },
        )
    return Response(
        content=raw,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=20", "Vary": "Accept-Encoding"},
    )


@router.get("/api/cameras/networks")
async def cameras_networks() -> dict[str, Any]:
    return {"networks": list(CAMERAS.networks().values()), **CAMERAS.stats()}


@router.get("/api/cameras/{cam_id}")
async def camera_detail(cam_id: str) -> dict[str, Any]:
    cam = CAMERAS.get(cam_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="cámara no encontrada en el catálogo")
    return {"camera": cam, "frame_url": f"/api/cameras/{cam_id}/frame"}


# --------------------------------------------------------------------------- #
# ficha del lugar: qué hay donde pinchas
# --------------------------------------------------------------------------- #
_GEO_LAND: dict[str, Any] = {}


def _geo(name: str) -> dict[str, Any]:
    """Carga perezosa y cacheada de las capas Natural Earth del backend."""
    if name not in _GEO_LAND:
        files = {
            "countries": "ne_110m_admin_0_countries.geojson",
            # 10m: 7.342 núcleos urbanos, para que «lugar más cercano» sea útil
            # también fuera de las grandes capitales
            "places": "places_10m.geojson",
        }
        path = Path(settings.geo_dir) / files[name]
        with path.open("rb") as fh:
            _GEO_LAND[name] = json.load(fh)
    return _GEO_LAND[name]


def _point_in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray casting sobre un anillo [lon, lat] (suficiente para Natural Earth)."""
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _country_at(lat: float, lon: float) -> dict[str, Any] | None:
    for feat in _geo("countries").get("features", []):
        geom = feat.get("geometry") or {}
        type_ = geom.get("type")
        polys = geom.get("coordinates") or []
        if type_ == "Polygon":
            polys = [polys]
        for poly in polys:
            if poly and _point_in_ring(lat, lon, [tuple(p[:2]) for p in poly[0]]):
                props = feat.get("properties") or {}
                return {
                    "name": props.get("NAME_ES") or props.get("NAME") or "",
                    "iso": props.get("ISO_A2") or "",
                    "continent": props.get("CONTINENT") or "",
                }
    return None


def _num_es(value: float, dec: int = 1) -> str:
    """Formato español: coma decimal (10,2 km)."""
    return f"{value:.{dec}f}".replace(".", ",")


def _nearest_place(lat: float, lon: float) -> dict[str, Any] | None:
    from ..models import haversine_m

    best = None
    for feat in _geo("places").get("features", []):
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        d = haversine_m(lat, lon, coords[1], coords[0])
        if best is None or d < best[0]:
            props = feat.get("properties") or {}
            best = (
                d,
                {
                    "name": props.get("NAME") or props.get("NAMEPAR") or "",
                    "kind": props.get("FEATURECLA") or "",
                    "region": props.get("ADM1NAME") or "",
                    "population": props.get("POP_MAX") or 0,
                    "lat": coords[1],
                    "lon": coords[0],
                    "distance_km": round(d / 1000.0, 1),
                },
            )
    return best[1] if best else None


@router.get("/api/layers")
async def layers_summary(request: Request) -> dict[str, Any]:
    """Recuento de absolutamente todo lo que la app puede pintar ahora mismo.

    Es lo que la interfaz muestra al lado de cada capa y categoría, para que se
    vea de un vistazo cuántos elementos hay y que ninguno se queda oculto.
    """
    store = _store(request)
    stats = await store.stats()
    by_category = {k: int(v) for k, v in (stats.get("by_category") or {}).items()}
    cams = CAMERAS.items
    redes: dict[str, dict[str, Any]] = {}
    for cam in cams.values():
        key = str(cam.get("network") or "otros")
        slot = redes.setdefault(
            key,
            {
                "label": cam.get("network_label") or key,
                "country": cam.get("country") or "",
                "count": 0,
                "online": 0,
            },
        )
        slot["count"] += 1
        if cam.get("online"):
            slot["online"] += 1
    return {
        "events": {
            "total": int(stats.get("events") or 0),
            "last_24h": int(stats.get("events_24h") or 0),
            "by_category": by_category,
            "window_hours": 24,
        },
        "aircraft": len(AIRCRAFT.items),
        "vessels": len(VESSELS.items),
        "satellites": len(SATCAT.sats),
        "air": len(AIR.items),
        "trains": len(TRAINS.items),
        "cameras": {"total": len(cams), "networks": redes},
        "places": _PLACES_CACHE.get("count") or _places_layer()["count"],
        "fences": len(getattr(request.app.state, "engine", None).fences)
        if getattr(request.app.state, "engine", None) is not None
        else 0,
        "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(
            timespec="seconds"
        ),
    }


@router.get("/api/where")
async def where(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(25.0, ge=0.2, le=500),
    limit: int = Query(200, ge=1, le=400),
    since_hours: int = Query(168, ge=1, le=720),
) -> dict[str, Any]:
    """Todo lo que hay en un punto del mapa.

    Es el destino del clic en cualquier lugar: devuelve país y núcleo urbano más
    cercano (Natural Earth), y cuenta lo que hay dentro del radio en el almacén
    (eventos) y en memoria (aeronaves, buques, satélites, cámaras, aire).
    """
    from ..models import haversine_m

    store = _store(request)
    radius_m = radius_km * 1000.0
    dlat = radius_km / 111.32
    dlon = radius_km / max(0.15, 111.32 * abs(__import__("math").cos(__import__("math").radians(lat))))
    bbox = (lon - dlon, lat - dlat, lon + dlon, lat + dlat)

    events = await store.query_bbox(bbox, since_hours=since_hours, limit=1200)
    near_events = []
    for ev in events:
        d = haversine_m(lat, lon, ev.lat, ev.lon)
        if d <= radius_m:
            near_events.append((d, ev))
    near_events.sort(key=lambda pair: pair[0])

    actors: dict[str, list[dict[str, Any]]] = {
        "aircraft": [], "vessels": [], "satellites": [], "air": [], "trains": []
    }
    sources = (
        ("aircraft", AIRCRAFT.items.values()),
        ("vessels", VESSELS.items.values()),
        ("satellites", SATCAT.sats.values()),
        ("air", AIR.items.values()),
        ("trains", TRAINS.items.values()),
    )
    for kind, values in sources:
        for item in values:
            alat, alon = item.get("lat"), item.get("lon")
            if alat is None or alon is None:
                continue
            if haversine_m(lat, lon, alat, alon) <= radius_m:
                actors[kind].append(item)

    cams = []
    for cam in CAMERAS.items.values():
        if haversine_m(lat, lon, cam.get("lat") or 0, cam.get("lon") or 0) <= radius_m:
            cams.append(cam)

    # Incidencias de tráfico DGT: los eventos de la fuente «dgt» llevan la
    # carretera, el punto kilométrico y la causa en el payload.
    traffic: list[dict[str, Any]] = []
    for d, ev in near_events:
        if ev.source != "dgt":
            continue
        pay = ev.payload if isinstance(ev.payload, dict) else {}
        traffic.append({
            "id": ev.id,
            "title": pay.get("title") or ev.title,
            "sub": " · ".join(str(x) for x in (
                pay.get("road") or pay.get("roadName"),
                f"km {pay.get('km')}" if pay.get("km") not in (None, "") else "",
                pay.get("cause") or ev.category,
                f"{_num_es(d / 1000)} km",
            ) if x),
            "lat": ev.lat,
            "lon": ev.lon,
            "distance_km": round(d / 1000, 1),
            "kind": "traffic",
            "severity": ev.severity_label or "",
        })

    country = _country_at(lat, lon)
    place = _nearest_place(lat, lon)

    def ev_item(d: float, ev) -> dict[str, Any]:
        return {
            "id": ev.id,
            "title": ev.title,
            "sub": " · ".join(
                str(x) for x in (ev.source.upper(), f"{_num_es(d / 1000)} km") if x
            ),
            "category": ev.category,
            "source": ev.source,
            "lat": ev.lat,
            "lon": ev.lon,
            "distance_km": round(d / 1000, 1),
            "ts": ev.event_time or "",
            "severity": ev.severity_label or "",
        }

    def actor_item(item: dict[str, Any], kind: str) -> dict[str, Any]:
        name = (
            item.get("callsign") or item.get("name") or item.get("title")
            or item.get("mmsi") or item.get("norad") or item.get("id")
        )
        if kind == "air":
            name = f"Sensor de aire {name}"
        return {
            "id": str(item.get("id")),
            "title": str(name or item.get("id")),
            "sub": kind_label(kind, item),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "kind": kind,
        }

    def cam_item(cam: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(cam.get("id")),
            "title": str(cam.get("name") or cam.get("id")),
            "sub": " · ".join(str(x) for x in (cam.get("network_label"), cam.get("place")) if x),
            "lat": cam.get("lat"),
            "lon": cam.get("lon"),
            "kind": "cameras",
        }

    counts = {
        "events": len(near_events),
        "aircraft": len(actors["aircraft"]),
        "vessels": len(actors["vessels"]),
        "satellites": len(actors["satellites"]),
        "air": len(actors["air"]),
        "trains": len(actors["trains"]),
        "traffic": len(traffic),
        "cameras": len(cams),
    }
    def qty(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}" if n else ""

    summary_bits = [b for b in (
        f"{country['name']}" if country else "",
        (
            f"{place['name']}"
            + (f" ({place['region']})" if place.get("region") else "")
            + f" a {_num_es(place['distance_km'])} km"
        )
        if place
        else "",
        qty(counts["events"], "evento (7 días)", "eventos (7 días)"),
        qty(counts["aircraft"], "aeronave", "aeronaves"),
        qty(counts["vessels"], "buque", "buques"),
        qty(counts["cameras"], "cámara", "cámaras"),
        qty(counts["trains"], "tren", "trenes"),
        qty(counts["traffic"], "incidencia de tráfico", "incidencias de tráfico"),
        qty(counts["air"], "sensor de aire", "sensores de aire"),
    ) if b]

    return {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "country": country,
        "place": place,
        "counts": counts,
        "summary": " · ".join(summary_bits) or "zona sin datos en el radio consultado",
        "events": [ev_item(d, ev) for d, ev in near_events[:limit]],
        "aircraft": [actor_item(a, "aircraft") for a in actors["aircraft"][:limit]],
        "vessels": [actor_item(a, "vessels") for a in actors["vessels"][:limit]],
        "satellites": [actor_item(a, "satellites") for a in actors["satellites"][:limit]],
        "air": [actor_item(a, "air") for a in actors["air"][:limit]],
        "trains": [actor_item(a, "trains") for a in actors["trains"][:limit]],
        "traffic": traffic[:limit],
        "cameras": [cam_item(c) for c in cams[:limit]],
        "window_hours": since_hours,
    }


def kind_label(kind: str, item: dict[str, Any]) -> str:
    if kind == "aircraft":
        return " · ".join(str(x) for x in (item.get("type"), f"{item.get('altitude_ft') or 0:.0f} ft") if x)
    if kind == "vessels":
        return " · ".join(str(x) for x in (item.get("ship_type"), f"{(item.get('speed_kn') or 0):.1f} kn") if x)
    if kind == "satellites":
        groups = item.get("groups") or ([item.get("group")] if item.get("group") else [])
        return " · ".join(str(x) for x in (", ".join(groups[:2]), f"{(item.get('altitude_km') or 0):.0f} km") if x)
    if kind == "trains":
        return " · ".join(str(x) for x in (
            item.get("line") or item.get("route"),
            item.get("destination") or item.get("headsign"),
            f"{(item.get('delay_s') or 0) / 60:.0f} min de retraso"
            if (item.get("delay_s") or 0) >= 60 else "puntual",
            item.get("operator"),
        ) if x)
    if kind == "air":
        pm = item.get("pm25") if item.get("pm25") is not None else item.get("pm10")
        bits = ["PM " + ("sin dato" if pm is None else f"{pm:.1f} µg/m³"), item.get("level") or ""]
        return " · ".join(b for b in bits if b)
    return ""


@router.get("/api/tiles/catalogue")
async def tiles_catalogue() -> dict:
    """Estilos de fondo de mapa disponibles (calles, oscuro, claro, satélite)."""
    return tiles_mod.catalogue()


@router.get("/api/tiles/{style}/{z}/{x}/{y}.{ext}")
async def tile(style: str, z: int, x: int, y: int, ext: str, request: Request) -> Response:
    """Tesela de mapa servida por el backend (con caché en disco).

    Se valida z/x/y y el estilo; cualquier tesela fuera de rango se rechaza sin
    tocar la red para que un cliente defectuoso no nos haga amplificar tráfico.
    """
    spec = tiles_mod.STYLES.get(style)
    if spec is None:
        raise HTTPException(status_code=404, detail="estilo de mapa desconocido")
    if not (0 <= z <= spec["maxzoom"]):
        raise HTTPException(status_code=404, detail="zoom fuera de rango")
    limit = 2 ** z
    if not (0 <= x < limit and 0 <= y < limit):
        raise HTTPException(status_code=404, detail="coordenada de tesela fuera de rango")
    try:
        body = await tiles_mod.fetch_tile(style, z, x, y)
    except tiles_mod.UnknownStyle:
        raise HTTPException(status_code=404, detail="estilo de mapa desconocido") from None
    except Exception as exc:  # noqa: BLE001 - el proveedor puede fallar: se informa
        raise HTTPException(status_code=502,
                            detail=f"proveedor de mapa no disponible: {str(exc)[:90]}") from exc
    media = "image/jpeg" if spec["ext"] == "jpg" else "image/png"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Cache-Control": "public, max-age=604800, immutable",
            "X-Aegis-Tiles": f"{style} {z}/{x}/{y}",
        },
    )


def _image_mime(body: bytes) -> str:
    """Tipo real de la imagen: las redes mezclan JPEG, GIF y PNG (el SCT, por
    ejemplo, sirve GIF en parte de sus cámaras). Servirlas como image/jpeg
    funciona por sniffing del navegador, pero es incorrecto."""
    if body[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


@router.get("/api/cameras/{cam_id}/frame")
async def camera_frame(request: Request, cam_id: str) -> Response:
    """Última imagen de la cámara, servida desde el backend.

    El proxy evita contenido mixto (http dentro de https), CORS y fugas de
    referrer al operador; además cachea 3 s para que varios visores abiertos no
    machaquen la misma URL.
    """
    cam = CAMERAS.get(cam_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="cámara no encontrada")
    url = cam.get("image") or ""
    now = time.time()
    cached = _FRAME_CACHE.get(cam_id)
    if cached and now - cached[0] < 3.0:
        return Response(content=cached[1], media_type=_image_mime(cached[1]),
                        headers={"Cache-Control": "no-store", "X-Aegis-Cache": "hit"})
    fetcher = getattr(request.app.state, "fetcher", None) or Fetcher()
    try:
        body = await fetcher.get_bytes(url, retries=2, timeout=20,
                                       headers={"Accept": "image/jpeg,image/*"})
    except Exception as exc:  # noqa: BLE001 - cámara caída: se informa, no se rompe
        raise HTTPException(status_code=502, detail=f"la cámara no responde: {str(exc)[:120]}") from exc
    if not body or len(body) < 200:
        raise HTTPException(status_code=502, detail="la cámara devolvió una imagen vacía")
    _FRAME_CACHE[cam_id] = (now, body)
    if len(_FRAME_CACHE) > 400:
        for key in sorted(_FRAME_CACHE, key=lambda k: _FRAME_CACHE[k][0])[:150]:
            _FRAME_CACHE.pop(key, None)
    return Response(content=body, media_type=_image_mime(body),
                    headers={"Cache-Control": "no-store", "X-Aegis-Cache": "miss"})


# --------------------------------------------------------------------------- #
# origen y destino de los transportes
# --------------------------------------------------------------------------- #
_ROUTE_CACHE: dict[str, Any] = {}
_ROUTE_TTL = 6 * 3600


@router.get("/api/route/{callsign}")
async def flight_route(callsign: str) -> dict[str, Any]:
    """Ruta del vuelo (origen → destino) a partir del indicativo.

    Fuente abierta y sin clave: adsbdb.com. Se cachea 6 h por indicativo.
    """
    cs = callsign.strip().upper()
    if not cs or len(cs) > 10:
        raise HTTPException(status_code=400, detail="indicativo no válido")
    hit = _ROUTE_CACHE.get(cs)
    if hit and time.time() - hit["t"] < _ROUTE_TTL:
        return hit["data"]

    import httpx

    url = f"https://api.adsbdb.com/v0/callsign/{cs}"
    data: dict[str, Any] = {"callsign": cs, "origin": None, "destination": None,
                            "airline": None, "source": "adsbdb.com", "found": False}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=UA) as client:
            r = await client.get(url)
        if r.status_code == 200:
            payload = r.json().get("response") or {}
            route = payload.get("flightroute") or {}
            airline = route.get("airline") or {}

            def airport(node: dict[str, Any] | None) -> dict[str, Any] | None:
                if not node:
                    return None
                return {
                    "iata": node.get("iata_code") or "",
                    "icao": node.get("icao_code") or "",
                    "name": node.get("name") or "",
                    "city": node.get("municipality") or "",
                    "country": node.get("country_name") or "",
                    "lat": node.get("latitude"),
                    "lon": node.get("longitude"),
                }

            data["origin"] = airport(route.get("origin"))
            data["destination"] = airport(route.get("destination"))
            data["airline"] = airline.get("name") if airline else None
            data["found"] = bool(data["origin"] or data["destination"])
    except Exception as exc:  # noqa: BLE001 - la ruta es un extra, nunca bloquea la ficha
        data["error"] = str(exc)[:120]

    _ROUTE_CACHE[cs] = {"t": time.time(), "data": data}
    return data


def _train_index():
    """Índice GTFS de Renfe del proceso (registrado por main al arrancar)."""
    global _GTFS_FALLBACK
    idx = APP_STATE.get("gtfs")
    if idx is None:
        from ..ingest import gtfs as gtfs_mod

        idx = gtfs_mod.GtfsIndex(ROOT)
        try:
            idx.load()
        except Exception:  # noqa: BLE001
            pass
        _GTFS_FALLBACK = idx
        APP_STATE["gtfs"] = idx
    return idx


def _train_itinerary(actor: dict[str, Any], max_stops: int = 60) -> dict[str, Any]:
    """Itinerario del tren con nombres y la posicion de cada parada.

    Los códigos de parada se traducen con el GTFS estático de Renfe; si el
    viaje no tiene itinerario (Cercanías), se devuelve igualmente destino y
    próxima parada, que es lo que el viajero necesita.
    """
    idx = _train_index()
    trip_id = str(actor.get("trip_id") or "")
    info = idx.trip_info(trip_id) if idx else {}
    stops = []
    for sid in (info.get("stops") or [])[:max_stops]:
        st = (idx.stops.get(sid) or {}) if idx else {}
        stops.append({"id": sid, "name": st.get("name") or sid, "lat": st.get("lat"), "lon": st.get("lon")})
    next_id = str(actor.get("next_stop") or "")
    return {
        "trip_id": trip_id,
        "line": info.get("route") or actor.get("line") or "",
        "line_label": actor.get("line_label") or (info.get("label") or ""),
        "destination": info.get("headsign") or actor.get("destination") or "",
        "next_stop": {"id": next_id, "name": (idx.stop_name(next_id) if idx and next_id else "") or actor.get("next_stop_name") or ""},
        "stops": stops,
        "has_geometry": bool(stops and all(s["lat"] is not None for s in stops[:2])),
        "alert": idx.alert_for(info.get("route") or "") if idx else "",
    }


@router.get("/api/live/{kind}/{aid}")
async def live_detail(kind: str, aid: str) -> dict[str, Any]:
    """Ficha completa de un elemento móvil: último estado + métricas de su estela."""
    if kind == "satellites":
        try:
            info = sats_mod.satellite_detail(int(aid))
        except ValueError:
            info = None
        if info is None:
            raise HTTPException(status_code=404, detail="satélite no encontrado en el catálogo")
        return info
    layer = _live_layer(kind)
    if layer is None:
        raise HTTPException(status_code=404, detail=f"capa desconocida: {kind}")
    detail = layer.detail(aid)
    if detail is None:
        raise HTTPException(status_code=404, detail="elemento no encontrado (¿fuera de cobertura?)")

    actor = detail.get("actor") or {}
    if kind == "aircraft":
        cs = (actor.get("callsign") or "").strip()
        if cs:
            try:
                detail["route"] = await flight_route(cs)
            except Exception:  # noqa: BLE001
                detail["route"] = None
    elif kind == "vessels":
        mmsi = actor.get("mmsi") or actor.get("id")
        meta = None
        try:
            from ..ingest.ais import vessel_meta

            meta = vessel_meta(int(mmsi)) if mmsi else None
        except Exception:  # noqa: BLE001
            meta = None
        detail["port"] = {
            "destination": (meta or {}).get("destination") or actor.get("destination") or "",
            "eta": (meta or {}).get("eta") or actor.get("eta") or "",
            "origin": (meta or {}).get("origin") or "",
            "coverage": "Báltico · Digitraffic (AIS abierto)",
        }
    elif kind in ("trains", "trenes"):
        detail["itinerary"] = _train_itinerary(actor)
    return detail


@router.get("/api/live/{kind}/{aid}/track")
async def live_track(kind: str, aid: str, minutes: float = Query(60, ge=1, le=240)) -> dict[str, Any]:
    """Estela del elemento como LineString para dibujar la trayectoria."""
    if kind == "satellites":
        try:
            coords = sats_mod.ground_track(int(aid), minutes=int(minutes))
        except ValueError:
            coords = []
        if not coords:
            raise HTTPException(status_code=404, detail="sin trayectoria orbital para ese NORAD")
        return {"kind": "satellites", "id": aid, "minutes": minutes,
                "points": len(coords),
                "geometry": {"type": "LineString", "coordinates": coords}}
    layer = _live_layer(kind)
    if layer is None:
        raise HTTPException(status_code=404, detail=f"capa desconocida: {kind}")
    track = layer.track(aid, minutes=minutes)
    if track is None:
        raise HTTPException(status_code=404, detail="sin trayectoria para ese elemento")
    return track


@router.get("/api/live/satellites/{norad}")
async def satellite_detail(norad: int) -> dict[str, Any]:
    """Ficha orbital: elementos TLE, apogeo/perigeo, velocidad y huella en tierra."""
    info = sats_mod.satellite_detail(norad)
    if info is None:
        raise HTTPException(status_code=404, detail="satélite no encontrado en el catálogo")
    return info


@router.get("/api/live/satellites/{norad}/orbit")
async def satellite_orbit(norad: int, minutes: int = Query(90, ge=10, le=200)) -> dict[str, Any]:
    track = sats_mod.ground_track(norad, minutes=minutes)
    if not track:
        raise HTTPException(status_code=404, detail="satélite no encontrado en el catálogo")
    return {
        "norad": norad,
        "minutes": minutes,
        "geometry": {"type": "LineString", "coordinates": track},
    }


# --------------------------------------------------------------------------- #
# geofences
# --------------------------------------------------------------------------- #
@router.get("/api/fences")
async def list_fences(request: Request) -> dict[str, Any]:
    engine = _engine(request)
    return {"engine": engine.status()["engine"], "fences": engine.geojson(),
            "definitions": [f.to_dict() for f in engine.fences.values()]}


@router.post("/api/fences")
async def create_fence(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    engine = _engine(request)
    try:
        lat = float(payload["lat"])
        lon = float(payload["lon"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=422, detail="lat/lon obligatorios")
    radius = float(payload.get("radius_m") or 200_000)
    fence = await engine.add_fence(
        {
            "id": payload.get("id"),
            "name": payload.get("name") or f"AOI {lat:.2f},{lon:.2f}",
            "kind": "circle",
            "lat": lat,
            "lon": lon,
            "radius_m": radius,
            "rules": payload.get("rules") or list(AVAILABLE_RULES),
        }
    )
    # feedback inmediato: cuántos objetos hay dentro ahora mismo
    inside_air = sum(
        1 for a in AIRCRAFT.items.values()
        if a.get("lat") is not None and fence.contains(a["lat"], a["lon"])
    )
    inside_sea = sum(
        1 for v in VESSELS.items.values()
        if v.get("lat") is not None and fence.contains(v["lat"], v["lon"])
    )
    await engine.emit_snapshot(fence, inside_air, inside_sea)
    return {
        "ok": True,
        "fence": fence.to_dict(),
        "geojson": fence.to_geojson(),
        "inside": {"aircraft": inside_air, "vessels": inside_sea},
    }


@router.delete("/api/fences/{fence_id}")
async def delete_fence(fence_id: str, request: Request) -> dict[str, Any]:
    ok = await _engine(request).delete_fence(fence_id)
    if not ok:
        raise HTTPException(status_code=404, detail="AOI no encontrado")
    return {"ok": True}


@router.get("/api/alerts")
async def list_alerts(request: Request, limit: int = Query(100, le=500)) -> dict[str, Any]:
    store = _store(request)
    engine = _engine(request)
    return {
        "alerts": await store.list_alerts(limit),
        "live": engine.alerts[-60:],
        "counters": engine.counters,
    }


# --------------------------------------------------------------------------- #
# AI
# --------------------------------------------------------------------------- #
@router.get("/api/ai/status")
async def ai_status() -> dict[str, Any]:
    status = await probe(force=True)
    return {"provider": status.provider, "model": status.model,
            "available": status.available, "detail": status.detail}


@router.post("/api/ai/briefing")
async def ai_briefing(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    store = _store(request)
    box = payload.get("bbox") or [-180.0, -85.0, 180.0, 85.0]
    box = tuple(float(v) for v in box)
    hours = float(payload.get("hours") or 24)
    categories = payload.get("categories") or None
    limit = int(payload.get("limit") or 400)
    events = await store.query_bbox(box, categories=categories, since_hours=hours, limit=limit)
    return await build_briefing(
        events,
        bbox=list(box),
        window=payload.get("window") or f"{int(hours)}h",
        use_llm=bool(payload.get("use_llm", True)),
    )


# --------------------------------------------------------------------------- #
# basemap (self-hosted so the app renders with zero external tile providers)
# --------------------------------------------------------------------------- #
_GEO_CACHE: dict[str, Any] = {}


_PLACES_CACHE: dict[str, Any] = {}


def _places_layer() -> dict[str, Any]:
    """7.342 núcleos urbanos (Natural Earth 1:10m) con etiqueta y país.

    Se sirven solo las propiedades que usa el mapa (nombre, rango, población y
    país) y las coordenadas redondeadas: el resto de campos triplicaría el peso.
    """
    if "layer" in _PLACES_CACHE:
        return _PLACES_CACHE["layer"]
    # El índice completo (7.342 núcleos) NO se retiene en RAM: se midió que
    # sumaba ~40 MB al proceso y solo se pide una vez por sesión de navegador.
    path = Path(settings.geo_dir) / "places_10m.geojson"
    with path.open("rb") as fh:
        data = json.load(fh)
    features = []
    for feat in data.get("features", []):
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        props = feat.get("properties") or {}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(coords[0], 4), round(coords[1], 4)]},
                "properties": {
                    "name": props.get("NAME") or "",
                    "rank": props.get("SCALERANK"),
                    "pop": props.get("POP_MAX") or 0,
                    "country": props.get("ADM0NAME") or "",
                    "region": props.get("ADM1NAME") or "",
                    "kind": props.get("FEATURECLA") or "",
                },
            }
        )
    layer = {
        "type": "FeatureCollection",
        "count": len(features),
        "source": "Natural Earth 1:10m · populated places",
        "features": features,
    }
    _PLACES_CACHE["count"] = len(features)
    return layer


_RAIL_CACHE: dict[str, Any] = {}


def _railroads_filtered(bbox: str | None, major: bool) -> dict:
    """Ferrocarril mundial filtrado por ventana visible.

    Enviar las 25 000 líneas de una vez obliga al motor del mapa a teselarlas
    todas (memoria y CPU del navegador). Se sirven solo las que caen dentro de
    la vista y, a escala continental, únicamente las troncales.
    """
    path = Path(settings.geo_dir) / "railroads.geojson"
    if "data" not in _RAIL_CACHE:
        raw = json.loads(path.read_text(encoding="utf-8"))
        feats = []
        for f in raw.get("features") or []:
            geom = f.get("geometry") or {}
            lines = geom.get("coordinates") or []
            if geom.get("type") == "LineString":
                lines = [lines]
            xs: list[float] = []
            ys: list[float] = []
            for line in lines:
                for c in line:
                    xs.append(c[0]); ys.append(c[1])
            if not xs:
                continue
            feats.append((min(xs), min(ys), max(xs), max(ys), f))
        _RAIL_CACHE["data"] = feats
    feats = _RAIL_CACHE["data"]
    if not bbox:
        return {"type": "FeatureCollection", "features": [f for *_, f in feats]}
    try:
        w, s_, e, n = (float(x) for x in bbox.split(","))
    except Exception:  # noqa: BLE001 - bbox mal formado: se devuelve todo
        return {"type": "FeatureCollection", "features": [f for *_, f in feats]}
    # Se ordenan de mayor a menor recorrido: si hay que recortar, se conservan
    # las líneas que de verdad dibujan la red (las esquirlas de 2 puntos no
    # aportan nada a la vista y sí cuestan teselado).
    def puntos(f: dict) -> int:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "LineString":
            return len(coords)
        return sum(len(line) for line in coords)

    candidatas = []
    for x0, y0, x1, y1, f in feats:
        if x1 < w or x0 > e or y1 < s_ or y0 > n:
            continue
        if major and (f.get("properties") or {}).get("c") != 1:
            continue
        candidatas.append((puntos(f), f))

    # Tope de puntos totales: el motor del mapa tesela cada segmento en el hilo
    # principal. Con más de ~45 000 puntos la pestaña se queda sin memoria en
    # equipos modestos, así que se recorta por longitud (no se inventa nada).
    MAX_PUNTOS = 45000
    candidatas.sort(key=lambda par: par[0], reverse=True)
    out: list[dict] = []
    total = 0
    for n, f in candidatas:
        if total + n > MAX_PUNTOS and out:
            continue
        out.append(f)
        total += n
        if total >= MAX_PUNTOS:
            break
    return {"type": "FeatureCollection", "features": out}


_ROADS_CACHE: dict[str, Any] = {}


def _roads_filtered(bbox: str | None, major: bool) -> dict:
    """Red viaria mundial (Natural Earth 1:10m) recortada a la vista.

    Igual que con el ferrocarril: solo lo que cae en pantalla y, a escala
    continental, solo autovías y primarias. Se guarda en una caché pequeña
    (la ventana de mapa se repite mucho al hacer zoom y arrastrar).
    """
    key = f"{bbox or 'all'}|{int(major)}"
    if key in _ROADS_CACHE:
        return _ROADS_CACHE[key]
    path = Path(settings.geo_dir) / "roads.geojson.gz"
    if "data" not in _ROADS_CACHE:
        if not path.exists():
            return {"type": "FeatureCollection", "features": []}
        raw = json.loads(gzip.decompress(path.read_bytes()))
        feats = []
        for f in raw.get("features") or []:
            geom = f.get("geometry") or {}
            lines = geom.get("coordinates") or []
            if geom.get("type") == "LineString":
                lines = [lines]
            xs: list[float] = []
            ys: list[float] = []
            for line in lines:
                for c in line:
                    xs.append(c[0]); ys.append(c[1])
            if not xs:
                continue
            feats.append((min(xs), min(ys), max(xs), max(ys), f))
        _ROADS_CACHE["data"] = feats
    feats = _ROADS_CACHE["data"]

    def puntos(f: dict) -> int:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "LineString":
            return len(coords)
        return sum(len(line) for line in coords)

    if not bbox:
        cand = [(puntos(f), f) for *_, f in feats]
    else:
        try:
            w, s_, e, n = (float(x) for x in bbox.split(","))
        except Exception:  # noqa: BLE001
            cand = [(puntos(f), f) for *_, f in feats]
        else:
            cand = []
            for x0, y0, x1, y1, f in feats:
                if x1 < w or x0 > e or y1 < s_ or y0 > n:
                    continue
                if major and (f.get("properties") or {}).get("c") != 1:
                    continue
                cand.append((puntos(f), f))
    MAX_PUNTOS = 40000
    cand.sort(key=lambda par: par[0], reverse=True)
    out: list[dict] = []
    total = 0
    for n, f in cand:
        if total + n > MAX_PUNTOS and out:
            continue
        out.append(f)
        total += n
        if total >= MAX_PUNTOS:
            break
    result = {"type": "FeatureCollection", "features": out}
    if len(_ROADS_CACHE) > 40:      # caché acotada: 40 ventanas como mucho
        _ROADS_CACHE.clear()
        _ROADS_CACHE["data"] = feats
    _ROADS_CACHE[key] = result
    return result


@router.get("/api/basemap/infra_view")
async def infra_view(
    bbox: str | None = Query(None, description="w,s,e,n en grados"),
    major: int = Query(0, ge=0, le=1),
    include: str = Query("roads,rail", description="qué redes incluir"),
) -> JSONResponse:
    """Red viaria y ferroviaria de la ventana visible, juntas en una petición."""
    wanted = {x.strip() for x in include.split(",") if x.strip()}
    parts: dict = {}
    if "roads" in wanted:
        parts["roads"] = _roads_filtered(bbox, bool(major))
    if "rail" in wanted:
        parts["rail"] = _railroads_filtered(bbox, bool(major))
    data = {
        "type": "FeatureCollection",
        "parts": parts,
        "counts": {k: len(v.get("features") or []) for k, v in parts.items()},
    }
    return JSONResponse(data, headers={"Cache-Control": "public, max-age=1800"})


@router.get("/api/basemap/railroads_view")
async def railroads_view(
    bbox: str | None = Query(None, description="w,s,e,n en grados"),
    major: int = Query(0, ge=0, le=1),
) -> JSONResponse:
    data = _railroads_filtered(bbox, bool(major))
    return JSONResponse(
        data,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/basemap/{name}")
async def basemap(name: str) -> JSONResponse:
    allowed = {"land", "countries", "places", "coastline", "land50", "railroads", "sealanes"}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="capa no disponible")
    if name == "places":
        return JSONResponse(_places_layer(), headers={"Cache-Control": "public, max-age=86400"})
    if name in _GEO_CACHE:
        return JSONResponse(_GEO_CACHE[name], headers={"Cache-Control": "public, max-age=86400"})
    file_map = {
        "land": "ne_110m_land.geojson",
        "countries": "ne_110m_admin_0_countries.geojson",
        "places": "ne_110m_populated_places.geojson",
        "coastline": "ne_110m_coastline.geojson",
        "land50": "ne_50m_land.geojson",
        # vías que usan los medios que vigilamos: ferrocarril (Natural Earth 10m,
        # todo el mundo) y derrotas marítimas reales (IMF PortWatch, derivadas AIS)
        "railroads": "railroads.geojson",
        "sealanes": "sealanes.geojson",
    }
    path = Path(settings.geo_dir) / file_map[name]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"falta {path.name} en {settings.geo_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    _GEO_CACHE[name] = data
    # las vías no cambian: caché de una semana en el navegador
    max_age = 7 * 86400 if name in ("railroads", "sealanes") else 86400
    return JSONResponse(data, headers={"Cache-Control": f"public, max-age={max_age}"})


# --------------------------------------------------------------------------- #
# websocket: push alerts (Tile38 DETECT stream equivalent)
# --------------------------------------------------------------------------- #
@router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket) -> None:
    await ws.accept()
    engine = ws.app.state.engine
    queue = engine.subscribe()
    try:
        await ws.send_json(
            {
                "type": "hello",
                "engine": engine.status()["engine"],
                "fences": len(engine.fences),
                "recent": engine.alerts[-10:],
            }
        )
        while True:
            try:
                alert = await asyncio.wait_for(queue.get(), timeout=20)
                await ws.send_json({"type": "alert", "alert": alert})
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        engine.unsubscribe(queue)
