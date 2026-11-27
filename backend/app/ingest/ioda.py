"""Cortes de internet a escala de país (IODA · Georgia Tech).

IODA mide la alcanzabilidad de la red con tres señales independientes (BGP,
sondeo activo y telescopio) y publica alertas por país, región y ASN. La API v2
es **abierta y sin clave**. Es la señal OSINT más limpia de un apagón: no opina,
mide.

El parser es tolerante a propósito: el servicio devuelve envoltorios anidados y
cambia detalles entre versiones, y una capa que se cae por un campo renombrado
no vale para vigilancia. Lo que no se entiende se descarta.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Iterable

from ..config import settings
from ..models import EventRecord, iso, parse_dt, utcnow
from .client import Fetcher

log = logging.getLogger("aegis.ioda")

ALERTS = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts"

# Cortacircuitos: si IODA no responde (pasa en algunas redes y en CI), no tiene
# sentido gastar 25 s por intento cada 10 minutos. Tras tres fallos seguidos se
# deja de intentar una hora y se registra el motivo; la app sigue igual.
_failures = 0
_cooldown_until = 0.0

_CENTROIDS: dict[str, tuple[float, float, str]] | None = None


def _centroids() -> dict[str, tuple[float, float, str]]:
    """ISO3/ISO2 → (lat, lon, nombre) desde Natural Earth, ya versionado."""
    global _CENTROIDS
    if _CENTROIDS is not None:
        return _CENTROIDS
    out: dict[str, tuple[float, float, str]] = {}
    path = Path(settings.geo_dir) / "ne_110m_admin_0_countries.geojson"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("sin cartografía para IODA: %s", exc)
        _CENTROIDS = out
        return out
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        geometry = feat.get("geometry") or {}
        coords = geometry.get("coordinates")
        if not coords:
            continue
        # centroide aproximado: media de los anillos exteriores
        points: list[tuple[float, float]] = []

        def walk(node: Any) -> None:
            if isinstance(node, (list, tuple)) and node and isinstance(node[0], (int, float)):
                if len(node) >= 2:
                    points.append((float(node[0]), float(node[1])))
                return
            if isinstance(node, (list, tuple)):
                for child in node:
                    walk(child)

        walk(coords)
        if not points:
            continue
        lon = sum(p[0] for p in points) / len(points)
        lat = sum(p[1] for p in points) / len(points)
        name = props.get("NAME") or props.get("ADMIN") or ""
        for key in ("ISO_A3", "ADM0_A3", "SOV_A3", "ISO_A2", "ISO_A2_EH"):
            code = str(props.get(key) or "").upper()
            if len(code) in (2, 3) and code not in {"-99", ""}:
                out.setdefault(code, (lat, lon, name))
    _CENTROIDS = out
    return out


def _iter_records(payload: Any) -> Iterable[dict[str, Any]]:
    """Aplana los envoltorios de IODA sin asumir una profundidad fija."""
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if any(k in item for k in ("entityCode", "entity_code", "entityName")):
                yield item
                continue
            for key in ("data", "results", "alerts", "events"):
                if key in item:
                    stack.append(item[key])
        elif isinstance(item, list):
            stack.extend(item)


def _severity(score: Any) -> tuple[float, str]:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 5.0, "orange"
    if value > 1:  # algunas respuestas traen la puntuación en 0-100
        value /= 100.0
    if value >= 0.75:
        return 8.5, "critical"
    if value >= 0.5:
        return 7.0, "red"
    if value >= 0.25:
        return 5.5, "orange"
    return 4.0, "yellow"


def parse(payload: Any) -> list[EventRecord]:
    """Convierte alertas de IODA en eventos; ignora lo que no sea de país."""
    centroids = _centroids()
    records: list[EventRecord] = []
    seen: set[str] = set()
    for row in _iter_records(payload):
        kind = str(row.get("entityType") or row.get("entity_type") or "country").lower()
        if kind not in ("country", "region"):
            continue
        code = str(row.get("entityCode") or row.get("entity_code") or "").upper()
        if not code or code in seen:
            continue
        where = centroids.get(code)
        if where is None:
            continue
        seen.add(code)
        when = parse_dt(row.get("time") or row.get("ts") or row.get("from")) or utcnow()
        score = row.get("score") or row.get("severity") or row.get("level")
        severity, label = _severity(score)
        datasource = row.get("datasource") or row.get("datasourceName") or "BGP+sondas"
        name = row.get("entityName") or where[2] or code
        title = f"Corte de internet en {name}"
        records.append(
            EventRecord(
                uid=f"ioda:{code}:{when.strftime('%Y%m%dT%H%M')}",
                source="ioda",
                category="network",
                subtype="outage",
                title=title,
                summary=(
                    f"IODA detecta una caída de alcanzabilidad en {name} ({code}) "
                    f"según {datasource}. Puntuación {score if score is not None else 'n/d'}."
                ),
                lat=where[0],
                lon=where[1],
                event_time=when,
                severity=severity,
                severity_label=label,
                country=name,
                iso3=code if len(code) == 3 else "",
                url="https://ioda.inetintel.cc.gatech.edu/",
                payload={"ioda": row, "datasource": datasource},
            )
        )
    return records


async def fetch(fetcher: Fetcher) -> list[EventRecord]:
    """Últimas alertas de país. Si IODA no responde, la capa calla y sigue."""
    global _failures, _cooldown_until
    now = time.time()
    if now < _cooldown_until:
        return []
    try:
        # 12 s: si la API no contesta en ese tiempo, no es útil para vigilancia
        payload = await fetcher.get_json(ALERTS, params={"limit": 60}, timeout=12, retries=1)
    except Exception as exc:  # noqa: BLE001 - cuerpo vacío, DNS, TLS, timeout…
        _failures += 1
        if _failures >= 3:
            _cooldown_until = now + 3600
            log.warning(
                "ioda no alcanzable (%s); se reintentará en 1 h. El resto de capas sigue.",
                str(exc)[:160],
            )
        else:
            log.info("ioda sin respuesta (%d/3): %s", _failures, str(exc)[:120])
        return []
    _failures = 0
    _cooldown_until = 0.0
    records = parse(payload)
    if records:
        log.info("ioda: %d cortes detectados", len(records))
    return records
