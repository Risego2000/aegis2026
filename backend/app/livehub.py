"""Canal en vivo único: un solo flujo SSE para toda la aplicación.

Antes el cliente mantenía diez `setInterval` en paralelo (6, 8, 10, 15, 20, 25,
30, 60, 300 y 600 s). Cada capa iba a su aire: el navegador pedía 20 veces por
minuto cosas que no habían cambiado y cada nueva capa añadía otro temporizador.

Aquí el servidor es el que vigila: cada segundo compara el estado de las capas
vivas y, solo cuando algo cambia, escribe un evento `update` con la lista de
capas que hay que volver a pedir. El cliente abre un `EventSource` y recarga
exactamente esas capas. Consecuencias:

  · peticiones ∝ cambios reales, no ∝ tiempo;
  · latencia de un segundo (antes 6-20 s por capa);
  · una sola conexión por pestaña, que además sirve de latido (`ping`).

También se emiten `event` con los sucesos nuevos según se guardan y `alert`
con las alertas del motor de zonas, así que el WebSocket deja de ser necesario
para la interfaz (se mantiene por compatibilidad).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

from .cameras import CAMERAS
from .live import AIRCRAFT, AIR, SATCAT, TRAINS, VESSELS

log = logging.getLogger("aegis.live")

# capa -> función que da su "huella" (cambia si cambia el contenido)
def _layer_versions() -> dict[str, Any]:
    return {
        "aircraft": (len(AIRCRAFT.items), round(AIRCRAFT.updated_at)),
        "vessels": (len(VESSELS.items), round(VESSELS.updated_at)),
        "trains": (len(TRAINS.items), round(TRAINS.updated_at)),
        "air": (len(AIR.items), round(AIR.updated_at)),
        "satellites": (len(SATCAT.sats), round(getattr(SATCAT, "updated_at", 0))),
        # las cámaras cambian una vez cada 30 min: huelle por tamaño + vuelta
        "cameras": (len(CAMERAS.items), CAMERAS.runs),
    }


class LiveHub:
    """Estado compartido del canal en vivo.

    El registry llama a `bump()` cuando termina una ingesta; el endpoint SSE
    compara y emite. Los sucesos nuevos se encolan en `events`.
    """

    def __init__(self) -> None:
        self.versions: dict[str, Any] = _layer_versions()
        self.event_seq: int = 0
        self.new_events: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.started = time.time()
        self.listeners = 0

    # ------------------------------------------------------------------ escritura
    def bump(self, layer: str | None = None) -> None:
        self.versions = _layer_versions()

    def push_events(self, events: list[dict[str, Any]]) -> None:
        """Sucesos recién guardados (los pasa el registry tras el upsert)."""
        if not events:
            return
        self.event_seq += 1
        self.new_events.extend(events[:50])
        if len(self.new_events) > 200:
            self.new_events = self.new_events[-200:]

    def push_alert(self, alert: dict[str, Any]) -> None:
        self.alerts.append(alert)
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

    # ------------------------------------------------------------------- lectura
    def changes(self) -> list[str]:
        """Capas cuya huella ha cambiado desde la última consulta."""
        now = _layer_versions()
        changed = [k for k, v in now.items() if self.versions.get(k) != v]
        if changed:
            self.versions = now
        return changed

    def stats(self) -> dict[str, Any]:
        return {
            "listeners": self.listeners,
            "event_seq": self.event_seq,
            "uptime_s": int(time.time() - self.started),
            "versions": {k: str(v) for k, v in self.versions.items()},
        }


HUB = LiveHub()


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def stream(request) -> AsyncIterator[str]:
    """Generador SSE: saludos + cambios + latido cada 15 s."""
    HUB.listeners += 1
    seen_seq = HUB.event_seq
    seen_alerts = len(HUB.alerts)
    try:
        # relleno inicial: el túnel/proxy no debe retener el flujo esperando
        # a llenar un buffer de 2 KB (es lo que dejaba mudo al SSE desde fuera)
        yield ":" + " " * 2048 + "\n\n"
        yield "retry: 5000\n\n"
        yield _sse("hello", {
            "channels": ["aircraft", "vessels", "trains", "air", "satellites", "cameras", "events", "alerts"],
            "versions": {k: str(v) for k, v in HUB.versions.items()},
            "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        last_ping = time.time()
        while True:
            if await request.is_disconnected():
                break
            changed = HUB.changes()
            if changed:
                yield _sse("update", {"layers": changed, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                last_ping = time.time()

            if HUB.event_seq != seen_seq:
                seen_seq = HUB.event_seq
                batch, HUB.new_events = HUB.new_events, []
                if batch:
                    yield _sse("event", {"events": batch})

            if len(HUB.alerts) != seen_alerts:
                fresh = HUB.alerts[seen_alerts:]
                seen_alerts = len(HUB.alerts)
                for al in fresh:
                    yield _sse("alert", al)

            if time.time() - last_ping > 10:
                last_ping = time.time()
                # el latido va relleno para que también sirva de descarga
                yield ": ping" + " " * 512 + "\n\n"
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:  # navegador cerrado
        raise
    finally:
        HUB.listeners = max(0, HUB.listeners - 1)
