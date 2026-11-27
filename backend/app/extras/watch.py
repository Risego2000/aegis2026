"""Watchlists: qué le importa al analista y cómo se le avisa.

Una regla es un filtro guardado (categoría, país, texto, área, gravedad). Cada
nuevo suceso se contrasta contra las reglas activas; si encaja, se registra el
impacto, se empuja al canal de avisos del mapa y, si la regla tiene URL, se
entrega por webhook (Slack, Telegram, n8n, lo que sea).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Iterable

import httpx

from .storage import ExtrasStore

log = logging.getLogger("aegis.watch")


def _in_bbox(event: Any, bbox: list[float] | None) -> bool:
    if not bbox or len(bbox) != 4:
        return True
    west, south, east, north = (float(v) for v in bbox)
    lat = float(getattr(event, "lat", 0) or 0)
    lon = float(getattr(event, "lon", 0) or 0)
    return west <= lon <= east and south <= lat <= north


def matches(watch: dict[str, Any], event: Any) -> bool:
    if not watch.get("active", True):
        return False
    kind = str(watch.get("kind") or "event")
    if kind not in ("event", "all"):
        return False
    query = str(watch.get("query") or "").strip().lower()
    if query:
        haystack = " ".join(
            str(getattr(event, field, "") or "")
            for field in ("title", "summary", "category", "iso3", "country")
        ).lower()
        if not all(term in haystack for term in query.split()):
            return False
    minimum = float(watch.get("min_severity") or 0)
    if minimum and float(getattr(event, "severity", 0) or 0) < minimum:
        return False
    return _in_bbox(event, watch.get("bbox"))


async def deliver(url: str, payload: dict[str, Any]) -> None:
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as exc:  # noqa: BLE001 - la entrega nunca rompe la ingesta
        log.warning("webhook %s: %s", url, exc)


def evaluate(events: Iterable[Any], store: ExtrasStore, hub: Any = None) -> int:
    """Contrasta los sucesos nuevos contra las reglas y reparte avisos."""
    watches = store.list_watchlists(active_only=True)
    if not watches:
        return 0
    hits = 0
    for event in events:
        for watch in watches:
            if not matches(watch, event):
                continue
            alert = {
                "ts": str(getattr(event, "event_time", "")),
                "title": str(getattr(event, "title", "") or "")[:200],
                "message": f"Regla «{watch['name']}» · {getattr(event, 'category', '')}",
                "severity": "critical" if float(getattr(event, "severity", 0) or 0) >= 8 else "warning",
                "event_type": "watchlist",
                "fence_id": watch["id"],
                "fence_name": watch["name"],
                "event_id": str(getattr(event, "id", "") or getattr(event, "uid", "")),
            }
            store.record_hit(watch["id"], alert["event_id"], alert["title"], alert)
            hits += 1
            if hub is not None:
                try:
                    hub.push_alert(alert)
                except Exception:  # noqa: BLE001
                    pass
            url = watch.get("webhook") or ""
            if url:
                # entrega en segundo plano: la ingesta no espera a Slack
                try:
                    asyncio.get_running_loop().create_task(deliver(url, alert))
                except RuntimeError:
                    pass
    if hits:
        log.info("watchlists: %d avisos", hits)
    return hits
