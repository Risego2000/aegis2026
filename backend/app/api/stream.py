"""Canal en vivo con **long-polling** en vez de SSE.

Motivo: el túnel público de Cloudflare (Quick Tunnel) acumula la respuesta y no
la entrega hasta que se cierra, así que `text/event-stream` llega mudo desde
fuera (funcionaba en local y por el túnel SSH, no por el principal). Una
petición que **devuelve** cada pocos segundos atraviesa cualquier proxy.

Diseño:

    GET /api/poll?since=<cursor>&wait=20

  · si hay cambios desde `since`, responde de inmediato;
  · si no, espera como mucho `wait` segundos y responde igualmente (latido);
  · el cliente encadena la siguiente petición al recibir la respuesta.

Resultado: latencia de ~1 s en local y ~2-4 s tras un túnel, con una petición
abierta por pestaña en lugar de diez temporizadores independientes.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import Query, Request

from ..livehub import HUB

MAX_WAIT = 25


async def _pending(since: int) -> dict[str, Any] | None:
    """Cambios pendientes desde el cursor, o None si no hay nada nuevo."""
    changed = HUB.changes()
    if HUB.event_seq > since or HUB.alerts or changed:
        alerts = HUB.alerts[-20:] if HUB.alerts else []
        return {
            "cursor": HUB.event_seq,
            "layers": changed,
            "alerts": alerts,
            "versions": {k: str(v) for k, v in HUB.versions.items()},
            "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    return None


async def api_poll(request: Request, since: int = Query(0, ge=0), wait: int = Query(18, ge=0, le=MAX_WAIT)) -> dict:
    """Devuelve en cuanto hay cambios; si no, late cada `wait` segundos."""
    started = time.monotonic()
    first = True
    while True:
        if await request.is_disconnected():
            break
        # el primer intento ya devuelve el estado actual (sin esperar)
        ready = await _pending(since) if not first else {
            "cursor": HUB.event_seq,
            "layers": [],
            "alerts": [],
            "versions": {k: str(v) for k, v in HUB.versions.items()},
            "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if ready is not None and (first or ready["layers"] or HUB.event_seq > since):
            return ready
        if time.monotonic() - started >= wait:
            return {
                "cursor": HUB.event_seq,
                "layers": [],
                "alerts": [],
                "versions": {k: str(v) for k, v in HUB.versions.items()},
                "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        first = False
        await asyncio.sleep(0.8)
    return {"cursor": HUB.event_seq, "layers": [], "alerts": [], "heartbeat": True}
