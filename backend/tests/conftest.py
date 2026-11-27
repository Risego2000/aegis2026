"""Arranque hermético de los tests: sin red y sin datos previos.

Las fuentes se apagan *antes* de importar `app.main` (la configuración se lee al
importar el módulo), la base es un SQLite temporal y el proveedor de IA es el
analista local. Así los tests no dependen de que USGS, GDELT o el túnel estén
de buen humor, y el CI no puede quedarse en rojo por un tercero.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# el backend se importa como paquete de primer nivel (`app.main`)
sys.path.insert(0, str(ROOT / "backend"))

for flag in (
    "USGS", "GDACS", "GDELT", "ADSB", "AIS", "FIRMS", "SATELLITES", "EONET",
    "EMSC", "NWS", "ADSB_FI", "DIGITRAFFIC", "TRAINS", "DGT", "CAMERAS", "AIR",
    "IODA",
):
    os.environ[f"ENABLE_{flag}"] = "false"

os.environ["SQLITE_PATH"] = str(Path(tempfile.mkdtemp(prefix="aegis-tests-")) / "osint.db")
os.environ["AI_PROVIDER"] = "local"
os.environ["RETENTION_DAYS"] = "1"
os.environ.setdefault("GEO_DIR", str(ROOT / "data" / "geo"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """Cliente con el ciclo de vida real: índice GTFS, geovallas y cero ingestas."""
    with TestClient(app) as test_client:
        yield test_client
