"""USGS live GeoJSON feeds — global earthquakes (M4.5+ by default).

Endpoint: https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson
Free, keyless, no rate limit worth worrying about (refresh ~1 min upstream).
"""
from __future__ import annotations

from ..config import settings
from ..models import EventRecord, parse_dt
from .client import Fetcher
from .es import es_usgs, pais_es as _pais_es


def lugar_es(place: str) -> str:
    """«68 km SSE of Tateyama, Japan» -> mismo texto con el país en español."""
    ciudad, _, pais = (place or "").rpartition(",")
    if ciudad and pais.strip():
        return f"{ciudad.strip()}, {_pais_es(pais.strip())}"
    return _pais_es(place) if place else "región sin identificar"


URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed}.geojson"


def magnitude_label(mag: float | None) -> str:
    if mag is None:
        return "green"
    if mag >= 7.0:
        return "red"
    if mag >= 6.0:
        return "orange"
    if mag >= 5.0:
        return "yellow"
    return "green"


def parse(payload: dict) -> list[EventRecord]:
    out: list[EventRecord] = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        depth = float(coords[2]) if len(coords) > 2 else None
        mag = props.get("mag")
        when = parse_dt(props.get("time"))
        if when is None:
            continue
        out.append(
            EventRecord(
                uid=f"usgs:{feature.get('id')}",
                source="usgs",
                category="earthquake",
                subtype=props.get("type") or "earthquake",
                title=es_usgs(props.get("title") or f"M{mag} earthquake"),
                summary=(
                    f"{lugar_es(props.get('place') or '')} · profundidad {depth or 0:.0f} km"
                    f" · red {props.get('net')} · {props.get('status')}"
                ),
                lat=lat,
                lon=lon,
                depth_km=depth,
                severity=float(mag) if mag is not None else None,
                severity_label=magnitude_label(mag),
                url=props.get("url") or "",
                event_time=when,
                payload={
                    "mag": mag,
                    "magType": props.get("magType"),
                    "place": props.get("place"),
                    "felt": props.get("felt"),
                    "tsunami": props.get("tsunami"),
                    "alert": props.get("alert"),
                    "sig": props.get("sig"),
                    "mmi": props.get("mmi"),
                    "url": props.get("url"),
                    "source": props.get("net"),
                    "ids": props.get("ids"),
                },
            )
        )
    return out


async def fetch(fetcher: Fetcher) -> list[EventRecord]:
    payload = await fetcher.get_json(URL.format(feed=settings.usgs_feed))
    return parse(payload)
