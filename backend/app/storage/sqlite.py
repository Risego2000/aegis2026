"""SQLite + R-Tree implementation of the Store contract.

Why it exists: the architecture targets PostGIS, but the system must be
*runnable* on a laptop / 1-vCPU free tier with zero external services. SQLite
with an R-Tree virtual table provides the same asymptotic behaviour as PostGIS
GiST for the two access patterns we care about (viewport bbox scans and radius
proximity), at zero operational cost.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import struct
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from ..models import Event, EventRecord, InfraHit, bbox_around, haversine_m, iso, parse_dt, utcnow
from . import dedup
from .base import Store, UpsertResult

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
PRAGMA mmap_size=268435456;
PRAGMA wal_autocheckpoint=512;   -- el diario se vacía cada ~2 MB
PRAGMA journal_size_limit=4194304;

CREATE TABLE IF NOT EXISTS events (
    rowid_      INTEGER PRIMARY KEY,
    id          TEXT UNIQUE NOT NULL,
    cluster_id  TEXT NOT NULL,
    source      TEXT NOT NULL,
    sources     TEXT NOT NULL DEFAULT '[]',
    category    TEXT NOT NULL,
    subtype     TEXT DEFAULT '',
    title       TEXT NOT NULL,
    summary     TEXT DEFAULT '',
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    depth_km    REAL,
    severity    REAL,
    severity_label TEXT DEFAULT '',
    country     TEXT DEFAULT '',
    iso3        TEXT DEFAULT '',
    event_time  TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    url         TEXT DEFAULT '',
    mentions    INTEGER NOT NULL DEFAULT 1,
    sources_count INTEGER NOT NULL DEFAULT 1,
    confidence  REAL NOT NULL DEFAULT 0.45,
    payload     TEXT NOT NULL DEFAULT '{}',
    geometry    TEXT,
    embedding   BLOB
);
CREATE INDEX IF NOT EXISTS events_time_idx     ON events(event_time DESC);
CREATE INDEX IF NOT EXISTS events_cat_idx      ON events(category, event_time DESC);
CREATE INDEX IF NOT EXISTS events_cluster_idx  ON events(cluster_id);
CREATE VIRTUAL TABLE IF NOT EXISTS events_rtree USING rtree(rowid_, min_lon, max_lon, min_lat, max_lat);

CREATE TABLE IF NOT EXISTS event_mentions (
    rowid_    INTEGER PRIMARY KEY,
    event_id  TEXT NOT NULL,
    source    TEXT NOT NULL,
    title     TEXT,
    url       TEXT,
    seen_at   TEXT NOT NULL,
    score     REAL,
    payload   TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS mentions_event_idx ON event_mentions(event_id, seen_at DESC);

CREATE TABLE IF NOT EXISTS infrastructure (
    rowid_    INTEGER PRIMARY KEY,
    id        TEXT UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    subtype   TEXT DEFAULT '',
    country   TEXT DEFAULT '',
    iso3      TEXT DEFAULT '',
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    population REAL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS infra_rtree USING rtree(rowid_, min_lon, max_lon, min_lat, max_lat);

CREATE TABLE IF NOT EXISTS ingest_runs (
    rowid_      INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    items       INTEGER NOT NULL DEFAULT 0,
    message     TEXT DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS runs_idx ON ingest_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS fences (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'circle',
    lat         REAL,
    lon         REAL,
    radius_m    REAL,
    geometry    TEXT,
    rules       TEXT DEFAULT '[]',
    active      INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    rowid_      INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL,
    fence_id    TEXT,
    actor_id    TEXT,
    actor_type  TEXT,
    event_type  TEXT,
    severity    TEXT,
    title       TEXT,
    message     TEXT,
    lat         REAL,
    lon         REAL,
    payload     TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS alerts_ts_idx ON alerts(ts DESC);
"""

COLUMNS = (
    "id, cluster_id, source, sources, category, subtype, title, summary, lat, lon,"
    " depth_km, severity, severity_label, country, iso3, event_time, first_seen,"
    " updated_at, url, mentions, sources_count, confidence, payload, geometry, embedding"
)


