"""Instant geofencing with Tile38-compatible FENCE/DETECT semantics.

The pattern (from the architecture doc): keep the *moving* world in an
in-memory spatial index, register fences, and only emit when an object changes
relationship with a fence — `DETECT enter,exit,inside`. Membership state is
diffed per collection, so the cost is O(actors) per refresh instead of
O(actors × fences × history).

Two backends:
  * `Tile38Client` (real Tile38 over RESP) when TILE38_URL is set — the
    authoritative geofence engine for multi-node deployments.
  * this in-process engine otherwise — identical semantics, zero services.

Rules are data, not code: an AOI carries a list of rule ids.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..config import settings
from ..models import Event, haversine_m, iso, utcnow
from ..storage.base import Store

SEVERITY_RANK = {"info": 1, "low": 1, "medium": 2, "high": 3, "critical": 4}

AVAILABLE_RULES = {
    "aircraft": "Cualquier aeronave entra o sale del AOI",
    "emergency": "Aeronave con squawk de emergencia (7500/7600/7700)",
    "vessel": "Buque entra o sale del AOI",
    "fast_vessel": "Buque a más de 32 nudos (posible interdicción)",
    "quake": "Sismo M4.5+ dentro del AOI",
    "disaster": "Alerta GDACS naranja/roja dentro del AOI",
}


def point_in_polygon(lat: float, lon: float, ring: list[list[float]]) -> bool:
    """Ray casting on [lon, lat] pairs."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def circle_polygon(lat: float, lon: float, radius_m: float, steps: int = 64) -> list[list[float]]:
    ring: list[list[float]] = []
    for i in range(steps):
        bearing = 2 * math.pi * i / steps
        dlat = (radius_m * math.cos(bearing)) / 111_320.0
        dlon = (radius_m * math.sin(bearing)) / (111_320.0 * max(0.05, math.cos(math.radians(lat))))
        ring.append([round(lon + dlon, 5), round(lat + dlat, 5)])
    ring.append(ring[0])
    return ring


@dataclass
class Fence:
    id: str
    name: str
    kind: str = "circle"
    lat: float | None = None
    lon: float | None = None
    radius_m: float | None = None
    geometry: dict[str, Any] | None = None
    rules: list[str] = field(default_factory=lambda: ["aircraft", "emergency", "vessel", "quake", "disaster"])
    active: bool = True

    def contains(self, lat: float, lon: float) -> bool:
        if not self.active:
            return False
        if self.geometry and self.geometry.get("type") == "Polygon":
            ring = self.geometry["coordinates"][0]
            return point_in_polygon(lat, lon, ring)
        if self.lat is None or self.lon is None or not self.radius_m:
            return False
        return haversine_m(self.lat, self.lon, lat, lon) <= self.radius_m

    def to_geojson(self) -> dict[str, Any]:
        if self.geometry:
            geom = self.geometry
        else:
            geom = {
                "type": "Polygon",
                "coordinates": [circle_polygon(self.lat or 0, self.lon or 0, self.radius_m or 0)],
            }
        return {"type": "Feature", "geometry": geom, "properties": {"id": self.id, "name": self.name}}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "lat": self.lat,
            "lon": self.lon,
            "radius_m": self.radius_m,
            "geometry": self.geometry,
            "rules": self.rules,
            "active": self.active,
        }


