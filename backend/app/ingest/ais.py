"""Maritime AIS positions.

Primary: aisstream.io websocket (global coverage, free API key — 30 s signup).
Fallback: Digitraffic open AIS REST feed (keyless, real-time, Baltic coverage).

Both produce the same actor shape consumed by the live layer and the fence
engine, so the rest of the system does not care which one is active.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from ..config import settings
from ..live import VESSELS
from .client import Fetcher

log = logging.getLogger("aegis.ais")

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
DIGITRAFFIC_LOCATIONS = "https://meri.digitraffic.fi/api/ais/v1/locations"
DIGITRAFFIC_VESSELS = "https://meri.digitraffic.fi/api/ais/v1/vessels"

_vessel_names: dict[int, dict] = {}
_names_fetched_at = 0.0


def _navstat_label(code: int | None) -> str:
    labels = {
        0: "under way (engine)", 1: "at anchor", 2: "not under command", 3: "restricted manoeuvrability",
        4: "constrained by draught", 5: "moored", 6: "aground", 7: "fishing", 8: "under way (sailing)",
        15: "undefined",
    }
    return labels.get(code if code is not None else 15, "unknown")


def _ship_type_label(code: int | None) -> str:
    code = code or 0
    if 70 <= code < 80:
        return "cargo"
    if 80 <= code < 90:
        return "tanker"
    if 60 <= code < 70:
        return "passenger"
    if 30 <= code < 40:
        return "fishing"
    if 50 <= code < 60:
        return "special"
    if code == 35:
        return "military"
    return "other"


def actor_from_aisstream(msg: dict) -> dict | None:
    meta = msg.get("MetaData") or {}
    body = msg.get("Message") or {}
    report = body.get("PositionReport") or body.get("StandardClassBPositionReport")
    if not report:
        return None
    lat = report.get("Latitude", meta.get("latitude"))
    lon = report.get("Longitude", meta.get("longitude"))
    if lat is None or lon is None:
        return None
    mmsi = meta.get("MMSI") or report.get("UserID")
    return {
        "id": str(mmsi),
        "mmsi": mmsi,
        "name": (meta.get("ShipName") or "").strip(),
        "lat": lat,
        "lon": lon,
        "speed_kn": report.get("Sog") or 0.0,
        "course": report.get("Cog") or 0.0,
        "heading": report.get("TrueHeading") or 0,
        "navstat": report.get("NavigationalStatus"),
        "navstat_label": _navstat_label(report.get("NavigationalStatus")),
        "rot": report.get("RateOfTurn"),
        "source": "aisstream.io",
    }


def vessel_meta(mmsi: int) -> dict | None:
    """Metadatos estáticos del buque (nombre, tipo, destino, ETA) si se conocen."""
    return _vessel_names.get(int(mmsi))


async def _refresh_vessel_names(fetcher: Fetcher) -> None:
    global _names_fetched_at
    if time.time() - _names_fetched_at < 6 * 3600 and _vessel_names:
        return
    try:
        payload = await fetcher.get_json(DIGITRAFFIC_VESSELS)
        for vessel in payload if isinstance(payload, list) else []:
            mmsi = vessel.get("mmsi")
            if mmsi:
                _vessel_names[int(mmsi)] = {
                    "name": vessel.get("name") or "",
                    "type": _ship_type_label(vessel.get("shipType")),
                    "imo": vessel.get("imo"),
                    "draught": vessel.get("draught"),
                    "destination": vessel.get("destination"),
                    "eta": vessel.get("eta"),
                    "call_sign": vessel.get("callSign"),
                }
        _names_fetched_at = time.time()
        log.info("AIS vessel metadata cached: %d ships", len(_vessel_names))
    except Exception as exc:  # noqa: BLE001
        log.warning("vessel metadata failed: %s", exc)


async def fetch_digitraffic(fetcher: Fetcher) -> list[dict]:
    await _refresh_vessel_names(fetcher)
    payload = await fetcher.get_json(DIGITRAFFIC_LOCATIONS)
    actors: list[dict] = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        mmsi = props.get("mmsi")
        # Digitraffic injects virtual AIS targets (MMSI 99xxxxxxx, "TESTSHIP"):
        # they are test fixtures, not real traffic.
        if mmsi and str(mmsi).startswith("99"):
            continue
        meta = _vessel_names.get(int(mmsi), {}) if mmsi else {}
        actors.append(
            {
                "id": str(mmsi),
                "mmsi": mmsi,
                "name": meta.get("name") or f"MMSI {mmsi}",
                "type": meta.get("type", "other"),
                "destination": meta.get("destination"),
                "lat": coords[1],
                "lon": coords[0],
                "speed_kn": props.get("sog") or 0.0,
                "course": props.get("cog") or 0.0,
                "heading": props.get("heading") or 0,
                "navstat": props.get("navStat"),
                "navstat_label": _navstat_label(props.get("navStat")),
                "source": "digitraffic.fi (open AIS)",
            }
        )
    VESSELS.upsert_many(actors)
    return actors


async def stream_aisstream(queue: asyncio.Queue) -> None:
    """Long-lived websocket reader; pushes normalised actors into `queue`."""
    import websockets

    subscribe = {
        "APIKey": settings.aisstream_key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"],
    }
    delay = 5
    while True:
        try:
            async with websockets.connect(AISSTREAM_URL, ping_interval=20, max_size=2**23) as ws:
                await ws.send(json.dumps(subscribe))
                log.info("aisstream.io connected")
                delay = 5
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("error"):
                        log.warning("aisstream error: %s", msg["error"])
                        break
                    actor = actor_from_aisstream(msg)
                    if actor:
                        await queue.put(actor)
        except Exception as exc:  # noqa: BLE001
            log.warning("aisstream disconnected: %s (retry in %ss)", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)
