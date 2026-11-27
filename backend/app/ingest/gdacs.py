"""GDACS disaster alerts (floods, cyclones, volcanoes, droughts, wildfires...).

Endpoint: /gdacsapi/api/events/geteventlist/SEARCH — public REST, returns a
GeoJSON FeatureCollection. Free, keyless.

Area events (cyclones, floods) also expose a footprint polygon through
/getgeometry, which we fetch for the current episode so the map can draw the
affected area instead of a single centroid.
"""
from __future__ import annotations

import logging

from ..models import EventRecord, parse_dt
from .es import es_gdacs

log = logging.getLogger("aegis.gdacs")

SEARCH = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GEOMETRY = "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"

# GDACS event types -> our taxonomy
TYPE_MAP = {
    "EQ": "earthquake",
    "TC": "disaster",
    "FL": "disaster",
    "VO": "disaster",
    "DR": "disaster",
    "TS": "disaster",
    "WF": "wildfire",
}
SUBTYPE = {
    "EQ": "earthquake",
    "TC": "tropical cyclone",
    "FL": "flood",
    "VO": "volcano",
    "DR": "drought",
    "TS": "tsunami",
    "WF": "wildfire",
}
POLYGON_TYPES = {"TC", "FL", "VO", "WF"}


def _severity(p: dict) -> tuple[float | None, str]:
    sd = p.get("severitydata") or {}
    sev = sd.get("severity")
    label = (p.get("episodealertlevel") or p.get("alertlevel") or "green").lower()
    try:
        return (float(sev) if sev is not None else None), label
    except (TypeError, ValueError):
        return None, label


def parse(payload: dict) -> list[EventRecord]:
    out: list[EventRecord] = []
    for feature in payload.get("features", []):
        p = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "Point" or len(coords) < 2:
            continue
        etype = (p.get("eventtype") or "").upper()
        severity, label = _severity(p)
        when = parse_dt(p.get("fromdate")) or parse_dt(p.get("datemodified"))
        if when is None:
            continue
        eventid, episodeid = p.get("eventid"), p.get("episodeid")
        sd = p.get("severitydata") or {}
        out.append(
            EventRecord(
                uid=f"gdacs:{eventid}:{episodeid}",
                source="gdacs",
                category=TYPE_MAP.get(etype, "disaster"),
                subtype=SUBTYPE.get(etype, etype.lower()),
                title=es_gdacs(p.get("name") or p.get("htmldescription") or "", label),
                summary=(
                    f"{p.get('htmldescription','')} · país {p.get('country','?')}"
                    f" · alerta {label.upper()} ({p.get('alertscore')})"
                ),
                lat=float(coords[1]),
                lon=float(coords[0]),
                severity=severity,
                severity_label=label,
                country=p.get("country") or "",
                iso3=p.get("iso3") or "",
                url=(p.get("url") or {}).get("report") or "",
                event_time=when,
                payload={
                    "eventtype": etype,
                    "eventid": eventid,
                    "episodeid": episodeid,
                    "alertlevel": p.get("alertlevel"),
                    "alertscore": p.get("alertscore"),
                    "episodealertlevel": p.get("episodealertlevel"),
                    "severitytext": sd.get("severitytext"),
                    "severityunit": sd.get("severityunit"),
                    "source": p.get("source"),
                    "affectedcountries": p.get("affectedcountries"),
                    "geometry_url": (p.get("url") or {}).get("geometry"),
                    "iscurrent": p.get("iscurrent"),
                },
            )
        )
    return out


async def fetch(fetcher, *, days: int = 7, enrich_polygons: int = 8) -> list[EventRecord]:
    from datetime import timedelta

    from ..models import utcnow, iso

    params = {
        "fromdate": (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "todate": utcnow().strftime("%Y-%m-%d"),
        "alertlevel": "Green;Orange;Red",
    }
    payload = await fetcher.get_json(SEARCH, params=params)
    records = parse(payload)

    # Enrich the most severe *current* area events with their footprint polygon.
    candidates = [r for r in records if r.payload.get("eventtype") in POLYGON_TYPES]
    candidates.sort(key=lambda r: (r.severity_label != "red", r.severity_label != "orange"))
    for rec in candidates[:enrich_polygons]:
        url = rec.payload.get("geometry_url")
        if not url:
            continue
        try:
            geo = await fetcher.get_json(url)
            feats = geo.get("features") if geo.get("type") == "FeatureCollection" else [geo]
            geom = (feats or [{}])[0].get("geometry") if feats else None
            if geom and geom.get("type") in ("Polygon", "MultiPolygon"):
                rec.geometry = geom
        except Exception as exc:  # noqa: BLE001 - polygons are a nice-to-have
            log.debug("gdacs geometry failed %s: %s", rec.uid, exc)
    return records
