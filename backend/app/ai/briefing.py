"""RAG-style AI briefing over the events currently in the operator's viewport.

Flow:
  viewport bbox + time window  ->  top-N consolidated events (already de-duped
  by the NLP pipeline)        ->  compact, citation-tagged context block
  ->  LLM (Ollama/Gemini)     ->  markdown executive briefing with [E#] refs

If no LLM is reachable, `local_briefing()` builds the same document from the
data with deterministic ranking — the feature never degrades to an error page.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from ..models import Event
from .providers import chat, probe

SYSTEM = (
    "Eres un analista OSINT senior de un centro de situación (fusion center). "
    "Escribes en español, tono seco, operativo, sin especulación. "
    "Solo puedes usar los eventos suministrados; cada afirmación debe llevar su "
    "referencia [E#]. Distingue hechos observados de inferencias. "
    "No inventes cifras, lugares ni actores que no aparezcan en el contexto."
)

CATEGORY_ES = {
    "earthquake": "sismo",
    "disaster": "desastre natural",
    "wildfire": "incendio",
    "conflict": "conflicto",
    "protest": "protesta",
    "diplomacy": "diplomacia",
    "economy": "economía",
    "news": "noticia",
    "military": "militar",
}

SEV_WEIGHT = {"red": 40, "critical": 34, "orange": 28, "high": 24, "yellow": 16, "green": 8, "info": 6}


def rank(event: Event) -> float:
    sev = SEV_WEIGHT.get((event.severity_label or "").lower(), 8)
    mag = (event.severity or 0) if event.category == "earthquake" else 0
    return sev + mag * 3 + 4 * math.log1p(max(0, event.mentions - 1)) + 6 * event.confidence


def _mins_ago(iso_ts: str) -> int:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - dt).total_seconds() // 60)
    except Exception:  # noqa: BLE001
        return 0


def build_context(events: list[Event], limit: int = 40) -> tuple[str, list[dict[str, Any]]]:
    ranked = sorted(events, key=rank, reverse=True)[:limit]
    lines = []
    citations = []
    for i, ev in enumerate(ranked, 1):
        ref = f"E{i}"
        citations.append(
            {
                "ref": ref,
                "id": ev.id,
                "title": ev.title,
                "category": ev.category,
                "lat": ev.lat,
                "lon": ev.lon,
                "url": ev.url,
                "severity": ev.severity_label,
            }
        )
        lines.append(
            f"[{ref}] {ev.event_time} (+{_mins_ago(ev.event_time)}m) | cat={ev.category}"
            f" | sev={ev.severity_label or '-'} | val={ev.severity if ev.severity is not None else '-'}"
            f" | {ev.lat:.3f},{ev.lon:.3f} | {ev.country or 'sin país'}"
            f" | fuentes={','.join(ev.sources)} (menciones={ev.mentions}, conf={ev.confidence})"
            f" | {ev.title}"
        )
    return "\n".join(lines), citations


def summary_numbers(events: Iterable[Event]) -> dict[str, Any]:
    events = list(events)
    by_cat = Counter(ev.category for ev in events)
    by_sev = Counter((ev.severity_label or "info").lower() for ev in events)
    by_country = Counter(ev.country.split(",")[-1].strip() for ev in events if ev.country)
    multi = [ev for ev in events if ev.sources_count > 1]
    return {
        "total": len(events),
        "by_category": dict(by_cat.most_common()),
        "by_severity": dict(by_sev),
        "by_country": dict(by_country.most_common(8)),
        "multi_source": len(multi),
        "mentions": sum(ev.mentions for ev in events),
    }


PROMPT = """Redacta un EXPEDIENTE DE SITUACIÓN con este formato exacto en markdown:

