"""Alertas de patrón: lo que un analista quiere que le avisen sin mirar.

El motor de geovallas ya avisa de «algo entró en esta zona». Esto es distinto:
patrones sobre los datos que ya tenemos, sin zonas dibujadas a mano.

* **Emergencia aérea**: squawk 7500/7600/7700 o campo `emergency`.
* **Posición estancada**: el avión sigue emitiendo pero su última posición tiene
  más de 3 minutos (transpondedor o GNSS degradado).
* **Buque que se apaga o salta**: reutiliza las anomalías AIS.
* **Tren con retraso > 20 min** (GTFS-RT de Renfe/Amtrak).
* **Foco de incendios que se dispara** en una celda de 1°.
* **Celda con varias aeronaves degradadas** (posible interferencia GNSS).

Cada patrón tiene enfriamiento (30 min) y clave estable: el mismo avión en
emergencia no genera 12 avisos, pero sí vuelve a avisar a la media hora.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from ..live import AIRCRAFT, TRAINS, VESSELS
from . import anomalies, gnss

log = logging.getLogger("aegis.patterns")

COOLDOWN_S = 1800
EMERGENCY_SQUAWKS = {
    "7500": ("interferencia ilícita", "critical"),
    "7600": ("fallo de radio", "high"),
    "7700": ("emergencia general", "critical"),
}
TRAIN_DELAY_S = 1200
STALE_POSITION_S = 180
WILDFIRE_RATIO = 3.0
WILDFIRE_MIN = 12

_seen: dict[str, float] = {}


def _key(kind: str, ident: str) -> str:
    return f"{kind}:{ident}"


def _fresh(key: str, now: float) -> bool:
    last = _seen.get(key, 0.0)
    if now - last < COOLDOWN_S:
        return False
    _seen[key] = now
    # poda: el diccionario no puede crecer sin fin en un proceso de semanas
    if len(_seen) > 4000:
        cutoff = now - COOLDOWN_S * 2
        for stale in [k for k, when in _seen.items() if when < cutoff]:
            _seen.pop(stale, None)
    return True


def _alert(
    *,
    kind: str,
    ident: str,
    title: str,
    message: str,
    severity: str,
    lat: float | None,
    lon: float | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "fence_id": f"pattern:{kind}",
        "fence_name": "Patrón automático",
        "actor_id": ident,
        "actor_type": kind,
        "event_type": "pattern",
        "severity": severity,
        "title": title,
        "message": message,
        "lat": lat,
        "lon": lon,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "payload": payload or {},
    }


def _aircraft(now: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for aid, actor in list(AIRCRAFT.items.items()):
        squawk = str(actor.get("squawk") or "").strip()
        emergency = str(actor.get("emergency") or "").strip().lower()
        callsign = actor.get("callsign") or aid
        if squawk in EMERGENCY_SQUAWKS or (emergency and emergency not in ("none", "no")):
            what, severity = EMERGENCY_SQUAWKS.get(squawk, ("emergencia declarada", "critical"))
            code = squawk or emergency
            if _fresh(_key("squawk", f"{aid}:{code}"), now):
                out.append(_alert(
                    kind="aircraft", ident=str(aid),
                    title=f"Emergencia aérea · {callsign}",
                    message=f"{callsign} declara {what} (squawk {squawk or '—'}). "
                            f"{actor.get('type') or '?'} a {float(actor.get('altitude_ft') or 0):.0f} ft.",
                    severity=severity, lat=actor.get("lat"), lon=actor.get("lon"),
                    payload={"squawk": squawk, "emergency": emergency},
                ))
        # posición vieja con el avión aún visible: típico de GNSS degradado
        seen_pos = actor.get("seen_pos")
        try:
            age = float(seen_pos) if seen_pos is not None else 0.0
        except (TypeError, ValueError):
            age = 0.0
        if age > STALE_POSITION_S and (actor.get("speed_kn") or 0) > 50:
            if _fresh(_key("stale", str(aid)), now):
                out.append(_alert(
                    kind="aircraft", ident=str(aid),
                    title=f"Posición estancada · {callsign}",
                    message=f"{callsign} lleva {age / 60:.0f} min sin actualizar posición a "
                            f"{float(actor.get('speed_kn') or 0):.0f} kt (transpondedor o GNSS).",
                    severity="medium", lat=actor.get("lat"), lon=actor.get("lon"),
                    payload={"seen_pos_s": age, "gnss": actor.get("gnss")},
                ))
    return out


def _vessels(store, now: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        found = anomalies.evaluate(store.last_seen("vessels") if store else None)
    except Exception as exc:  # noqa: BLE001
        log.debug("patrones AIS: %s", exc)
        return out
    for item in found.get("items", []):
        if not _fresh(_key(item["kind"], str(item["id"])), now):
            continue
        out.append(_alert(
            kind="vessel", ident=str(item["id"]),
            title=f"Anomalía marítima · {item.get('name') or item['id']}",
            message=str(item.get("detail") or item["kind"]),
            severity=item.get("severity") or "low",
            lat=item.get("lat"), lon=item.get("lon"),
            payload={"pattern": item["kind"]},
        ))
    return out


def _trains(now: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tid, actor in list(TRAINS.items.items()):
        delay = actor.get("delay_s")
        try:
            delay = float(delay) if delay is not None else 0.0
        except (TypeError, ValueError):
            continue
        if delay < TRAIN_DELAY_S:
            continue
        if not _fresh(_key("train", str(tid)), now):
            continue
        label = actor.get("name") or actor.get("line") or tid
        out.append(_alert(
            kind="train", ident=str(tid),
            title=f"Retraso de {delay / 60:.0f} min · {label}",
            message=f"{label} acumula {delay / 60:.0f} min sobre el horario previsto.",
            severity="medium" if delay < 3600 else "high",
            lat=actor.get("lat"), lon=actor.get("lon"),
            payload={"delay_s": delay, "line": actor.get("line")},
        ))
    return out


def _wildfires(events: Iterable[Any], now: float) -> list[dict[str, Any]]:
    """Un salto de focos en la misma celda de 1° respecto a las horas previas."""
    import math

    recent: Counter[tuple[int, int]] = Counter()
    older: Counter[tuple[int, int]] = Counter()
    sample: dict[tuple[int, int], Any] = {}
    limit = now - 3 * 3600
    for ev in events:
        if getattr(ev, "category", "") != "wildfire":
            continue
        lat, lon = getattr(ev, "lat", None), getattr(ev, "lon", None)
        if lat is None or lon is None:
            continue
        cell = (math.floor(float(lat)), math.floor(float(lon)))
        try:
            stamp = datetime.fromisoformat(
                str(getattr(ev, "event_time", "")).replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            continue
        if stamp >= limit:
            recent[cell] += 1
            sample.setdefault(cell, ev)
        else:
            older[cell] += 1
    out: list[dict[str, Any]] = []
    for cell, count in recent.items():
        if count < WILDFIRE_MIN:
            continue
        baseline = older.get(cell, 0) / 7.0        # media de las ~21 h anteriores
        ratio = count / baseline if baseline >= 1 else float(count)
        if baseline >= 1 and ratio < WILDFIRE_RATIO:
            continue
        if not _fresh(_key("wildfire", f"{cell[0]},{cell[1]}"), now):
            continue
        ev = sample[cell]
        out.append(_alert(
            kind="wildfire", ident=f"{cell[0]},{cell[1]}",
            title=f"Repunte de focos · celda {cell[0]},{cell[1]}",
            message=f"{count} focos en 3 h frente a {baseline:.1f} de media (×{ratio:.1f}).",
            severity="high" if count >= WILDFIRE_MIN * 2 else "medium",
            lat=float(cell[0]) + 0.5, lon=float(cell[1]) + 0.5,
            payload={"count_3h": count, "baseline": round(baseline, 2), "ratio": round(ratio, 2)},
        ))
    return out


def _gnss(now: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        result = gnss.evaluate(list(AIRCRAFT.items.values()))
    except Exception:  # noqa: BLE001
        return out
    for cell in result.get("cells", []):
        if cell["level"] != "alert":
            continue
        if not _fresh(_key("gnss", cell["cell"]), now):
            continue
        out.append(_alert(
            kind="gnss", ident=cell["cell"],
            title=f"Posible interferencia GNSS · {cell['cell']}",
            message=cell["detail"],
            severity="high", lat=cell["lat"], lon=cell["lon"],
            payload={"degraded": cell["degraded"], "evaluated": cell["evaluated"], "index": cell["index"]},
        ))
    return out


def scan(events: Iterable[Any] | None = None, store: Any = None, hub: Any = None) -> list[dict[str, Any]]:
    """Ejecuta todos los patrones y empuja lo nuevo al canal de avisos."""
    now = time.time()
    alerts: list[dict[str, Any]] = []
    for detector in (
        lambda: _aircraft(now),
        lambda: _vessels(store, now),
        lambda: _trains(now),
        lambda: _gnss(now),
        lambda: _wildfires(events or [], now),
    ):
        try:
            alerts.extend(detector())
        except Exception as exc:  # noqa: BLE001 - un patrón roto no para los demás
            log.warning("patrón: %s", exc)
    if alerts and hub is not None:
        for alert in alerts[:40]:
            try:
                hub.push_alert(alert)
            except Exception:  # noqa: BLE001
                break
    if alerts:
        log.info("patrones: %d avisos nuevos", len(alerts))
    return alerts
