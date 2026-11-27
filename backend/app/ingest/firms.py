"""NASA FIRMS — anomalías térmicas / focos activos en tiempo casi real.

Dos caminos, ambos con **datos reales** de FIRMS:

1. **Sin clave (por defecto).** Ficheros CSV globales abiertos que NASA publica
   cada pocas horas — no requieren registro:
   `data/active_fire/<producto>/csv/<fichero>_Global_24h.csv`
   Se cargan VIIRS (NOAA-20, sensor VIIRS C2) y MODIS C6.1 y se consolidan.
2. **Con `FIRMS_MAP_KEY`** (gratis, autoalta instantánea en
   https://firms.modaps.eosdis.nasa.gov/api/map_key/). Consulta el API de área
   por cajas continentales, que se refresca antes que los CSV.

Las detecciones son muy densas a escala planetaria (≈93.000 en 24 h), así que se
agrupan en celdas de 0,1° quedándose con la más energética (FRP) y se descartan
las débiles (< 20 MW): eso deja unos pocos miles de focos significativos, que es
lo que se puede leer en un mapa global sin ahogarlo.
"""
from __future__ import annotations

import csv
import io
import logging

from ..config import settings
from ..models import EventRecord, parse_dt, utcnow
from .client import Fetcher

log = logging.getLogger("aegis.firms")

AREA = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/1"
STATIC = "https://firms.modaps.eosdis.nasa.gov/data/active_fire/{product}/csv/{file}"

# Productos abiertos (sin clave). Los ficheros _Global_24h cubren todo el planeta.
STATIC_SOURCES = (
    ("noaa-20-viirs-c2", "J1_VIIRS_C2_Global_24h.csv", "VIIRS NOAA-20"),
    ("modis-c6.1", "MODIS_C6_1_Global_24h.csv", "MODIS C6.1"),
)

# Cajas continentales para el camino con clave (el API limita el área por petición).
REGIONS = {
    "EUROPE": "-25,34,45,72",
    "AFRICA_ME": "-20,-35,60,40",
    "ASIA_PACIFIC": "60,-15,180,60",
    "AMERICAS": "-170,-56,-30,72",
}

MIN_FRP = 20.0        # MW: por debajo son ruido térmico a escala global
CELL_DEG = 0.1        # agrupación espacial de detecciones
MAX_EVENTS = 4000     # tope por ciclo


def _confidence(row: dict) -> tuple[str, int]:
    """FIRMS no es homogéneo: VIIRS usa low/nominal/high, MODIS un porcentaje."""
    raw = (row.get("confidence") or "").strip().lower()
    if raw in ("l", "low"):
        return "low", 30
    if raw in ("n", "nominal"):
        return "nominal", 65
    if raw in ("h", "high"):
        return "high", 90
    try:
        pct = int(float(raw))
    except ValueError:
        return "nominal", 50
    label = "high" if pct >= 80 else "nominal" if pct >= 40 else "low"
    return label, max(1, min(100, pct))


def _when(row: dict):
    date = (row.get("acq_date") or "").strip()
    t = (row.get("acq_time") or "0000").strip().zfill(4)
    return parse_dt(f"{date}T{t[:2]}:{t[2:]}") or utcnow()


