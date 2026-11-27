"""Orbital tracking: Celestrak element sets + SGP4 propagation.

* Catalogue: https://celestrak.org/NORAD/elements/gp.php?GROUP=<group>&FORMAT=tle
  (public, keyless, rate-limited by politeness only — we refresh every 6 h).
* Propagation: SGP4 (Vallado reference implementation, `sgp4` package) from
  TEME to geodetic coordinates + ground-track sampling for the orbit trail.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import settings
from ..live import SATCAT
from .client import Fetcher

log = logging.getLogger("aegis.sats")

# Espejo comunitario actualizado cada 30 min: mismo formato TLE, sin claves.
# CelesTrak bloquea con frecuencia las IPs de centros de datos.
TLE_MIRROR = "https://raw.githubusercontent.com/astrion-tech/celestrak-mirror/main/tle/{group}.tle"

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
TLE_TTL_S = 6 * 3600

_satellites: list[dict] = []
_tle_fetched_at = 0.0

WGS84_A = 6378.137  # km
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)


def gmst(jd_ut1: float) -> float:
    """Greenwich mean sidereal time (rad) — IAU-82 polynomial."""
    tut1 = (jd_ut1 - 2451545.0) / 36525.0
    temp = (
        -6.2e-6 * tut1 ** 3
        + 0.093104 * tut1 ** 2
        + (876600.0 * 3600 + 8640184.812866) * tut1
        + 67310.54841
    )
    return math.radians(temp / 240.0) % (2 * math.pi)


def eci_to_geodetic(x: float, y: float, z: float, jd: float) -> tuple[float, float, float]:
    """TEME/ECI (km) -> lat, lon, altitude (km)."""
    theta = gmst(jd)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    xe = cos_t * x + sin_t * y
    ye = -sin_t * x + cos_t * y
    ze = z
    lon = math.atan2(ye, xe)
    p = math.hypot(xe, ye)
    lat = math.atan2(ze, p * (1 - WGS84_E2))
    for _ in range(6):
        sin_lat = math.sin(lat)
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
        alt = p / math.cos(lat) - n
        lat = math.atan2(ze, p * (1 - WGS84_E2 * n / (n + alt)))
    sin_lat = math.sin(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat ** 2)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), ((math.degrees(lon) + 540) % 360) - 180, alt


def _jday(dt: datetime) -> tuple[float, float]:
    from sgp4.api import jday

    return jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)


def parse_tle(text: str) -> list[dict]:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out: list[dict] = []
    i = 0
    while i + 2 < len(lines) + 1 and i + 1 < len(lines):
        name = lines[i].strip()
        l1 = lines[i + 1] if i + 1 < len(lines) else ""
        l2 = lines[i + 2] if i + 2 < len(lines) else ""
        if l1.startswith("1 ") and l2.startswith("2 "):
            try:
                norad = int(l1[2:7])
            except ValueError:
                i += 3
                continue
            out.append({"name": name, "norad": norad, "line1": l1, "line2": l2})
            i += 3
        else:
            i += 1
    return out


# Si CelesTrak rechaza la IP se deja de intentar durante 15 min (circuito abierto)
_celestrak_blocked_until = 0.0

CACHE_PATH = Path(__file__).resolve().parents[3] / "data" / "tle_cache.json"


def _save_cache(entries: list[dict]) -> None:
    """Guarda línea 1/2 + grupos para poder arrancar sin red (Celestrak caído)."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"norad": e["norad"], "name": e.get("name", ""), "line1": e["line1"],
             "line2": e["line2"], "groups": e.get("groups", [])}
            for e in entries
        ]
        CACHE_PATH.write_text(json.dumps({"ts": time.time(), "satellites": payload}))
    except Exception as exc:  # noqa: BLE001 - la caché nunca debe romper la ingesta
        log.warning("no se pudo escribir la caché de TLE: %s", exc)


def _load_cache() -> list[dict]:
    try:
        if not CACHE_PATH.exists():
            return []
        raw = json.loads(CACHE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return []
    from sgp4.api import Satrec

    out: list[dict] = []
    for entry in raw.get("satellites", []):
        try:
            sat = Satrec.twoline2rv(entry["line1"], entry["line2"])
        except Exception:  # noqa: BLE001
            continue
        jd = float(getattr(sat, "jdsatepoch", 0)) + float(getattr(sat, "jdsatepochF", 0))
        out.append({
            **entry,
            "sat": sat,
            "epoch": (datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=jd - 2451545.0))
            if jd else datetime.now(timezone.utc),
        })
    return out


