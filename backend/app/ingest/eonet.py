"""NASA EONET v3 — natural events (wildfires, storms, volcanoes, ice, floods).

Free, keyless, maintained by NASA's Earth Observatory. Complements NASA FIRMS
(thermal anomalies, needs a free MAP_KEY) because EONET publishes curated
*events* with geometry — points, lines (storm tracks) and polygons (fire
complexes) — so it feeds the map even when no FIRMS key is configured.

Endpoint: https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=20
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import EventRecord, parse_dt
from .client import Fetcher

URL = "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days={days}&limit=300"

# EONET category id -> (our category, human label)
CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "wildfires": ("wildfire", "incendio"),
    "severeStorms": ("disaster", "tormenta severa"),
    "volcanoes": ("disaster", "volcán"),
    "floods": ("disaster", "inundación"),
    "landslides": ("disaster", "deslizamiento"),
    "drought": ("disaster", "sequía"),
    "dustHaze": ("disaster", "polvo/calima"),
    "tempExtremes": ("disaster", "temperatura extrema"),
    "seaLakeIce": ("disaster", "hielo marino"),
    "snow": ("disaster", "nieve"),
    "earthquakes": ("earthquake", "sismo"),
    "manmade": ("disaster", "origen antrópico"),
    "waterColor": ("news", "calidad del agua"),
}

SEVERITY_BY_CATEGORY = {
    "wildfires": ("orange", 3.0),
    "severeStorms": ("orange", 3.5),
    "volcanoes": ("orange", 3.5),
    "floods": ("yellow", 2.5),
    "earthquakes": ("yellow", 3.0),
}


def _centroid(coords: list) -> tuple[float, float]:
    """Centroide aproximado de una lista de pares [lon, lat]."""
    pts = [c for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
    if not pts:
        return 0.0, 0.0
    return (
        sum(float(p[1]) for p in pts) / len(pts),
        sum(float(p[0]) for p in pts) / len(pts),
    )


def parse(payload: dict) -> list[EventRecord]:
    out: list[EventRecord] = []
    for event in payload.get("events") or []:
        geometries = event.get("geometry") or []
        if not geometries:
            continue
        last = geometries[-1]
        gtype = (last.get("type") or "Point")
        coords = last.get("coordinates")
        if not coords:
            continue

        geometry = None
        if gtype == "Point":
            lon, lat = float(coords[0]), float(coords[1])
        elif gtype == "Polygon" and coords and coords[0]:
            lat, lon = _centroid(coords[0])
            geometry = {"type": "Polygon", "coordinates": coords}
        elif gtype == "LineString":
            lat, lon = _centroid(coords)
            geometry = {"type": "LineString", "coordinates": coords}
        else:
            lat, lon = _centroid(coords[0] if isinstance(coords[0], list) else coords)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        cat_ids = [c.get("id", "") for c in event.get("categories") or []]
        cat_id = cat_ids[0] if cat_ids else "manmade"
        category, label = CATEGORY_MAP.get(cat_id, ("disaster", "evento natural"))
        severity_label, severity = SEVERITY_BY_CATEGORY.get(cat_id, ("yellow", 2.0))

        when = parse_dt(last.get("date")) or parse_dt(event.get("closed") or "") or datetime.now(timezone.utc)
        sources = event.get("sources") or []
        url = (sources[0].get("url") if sources else "") or ""
        title = event.get("title") or f"{label} sin nombre"

        out.append(
            EventRecord(
                uid=f"eonet:{event.get('id')}",
                source="eonet",
                category=category,
                subtype=label,
                title=f"{title} · {label}",
                summary=(event.get("description") or "")[:600]
                or f"{label.capitalize()} monitorizado por NASA EONET · {gtype.lower()}",
                lat=lat,
                lon=lon,
                severity=severity,
                severity_label=severity_label,
                url=url,
                event_time=when,
                payload={
                    "eonet_id": event.get("id"),
                    "categories": cat_ids,
                    "geometry_type": gtype,
                    "sources": [s.get("id") for s in sources],
                    "closed": event.get("closed"),
                },
                geometry=geometry,
            )
        )
    return out


async def fetch(fetcher: Fetcher, *, days: int = 20) -> list[EventRecord]:
    payload = await fetcher.get_json(URL.format(days=days), retries=2)
    return parse(payload)
