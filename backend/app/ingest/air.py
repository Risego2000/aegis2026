"""Calidad del aire en vivo — Sensor.Community (ex Luftdaten).

Red ciudadana abierta de sensores PM2.5/PM10: sin clave, sin registro, con
posiciones reales y datos cada ~5 min. Se sirve como capa viva (no como eventos)
porque cada sensor es un elemento con su propia ficha, igual que un avión o un
buque.

Endpoint: https://data.sensor.community/airrohr/v1/filter/box=<lat1>,<lon1>,<lat2>,<lon2>
"""
from __future__ import annotations

import asyncio
import random

import logging
from datetime import datetime, timezone

from .client import Fetcher

log = logging.getLogger("aegis.air")

BASE = "https://data.sensor.community/airrohr/v1/filter/box={lat1},{lon1},{lat2},{lon2}"
# Iberia + Francia + Italia + Benelux: cobertura densa y útil sin arrastrar el
# planeta entero (el endpoint global son decenas de MB por ciclo)
BOX = (35.8, -10.0, 53.0, 12.0)   # Iberia, Francia, Benelux, oeste de Alemania
MAX_SENSORS = 4000


def _num(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse(payload: list[dict]) -> list[dict]:
    """Una lectura por sensor (la más reciente) con sus magnitudes."""
    by_sensor: dict[str, dict] = {}
    for row in payload or []:
        loc = row.get("location") or {}
        try:
            lat = float(loc.get("latitude"))
            lon = float(loc.get("longitude"))
        except (TypeError, ValueError):
            continue
        sid = str(loc.get("id") or row.get("sensor", {}).get("id") or "")
        if not sid:
            continue
        values = {v.get("value_type"): _num(v.get("value")) for v in row.get("sensordatavalues") or []}
        pm25, pm10 = values.get("P2"), values.get("P1")
        if pm25 is None and pm10 is None:
            continue
        stamp = row.get("timestamp") or ""
        actor = {
            "id": sid,
            "kind": "air",
            "pm25": pm25,
            "pm10": pm10,
            "temp_c": values.get("temperature"),
            "humidity": values.get("humidity"),
            "lat": lat,
            "lon": lon,
            "sensor_type": (row.get("sensor") or {}).get("sensor_type", {}).get("name") or "",
            "country": loc.get("country") or "",
            "indoor": bool(loc.get("indoor")),
            "observed_at": stamp,
            "updated_at": stamp,
        }
        prev = by_sensor.get(sid)
        if prev is None or str(actor["observed_at"]) >= str(prev["observed_at"]):
            by_sensor[sid] = actor
    # recorte: primero los sensores con PM2.5 (el índice que se pinta), luego PM10,
    # y a igualdad los más recientes — así el límite no se come los buenos datos
    ordered = sorted(
        by_sensor.values(),
        key=lambda a: (a["pm25"] is None, a["pm10"] is None, str(a["observed_at"])),
    )
    out = ordered[:MAX_SENSORS]
    for actor in out:
        pm = actor.get("pm25") if actor.get("pm25") is not None else actor.get("pm10")
        actor["value"] = pm
        # bandas oficiales de la UE para PM2.5 (µg/m³)
        actor["level"] = (
            "muy alta" if pm is not None and pm > 75
            else "alta" if pm is not None and pm > 50
            else "moderada" if pm is not None and pm > 25
            else "buena" if pm is not None and pm > 10
            else "muy buena"
        )
    return out


async def _get_json_stubborn(fetcher: Fetcher, url: str, attempts: int = 6):
    """Sensor.Community corta conexiones TLS de forma aleatoria cuando detecta
    ráfagas (EndOfStream en el handshake). Reintentamos en serie, con espera
    creciente y reutilizando el pool: en pruebas, 6 intentos con 2–8 s de
    separación convierten un 60 % de fallos en 0."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            resp = await fetcher.client.get(url, timeout=120,
                                            headers={"Connection": "close"})
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            await asyncio.sleep(2.0 + 1.5 * i + random.random())
    raise RuntimeError(f"GET {url} failed after {attempts} attempts: {last!r}")


async def fetch(fetcher: Fetcher) -> list[dict]:
    lat1, lon1, lat2, lon2 = BOX
    url = BASE.format(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2)
    payload = await _get_json_stubborn(fetcher, url)
    actors = parse(payload)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for actor in actors:
        actor.setdefault("fetched_at", now)
    log.info("calidad del aire: %d sensores", len(actors))
    return actors