async def refresh_tles(fetcher: Fetcher, force: bool = False) -> int:
    global _satellites, _tle_fetched_at
    from sgp4.api import Satrec

    if not force and _satellites and time.time() - _tle_fetched_at < TLE_TTL_S:
        return len(_satellites)
    seen: dict[int, dict] = {}

    async def load_group(group: str) -> tuple[str, str | None]:
        """CelesTrak primero; si la IP está bloqueada, el espejo comunitario."""
        global _celestrak_blocked_until
        attempts: list[str] = []
        if time.time() >= _celestrak_blocked_until:
            attempts.append(TLE_URL.format(group=group))
        attempts.append(TLE_MIRROR.format(group=group))
        for url in attempts:
            try:
                text = await fetcher.get_text(url, retries=1)
                if "celestrak.org" not in url:
                    log.info("grupo %s servido por el espejo de GitHub", group)
                return group, text
            except Exception as exc:  # noqa: BLE001
                host = url.split("/")[2]
                if "celestrak.org" in host:
                    _celestrak_blocked_until = time.time() + 900
                log.warning("grupo %s vía %s: %s", group, host, str(exc)[:120])
        return group, None

    groups = [g.strip() for g in settings.celestrak_groups.split(",") if g.strip()]
    # en paralelo: el arranque no se queda esperando a un proveedor lento
    results = await asyncio.gather(*(load_group(g) for g in groups)) if groups else []
    for group, text in results:
        if not text:
            continue
        for entry in parse_tle(text):
            if entry["norad"] in seen:
                seen[entry["norad"]]["groups"].append(group)
                continue
            try:
                sat = Satrec.twoline2rv(entry["line1"], entry["line2"])
            except Exception:  # noqa: BLE001 - elementos malformados: se descartan
                continue
            entry["sat"] = sat
            jd = float(getattr(sat, "jdsatepoch", 0)) + float(getattr(sat, "jdsatepochF", 0))
            entry["epoch"] = (
                datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=jd - 2451545.0)
                if jd else datetime.now(timezone.utc)
            )
            entry["groups"] = [group]
            seen[entry["norad"]] = entry

    _satellites = list(seen.values())
    _tle_fetched_at = time.time()
    _save_cache(_satellites)
    SATCAT.tle_updated_at = _tle_fetched_at
    log.info("celestrak: %d satélites cargados", len(_satellites))
    return len(_satellites)


def _propagate(entry: dict, when: datetime) -> dict | None:
    jd, fr = _jday(when)
    err, r, _v = entry["sat"].sgp4(jd, fr)
    if err != 0:
        return None
    lat, lon, alt = eci_to_geodetic(r[0], r[1], r[2], jd + fr)
    return {
        "id": str(entry["norad"]),
        "norad": entry["norad"],
        "name": entry["name"],
        "groups": entry["groups"],
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "altitude_km": round(alt, 1),
        "inclination": round(math.degrees(entry["sat"].inclo), 2),
        "period_min": round((2 * math.pi / entry["sat"].no_kozai), 2),
    }


def propagate_all(when: datetime | None = None) -> list[dict]:
    when = when or datetime.now(timezone.utc)
    positions = []
    for entry in _satellites:
        pos = _propagate(entry, when)
        if pos:
            positions.append(pos)
    SATCAT.set_positions(positions)
    return positions


MU_EARTH = 398600.4418          # km^3/s^2
R_EARTH = 6378.137              # km


def satellite_detail(norad: int) -> dict | None:
    """Ficha orbital completa: elementos TLE, geometría de la órbita y estado."""
    entry = next((s for s in _satellites if s["norad"] == int(norad)), None)
    if entry is None:
        return None
    sat = entry["sat"]
    now = datetime.now(timezone.utc)
    pos = _propagate(entry, now)
    if pos is None:
        return None

    # OJO: Satrec.no_kozai viene en rad/min (sgp4), no en rad/s
    n_rad_s = float(sat.no_kozai) / 60.0
    a_km = (MU_EARTH / (n_rad_s ** 2)) ** (1 / 3) if n_rad_s else 0.0
    ecc = float(sat.ecco)
    apogee_km = a_km * (1 + ecc) - R_EARTH
    perigee_km = a_km * (1 - ecc) - R_EARTH
    alt = pos["altitude_km"]
    footprint_km = R_EARTH * math.acos(min(1.0, R_EARTH / (R_EARTH + max(alt, 1.0))))
    speed_kms = math.sqrt(MU_EARTH / (R_EARTH + max(alt, 1.0)))

    return {
        **pos,
        "type": "satellite",
        "epoch": entry["epoch"].isoformat(timespec="seconds"),
        "tle_age_min": round((now - entry["epoch"]).total_seconds() / 60, 1),
        "orbit": {
            "semi_major_axis_km": round(a_km, 1),
            "apogee_km": round(apogee_km, 1),
            "perigee_km": round(perigee_km, 1),
            "eccentricity": round(ecc, 6),
            "inclination_deg": pos["inclination"],
            "period_min": pos["period_min"],
            "raan_deg": round(math.degrees(sat.nodeo), 2),
            "arg_perigee_deg": round(math.degrees(sat.argpo), 2),
            "mean_anomaly_deg": round(math.degrees(sat.mo), 2),
            "bstar": float(sat.bstar),
        },
        "state": {
            "altitude_km": round(alt, 1),
            "speed_km_s": round(speed_kms, 3),
            "orbits_per_day": round(1440 / pos["period_min"], 2) if pos["period_min"] else None,
            "footprint_radius_km": round(footprint_km, 0),
        },
        "tle": [entry.get("line1", ""), entry.get("line2", "")],
    }


def ground_track(norad: int, minutes: int = 90, step_s: int = 60) -> list[list[float]]:
    entry = next((s for s in _satellites if s["norad"] == int(norad)), None)
    if entry is None:
        return []
    now = datetime.now(timezone.utc)
    coords: list[list[float]] = []
    for offset in range(-minutes // 2, minutes // 2 + 1, max(1, step_s // 60)):
        pos = _propagate(entry, now + timedelta(minutes=offset))
        if pos:
            coords.append([pos["lon"], pos["lat"]])
    return coords


async def fetch(fetcher: Fetcher) -> int:
    count = await refresh_tles(fetcher)
    propagate_all()
    return count