def records_from_csv(text: str, origin: str) -> list[EventRecord]:
    """Normaliza un CSV de FIRMS (API de área o fichero global) a `EventRecord`."""
    out: list[EventRecord] = []
    if not text or text.lstrip().startswith("<"):
        return out
    for row in csv.DictReader(io.StringIO(text)):
        try:
            lat = float(row.get("latitude") or "")
            lon = float(row.get("longitude") or "")
        except ValueError:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        try:
            frp = float(row.get("frp") or 0)
        except ValueError:
            frp = 0.0
        conf_label, conf_pct = _confidence(row)
        instrument = (row.get("instrument") or "VIIRS").strip()
        satellite = (row.get("satellite") or "").strip()
        brightness = row.get("bright_ti4") or row.get("brightness") or ""
        when = _when(row)
        acq = f"{row.get('acq_date','')}T{(row.get('acq_time') or '0000').zfill(4)}"
        out.append(
            EventRecord(
                uid=f"firms:{acq}:{lat:.3f}:{lon:.3f}",
                source="firms",
                category="wildfire",
                subtype="thermal anomaly",
                title=f"Foco térmico {instrument} {satellite} · FRP {frp:.0f} MW",
                summary=(
                    f"confianza {conf_label} ({conf_pct}%) · brillo {brightness} K · FRP {frp:.1f} MW · "
                    f"{'noche' if (row.get('daynight') or '').upper() == 'N' else 'día'} · "
                    f"{lat:.3f},{lon:.3f}"
                ),
                lat=lat,
                lon=lon,
                severity=frp if frp > 0 else float(conf_pct),
                severity_label="high" if conf_label == "high" else ("yellow" if conf_label == "nominal" else "green"),
                event_time=when,
                url=(
                    "https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@"
                    f"{lon:.3f},{lat:.3f},9z"
                ),
                payload={
                    "confidence": conf_label,
                    "confidence_pct": conf_pct,
                    "brightness_k": brightness,
                    "frp_mw": frp,
                    "satellite": satellite,
                    "instrument": instrument,
                    "daynight": row.get("daynight"),
                    "version": row.get("version"),
                    "origin": origin,
                },
            )
        )
    return out


def consolidate(records: list[EventRecord]) -> list[EventRecord]:
    """Agrupa por celda y deja el foco más energético de cada una."""
    cells: dict[tuple[float, float], EventRecord] = {}
    for rec in records:
        if (rec.severity or 0) < MIN_FRP:
            continue
        key = (round(rec.lat / CELL_DEG) * CELL_DEG, round(rec.lon / CELL_DEG) * CELL_DEG)
        current = cells.get(key)
        if current is None or (rec.severity or 0) > (current.severity or 0):
            cells[key] = rec
    ordered = sorted(cells.values(), key=lambda r: r.severity or 0, reverse=True)
    return ordered[:MAX_EVENTS]


async def fetch(fetcher: Fetcher) -> list[EventRecord]:
    records: list[EventRecord] = []
    used: list[str] = []

    if settings.firms_map_key:
        # Camino preferente: API de área (más fresca), cuatro cajas continentales
        for name, box in REGIONS.items():
            try:
                text = await fetcher.get_text(
                    AREA.format(key=settings.firms_map_key, source="VIIRS_SNPP_NRT", area=box), retries=1
                )
            except Exception as exc:  # noqa: BLE001 - si el API falla se usa el fichero global
                log.warning("FIRMS área %s: %s", name, str(exc)[:120])
                continue
            if "No data" in text[:200]:
                continue
            records.extend(records_from_csv(text, f"area:{name}"))
            used.append(name)

    if not records:
        # Camino sin clave: ficheros globales abiertos de NASA
        for product, filename, label in STATIC_SOURCES:
            try:
                text = await fetcher.get_text(STATIC.format(product=product, file=filename), retries=1)
            except Exception as exc:  # noqa: BLE001 - un producto caído no invalida el otro
                log.warning("FIRMS %s: %s", label, str(exc)[:120])
                continue
            part = records_from_csv(text, f"static:{product}")
            log.info("FIRMS %s: %d detecciones", label, len(part))
            records.extend(part)
            used.append(label)

    if not records:
        raise RuntimeError("FIRMS no devolvió detecciones (¿mantenimiento de NASA?)")

    final = consolidate(records)
    log.info(
        "FIRMS: %d detecciones → %d focos consolidados (celda %.1f°, FRP ≥ %.0f MW) · %s",
        len(records), len(final), CELL_DEG, MIN_FRP, ", ".join(used),
    )
    return final