def _safe_json(raw: Any, fallback: Any = None) -> Any:
    """JSON tolerante: un payload recortado por la poda no debe romper la lectura."""
    if raw is None or raw == "":
        return fallback if fallback is not None else {}
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return fallback if fallback is not None else {}


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes | None) -> list[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        cluster_id=row["cluster_id"],
        source=row["source"],
        sources=json.loads(row["sources"] or "[]"),
        category=row["category"],
        subtype=row["subtype"] or "",
        title=row["title"],
        summary=row["summary"] or "",
        lat=row["lat"],
        lon=row["lon"],
        depth_km=row["depth_km"],
        severity=row["severity"],
        severity_label=row["severity_label"] or "",
        country=row["country"] or "",
        iso3=row["iso3"] or "",
        event_time=row["event_time"],
        first_seen=row["first_seen"],
        updated_at=row["updated_at"],
        url=row["url"] or "",
        mentions=row["mentions"],
        sources_count=row["sources_count"],
        confidence=row["confidence"],
        payload=_safe_json(row["payload"]),
        geometry=json.loads(row["geometry"]) if row["geometry"] else None,
        embedding=_unpack(row["embedding"]),
    )


class SqliteStore(Store):
    backend = "sqlite-rtree"

    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.create_function("haversine_m", 4, haversine_m, deterministic=True)
        self._cache: dict[str, Event] = {}

    # ------------------------------------------------------------------ #
    async def init(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    async def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()

    # ------------------------------------------------------------------ #
    # Dedup candidates: index probe, never a table scan.
    # ------------------------------------------------------------------ #
    def _candidates(self, rec: EventRecord) -> tuple[list[Event], dict[str, float]]:
        radius = dedup.radius_for(rec.category)
        window = dedup.time_window_for(rec.category)
        w, s, e, n = bbox_around(rec.lat, rec.lon, radius)
        since = iso(rec.event_time - window)
        until = iso(rec.event_time + window)
        rows = self._conn.execute(
            f"""
            SELECT {COLUMNS} FROM events
            JOIN events_rtree ON events_rtree.rowid_ = events.rowid_
            WHERE events_rtree.max_lon >= ? AND events_rtree.min_lon <= ?
              AND events_rtree.max_lat >= ? AND events_rtree.min_lat <= ?
              AND events.event_time BETWEEN ? AND ?
            ORDER BY events.event_time DESC
            LIMIT 60
            """,
            (w, e, s, n, since, until),
        ).fetchall()
        events = [_row_to_event(r) for r in rows]
        dist = {ev.id: haversine_m(rec.lat, rec.lon, ev.lat, ev.lon) for ev in events}
        return events, dist

    def _by_uid(self, uid: str) -> Event | None:
        row = self._conn.execute(f"SELECT {COLUMNS} FROM events WHERE id = ?", (uid,)).fetchone()
        return _row_to_event(row) if row else None

    async def upsert(self, records: Sequence[EventRecord]) -> UpsertResult:
        result = UpsertResult()
        now = iso(utcnow())
        with self._lock:
            for rec in records:
                if rec.lat is None or rec.lon is None:
                    result.skipped += 1
                    continue
                if not rec.embedding:
                    from ..models import embed

                    rec.embedding = embed(rec.text_blob())

                # Re-polling the same raw record (USGS/GDACS refresh every cycle)
                # must refresh it, never inflate its mention counter.
                same = self._by_uid(rec.uid)
                if same is not None:
                    self._refresh(same, rec, now)
                    result.merged += 1
                    continue

                existing = self._candidates(rec)
                decision = dedup.decide(rec, *existing)

                if decision.merge and decision.event is not None:
                    self._merge_into(decision.event, rec, decision.score, now)
                    result.merged += 1
                    continue

                event_id = self._insert(rec, now)
                result.inserted += 1
                if event_id:
                    result.fresh.append(event_id)

            self._conn.commit()
        return result

    def _insert(self, rec: EventRecord, now: str) -> str:
        """Inserta y devuelve el id del suceso (para avisar al canal en vivo)."""
        event_time = iso(rec.event_time)
        cur = self._conn.execute(
            """
            INSERT INTO events (id, cluster_id, source, sources, category, subtype, title, summary,
                lat, lon, depth_km, severity, severity_label, country, iso3, event_time, first_seen,
                updated_at, url, mentions, sources_count, confidence, payload, geometry, embedding)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                updated_at=excluded.updated_at,
                severity=COALESCE(MAX(events.severity, excluded.severity), events.severity, excluded.severity),
                payload=excluded.payload
            """,
            (
                rec.uid,
                rec.uid,
                rec.source,
                json.dumps([rec.source]),
                rec.category,
                rec.subtype,
                rec.title[:500],
                (rec.summary or "")[:4000],
                rec.lat,
                rec.lon,
                rec.depth_km,
                rec.severity,
                rec.severity_label,
                rec.country,
                rec.iso3,
                event_time,
                now,
                now,
                rec.url,
                1,
                1,
                dedup.confidence(1, 1),
                json.dumps(rec.payload, default=str)[:20000],
                json.dumps(rec.geometry) if rec.geometry else None,
                _pack(rec.embedding),
            ),
        )
        rowid = cur.lastrowid
        self._conn.execute(
            "INSERT OR REPLACE INTO events_rtree(rowid_, min_lon, max_lon, min_lat, max_lat)"
            " VALUES (?,?,?,?,?)",
            (rowid, rec.lon, rec.lon, rec.lat, rec.lat),
        )
        self._conn.execute(
            "INSERT INTO event_mentions(event_id, source, title, url, seen_at, score, payload)"
            " VALUES (?,?,?,?,?,?,?)",
            (rec.uid, rec.source, rec.title[:400], rec.url, now, 1.0, "{}"),
        )
        return rec.uid

    def _refresh(self, event: Event, rec: EventRecord, now: str) -> None:
        """Idempotent re-ingest of the very same record: no new mention."""
        self._conn.execute(
            """
            UPDATE events SET updated_at=?, severity=COALESCE(?, severity),
                severity_label=COALESCE(NULLIF(?,''), severity_label),
                payload=?, title=?, summary=?, url=COALESCE(NULLIF(?,''), url)
            WHERE id=?
            """,
            (now, rec.severity, rec.severity_label,
             json.dumps(rec.payload, default=str)[:20000],
             rec.title[:500], (rec.summary or "")[:4000], rec.url, event.id),
        )

    def _merge_into(self, event: Event, rec: EventRecord, score: float, now: str) -> None:
        sources = sorted(set(event.sources) | {rec.source})
        mentions = event.mentions + 1
        severity = event.severity
        if rec.severity is not None:
            severity = max(severity or 0.0, rec.severity)
        label = event.severity_label
        if dedup.SOURCE_PRIORITY.get(rec.source, 0) > dedup.SOURCE_PRIORITY.get(event.source, 0):
            label = rec.severity_label or label
        payload = dedup.merge_payload(event.payload, rec)
        payload.setdefault("aliases", [])
        if rec.uid not in payload["aliases"]:
            payload["aliases"].append(rec.uid)
            del payload["aliases"][:-20]
        # keep the earliest observation time, but never let a stale GDELT row
        # rewind a fresh authoritative timestamp
        event_time = min(event.event_time, iso(rec.event_time))
        self._conn.execute(
            """
            UPDATE events SET sources=?, mentions=?, sources_count=?, severity=?,
                severity_label=?, confidence=?, payload=?, updated_at=?, event_time=?
            WHERE id=?
            """,
            (
                json.dumps(sources),
                mentions,
                len(sources),
                severity,
                label,
                dedup.confidence(mentions, len(sources)),
                json.dumps(payload, default=str)[:20000],
                now,
                event_time,
                event.id,
            ),
        )
        self._conn.execute(
            "INSERT INTO event_mentions(event_id, source, title, url, seen_at, score, payload)"
            " VALUES (?,?,?,?,?,?,?)",
            (event.id, rec.source, rec.title[:400], rec.url, now, round(score, 4), "{}"),
        )

    # ------------------------------------------------------------------ #
    async def query_bbox(
        self,
        bbox: tuple[float, float, float, float],
        categories: Sequence[str] | None = None,
        since_hours: float = 24.0,
        limit: int = 5000,
        search: str | None = None,
        sources: Sequence[str] | None = None,
    ) -> list[Event]:
        w, s, e, n = bbox
        since = iso(utcnow() - timedelta(hours=since_hours))
        sql = [
            f"SELECT {COLUMNS} FROM events",
            "JOIN events_rtree ON events_rtree.rowid_ = events.rowid_",
            "WHERE events_rtree.max_lon >= ? AND events_rtree.min_lon <= ?",
            "AND events_rtree.max_lat >= ? AND events_rtree.min_lat <= ?",
            "AND events.event_time >= ?",
        ]
        args: list[Any] = [w, e, s, n, since]
        if categories:
            sql.append(f"AND events.category IN ({','.join('?' * len(categories))})")
            args.extend(categories)
        if sources:
            sql.append(f"AND events.source IN ({','.join('?' * len(sources))})")
            args.extend(sources)
        if search:
            sql.append("AND (events.title LIKE ? OR events.summary LIKE ?)")
            args.extend([f"%{search}%", f"%{search}%"])
        sql.append("ORDER BY events.event_time DESC LIMIT ?")
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(" ".join(sql), args).fetchall()
        return [_row_to_event(r) for r in rows]

    async def get(self, event_id: str) -> Event | None:
        with self._lock:
            return self._by_uid(event_id)

    async def mentions(self, event_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT source, title, url, seen_at, score FROM event_mentions"
                " WHERE event_id=? ORDER BY seen_at DESC LIMIT ?",
                (event_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    async def nearby(
        self,
        lat: float,
        lon: float,
        radius_m: float = 100_000,
        kinds: Sequence[str] | None = None,
        limit: int = 40,
    ) -> list[InfraHit]:
        """ST_DWithin equivalent: R-Tree box probe -> exact haversine residual."""
        w, s, e, n = bbox_around(lat, lon, radius_m)
        sql = [
            "SELECT infrastructure.*, haversine_m(lat, lon, ?, ?) AS distance_m FROM infrastructure",
            "JOIN infra_rtree ON infra_rtree.rowid_ = infrastructure.rowid_",
            "WHERE infra_rtree.max_lon >= ? AND infra_rtree.min_lon <= ?",
            "AND infra_rtree.max_lat >= ? AND infra_rtree.min_lat <= ?",
            "AND distance_m <= ?",
        ]
        args: list[Any] = [lat, lon, w, e, s, n, radius_m]
        if kinds:
            sql.append(f"AND infrastructure.kind IN ({','.join('?' * len(kinds))})")
            args.extend(kinds)
        sql.append("ORDER BY distance_m ASC LIMIT ?")
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(" ".join(sql), args).fetchall()
        return [
            InfraHit(
                id=r["id"],
                name=r["name"],
                kind=r["kind"],
                subtype=r["subtype"] or "",
                country=r["country"] or "",
                iso3=r["iso3"] or "",
                lat=r["lat"],
                lon=r["lon"],
                population=r["population"] or 0,
                distance_m=round(r["distance_m"], 1),
            )
            for r in rows
        ]

    async def seed_infrastructure(self, items: Sequence[dict[str, Any]]) -> int:
        added = 0
        with self._lock:
            for item in items:
                exist = self._conn.execute(
                    "SELECT rowid_ FROM infrastructure WHERE id=?", (item["id"],)
                ).fetchone()
                if exist:
                    continue
                cur = self._conn.execute(
                    "INSERT INTO infrastructure(id,name,kind,subtype,country,iso3,lat,lon,population)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        item["id"],
                        item["name"],
                        item["kind"],
                        item.get("subtype", ""),
                        item.get("country", ""),
                        item.get("iso3", ""),
                        item["lat"],
                        item["lon"],
                        item.get("population", 0),
                    ),
                )
                self._conn.execute(
                    "INSERT OR REPLACE INTO infra_rtree(rowid_, min_lon, max_lon, min_lat, max_lat)"
                    " VALUES (?,?,?,?,?)",
                    (cur.lastrowid, item["lon"], item["lon"], item["lat"], item["lat"]),
                )
                added += 1
            self._conn.commit()
        return added

    # ------------------------------------------------------------------ #
    async def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
            by_cat = self._conn.execute(
                "SELECT category, COUNT(*) c FROM events GROUP BY category ORDER BY c DESC"
            ).fetchall()
            by_sev = self._conn.execute(
                "SELECT COALESCE(severity_label,'') s, COUNT(*) c FROM events GROUP BY s"
            ).fetchall()
            last24 = self._conn.execute(
                "SELECT COUNT(*) c FROM events WHERE event_time >= ?",
                (iso(utcnow() - timedelta(hours=24)),),
            ).fetchone()["c"]
            mentions = self._conn.execute("SELECT COUNT(*) c FROM event_mentions").fetchone()["c"]
            infra = self._conn.execute("SELECT COUNT(*) c FROM infrastructure").fetchone()["c"]
            sources = self._conn.execute(
                "SELECT COUNT(*) c FROM events WHERE sources_count > 1"
            ).fetchone()["c"]
        return {
            "backend": self.backend,
            "events": total,
            "events_24h": last24,
            "by_category": {r["category"]: r["c"] for r in by_cat},
            "by_severity": {r["s"]: r["c"] for r in by_sev},
            "mentions": mentions,
            "infrastructure": infra,
            "multi_source_events": sources,
        }

    async def record_run(
        self, source: str, ok: bool, items: int, message: str, duration_ms: int
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ingest_runs(source, started_at, ok, items, message, duration_ms)"
                " VALUES (?,?,?,?,?,?)",
                (source, iso(utcnow()), 1 if ok else 0, items, message[:500], duration_ms),
            )
            self._conn.commit()

    async def runs(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT source, started_at, ok, items, message, duration_ms FROM ingest_runs"
                " ORDER BY rowid_ DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) | {"ok": bool(r["ok"])} for r in rows]

    # ------------------------------------------------------------------ #
    async def add_fence(self, fence: dict[str, Any]) -> dict[str, Any]:
        fence = dict(fence)
        fence.setdefault("id", f"fence-{int(time.time()*1000)}")
        fence.setdefault("created_at", iso(utcnow()))
        fence.setdefault("active", 1)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO fences(id,name,kind,lat,lon,radius_m,geometry,rules,active,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    fence["id"],
                    fence.get("name", "AOI"),
                    fence.get("kind", "circle"),
                    fence.get("lat"),
                    fence.get("lon"),
                    fence.get("radius_m"),
                    json.dumps(fence["geometry"]) if fence.get("geometry") else None,
                    json.dumps(fence.get("rules", [])),
                    int(fence.get("active", 1)),
                    fence["created_at"],
                ),
            )
            self._conn.commit()
        return fence

    async def list_fences(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM fences ORDER BY created_at ASC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["geometry"] = json.loads(d["geometry"]) if d["geometry"] else None
            d["rules"] = json.loads(d["rules"] or "[]")
            d["active"] = bool(d["active"])
            out.append(d)
        return out

    async def delete_fence(self, fence_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM fences WHERE id=?", (fence_id,))
            self._conn.commit()
        return cur.rowcount > 0

    async def add_alert(self, alert: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO alerts(ts,fence_id,actor_id,actor_type,event_type,severity,title,message,lat,lon,payload)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    alert.get("ts") or iso(utcnow()),
                    alert.get("fence_id"),
                    alert.get("actor_id"),
                    alert.get("actor_type"),
                    alert.get("event_type"),
                    alert.get("severity"),
                    alert.get("title"),
                    alert.get("message"),
                    alert.get("lat"),
                    alert.get("lon"),
                    json.dumps(alert.get("payload", {}), default=str)[:8000],
                ),
            )
            self._conn.execute("DELETE FROM alerts WHERE rowid_ NOT IN (SELECT rowid_ FROM alerts ORDER BY rowid_ DESC LIMIT 2000)")
            self._conn.commit()

    async def delete_alerts_for_fence(self, fence_id: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM alerts WHERE fence_id=?", (fence_id,))
            self._conn.commit()
        return cur.rowcount

    async def list_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts,fence_id,actor_id,actor_type,event_type,severity,title,message,lat,lon,payload"
                " FROM alerts ORDER BY rowid_ DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"] or "{}")
            out.append(d)
        return out

    # ------------------------------------------------------------------ #
    async def prune(self, retention_days: int) -> int:
        """Poda por antigüedad + adelgaza payloads + compacta el fichero.

        El `VACUUM` es la parte que importa: sin él SQLite no devuelve el
        espacio de las filas borradas al sistema y la base solo crece (62 MB
        para 47 MB de eventos). Se lanza en un hilo aparte para no bloquear.
        """
        cutoff = iso(utcnow() - timedelta(hours=retention_days * 24))
        thin_cutoff = iso(utcnow() - timedelta(days=1))
        with self._lock:
            ids = self._conn.execute(
                "SELECT rowid_ FROM events WHERE event_time < ? AND mentions < 3"
                " AND COALESCE(severity,0) < 6",
                (cutoff,),
            ).fetchall()
            for r in ids:
                self._conn.execute("DELETE FROM events_rtree WHERE rowid_=?", (r["rowid_"],))
            self._conn.execute(
                "DELETE FROM events WHERE event_time < ? AND mentions < 3 AND COALESCE(severity,0) < 6",
                (cutoff,),
            )
            self._conn.execute("DELETE FROM ingest_runs WHERE started_at < ?", (cutoff,))
            # el detalle crudo de cada fuente solo es útil el primer día: guardarlo
            # un mes ocupa decenas de MB y la ficha ya muestra lo esencial
            self._conn.execute(
                "UPDATE events SET payload = '{}' WHERE event_time < ? AND LENGTH(payload) > 2",
                (thin_cutoff,),
            )
            # y recorta cualquier payload desmedido: la ficha no necesita 20 KB
            self._conn.execute(
                "UPDATE events SET payload = SUBSTR(payload, 1, 2000) WHERE LENGTH(payload) > 2000"
            )
            self._conn.commit()
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")
            self._conn.commit()
        return len(ids)
