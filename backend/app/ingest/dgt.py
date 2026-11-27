"""Incidencias de tráfico de la DGT — DATEX II (nivel C), datos abiertos.

El mismo nodo NAP que sirve las cámaras publica la situación del tráfico en
XML DATEX II: 506 situaciones / 810 registros por ciclo, con tipo, causa, hora,
carretera, punto kilométrico, municipio y provincia y coordenadas.

    https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml  (~3,7 MB)

Cada registro se convierte en un suceso de categoría `trafico`, que se pinta con
el resto de la inteligencia (accidentes, obras, cortes, restricciones…). Los
registros sin coordenadas se descartan: preferimos no tener el punto a tenerlo
mal situado.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

from ..models import EventRecord
from .client import Fetcher

log = logging.getLogger("aegis.dgt")

URL = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml"

# causa DATEX II -> etiqueta en español
CAUSE_ES = {
    "accident": "accidente",
    "roadMaintenance": "obras",
    "maintenanceWorks": "obras",
    "obstruction": "obstrucción",
    "vehicleObstruction": "vehículo averiado",
    "environmentalObstruction": "obstáculo",
    "infrastructureDamageObstruction": "daño en la vía",
    "roadOrCarriagewayOrLaneManagement": "gestión de carriles",
    "abnormalTraffic": "tráfico anómalo",
    "poorEnvironment": "condiciones ambientales",
    "weatherCondition": "meteorología",
    "restriction": "restricción",
    "publicEvent": "evento público",
    "authorityOperation": "operación especial",
    "generalObstruction": "obstrucción",
}

SEVERITY = {
    "accident": ("high", 6.5),
    "obstruction": ("medium", 4.5),
    "vehicleObstruction": ("medium", 4.0),
    "environmentalObstruction": ("medium", 4.0),
    "infrastructureDamageObstruction": ("medium", 4.5),
    "abnormalTraffic": ("medium", 4.0),
    "weatherCondition": ("medium", 4.0),
    "poorEnvironment": ("low", 3.0),
    "roadMaintenance": ("info", 2.0),
    "maintenanceWorks": ("info", 2.0),
}


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _first(node: ET.Element, name: str) -> str:
    for el in node.iter():
        if _local(el.tag) == name and (el.text or "").strip():
            return (el.text or "").strip()
    return ""


def _all(node: ET.Element, name: str) -> list[str]:
    return [(el.text or "").strip() for el in node.iter() if _local(el.tag) == name and (el.text or "").strip()]


def _iso(value: str) -> str:
    """DATEX usa +01:00/+02:00; se normaliza a ISO con offset tal cual."""
    value = (value or "").strip()
    return value if value else ""


def parse(xml_text: str) -> list[EventRecord]:
    """XML DATEX II → sucesos. Tolerante: un registro roto no tumba el resto."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("DGT: XML ilegible: %s", exc)
        return []

    out: list[EventRecord] = []
    for sit in root.iter():
        if _local(sit.tag) != "situation":
            continue
        sit_id = sit.get("id") or ""
        for rec in sit:
            if _local(rec.tag) != "situationRecord":
                continue
            rec_id = rec.get("id") or ""
            lat = _first(rec, "latitude")
            lon = _first(rec, "longitude")
            if not lat or not lon:
                continue
            try:
                flat, flon = float(lat), float(lon)
            except ValueError:
                continue

            cause = _first(rec, "causeType")
            detail = _first(rec, "roadMaintenanceType") or _first(rec, "accidentType") or ""
            label = CAUSE_ES.get(cause) or CAUSE_ES.get(detail) or cause or "incidencia"
            road = _first(rec, "roadName")
            destination = _first(rec, "roadDestination")
            km = _first(rec, "kilometerPoint")
            municipality = _first(rec, "municipality")
            province = _first(rec, "province")
            community = _first(rec, "autonomousCommunity")
            start = _iso(_first(rec, "overallStartTime") or _first(rec, "situationRecordCreationTime"))
            validity = _first(rec, "validityStatus")
            lane = _first(rec, "laneUsage")
            direction = _first(rec, "tpegDirection")

            title_bits = [label.capitalize()]
            if road:
                title_bits.append(road)
            if km:
                title_bits.append(f"km {km}")
            if municipality:
                title_bits.append(municipality)
            title = " · ".join(title_bits)

            summary_bits = []
            if destination:
                summary_bits.append(f"sentido {destination}")
            if direction:
                summary_bits.append(f"dirección {direction}")
            if lane and lane != "allLanesCompleteCarriageway":
                summary_bits.append(f"carril {lane}")
            if province:
                summary_bits.append(f"provincia de {province}")
            if community:
                summary_bits.append(community)
            if validity:
                summary_bits.append(f"estado {validity}")

            severity_label, severity = SEVERITY.get(cause, ("info", 2.5))
            from datetime import datetime, timezone

            try:
                when = datetime.fromisoformat(start)
            except ValueError:
                when = datetime.now(tz=timezone.utc)

            out.append(
                EventRecord(
                    uid=f"dgt:{sit_id}:{rec_id}",
                    source="dgt",
                    category="trafico",
                    title=title[:240],
                    lat=flat,
                    lon=flon,
                    event_time=when,
                    summary=" · ".join(summary_bits)[:500],
                    subtype=label,
                    severity=severity,
                    severity_label=severity_label,
                    country="Spain",
                    iso3="ESP",
                    url="https://www.dgt.es/incidentes",
                    payload={
                        "carretera": road,
                        "km": km,
                        "municipio": municipality,
                        "provincia": province,
                        "comunidad": community,
                        "causa": cause,
                        "validez": validity,
                        "direccion": direction,
                    },
                )
            )
    # registros duplicados de la misma situación: gana el primero (el más nuevo)
    seen: set[str] = set()
    unique: list[EventRecord] = []
    for ev in out:
        if ev.uid in seen:
            continue
        seen.add(ev.uid)
        unique.append(ev)
    return unique


async def refresh(fetcher: Fetcher) -> list[EventRecord]:
    try:
        text = await fetcher.get_text(URL, timeout=90, retries=2,
                                      headers={"Accept": "application/xml,text/xml,*/*"})
    except Exception as exc:  # noqa: BLE001
        log.warning("DGT incidencias: %s", exc)
        return []
    events = parse(text)
    log.info("DGT: %d incidencias de tráfico", len(events))
    return events
