"""In-memory live layer: latest positions of aircraft, vessels and satellites.

Moving telemetry never goes to the relational store (it would be millions of
rows/day for zero analytical value) — it lives here, in a dict keyed by the
transponder/MMSI/NORAD id, and is served as GeoJSON to the client-side
Supercluster index. Only *alerts* derived from it are persisted.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Any, Iterable

from .models import utcnow


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


class LiveLayer:
    """Última posición **y trayectoria** de cada elemento móvil.

    El histórico es un deque acotado por actor (no se persiste): sirve para
    dibujar la estela en el mapa y para calcular distancia recorrida, rumbo
    medio y velocidad efectiva. Se muestrea solo cuando el elemento se ha
    movido lo suficiente, para no llenar memoria con ruido de GPS.
    """

    MAX_SAMPLES = 90          # ~30 min de historia por elemento
    MIN_SAMPLE_S = 4.0        # no muestrear más de una vez cada 4 s
    MIN_MOVE_KM = 0.05        # ni si se ha movido menos de 50 m

    def __init__(self, name: str, ttl_s: float = 180.0):
        self.name = name
        self.ttl_s = ttl_s
        self.items: dict[str, dict[str, Any]] = {}
        self.history: dict[str, deque] = {}
        self.first_seen: dict[str, float] = {}
        self.updated_at: float = 0.0
        self.ingested: int = 0

    def upsert_many(self, actors: Iterable[dict[str, Any]]) -> None:
        now = time.time()
        for actor in actors:
            aid = str(actor.get("id") or "").strip()
            if not aid or actor.get("lat") is None or actor.get("lon") is None:
                continue
            actor["_ts"] = now
            previous = self.items.get(aid)
            self.items[aid] = actor
            self.ingested += 1
            self.first_seen.setdefault(aid, now)
            self._sample(aid, actor, previous, now)
        self.updated_at = now
        self._evict(now)

    def _sample(self, aid: str, actor: dict, previous: dict | None, now: float) -> None:
        trail = self.history.get(aid)
        if trail is None:
            trail = self.history[aid] = deque(maxlen=self.MAX_SAMPLES)
        if trail:
            t_prev, lat_prev, lon_prev = trail[-1][0], trail[-1][1], trail[-1][2]
            if now - t_prev < self.MIN_SAMPLE_S:
                return
            if haversine_km(lat_prev, lon_prev, actor["lat"], actor["lon"]) < self.MIN_MOVE_KM:
                return
        trail.append((
            now, float(actor["lat"]), float(actor["lon"]),
            float(actor.get("altitude_ft") or 0.0),
            float(actor.get("speed_kn") or 0.0),
            float(actor.get("track") or actor.get("course") or 0.0),
        ))

    def detail(self, aid: str) -> dict[str, Any] | None:
        """Ficha completa: último estado + métricas derivadas de la estela."""
        actor = self.items.get(aid)
        if not actor:
            return None
        trail = list(self.history.get(aid) or [])
        distance_km = 0.0
        for a, b in zip(trail, trail[1:]):
            distance_km += haversine_km(a[1], a[2], b[1], b[2])
        span_s = (trail[-1][0] - trail[0][0]) if len(trail) > 1 else 0.0
        now = time.time()
        props = {k: v for k, v in actor.items() if k != "_ts"}
        props.update(
            {
                "id": aid,
                "age_s": round(now - actor.get("_ts", now), 1),
                "first_seen_s": round(now - self.first_seen.get(aid, now), 1),
                "samples": len(trail),
                "track_minutes": round(span_s / 60, 1),
                "distance_km": round(distance_km, 2),
                "avg_speed_kmh": round(distance_km / (span_s / 3600), 1) if span_s > 0 else 0.0,
            }
        )
        return {"kind": self.name, "actor": props,
                "history": [{"ts": t, "lat": la, "lon": lo, "altitude_ft": al,
                             "speed_kn": sp, "track": tr}
                            for t, la, lo, al, sp, tr in trail]}

    def track(self, aid: str, minutes: float = 60.0) -> dict[str, Any] | None:
        """Estela como GeoJSON LineString (lo que pinta el mapa)."""
        trail = list(self.history.get(aid) or [])
        if not trail:
            actor = self.items.get(aid)
            if not actor:
                return None
            trail = [(actor.get("_ts", time.time()), float(actor["lat"]), float(actor["lon"]), 0, 0, 0)]
        cutoff = time.time() - minutes * 60
        trail = [s for s in trail if s[0] >= cutoff] or trail[-2:] or trail[-1:]
        coords = [[s[2], s[1]] for s in trail]
        distance_km = sum(haversine_km(a[1], a[2], b[1], b[2]) for a, b in zip(trail, trail[1:]))
        return {
            "kind": self.name,
            "id": aid,
            "minutes": minutes,
            "points": len(coords),
            "distance_km": round(distance_km, 2),
            "geometry": {"type": "LineString", "coordinates": coords},
            "samples": [
                {"ts": int(s[0]), "lat": s[1], "lon": s[2], "altitude_ft": s[3], "speed_kn": s[4]}
                for s in trail
            ],
        }

    def _evict(self, now: float) -> None:
        if len(self.items) < 200:
            return
        deadline = now - self.ttl_s
        if deadline <= 0:
            return
        stale = [k for k, v in self.items.items() if v.get("_ts", 0) < deadline]
        for k in stale:
            self.items.pop(k, None)
            # la estela se conserva un rato más: un avión que sale del radar
            # sigue teniendo trayectoria útil para el analista
            trail = self.history.get(k)
            if trail and (not trail or now - trail[-1][0] > self.ttl_s * 4):
                self.history.pop(k, None)
                self.first_seen.pop(k, None)

    def clear(self) -> None:
        self.items.clear()
        self.history.clear()
        self.first_seen.clear()

    def geojson(self, bbox: tuple[float, float, float, float] | None = None,
                limit: int = 20000) -> dict[str, Any]:
        features = []
        for aid, actor in self.items.items():
            lat, lon = actor["lat"], actor["lon"]
            if bbox:
                w, s, e, n = bbox
                if not (w <= lon <= e and s <= lat <= n):
                    continue
            props = {k: v for k, v in actor.items() if k != "_ts"}
            props["age_s"] = round(time.time() - actor.get("_ts", time.time()), 1)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": props,
                }
            )
            if len(features) >= limit:
                break
        return {
            "type": "FeatureCollection",
            "count": len(features),
            "updated_at": utcnow().isoformat(timespec="seconds"),
            "features": features,
        }

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "count": len(self.items),
            "updated_at": (
                utcnow().fromtimestamp(self.updated_at).isoformat(timespec="seconds")
                if self.updated_at
                else None
            ),
        }


class SatelliteLayer:
    """Propagated with SGP4 from Celestrak TLEs (see ingest/satellites.py)."""

    def __init__(self) -> None:
        self.sats: dict[str, dict[str, Any]] = {}
        self.updated_at: float = 0.0
        self.tle_updated_at: float = 0.0

    def set_positions(self, positions: list[dict[str, Any]]) -> None:
        self.sats = {p["id"]: p for p in positions}
        self.updated_at = time.time()

    def geojson(self) -> dict[str, Any]:
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                "properties": s,
            }
            for s in self.sats.values()
        ]
        return {
            "type": "FeatureCollection",
            "count": len(features),
            "updated_at": utcnow().isoformat(timespec="seconds"),
            "features": features,
        }

    def stats(self) -> dict[str, Any]:
        return {"name": "satellites", "count": len(self.sats),
                "tle_age_min": round((time.time() - self.tle_updated_at) / 60, 1) if self.tle_updated_at else None}


AIRCRAFT = LiveLayer("aircraft", ttl_s=120)
# sensores de calidad del aire: estáticos, sin histórico de trayectoria
AIR = LiveLayer("air", ttl_s=7200)
VESSELS = LiveLayer("vessels", ttl_s=1800)
# Trenes (Renfe, FGC y Amtrak): TTL corto para que no queden trenes fantasma
TRAINS = LiveLayer("trains", ttl_s=120)
SATCAT = SatelliteLayer()
