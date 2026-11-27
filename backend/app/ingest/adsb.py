"""ADS-B telemetry from adsb.lol (keyless, community-fed, global).

We poll point queries around a set of watch regions (the public endpoint caps
the radius at 250 NM). Each response is normalised to a flat actor dict, pushed
into the live layer (client-side Supercluster) and into the geofence engine
(FENCE / DETECT enter,exit,inside).
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..config import HOTSPOTS, settings
from ..extras.gnss import aircraft_status
from ..live import AIRCRAFT
from .client import Fetcher

log = logging.getLogger("aegis.adsb")

EMERGENCY_SQUAWKS = {"7500", "7600", "7700"}

# ---------------------------------------------------------------------------
# Aeronaves militares y oficiales
# ---------------------------------------------------------------------------
# No se adivina por el aspecto: se marca lo que el propio dato identifica.
#   · prefijo del indicativo de llamada (RCH = Air Mobility Command, IFC =
#     vuelos de Estado contratados, SAM = Special Air Mission de la USAF…)
#   · flotas militares conocidas por tipo ICAO
#   · unión de ambos conjuntos con la lista /v2/mil del agregador cuando
#     responde (gratuita y sin clave, pero intermitente: si falla, no pasa nada)
MIL_CALLSIGN_PREFIXES = (
    "RCH", "REACH", "RANGER", "SAM", "VENUS", "SPAR", "EXEC", "MAGMA",
    "TITAN", "KNIFE", "BOLT", "CASA", "HERKY", "GRZLY", "DARK", "PYTHN",
    "NATO", "CFC", "CHALICE", "MISTY", "HAWK", "VIPER", "REDEYE",
    "FAF", "GAF", "RRF", "IAM", "BAF", "NAF", "AME", "CTM", "PLF", "HAF",
)
STATE_CALLSIGN_PREFIXES = ("AF", "CF", "GO", "EXEC", "SPAR", "SAM", "VENUS", "PEACH")

MIL_TYPES = {
    # transporte estratégico y táctico
    "C17", "C5M", "C130", "C30J", "C27J", "C27", "A400", "C295", "C160",
    "C12", "C21", "C40", "C37", "C20", "C26", "C32", "C9", "C2", "E6", "E2",
    # reabastecimiento y vigilancia
    "K35R", "K35E", "K46", "KC10", "K130", "KC45", "P3", "P8", "E3TF",
    "E3CF", "E3", "E7", "E8", "RC135", "RC12", "RC26", "U2", "RQ4", "MQ9",
    "MQ1", "MQ4", "RQ7", "RQ11", "RQ20", "GLHK", "GLH",
    # cazas
    "F16", "F15", "F18", "F22", "F35", "FA18", "EA18", "EF18", "F5", "F4",
    "MIG29", "SU27", "SU30", "SU34", "SU35", "J10", "J11", "J20", "T38",
    "TOR", "EUFI", "RFAL", "MIR2", "MIR4", "JAS39", "A10", "H64", "AH64",
    "H60", "UH60", "CH47", "C47", "V22", "NH90", "AS32", "EC45", "H47",
    # transporte vip / oficial
    "GLF5", "GLF4", "GLF6", "GL7T", "GLEX", "CL60", "C68A", "C56X", "FA7X",
    "FA8X", "F900", "E35L", "E55P", "LJ45", "BE40", "HDJT", "PC24", "C25A",
}
# aviones de ala fija de transporte/patrulla vs. helicópteros y drones
_MIL_HELI = {"H64", "AH64", "H60", "UH60", "CH47", "H47", "V22", "NH90", "AS32", "EC45", "C47"}
_MIL_DRONE = {"RQ4", "MQ9", "MQ1", "MQ4", "RQ7", "RQ11", "RQ20", "GLHK", "GLH", "U2"}


def classify_aircraft(ac: dict) -> str:
    """'military' | 'state' | '' — solo con datos que el feed ya trae."""
    dbflags = ac.get("dbFlags")
    # dbFlags bit 0 = militar, bit 1 = interés (aerolínea/Estado) en la API de ADSBX
    if isinstance(dbflags, int) and dbflags & 1:
        return "military"
    kind = (ac.get("type") or "").strip().upper()
    if kind in MIL_TYPES:
        return "military"
    cs = (ac.get("flight") or "").strip().upper()
    if cs:
        head = cs.split()[0]
        if head[:4] in MIL_CALLSIGN_PREFIXES or head[:3] in MIL_CALLSIGN_PREFIXES:
            return "military"
        if head[:2] in STATE_CALLSIGN_PREFIXES and kind in MIL_TYPES:
            return "state"
    return ""


def _military_icon(kind: str) -> str:
    if kind in _MIL_HELI:
        return "heli"
    if kind in _MIL_DRONE:
        return "drone"
    return "milPlane"


def normalise(ac: dict) -> dict | None:
    lat, lon = ac.get("lat"), ac.get("lon")
    if lat is None or lon is None:
        return None
    alt = ac.get("alt_baro")
    alt_ft = float(alt) if isinstance(alt, (int, float)) else 0.0
    # El agregador devuelve de vez en cuando valores corruptos (altitud de
    # 100.000 ft, GS de 3.000 kt). Se descartan en origen: mejor un campo vacío
    # que un dato que envenene filtros y análisis.
    if not (-1500 <= alt_ft <= 80000):
        alt_ft = 0.0
    speed = ac.get("gs")
    speed_kn = float(speed) if isinstance(speed, (int, float)) and 0 <= speed <= 700 else 0.0
    track = ac.get("track") or ac.get("true_heading") or 0.0
    track = float(track) if isinstance(track, (int, float)) and 0 <= track <= 360 else 0.0
    callsign = (ac.get("flight") or "").strip()
    squawk = str(ac.get("squawk") or "").strip()
    return {
        "id": ac.get("hex") or f"{lat:.4f}{lon:.4f}",
        "callsign": callsign,
        "registration": ac.get("r") or "",
        "type": ac.get("t") or "",
        "category": ac.get("category") or "",
        "lat": lat,
        "lon": lon,
        "altitude_ft": alt_ft,
        "speed_kn": speed_kn,
        "track": track,
        "vertical_fpm": ac.get("baro_rate") or 0.0,
        "squawk": squawk,
        "emergency": (ac.get("emergency") or "none") != "none" or squawk in EMERGENCY_SQUAWKS,
        "on_ground": alt == "ground",
        "mil": classify_aircraft(ac),
        "mlat": bool(ac.get("mlat")),
        "seen_pos": ac.get("seen_pos"),
        # Calidad de la señal GNSS tal y como la declara el avión: es lo que
        # permite detectar interferencia (NIC/NACp a 0 con posición emitida).
        "nic": ac.get("nic"),
        "nac_p": ac.get("nac_p") if ac.get("nac_p") is not None else ac.get("nacp"),
        "gnss": aircraft_status({
            "nic": ac.get("nic"),
            "nac_p": ac.get("nac_p") if ac.get("nac_p") is not None else ac.get("nacp"),
        }),
        "source": "adsb.lol",
    }


# Segundo agregador comunitario, mismo formato de respuesta que adsb.lol pero con
# otra red de receptores. Si uno limita o cae, el otro tapa el hueco: más
# cobertura sin claves ni coste. Se alterna uno u otro por región y ciclo.
SECONDARY_PROVIDERS = (
    ("adsb.fi", "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{radius}"),
)

# adsb.lol throttles to ~1 req/s per IP; rotating half the watch regions per
# cycle keeps us at ~6 requests/sweep while covering every region every 2 sweeps.
_ROTATION_STATE = {"offset": 0}
# cortacircuitos por proveedor: tras un 429 se deja descansar unos minutos
_COOLDOWN: dict[str, float] = {}


def _available(providers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    now = time.time()
    ready = [p for p in providers if _COOLDOWN.get(p[0], 0) <= now]
    return ready or providers


def _rotation(codes: list[str], take: int) -> list[str]:
    offset = _ROTATION_STATE["offset"] % len(codes)
    ordered = codes[offset:] + codes[:offset]
    _ROTATION_STATE["offset"] = (offset + take) % len(codes)
    return ordered[:take]


_FOCUS_LOCK = {"until": 0.0}


MIL_URL = "https://opendata.adsb.fi/api/v2/mil"
_MIL_SEEN: dict[str, float] = {}
_MIL_LOCK = {"until": 0.0}


async def fetch_military(fetcher: Fetcher) -> list[dict]:
    """Lista mundial de militares/Estado (una sola petición por minuto).

    El agregador la publica sin clave; cuando está limitado se conserva la
    última marca durante 20 minutos para que el mapa no parpadee.
    """
    now = time.time()
    if now < _MIL_LOCK["until"]:
        return []
    _MIL_LOCK["until"] = now + 60.0
    try:
        payload = await fetcher.get_json(MIL_URL, retries=1, timeout=20)
    except Exception as exc:  # noqa: BLE001 - es un refuerzo, no un requisito
        log.info("adsb mil: %s", exc)
        return []
    actors: dict[str, dict] = {}
    for ac in payload.get("ac") or payload.get("aircraft") or []:
        actor = normalise(ac)
        if not actor:
            continue
        actor["mil"] = actor.get("mil") or "military"
        actor["source"] = "adsb.fi/mil"
        actor["region"] = "mil"
        _MIL_SEEN[actor["id"]] = now
        actors[actor["id"]] = actor
    if actors:
        AIRCRAFT.upsert_many(actors.values())
    return list(actors.values())


async def focus(fetcher: Fetcher, lat: float, lon: float, radius: int = 250) -> int:
    """Refresco puntual de la zona visible (máx. 1 cada 4 s por proceso).

    Permite que el mapa muestre tráfico que se mueve de verdad donde el usuario
    está mirando, sin castigar a los agregadores comunitarios.
    """
    now = time.time()
    if now < _FOCUS_LOCK["until"]:
        return 0
    _FOCUS_LOCK["until"] = now + 4.0
    radius = max(50, min(int(radius), 250))
    base: list[tuple[str, str]] = [("adsb.lol", settings.adsb_base + "/v2/point/{lat}/{lon}/{radius}")]
    if settings.enable_adsbfi:
        base.extend(SECONDARY_PROVIDERS)
    actors: dict[str, dict] = {}
    for name, template in _available(base):
        try:
            payload = await fetcher.get_json(template.format(lat=lat, lon=lon, radius=radius), retries=1)
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc):
                _COOLDOWN[name] = time.time() + 180
            continue
        for ac in payload.get("ac") or payload.get("aircraft") or []:
            actor = normalise(ac)
            if actor:
                actor["source"] = name
                actors[actor["id"]] = actor
        if actors:
            break
    if actors:
        AIRCRAFT.upsert_many(actors.values())
    return len(actors)


async def fetch(fetcher: Fetcher) -> list[dict]:
    actors: dict[str, dict] = {}
    codes = list(HOTSPOTS.keys())
    base: list[tuple[str, str]] = [("adsb.lol", settings.adsb_base + "/v2/point/{lat}/{lon}/{radius}")]
    if settings.enable_adsbfi:
        base.extend(SECONDARY_PROVIDERS)
    providers = _available(base)

    # media vuelta por ciclo: cada región refresca cada ~2 ciclos sin provocar
    # los 429 de adsb.lol (que limitan por IP). Con ADSB_FULL_SWEEP se recorren todas.
    take = len(codes) if settings.adsb_full_sweep else max(4, len(codes) // 2)
    sweep = _rotation(codes, take)
    for index, code in enumerate(sweep):
        lat, lon, radius = HOTSPOTS[code]
        name, template = providers[index % len(providers)]
        url = template.format(lat=lat, lon=lon, radius=radius)
        try:
            payload = await fetcher.get_json(url, retries=1)
        except Exception as exc:  # noqa: BLE001 - un proveedor caído no debe matar el barrido
            if "429" in str(exc):
                _COOLDOWN[name] = time.time() + 180
                log.warning("adsb %s limitando (429): descanso de 3 min", name)
            else:
                log.warning("adsb %s/%s failed: %s", name, code, exc)
            # reintento inmediato en el otro agregador de la misma región
            other = providers[(index + 1) % len(providers)]
            if other[0] == name:
                continue
            try:
                payload = await fetcher.get_json(other[1].format(lat=lat, lon=lon, radius=radius), retries=1)
                name = other[0]
            except Exception:  # noqa: BLE001
                continue
        for ac in payload.get("ac") or payload.get("aircraft") or []:
            actor = normalise(ac)
            if actor:
                actor["region"] = code
                actor["source"] = name
                actors[actor["id"]] = actor
        await asyncio.sleep(2.2)   # ~0,45 req/s: dentro de la política de adsb.lol
    AIRCRAFT.upsert_many(actors.values())
    return list(actors.values())