## Resumen ejecutivo
(3-5 frases, lo que un mando necesita saber primero, con referencias [E#])

## Eventos principales
(5-8 viñetas ordenadas por criticidad: qué, dónde, cuándo, corroboración [E#])

## Patrón y contexto
(2-4 frases sobre concentración geográfica, actores recurrentes, escalada o
desescalada; separa explícitamente inferencia de observación)

## Vacíos de información
(2-3 viñetas sobre lo que NO se puede confirmar con los datos disponibles)

## Vigilancia sugerida
(3 viñetas accionables: qué mirar, dónde, con qué umbral)

VENTANA: {window}
BBOX: {bbox}
EVENTOS CONSOLIDADOS ({count} en la ventana, {multi} multi-fuente, {mentions} menciones totales):

{context}
"""


def local_briefing(events: list[Event], *, window: str, bbox: list[float], provider: str = "local") -> str:
    """Deterministic analyst output — no LLM required."""
    numbers = summary_numbers(events)
    ranked = sorted(events, key=rank, reverse=True)
    top = ranked[:8]
    context, citations = build_context(events, limit=40)
    ref_of = {c["id"]: c["ref"] for c in citations}

    out: list[str] = []
    out.append("## Resumen ejecutivo")
    if not events:
        out.append(
            "No hay eventos consolidados en la ventana del mapa seleccionada. "
            "Amplía el área, alarga la ventana temporal o lanza una ingesta manual."
        )
    else:
        cats = ", ".join(f"{CATEGORY_ES.get(k, k)} ({v})" for k, v in list(numbers["by_category"].items())[:4])
        crit = [ev for ev in ranked if (ev.severity_label or "").lower() in ("red", "critical", "orange", "high")]
        out.append(
            f"En la ventana consultada se han consolidado **{numbers['total']} eventos** "
            f"a partir de **{numbers['mentions']} menciones** de las fuentes conectadas "
            f"({cats}). {numbers['multi_source']} eventos están corroborados por más de una "
            f"fuente. {len(crit)} eventos superan el umbral de criticidad alta."
        )
        if crit:
            lead = crit[0]
            out.append(
                f"El foco prioritario es **{lead.title}** "
                f"({lead.lat:.2f}, {lead.lon:.2f}) [{ref_of.get(lead.id,'E1')}], "
                f"con {lead.sources_count} fuente(s) y severidad {lead.severity_label or 'n/d'}."
            )

    out.append("\n## Eventos principales")
    for ev in top:
        corroboration = f"{len(ev.sources)} fuentes / {ev.mentions} menciones" if ev.mentions > 1 else "fuente única"
        out.append(
            f"- **{ev.title}** — {CATEGORY_ES.get(ev.category, ev.category)}"
            f"{f' {ev.severity_label.upper()}' if ev.severity_label else ''}"
            f" en {ev.country or f'{ev.lat:.2f},{ev.lon:.2f}'}"
            f" (hace {_mins_ago(ev.event_time)} min · {corroboration}) "
            f"[{ref_of.get(ev.id,'E?')}]"
        )
    if not top:
        out.append("- Sin eventos en la ventana.")

    out.append("\n## Patrón y contexto")
    clusters = defaultdict(int)
    for ev in events:
        clusters[(round(ev.lat), round(ev.lon))] += 1
    hot = sorted(clusters.items(), key=lambda kv: kv[1], reverse=True)[:3]
    if hot:
        out.append(
            "Concentraciones observadas (celdas de 1°): "
            + "; ".join(f"{lat}°,{lon}° → {n} eventos" for (lat, lon), n in hot)
            + "."
        )
    if numbers["by_country"]:
        out.append(
            "Países/regiones con más registros: "
            + ", ".join(f"{k} ({v})" for k, v in list(numbers["by_country"].items())[:5])
            + "."
        )
    out.append(
        "_Inferencia:_ la densidad relativa indica dónde se concentra la cobertura "
        "informativa, no necesariamente dónde ocurre más; GDELT sobrerrepresenta "
        "regiones con prensa digital densa."
    )

    out.append("\n## Vacíos de información")
    out.append("- No se dispone de verificación independiente fuera de las fuentes listadas.")
    out.append(f"- {max(0, numbers['total'] - numbers['multi_source'])} eventos siguen siendo de fuente única.")
    out.append("- La telemetría ADS-B depende de receptores comunitarios: hay vacíos de cobertura oceánica y a baja cota.")

    out.append("\n## Vigilancia sugerida")
    if events:
        ev = ranked[0]
        out.append(f"- Monitorizar un AOI de 150 km en torno a {ev.lat:.2f},{ev.lon:.2f} con reglas sismo/desastre/aviación.")
    out.append("- Elevar el umbral de alerta a M6.0+ y alertas GDACS naranja/roja en la ventana activa.")
    out.append("- Revisar squawk 7700/7600/7500 y buques >32 kn dentro de los AOI definidos.")
    out.append(f"\n---\n_Expediente generado por el analista local determinista ({provider}). "
               "Conecta Ollama o Gemini para narrativa generativa._")
    return "\n".join(out)


async def build_briefing(
    events: list[Event],
    *,
    bbox: list[float] | None = None,
    window: str = "24h",
    use_llm: bool = True,
) -> dict[str, Any]:
    status = await probe()
    context, citations = build_context(events)
    numbers = summary_numbers(events)
    provider = "local"

    markdown = ""
    if use_llm and status.provider in ("ollama", "gemini") and status.available and events:
        prompt = PROMPT.format(
            window=window,
            bbox=", ".join(f"{v:.2f}" for v in (bbox or [])),
            count=len(events),
            multi=numbers["multi_source"],
            mentions=numbers["mentions"],
            context=context,
        )
        text, provider = await chat(prompt, system=SYSTEM)
        if text and len(text) > 120:
            markdown = text
        else:
            provider = "local"

    if not markdown:
        markdown = local_briefing(events, window=window, bbox=bbox or [], provider=provider)

    # strip any hallucinated citation that is not in the context
    valid_refs = {c["ref"] for c in citations}
    for ref in set(re.findall(r"\[(E\d+)\]", markdown)):
        if ref not in valid_refs:
            markdown = markdown.replace(f"[{ref}]", "")

    return {
        "markdown": markdown,
        "provider": provider,
        "llm_available": status.provider in ("ollama", "gemini") and status.available,
        "ai_status": {
            "provider": status.provider,
            "model": status.model,
            "available": status.available,
            "detail": status.detail,
        },
        "window": window,
        "bbox": bbox,
        "event_count": len(events),
        "numbers": numbers,
        "citations": citations,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
