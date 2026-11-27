"""Anomalías de tráfico marítimo y aéreo sobre los datos que ya recibimos.

Tres patrones clásicos del análisis marítimo, todos con datos propios:

* **Hueco AIS**: el barco deja de transmitir y luego reaparece. Puede ser
  cobertura (Digitraffic solo cubre el Báltico) o apagado deliberado; el
  analista ve la duración y decide.
* **Velocidad imposible**: dos posiciones separadas más de lo que el casco
  puede navegar en ese tiempo → error de posición o suplantación.
* **Fondeo/deriva en alta mar**: quieto durante mucho tiempo lejos de la costa
  (no se calcula la costa: se usa la distancia al punto anterior y la velocidad).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterable

from ..live import VESSELS
from ..models import haversine_m

MAX_SPEED_KN = 55.0          # el buque más rápido del mundo ronda 40-50 kn
GAP_S = 900                  # 15 min sin posición con el resto de la flota viva
STATIONARY_S = 1800          # 30 min parado
STATIONARY_KM = 1.5


def _trail(actor_id: str) -> list[tuple[float, float, float, float, float, float]]:
    # el histórico es un deque acotado: se copia para poder recorrerlo por pares
    return list(VESSELS.history.get(actor_id) or [])


def impossible_speeds(min_km: float = 5.0) -> list[dict[str, Any]]:
    """Saltos que exigen más velocidad de la que un buque puede llevar."""
    out: list[dict[str, Any]] = []
    for actor_id in list(VESSELS.history):
        trail = _trail(actor_id)
        for a, b in zip(trail, trail[1:]):
            dt = b[0] - a[0]
            if dt < 120:
                continue
            dist_km = haversine_m(a[1], a[2], b[1], b[2]) / 1000.0
            if dist_km < min_km:
                continue
            knots = dist_km / (dt / 3600.0) / 1.852
            if knots > MAX_SPEED_KN:
                actor = VESSELS.items.get(actor_id, {})
                out.append(
                    {
                        "kind": "ais_impossible_speed",
                        "id": actor_id,
                        "lat": b[1],
                        "lon": b[2],
                        "severity": "high",
                        "detail": (
                            f"{dist_km:.0f} km en {dt / 60:.0f} min → {knots:.0f} kn "
                            f"(máximo creíble {MAX_SPEED_KN:.0f} kn)"
                        ),
                        "name": actor.get("name") or actor.get("mmsi") or actor_id,
                    }
                )
                break
    return out


def stationary_at_sea() -> list[dict[str, Any]]:
    """Buques parados mucho tiempo: fondeo, avería o transferencia."""
    out: list[dict[str, Any]] = []
    for actor_id in list(VESSELS.history):
        trail = _trail(actor_id)
        if len(trail) < 6:
            continue
        first, last = trail[0], trail[-1]
        span = last[0] - first[0]
        if span < STATIONARY_S:
            continue
        moved_km = haversine_m(first[1], first[2], last[1], last[2]) / 1000.0
        if moved_km > STATIONARY_KM:
            continue
        actor = VESSELS.items.get(actor_id, {})
        out.append(
            {
                "kind": "ais_stationary",
                "id": actor_id,
                "lat": last[1],
                "lon": last[2],
                "severity": "low",
                "detail": f"{span / 60:.0f} min con {moved_km:.1f} km de desplazamiento",
                "name": actor.get("name") or actor.get("mmsi") or actor_id,
            }
        )
    return out


def gaps(last_seen: dict[str, str], now: float | None = None) -> list[dict[str, Any]]:
    """Buques que estaban emitiendo y llevan un rato sin hacerlo."""
    now = now or time.time()
    out: list[dict[str, Any]] = []
    for actor_id, stamp in last_seen.items():
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            silent_s = now - moment.timestamp()
        except (ValueError, AttributeError):
            continue
        if silent_s < GAP_S:
            continue
        actor = VESSELS.items.get(actor_id, {})
        out.append(
            {
                "kind": "ais_gap",
                "id": actor_id,
                "lat": actor.get("lat"),
                "lon": actor.get("lon"),
                "severity": "medium" if silent_s > 3600 else "low",
                "detail": f"{silent_s / 60:.0f} min sin posición (cobertura o apagado)",
                "name": actor.get("name") or actor.get("mmsi") or actor_id,
            }
        )
    return out


def evaluate(last_seen: dict[str, str] | None = None) -> dict[str, Any]:
    items = impossible_speeds() + stationary_at_sea()
    if last_seen:
        items += gaps(last_seen)
    items.sort(key=lambda i: {"high": 0, "medium": 1, "low": 2}.get(i["severity"], 3))
    return {
        "count": len(items),
        "items": items[:200],
        "by_kind": {kind: sum(1 for i in items if i["kind"] == kind) for kind in
                    ("ais_gap", "ais_impossible_speed", "ais_stationary")},
    }
