"""Graduación de la información: código Admiralty (NATO AJP-2.1) y TLP.

Una app OSINT se convierte en producto citable cuando dice **de dónde viene**
cada afirmación y **cuánto se fía** de ella. El estándar que usan las agencias
es el código Admiralty: una letra para la fiabilidad de la fuente (A-F) y un
número para la credibilidad de la información (1-6), evaluados por separado.

Aquí se derivan de lo que el sistema ya sabe —el historial de fuentes
(`ingest_runs`), la corroboración (`sources_count`, `mentions`), la antigüedad y
la confianza de la deduplicación— sin inventar juicios: la fórmula es pública y
estable, y se explica en cada evento.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import settings

# --------------------------------------------------------------------------- #
# Fiabilidad de la fuente (A-F)
# --------------------------------------------------------------------------- #
# Se asigna por naturaleza de la fuente, no por su última respuesta: una red
# sismológica oficial no es lo mismo que un agregador de prensa. El valor se
# documenta aquí para que cualquiera pueda discutirlo.
SOURCE_RELIABILITY: dict[str, tuple[str, str]] = {
    # redes e instituciones con datos primarios
    "usgs": ("A", "red sismológica oficial de EE. UU."),
    "emsc": ("A", "red sismológica europea (CSEM)"),
    "gdacs": ("B", "agregador oficial de la ONU (JRC)"),
    "eonet": ("A", "catálogo curado de la NASA"),
    "firms": ("B", "detección satelital de la NASA (falsos positivos por nubes/humo)"),
    "nws": ("A", "servicio meteorológico oficial de EE. UU."),
    "dgt": ("A", "administración de tráfico (DATEX II)"),
    "renfe-avisos": ("A", "operador ferroviario (GTFS-RT)"),
    "trains": ("B", "posiciones GTFS-RT del operador"),
    "ais": ("B", "AIS comunitario (cobertura y suplantación posibles)"),
    "adsb": ("B", "ADS-B comunitario (multilateración variable)"),
    "adsb-mil": ("B", "ADS-B comunitario · lista militar"),
    "satellites": ("A", "catálogo orbital Celestrak + SGP4"),
    "cameras": ("B", "redes públicas de cámaras (disponibilidad variable)"),
    "air": ("C", "red ciudadana de sensores (calibración heterogénea)"),
    "gdelt": ("C", "codificación automática de prensa (sin revisión humana)"),
    "ioda": ("A", "medición de red (BGP, sondas, telescopio)"),
    "opensanctions": ("B", "agregación de listas oficiales"),
}

RELIABILITY_LABEL = {
    "A": "completamente fiable",
    "B": "normalmente fiable",
    "C": "bastante fiable",
    "D": "normalmente no fiable",
    "E": "no fiable",
    "F": "no se puede juzgar",
}

CREDIBILITY_LABEL = {
    1: "confirmada por otras fuentes",
    2: "probablemente cierta",
    3: "posiblemente cierta",
    4: "dudosa",
    5: "improbable",
    6: "no se puede juzgar",
}


def reliability_for(source: str, sources: list[str] | None = None) -> tuple[str, str]:
    """La mejor fiabilidad entre las fuentes que corroboran el suceso."""
    candidates = [s for s in ([source] + list(sources or [])) if s]
    best = "F"
    why = "fuente no catalogada"
    for name in candidates:
        grade, reason = SOURCE_RELIABILITY.get(name, ("F", "fuente no catalogada"))
        if grade < best:  # A < B < C…
            best, why = grade, reason
    return best, why


def credibility_for(
    *,
    mentions: int,
    sources_count: int,
    confidence: float,
    age_hours: float,
    known_source: bool,
) -> int:
    """Credibilidad (1-6) con una regla explícita y monótona.

    1 = confirmada por otras fuentes; 2 = probablemente cierta; 3 = posiblemente
    cierta; 4 = dudosa (fuente única y vieja); 6 = no se puede juzgar (fuente
    desconocida). No se usa 5: para afirmar que algo es *improbable* hay que
    haberlo contrastado, y aquí no se inventa.
    """
    if not known_source:
        return 6
    if sources_count >= 3:
        return 1
    if sources_count == 2:
        return 2
    if confidence >= 0.62 and mentions >= 3:
        return 2
    if age_hours > 7 * 24:
        return 4
    return 3


def grade_event(event: Any, now: datetime | None = None) -> dict[str, Any]:
    """Bloque de graduación que se añade a cada evento servido por la API."""
    now = now or datetime.now(timezone.utc)
    source = getattr(event, "source", "") or ""
    sources = list(getattr(event, "sources", None) or [])
    reliability, why = reliability_for(source, sources)
    try:
        event_time = datetime.fromisoformat(str(getattr(event, "event_time", "")).replace("Z", "+00:00"))
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - event_time).total_seconds() / 3600)
    except Exception:  # noqa: BLE001 - una fecha rara no debe romper la ficha
        age_hours = 0.0
    credibility = credibility_for(
        mentions=int(getattr(event, "mentions", 1) or 1),
        sources_count=int(getattr(event, "sources_count", 1) or 1),
        confidence=float(getattr(event, "confidence", 0.45) or 0.45),
        age_hours=age_hours,
        known_source=source in SOURCE_RELIABILITY,
    )
    return {
        "admiralty": f"{reliability}{credibility}",
        "source_reliability": reliability,
        "source_reliability_label": RELIABILITY_LABEL[reliability],
        "source_reliability_reason": why,
        "info_credibility": credibility,
        "info_credibility_label": CREDIBILITY_LABEL[credibility],
        "tlp": settings.tlp.upper(),
        "grading": (
            f"Fiabilidad de la fuente {reliability} ({RELIABILITY_LABEL[reliability]}: {why}); "
            f"credibilidad de la información {credibility} ({CREDIBILITY_LABEL[credibility]}). "
            f"{int(getattr(event, 'sources_count', 1) or 1)} fuente(s), "
            f"{int(getattr(event, 'mentions', 1) or 1)} mención(es)."
        ),
    }


def grade_summary(events: list[Any]) -> dict[str, int]:
    """Reparto por grado Admiralty, para cabeceras de informe."""
    counts: dict[str, int] = {}
    for ev in events:
        code = grade_event(ev)["admiralty"]
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
