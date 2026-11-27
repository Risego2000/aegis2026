"""NOAA / National Weather Service — avisos meteorológicos activos (EE. UU.).

Free, keyless (solo pide un User-Agent identificable). Es la fuente oficial de
alertas severas en Estados Unidos: inundaciones, huracanes, incendios forestales
declarados, vientos extremos… Cada alerta trae polígono, severidad y urgencia.

Endpoint: https://api.weather.gov/alerts/active
"""
from __future__ import annotations

from ..models import EventRecord, parse_dt
from .client import Fetcher
from .es import es_nws

URL = "https://api.weather.gov/alerts/active?severity={severity}&status=actual"

SEVERITY_MAP = {          # NWS -> (nuestra etiqueta, score)
    "Extreme": ("red", 4.5),
    "Severe": ("orange", 3.5),
    "Moderate": ("yellow", 2.5),
    "Minor": ("green", 1.5),
    "Unknown": ("green", 1.0),
}

# Tipos que no son desastre natural y ensucian el mapa
SKIP_EVENTS = {"Administrative Message", "Practice/Demo Warning", "Test Message"}

# Avisos que en realidad hablan de fuego (no basta con buscar la palabra "Fire")
FIRE_EVENTS = {
    "Red Flag Warning", "Fire Weather Watch", "Fire Warning", "Wildfire",
    "ExtREME FIRE DANGER", "Evacuation - Immediate", "Evacuation - Warning",
}

MAX_ALERTS = 120          # el feed completo puede traer miles; nos quedamos con lo severo


def _centroid(coords: list) -> tuple[float, float] | None:
    pts = [c for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
    if not pts:
        return None
    # los anillos pueden venir cerrados: el punto repetido no molesta al promedio
    return (sum(float(p[1]) for p in pts) / len(pts), sum(float(p[0]) for p in pts) / len(pts))


def _geometry_point(geometry: dict | None) -> tuple[float, float] | None:
    if not geometry:
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon" and coords:
        return _centroid(coords[0])
    if gtype == "MultiPolygon" and coords:
        ring = coords[0][0] if coords[0] else []
        return _centroid(ring)
    if gtype == "Point" and coords:
        return (float(coords[1]), float(coords[0]))
    return None


def parse(payload: dict, *, limit: int = MAX_ALERTS) -> list[EventRecord]:
    out: list[EventRecord] = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        event_name = props.get("event") or "Alerta meteorológica"
        if event_name in SKIP_EVENTS:
            continue

        point = _geometry_point(feature.get("geometry"))
        if point is None:
            continue                      # sin polígono no hay pin fiable
        lat, lon = point

        severity_label, score = SEVERITY_MAP.get(props.get("severity") or "Unknown", ("yellow", 2.0))
        when = parse_dt(props.get("sent")) or parse_dt(props.get("effective")) or parse_dt(props.get("onset"))
        if when is None:
            continue

        alert_id = props.get("id") or f"{event_name}-{props.get('areaDesc', '')[:24]}"
        area = (props.get("areaDesc") or "").replace("\n", " ").strip()
        headline = (props.get("headline") or props.get("description") or "").replace("\n", " ")

        record = EventRecord(
            uid=f"nws:{alert_id}",
            source="nws",
            category="wildfire" if (event_name in FIRE_EVENTS or "Fire" in event_name) else "disaster",
            subtype=event_name,
            title=es_nws(f"{event_name} · {area[:60]}"),
            summary=headline[:600],
            lat=lat,
            lon=lon,
            severity=score,
            severity_label=severity_label,
            country="United States",
            iso3="USA",
            url=props.get("@id") or "",
            event_time=when,
            payload={
                "event": event_name,
                "severity": props.get("severity"),
                "certainty": props.get("certainty"),
                "urgency": props.get("urgency"),
                "status": props.get("status"),
                "area": area,
                "sender": props.get("senderName"),
                "ends": props.get("ends"),
            },
            geometry=feature.get("geometry"),
        )
        out.append(record)
        if len(out) >= limit:
            break
    return out


async def fetch(fetcher: Fetcher, *, severity: str = "Extreme,Severe") -> list[EventRecord]:
    payload = await fetcher.get_json(
        URL.format(severity=severity),
        retries=2,
        headers={"User-Agent": "AegisOSINT/1.0 (open-source OSINT super app)"},
    )
    return parse(payload)