class GeofenceEngine:
    def __init__(self, store: Store):
        self.store = store
        self.fences: dict[str, Fence] = {}
        self.membership: dict[tuple[str, str], set[str]] = {}   # (fence_id, layer) -> ids
        self.actor_pos: dict[str, tuple[float, float]] = {}
        self.alerts: list[dict[str, Any]] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._throttle: dict[tuple, float] = {}
        self.counters: dict[str, int] = {"enter": 0, "exit": 0, "inside": 0, "rule": 0}

    # ------------------------------------------------------------------ #
    async def load(self) -> None:
        for f in await self.store.list_fences():
            fence = Fence(
                id=f["id"], name=f["name"], kind=f.get("kind") or "circle",
                lat=f.get("lat"), lon=f.get("lon"), radius_m=f.get("radius_m"),
                geometry=f.get("geometry"), rules=f.get("rules") or [], active=bool(f.get("active", True)),
            )
            self.fences[fence.id] = fence

    async def add_fence(self, payload: dict[str, Any]) -> Fence:
        fence = Fence(
            id=payload.get("id") or f"aoi-{int(time.time()*1000)}",
            name=payload.get("name") or "AOI",
            kind=payload.get("kind") or "circle",
            lat=payload.get("lat"),
            lon=payload.get("lon"),
            radius_m=payload.get("radius_m"),
            geometry=payload.get("geometry"),
            rules=payload.get("rules") or list(AVAILABLE_RULES.keys()),
            active=True,
        )
        self.fences[fence.id] = fence
        await self.store.add_fence(fence.to_dict())
        return fence

    async def delete_fence(self, fence_id: str) -> bool:
        self.fences.pop(fence_id, None)
        for key in [k for k in self.membership if k[0] == fence_id]:
            self.membership.pop(key, None)
        # un AOI borrado no debe seguir apareciendo en el feed de alertas
        self.alerts = [a for a in self.alerts if a.get("fence_id") != fence_id]
        await self.store.delete_alerts_for_fence(fence_id)
        return await self.store.delete_fence(fence_id)

    def geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [f.to_geojson() for f in self.fences.values()],
        }

    # ------------------------------------------------------------------ #
    # pub/sub
    # ------------------------------------------------------------------ #
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _emit(self, alert: dict[str, Any]) -> None:
        alert.setdefault("ts", iso(utcnow()))
        key = (alert.get("fence_id"), alert.get("actor_id"), alert.get("event_type"), alert.get("title"))
        now = time.time()
        last = self._throttle.get(key, 0)
        if now - last < 600:      # de-bounce: 10 min per (fence, object, rule)
            return
        self._throttle[key] = now
        self.alerts.append(alert)
        del self.alerts[:-400]
        self.counters[alert["event_type"]] = self.counters.get(alert["event_type"], 0) + 1
        await self.store.add_alert(alert)
        try:
            from ..livehub import HUB

            HUB.push_alert(alert)          # mismo aviso por el canal SSE
        except Exception:  # noqa: BLE001
            pass
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(alert)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    async def emit_snapshot(self, fence: Fence, aircraft: int, vessels: int) -> None:
        """One-shot 'estado actual' alert right after an AOI is created, so the
        operator gets immediate feedback instead of waiting for the next sweep."""
        if not (aircraft or vessels):
            await self._emit({
                "fence_id": fence.id, "fence_name": fence.name, "actor_id": fence.id,
                "actor_type": "aoi", "event_type": "inside", "severity": "info",
                "title": f"AOI activo · {fence.name}",
                "message": "sin objetos dentro en este momento · vigilancia armada",
                "lat": fence.lat, "lon": fence.lon, "payload": {"rules": fence.rules},
            })
            return
        await self._emit({
            "fence_id": fence.id, "fence_name": fence.name, "actor_id": fence.id,
            "actor_type": "aoi", "event_type": "inside", "severity": "info",
            "title": f"AOI activo · {fence.name}",
            "message": f"{aircraft} aeronaves y {vessels} buques dentro ahora mismo · "
                       f"reglas: {', '.join(fence.rules)}",
            "lat": fence.lat, "lon": fence.lon,
            "payload": {"aircraft": aircraft, "vessels": vessels, "rules": fence.rules},
        })

    # ------------------------------------------------------------------ #
    # moving objects: aircraft / vessels
    # ------------------------------------------------------------------ #
    async def update_positions(self, layer: str, actors: Iterable[dict[str, Any]]) -> None:
        """Diff membership per fence and fire enter/exit/inside events."""
        current: dict[str, dict[str, Any]] = {}
        for actor in actors:
            aid = str(actor.get("id"))
            lat, lon = actor.get("lat"), actor.get("lon")
            if lat is None or lon is None:
                continue
            current[aid] = actor
            self.actor_pos[aid] = (lat, lon)

        for fence in list(self.fences.values()):
            if not fence.active or layer not in fence.rules:
                continue
            key = (fence.id, layer)
            previous = self.membership.get(key, set())
            now_inside = {aid for aid, a in current.items() if fence.contains(a["lat"], a["lon"])}
            self.membership[key] = now_inside

            for aid in now_inside - previous:
                actor = current[aid]
                await self._emit(
                    self._alert(
                        fence, actor, layer, "enter",
                        f"{self._label(layer, actor)} entró en {fence.name}",
                        actor,
                    )
                )
            for aid in previous - now_inside:
                actor = current.get(aid) or {"id": aid}
                await self._emit(
                    self._alert(
                        fence, actor, layer, "exit",
                        f"{self._label(layer, actor)} salió de {fence.name}",
                        actor,
                    )
                )
            # `inside` is emitted for objects that stay inside but match a rule
            for aid in now_inside:
                actor = current[aid]
                if layer == "aircraft" and str(actor.get("squawk") or "") in settings.emergency_squawks:
                    await self._emit(
                        self._alert(
                            fence, actor, layer, "rule",
                            f"EMERGENCY squawk {actor.get('squawk')} dentro de {fence.name}",
                            actor, severity="critical",
                        )
                    )

        # ---- global rules (independent of AOIs) -------------------------
        for aid, actor in current.items():
            if layer != "aircraft":
                continue
            squawk = str(actor.get("squawk") or "")
            if squawk in settings.emergency_squawks:
                code = {"7500": "interferencia ilícita", "7600": "fallo de radio", "7700": "emergencia general"}[squawk]
                await self._emit(
                    {
                        "fence_id": None,
                        "actor_id": aid,
                        "actor_type": layer,
                        "event_type": "rule",
                        "severity": "critical",
                        "title": f"Squawk {squawk} · {code}",
                        "message": f"{actor.get('callsign') or aid} ({actor.get('type') or '?'}) "
                                   f"FL{actor.get('altitude_ft') or 0:.0f} — {actor.get('lat'):.3f},{actor.get('lon'):.3f}",
                        "lat": actor.get("lat"),
                        "lon": actor.get("lon"),
                        "payload": actor,
                    }
                )

    def _label(self, layer: str, actor: dict[str, Any]) -> str:
        if layer == "aircraft":
            return f"✈ {actor.get('callsign') or actor.get('id')} ({actor.get('type') or '?'})"
        if layer == "vessel":
            return f"⚓ {actor.get('name') or actor.get('id')}"
        return f"{layer}:{actor.get('id')}"

    def _alert(self, fence: Fence, actor: dict[str, Any], layer: str,
               etype: str, title: str, src: dict[str, Any], severity: str = "medium") -> dict[str, Any]:
        return {
            "fence_id": fence.id,
            "fence_name": fence.name,
            "actor_id": str(src.get("id")),
            "actor_type": layer,
            "event_type": etype,
            "severity": severity,
            "title": title,
            "message": self._describe(layer, src),
            "lat": src.get("lat"),
            "lon": src.get("lon"),
            "payload": {k: v for k, v in src.items() if k not in ("lat", "lon")},
        }

    def _describe(self, layer: str, a: dict[str, Any]) -> str:
        if layer == "aircraft":
            return (
                f"{a.get('callsign') or a.get('id')} · {a.get('type') or '?'} · "
                f"{a.get('altitude_ft') or 0:.0f} ft · {a.get('speed_kn') or 0:.0f} kt"
            )
        if layer == "vessel":
            return f"{a.get('name') or a.get('id')} · {a.get('speed_kn') or 0:.1f} kt · rumbo {a.get('course') or 0:.0f}°"
        return str(a.get("id"))

    # ------------------------------------------------------------------ #
    # static events: quakes / disasters
    # ------------------------------------------------------------------ #
    async def evaluate_events(self, events: list[Event]) -> None:
        for ev in events:
            for fence in list(self.fences.values()):
                if not fence.active or not fence.contains(ev.lat, ev.lon):
                    continue
                if ev.category == "earthquake" and "quake" in fence.rules:
                    if (ev.severity or 0) >= 4.5:
                        await self._emit(
                            {
                                "fence_id": fence.id,
                                "fence_name": fence.name,
                                "actor_id": ev.id,
                                "actor_type": "event",
                                "event_type": "rule",
                                "severity": "critical" if (ev.severity or 0) >= settings.big_quake_mag else "high",
                                "title": f"Sismo M{ev.severity:.1f} en {fence.name}",
                                "message": ev.title,
                                "lat": ev.lat,
                                "lon": ev.lon,
                                "payload": {"event_id": ev.id, "category": ev.category},
                            }
                        )
                if ev.category == "disaster" and "disaster" in fence.rules:
                    if (ev.severity_label or "").lower() in ("orange", "red"):
                        await self._emit(
                            {
                                "fence_id": fence.id,
                                "fence_name": fence.name,
                                "actor_id": ev.id,
                                "actor_type": "event",
                                "event_type": "rule",
                                "severity": "critical" if ev.severity_label.lower() == "red" else "high",
                                "title": f"Alerta {ev.severity_label.upper()} · {ev.subtype} en {fence.name}",
                                "message": ev.title,
                                "lat": ev.lat,
                                "lon": ev.lon,
                                "payload": {"event_id": ev.id, "category": ev.category},
                            }
                        )

    def status(self) -> dict[str, Any]:
        return {
            "engine": "tile38" if settings.tile38_url else "in-process",
            "fences": len(self.fences),
            "tracked_objects": len(self.actor_pos),
            "counters": self.counters,
            "subscribers": len(self._subscribers),
            "rules": AVAILABLE_RULES,
        }
