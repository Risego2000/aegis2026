"""Deduplication rules for the ingest pipeline.

GDELT alone emits ~900 geolocated events every 15 minutes and the same
earthquake arrives from both USGS and GDACS. Before anything is written we
compare the new item against spatially-near, temporally-close candidates using
a cheap index probe, then decide with two independent signals:

* geometric/time proximity (distance in metres, delta in seconds)
* semantic similarity (local hashing embedding cosine + token Jaccard)

The winner absorbs the loser: the database keeps ONE consolidated event with a
mention counter, a source list and a confidence score — which is exactly what
the map and the RAG briefing consume.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..models import Event, EventRecord, cosine, jaccard

# Merge radius (metres) and merge window per category.
MERGE_RADIUS_M: dict[str, float] = {
    "earthquake": 250_000,
    "disaster": 300_000,
    "wildfire": 8_000,
    "conflict": 120_000,
    "protest": 70_000,
    "military": 120_000,
    "diplomacy": 80_000,
    "economy": 80_000,
    "news": 100_000,
    "network": 400_000,   # un apagón afecta a un país entero
}

MERGE_WINDOW_H: dict[str, float] = {
    "earthquake": 6,
    "disaster": 72,
    "wildfire": 12,
    "conflict": 12,
    "protest": 12,
    "military": 12,
    "diplomacy": 24,
    "economy": 24,
    "news": 12,
    "network": 24,
}

# Categories that may collapse into each other (cross-source fusion).
COMPATIBLE = {
    "earthquake": {"earthquake", "disaster"},
    "disaster": {"disaster", "earthquake", "news"},
    "wildfire": {"wildfire"},
    "conflict": {"conflict", "military", "news"},
    "military": {"military", "conflict", "news"},
    "protest": {"protest", "conflict", "news"},
    "diplomacy": {"diplomacy", "news"},
    "economy": {"economy", "news"},
    "news": {"news", "conflict", "military", "protest", "diplomacy", "economy"},
    "network": {"network"},
}

TEXT_MERGE_THRESHOLD = 0.42

# Source trust used when two records are fused.
SOURCE_PRIORITY = {
    "usgs": 100,
    "gdacs": 95,
    "firms": 80,
    "ais": 70,
    "adsb": 70,
    "gdelt": 55,
    "ioda": 90,
}


def payload_of(event: Any) -> dict[str, Any]:
    """Payload de un evento guardado, tolerante a JSON recortado.

    La poda recorta payloads largos (21 KB → 2 KB) para no engordar la base;
    el recorte puede dejar un JSON inválido y eso no debe romper la deducción.
    """
    raw = getattr(event, "payload", None)
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        import json

        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@dataclass
class MatchDecision:
    event: Event | None
    score: float
    reason: str

    @property
    def merge(self) -> bool:
        return self.event is not None


def similarity(new: EventRecord, existing: Event) -> tuple[float, str]:
    """Return (score in [0,1], human readable reason)."""
    cos = cosine(new.embedding, existing.embedding or [])
    text_existing = " ".join(
        [existing.title or "", existing.subtype or "", existing.summary or ""]
    )
    jac = jaccard(new.text_blob(), text_existing)
    combined = 0.6 * cos + 0.4 * jac if cos or jac else 0.0
    return combined, f"cos={cos:.2f} jac={jac:.2f}"


def decide(new: EventRecord, candidates: list[Event], distances: dict[str, float]) -> MatchDecision:
    """Pick the best merge target among index-derived candidates."""
    best: Event | None = None
    best_score = 0.0
    best_reason = ""

    compatible = COMPATIBLE.get(new.category, {new.category})
    sig_new = (new.payload or {}).get("signature")
    for cand in candidates:
        if cand.category not in compatible:
            continue
        # Two GDELT rows with different CAMEO signatures are different events even
        # if the headline template looks identical ("Threaten: IRAN → ISRAEL" vs
        # "Threaten: ORGANIZED CRIME"). Structural identity beats lexical match.
        sig_old = payload_of(cand).get("signature")
        if sig_new and sig_old and sig_new != sig_old:
            continue
        dist = distances.get(cand.id)
        if dist is None:
            continue

        # --- 1. seismo-geometric rule: a quake reported twice is the same quake
        if new.category in ("earthquake", "disaster") and cand.category in ("earthquake", "disaster"):
            mag_new = new.severity if new.severity is not None else 0
            mag_old = cand.severity if cand.severity is not None else 0
            mag_ok = abs(mag_new - mag_old) <= 1.0 if (mag_new and mag_old) else True
            if dist <= 150_000 and mag_ok:
                # same physical source region + compatible magnitude
                score = 0.9 + 0.1 * (1 - min(1.0, dist / 150_000))
                if score > best_score:
                    best, best_score, best_reason = cand, score, f"geo-rule d={dist/1000:.0f}km"
                continue

        # --- 2. semantic rule
        score, why = similarity(new, cand)
        # identical URL or same source id is a hard signal
        if new.url and cand.url and new.url == cand.url:
            score = max(score, 0.95)
            why += " same-url"
        if score > best_score:
            best, best_score, best_reason = cand, score, why

    if best is not None:
        if best_score < TEXT_MERGE_THRESHOLD and "geo-rule" not in best_reason:
            # weak match: only accept if distance is small and time is very close
            dist = distances.get(best.id, 1e9)
            if dist <= 25_000 and best_score >= 0.30:
                return MatchDecision(best, best_score, best_reason + " weak-near")
            return MatchDecision(None, best_score, best_reason)
        return MatchDecision(best, best_score, best_reason)
    return MatchDecision(None, 0.0, "no-candidate")


def confidence(mentions: int, sources_count: int, base: float = 0.45) -> float:
    value = base + 0.18 * max(0, sources_count - 1) + 0.12 * math.log1p(max(0, mentions - 1))
    return round(min(0.99, value), 3)


def merge_payload(old: dict[str, Any], new: EventRecord) -> dict[str, Any]:
    payload = dict(old or {})
    corroboration = payload.setdefault("corroboration", [])
    entry = {
        "source": new.source,
        "url": new.url,
        "title": new.title,
        "at": new.event_time.isoformat(timespec="seconds"),
    }
    if entry not in corroboration:
        corroboration.append(entry)
        del corroboration[:-15]
    # keep first payload fields, add anything new under "extra"
    for key, value in new.payload.items():
        payload.setdefault(key, value)
    return payload


def time_window_for(category: str) -> timedelta:
    return timedelta(hours=MERGE_WINDOW_H.get(category, 12))


def radius_for(category: str) -> float:
    return MERGE_RADIUS_M.get(category, 100_000)
