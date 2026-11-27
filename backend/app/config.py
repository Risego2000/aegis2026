"""Central configuration.

Everything is env-driven so the same code runs on a laptop, on the Oracle Cloud
ARM "Always Free" box (4 vCPU / 24 GB) or in CI, without code changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:  # optional convenience
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Watch regions used by the ADS-B collector (adsb.lol is keyless, point queries
# are limited to 250 NM radius). Add/remove freely: "CODE": (lat, lon, radius_nm)
# --------------------------------------------------------------------------- #
# Regiones de vigilancia ADS-B (radio en millas náuticas).
# Diez zonas bastan para un tablero mundial legible (~800-950 aeronaves) y
# dejan el proceso en ~350 MB: esta caja comparte 2 GB con el navegador del
# operador y cada región de más se paga en memoria y en cuota del proveedor.
HOTSPOTS: dict[str, tuple[float, float, int]] = {
    "MAD": (40.47, -3.56, 250),
    "LON": (51.47, -0.45, 250),
    "IST": (41.27, 28.75, 250),
    "DXB": (25.25, 55.36, 250),
    "KYIV": (50.34, 30.89, 250),
    "HKG": (22.31, 113.91, 250),
    "JFK": (40.64, -73.78, 250),
    "LAX": (33.94, -118.40, 250),
    "SIN": (1.36, 103.99, 250),
    "GRU": (-23.43, -46.47, 250),
}


@dataclass
class Settings:
    # --- storage -----------------------------------------------------------
    # SQLite is the zero-dependency default. Point DATABASE_URL at PostGIS for
    # the production path (see backend/sql/schema_postgis.sql).
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    sqlite_path: str = field(
        default_factory=lambda: _env("SQLITE_PATH", str(ROOT / "data" / "osint.db"))
    )
    retention_days: int = field(default_factory=lambda: int(_num("RETENTION_DAYS", 7)))

    # --- geofencing --------------------------------------------------------
    # If TILE38_URL is set (tile38://localhost:9851) the fence engine talks to a
    # real Tile38 instance over RESP; otherwise the in-process engine with the
    # same FENCE/DETECT(enter,exit,inside) semantics is used.
    tile38_url: str = field(default_factory=lambda: _env("TILE38_URL"))

    # --- data sources ------------------------------------------------------
    enable_usgs: bool = field(default_factory=lambda: _bool("ENABLE_USGS", True))
    enable_gdacs: bool = field(default_factory=lambda: _bool("ENABLE_GDACS", True))
    enable_gdelt: bool = field(default_factory=lambda: _bool("ENABLE_GDELT", True))
    enable_adsb: bool = field(default_factory=lambda: _bool("ENABLE_ADSB", True))
    enable_ais: bool = field(default_factory=lambda: _bool("ENABLE_AIS", True))
    enable_firms: bool = field(default_factory=lambda: _bool("ENABLE_FIRMS", True))
    enable_satellites: bool = field(default_factory=lambda: _bool("ENABLE_SATELLITES", True))
    enable_eonet: bool = field(default_factory=lambda: _bool("ENABLE_EONET", True))
    enable_emsc: bool = field(default_factory=lambda: _bool("ENABLE_EMSC", True))
    enable_nws: bool = field(default_factory=lambda: _bool("ENABLE_NWS", True))
    enable_adsbfi: bool = field(default_factory=lambda: _bool("ENABLE_ADSB_FI", True))

    usgs_interval: int = field(default_factory=lambda: int(_num("USGS_INTERVAL", 120)))
    gdacs_interval: int = field(default_factory=lambda: int(_num("GDACS_INTERVAL", 300)))
    gdelt_interval: int = field(default_factory=lambda: int(_num("GDELT_INTERVAL", 900)))
    adsb_interval: int = field(default_factory=lambda: int(_num("ADSB_INTERVAL", 20)))
    # recorrer todas las regiones en cada ciclo (más movimiento en pantalla)
    adsb_full_sweep: bool = field(default_factory=lambda: _bool("ADSB_FULL_SWEEP", True))
    ais_interval: int = field(default_factory=lambda: int(_num("AIS_INTERVAL", 60)))
    firms_interval: int = field(default_factory=lambda: int(_num("FIRMS_INTERVAL", 900)))
    sat_interval: int = field(default_factory=lambda: int(_num("SAT_INTERVAL", 5)))
    eonet_interval: int = field(default_factory=lambda: int(_num("EONET_INTERVAL", 600)))
    emsc_interval: int = field(default_factory=lambda: int(_num("EMSC_INTERVAL", 180)))
    nws_interval: int = field(default_factory=lambda: int(_num("NWS_INTERVAL", 300)))

    # USGS magnitude floor for the live feed (4.5_day / 2.5_day / all_day)
    usgs_feed: str = field(default_factory=lambda: _env("USGS_FEED", "4.5_day"))

    # NASA FIRMS: los CSV globales 24 h son ABIERTOS (sin clave) -> modo por defecto.
    # Si se define MAP_KEY (alta manual gratuita en
    # https://firms.modaps.eosdis.nasa.gov/api/map_key/) se usa el endpoint /area
    # con el bbox y la ventana de días, lo que permite recortes geográficos finos.
    firms_map_key: str = field(default_factory=lambda: _env("FIRMS_MAP_KEY"))

    # aisstream.io free API key (global AIS over websocket)
    aisstream_key: str = field(default_factory=lambda: _env("AISSTREAM_API_KEY"))
    # Keyless fallback: Digitraffic open AIS feed (real live data, Baltic coverage)
    enable_digitraffic: bool = field(default_factory=lambda: _bool("ENABLE_DIGITRAFFIC", True))

    # cámaras públicas abiertas (TfL, Caltrans, NYC TMC, Digitraffic)
    enable_trains: bool = field(default_factory=lambda: _bool("ENABLE_TRAINS", True))
    enable_dgt: bool = field(default_factory=lambda: _bool("ENABLE_DGT", True))
    dgt_interval: int = field(default_factory=lambda: int(_num("DGT_INTERVAL", 300)))
    aegis_token: str = field(default_factory=lambda: _env("AEGIS_TOKEN", ""))
    trains_interval: int = field(default_factory=lambda: int(_num("TRAINS_INTERVAL", 20)))
    enable_cameras: bool = field(default_factory=lambda: _bool("ENABLE_CAMERAS", True))
    cameras_interval: int = field(default_factory=lambda: int(_num("CAMERAS_INTERVAL", 1800)))

    # calidad del aire (Sensor.Community, sin clave)
    enable_air: bool = field(default_factory=lambda: _bool("ENABLE_AIR", True))
    air_interval: int = field(default_factory=lambda: int(_num("AIR_INTERVAL", 600)))

    # adsb.lol / OpenSky style endpoint (both keyless)
    adsb_base: str = field(default_factory=lambda: _env("ADSB_BASE", "https://api.adsb.lol"))
    celestrak_groups: str = field(
        default_factory=lambda: _env("CELESTRAK_GROUPS", "stations,gps-ops,weather,geo,science,military,oneweb")
    )

    # --- AI ---------------------------------------------------------------
    # ai_provider: auto | ollama | gemini | local
    ai_provider: str = field(default_factory=lambda: _env("AI_PROVIDER", "auto"))
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3.2"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.0-flash"))

    # --- server -----------------------------------------------------------
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_num("PORT", 8000)))
    frontend_dir: str = field(default_factory=lambda: _env("FRONTEND_DIR") or str(
        next(
            (p for p in (ROOT / "frontend" / "out", ROOT / "frontend" / "site") if (p / "index.html").exists()),
            ROOT / "frontend" / "out",
        )
    ))
    geo_dir: str = field(default_factory=lambda: _env("GEO_DIR", str(ROOT / "data" / "geo")))
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS", "*"))

    # Fence/rule thresholds ------------------------------------------------
    emergency_squawks: tuple[str, ...] = ("7500", "7600", "7700")
    fast_vessel_kn: float = 32.0
    big_quake_mag: float = 6.0


settings = Settings()
