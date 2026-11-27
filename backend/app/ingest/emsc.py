"""EMSC (seismicportal.eu) — sismos de Europa, Mediterráneo y Oriente Medio.

Free, keyless, FDSN-compatible. Aporta lo que USGS deja fuera por su umbral de
M4.5: enjambres y sismos moderados (M2.5+) con resolución regional, que son los
que interesan para el Mediterráneo y los Balcanes.

Endpoint: https://www.seismicportal.eu/fdsnws/event/1/query?format=json
"""
from __future__ import annotations

from ..models import EventRecord, parse_dt
from .client import Fetcher
from .usgs import magnitude_label
from .es import es_emsc

URL = (
    "https://www.seismicportal.eu/fdsnws/event/1/query"
    "?format=json&limit=200&minmag={minmag}&orderby=time"
)


def parse(payload: dict) -> list[EventRecord]:
    out: list[EventRecord] = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        depth = abs(float(coords[2])) if len(coords) > 2 and coords[2] is not None else None
        mag = props.get("mag")
        try:
            mag_f = float(mag) if mag is not None else None
        except (TypeError, ValueError):
            mag_f = None
        when = parse_dt(props.get("time"))
        if when is None:
            continue

        region = (props.get("flynn_region") or "región no especificada").strip()
        agency = props.get("auth") or props.get("agency") or "EMSC"
        eid = feature.get("id") or props.get("unid") or props.get("source_id")
        if not eid:
            continue

        out.append(
            EventRecord(
                uid=f"emsc:{eid}",
                source="emsc",
                category="earthquake",
                subtype=props.get("magtype") or "earthquake",
                title=es_emsc(f"M{mag_f:.1f} · {region}" if mag_f is not None else f"Sismo · {region}"),
                summary=(
                    f"{region} · profundidad {depth or 0:.0f} km · red {agency}"
                    f" · revisado: {props.get('lastupdate') or '—'}"
                ),
                lat=lat,
                lon=lon,
                depth_km=depth,
                severity=mag_f,
                severity_label=magnitude_label(mag_f),
                url=f"https://www.seismicportal.eu/eventdetails.html?unid={eid}",
                event_time=when,
                payload={
                    "mag": mag_f,
                    "magtype": props.get("magtype"),
                    "agency": agency,
                    "region": region,
                    "depth": depth,
                    "unid": eid,
                },
            )
        )
    return out


async def fetch(fetcher: Fetcher, *, minmag: float = 2.5) -> list[EventRecord]:
    payload = await fetcher.get_json(URL.format(minmag=minmag), retries=2)
    return parse(payload)
