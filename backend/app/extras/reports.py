"""Productos de diseminación: SITREP, perfil PMESII y export STIX 2.1.

Lo que una agencia entrega no es un mapa: es un documento con fuentes, grados y
confianza. Aquí se generan en Markdown (para leer y para pegar en un informe) y
en STIX (para un SOC o un MISP).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from .tradecraft import CREDIBILITY_LABEL, grade_event, grade_summary

CATEGORY_ES = {
    "earthquake": "Sismos",
    "disaster": "Desastres",
    "wildfire": "Incendios",
    "conflict": "Conflicto",
    "protest": "Protestas",
    "military": "Militar",
    "diplomacy": "Diplomacia",
    "economy": "Economía",
    "news": "Noticias",
    "network": "Red / Internet",
    "trafico": "Tráfico",
    "transporte": "Transporte",
}

# PMESII: las seis dimensiones con las que se describe un país en inteligencia.
PMESII = {
    "political": ("P", "Político"),
    "military": ("M", "Militar"),
    "economic": ("E", "Económico"),
    "social": ("S", "Social"),
    "information": ("I", "Información"),
    "infrastructure": ("I", "Infraestructura"),
}

_CATEGORY_TO_PMESII = {
    "conflict": "military",
    "military": "military",
    "protest": "social",
    "diplomacy": "political",
    "economy": "economic",
    "news": "information",
    "network": "infrastructure",
    "disaster": "infrastructure",
    "earthquake": "infrastructure",
    "wildfire": "infrastructure",
    "trafico": "infrastructure",
    "transporte": "infrastructure",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _line(event: Any, index: int) -> str:
    grade = grade_event(event)
    stamp = str(getattr(event, "event_time", ""))[:16].replace("T", " ")
    title = str(getattr(event, "title", "") or "").replace("|", "/")[:110]
    country = str(getattr(event, "iso3", "") or "")
    sources = ", ".join(getattr(event, "sources", None) or [getattr(event, "source", "")])
    return (
        f"| {index} | {stamp}Z | {country} | {title} | {CATEGORY_ES.get(getattr(event, 'category', ''), getattr(event, 'category', ''))} "
        f"| {grade['admiralty']} | {sources} |"
    )


def sitrep(events: Iterable[Any], hours: float, bbox: list[float] | None = None) -> str:
    """Informe de situación en Markdown, con grados y fuentes citadas."""
    items = list(events)
    by_cat: dict[str, int] = {}
    for ev in items:
        key = str(getattr(ev, "category", "") or "otros")
        by_cat[key] = by_cat.get(key, 0) + 1
    ordered = sorted(
        items,
        key=lambda e: (float(getattr(e, "severity", 0) or 0), str(getattr(e, "event_time", ""))),
        reverse=True,
    )
    top = ordered[:15]
    grades = grade_summary(items)
    box = "mundo" if not bbox else ", ".join(f"{v:.2f}" for v in bbox)
    head = [
        "# SITREP · AEGIS",
        "",
        f"**Ventana:** últimas {hours:g} h · **Área:** {box} · **Generado:** {_now().isoformat(timespec='minutes')}Z",
        f"**Sucesos:** {len(items)} · **Fuentes citadas:** {len({s for e in items for s in (getattr(e, 'sources', None) or [getattr(e, 'source', '')])})}",
        "",
        "## 1. Reparto por categoría",
        "",
    ]
    for cat, count in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        head.append(f"- **{CATEGORY_ES.get(cat, cat)}**: {count}")
    head += [
        "",
        "## 2. Graduación de la información (NATO AJP-2.1)",
        "",
        "| Código | Significado | Sucesos |",
        "|---|---|---|",
    ]
    for code, count in grades.items():
        head.append(f"| {code} | fuente {code[0]} · información {code[1:]} | {count} |")
    head += [
        "",
        "## 3. Sucesos de mayor gravedad",
        "",
        "| # | Hora (UTC) | País | Suceso | Categoría | Grado | Fuentes |",
        "|---|---|---|---|---|---|---|",
    ]
    head += [_line(ev, i + 1) for i, ev in enumerate(top)]
    head += [
        "",
        "## 4. Notas de método",
        "",
        "- Grado **A-F** = fiabilidad de la fuente; **1-6** = credibilidad de la información "
        f"({CREDIBILITY_LABEL[1]} … {CREDIBILITY_LABEL[6]}).",
        "- Los datos son abiertos y sin verificación humana: esta app documenta, no sentencia.",
        "",
    ]
    return "\n".join(head)


def country_profile(events: Iterable[Any], iso3: str) -> dict[str, Any]:
    """Perfil PMESII aproximado con lo que hay en el archivo."""
    code = (iso3 or "").upper()
    items = [e for e in events if str(getattr(e, "iso3", "") or "").upper() == code]
    dimensions: dict[str, dict[str, Any]] = {
        key: {"code": meta[0], "label": meta[1], "events": 0, "severity": 0.0}
        for key, meta in PMESII.items()
    }
    sources: dict[str, int] = {}
    categories: dict[str, int] = {}
    for ev in items:
        dim = _CATEGORY_TO_PMESII.get(str(getattr(ev, "category", "")), "information")
        dimensions[dim]["events"] += 1
        dimensions[dim]["severity"] += float(getattr(ev, "severity", 0) or 0)
        cat = str(getattr(ev, "category", "") or "otros")
        categories[cat] = categories.get(cat, 0) + 1
        for src in (getattr(ev, "sources", None) or [getattr(ev, "source", "")]):
            sources[src] = sources.get(src, 0) + 1
    total = len(items)
    pressure = sum(
        d["events"] * (1.0 if key not in ("military", "infrastructure") else 1.6)
        for key, d in dimensions.items()
    )
    # Índice 0-100: más alto = más estable. Heurística transparente, no un juicio.
    stability = max(0, min(100, round(100 - (pressure / max(1.0, total)) * 12 - min(40, total * 0.4))))
    for dim in dimensions.values():
        dim["severity"] = round(dim["severity"], 1)
    return {
        "iso3": code,
        "events": total,
        "window_hours": 168,
        "stability_index": stability,
        "stability_label": (
            "estable" if stability >= 75 else "tensa" if stability >= 50 else "inestable" if stability >= 25 else "crítica"
        ),
        "dimensions": dimensions,
        "categories": dict(sorted(categories.items(), key=lambda kv: -kv[1])),
        "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])[:12]),
        "method": "Heurística sobre sucesos abiertos de 7 días; no sustituye a un análisis humano.",
    }


def stix_bundle(events: Iterable[Any], tlp: str = "CLEAR") -> dict[str, Any]:
    """STIX 2.1: un `incident` por suceso, con referencia externa y grado."""
    now = _now().isoformat(timespec="seconds").replace("+00:00", "Z")
    identity_id = f"identity--{uuid.uuid5(uuid.NAMESPACE_URL, 'aegis-osint')}"
    objects: list[dict[str, Any]] = [
        {
            "type": "identity",
            "spec_version": "2.1",
            "id": identity_id,
            "created": now,
            "modified": now,
            "name": "AEGIS · centro de inteligencia abierta",
            "identity_class": "system",
        }
    ]
    for ev in events:
        grade = grade_event(ev)
        ev_id = str(getattr(ev, "id", "") or getattr(ev, "uid", ""))
        event_id = f"incident--{uuid.uuid5(uuid.NAMESPACE_URL, 'aegis:' + ev_id)}"
        name = str(getattr(ev, "title", "") or "suceso")[:120]
        obj: dict[str, Any] = {
            "type": "incident",
            "spec_version": "2.1",
            "id": event_id,
            "created": now,
            "modified": now,
            "created_by_ref": identity_id,
            "name": name,
            "description": str(getattr(ev, "summary", "") or "")[:1000],
            "confidence": int(round(float(getattr(ev, "confidence", 0.5) or 0.5) * 100)),
            "labels": [str(getattr(ev, "category", "") or "news")],
            "x_aegis_admiralty": grade["admiralty"],
            "x_aegis_tlp": (tlp or grade["tlp"]).upper(),
        }
        url = str(getattr(ev, "url", "") or "")
        if url:
            obj["external_references"] = [{"source_name": getattr(ev, "source", "aegis"), "url": url}]
        objects.append(obj)
    return {
        "type": "bundle",
        "id": f"bundle--{uuid.uuid4()}",
        "objects": objects,
    }
