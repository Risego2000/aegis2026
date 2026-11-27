"""PostgreSQL + PostGIS implementation of the Store contract (production path).

Activated automatically when DATABASE_URL is set, e.g.

    DATABASE_URL=postgresql://osint:osint@localhost:5432/osint

Requires `pip install asyncpg`. The DDL lives in backend/sql/schema_postgis.sql
and is applied by `init()`.

Rules enforced here (see architecture doc):
  * proximity = `ST_DWithin(geom, point, metres)` on a GiST index — never
    `ST_Buffer(...) && ST_Intersects(...)`.
  * viewport queries = `geom && ST_MakeEnvelope(...)` on the same GiST index.
  * time-series shape = BRIN on event_time + declarative monthly partitions.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Sequence

from ..models import Event, EventRecord, InfraHit, iso, utcnow
from . import dedup
from .base import Store, UpsertResult

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "sql" / "schema_postgis.sql"

COLS = """id, cluster_id, source, sources, category, subtype, title, summary,
          lat, lon, depth_km, severity, severity_label, country, iso3,
          event_time, first_seen, updated_at, url, mentions, sources_count,
          confidence, payload, geometry_json, embedding"""


def _row_to_event(r) -> Event:
    return Event(
        id=r["id"],
        cluster_id=r["cluster_id"],
        source=r["source"],
        sources=list(r["sources"] or []),
        category=r["category"],
        subtype=r["subtype"] or "",
        title=r["title"],
        summary=r["summary"] or "",
        lat=r["lat"],
        lon=r["lon"],
        depth_km=r["depth_km"],
        severity=r["severity"],
        severity_label=r["severity_label"] or "",
        country=r["country"] or "",
        iso3=r["iso3"] or "",
        event_time=r["event_time"].isoformat(timespec="seconds"),
        first_seen=r["first_seen"].isoformat(timespec="seconds"),
        updated_at=r["updated_at"].isoformat(timespec="seconds"),
        url=r["url"] or "",
        mentions=r["mentions"],
        sources_count=r["sources_count"],
        confidence=r["confidence"],
        payload=r["payload"] or {},
        geometry=json.loads(r["geometry_json"]) if r["geometry_json"] else None,
        embedding=list(r["embedding"] or []),
    )


class PostgisStore(Store):
    backend = "postgis"

    def __init__(self, dsn: str):
        import asyncpg  # imported lazily so the default install stays light

        self._asyncpg = asyncpg
        self.dsn = dsn
        self.pool: Any = None

    async def init(self) -> None:
        self.pool = await self._asyncpg.create_pool(self.dsn, min_size=1, max_size=8)
        ddl = SCHEMA_FILE.read_text(encoding="utf-8")
        async with self.pool.acquire() as con:
            await con.execute(ddl)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    # ------------------------------------------------------------------ #
    async def _candidates(self, con, rec: EventRecord):
        """GiST-backed candidate probe: one index range scan + exact distances."""
        radius = dedup.radius_for(rec.category)
        window = dedup.time_window_for(rec.category)
        rows = await con.fetch(
            f"""
            SELECT {COLS}, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint($1,$2),4326)::geography) AS dist_m
            FROM events
            WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint($1,$2),4326), $3)   -- index probe
              AND event_time BETWEEN $4 AND $5
            ORDER BY event_time DESC
            LIMIT 60
            """,
            rec.lon,
            rec.lat,
            radius / 111_000.0,          # ST_Expand takes degrees (SRID units)
            rec.event_time - window,
            rec.event_time + window,
        )
        events = [_row_to_event(r) for r in rows]
        dist = {r["id"]: float(r["dist_m"]) for r in rows}
        return events, dist

    async def upsert(self, records: Sequence[EventRecord]) -> UpsertResult:
        from ..models import embed

        result = UpsertResult()
        async with self.pool.acquire() as con:
            for rec in records:
                if rec.lat is None or rec.lon is None:
                    result.skipped += 1
                    continue
                if not rec.embedding:
                    rec.embedding = embed(rec.text_blob())
                # idempotent refresh of the identical record (same source id)
                same = await con.fetchrow("SELECT id FROM events WHERE id=$1 LIMIT 1", rec.uid)
                if same is not None:
                    await con.execute(
                        """UPDATE events SET updated_at=now(), severity=COALESCE($2, severity),
                                  severity_label=COALESCE(NULLIF($3,''), severity_label),
                                  payload=$4, title=$5, summary=$6 WHERE id=$1""",
                        rec.uid, rec.severity, rec.severity_label,
                        json.dumps(rec.payload, default=str), rec.title[:500], rec.summary or "",
                    )
                    result.merged += 1
                    continue

                candidates, distances = await self._candidates(con, rec)
                decision = dedup.decide(rec, candidates, distances)
                if decision.merge and decision.event:
                    await self._merge(con, decision.event, rec, decision.score)
                    result.merged += 1
                else:
                    await self._insert(con, rec)
                    result.inserted += 1
        return result

    async def _insert(self, con, rec: EventRecord) -> None:
        await con.execute(
            """
            INSERT INTO events (id, cluster_id, source, sources, category, subtype, title, summary,
                lat, lon, geom, depth_km, severity, severity_label, country, iso3, event_time,
                first_seen, updated_at, url, mentions, sources_count, confidence, payload,
                geometry_json, embedding)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    ST_SetSRID(ST_MakePoint($10,$9),4326)::geography,
                    $11,$12,$13,$14,$15,$16,$17,$17,$18,$19,$20,$21,$22,$23,$24)
            ON CONFLICT (id, event_time) DO UPDATE SET
                updated_at = EXCLUDED.updated_at,
                severity = COALESCE(GREATEST(events.severity, EXCLUDED.severity), events.severity, EXCLUDED.severity),
                payload = EXCLUDED.payload
            """,
            rec.uid,
            rec.uid,
            rec.source,
            [rec.source],
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
            rec.event_time,
            utcnow(),
            rec.url,
            1,
            1,
            dedup.confidence(1, 1),
            json.dumps(rec.payload, default=str),
            json.dumps(rec.geometry) if rec.geometry else None,
            rec.embedding,
        )
        await con.execute(
            "INSERT INTO event_mentions(event_id, source, title, url, seen_at, score)"
            " VALUES ($1,$2,$3,$4,now(),1.0)",
            rec.uid,
            rec.source,
            rec.title[:400],
            rec.url,
        )

    async def _merge(self, con, event: Event, rec: EventRecord, score: float) -> None:
        sources = sorted(set(event.sources) | {rec.source})
        mentions = event.mentions + 1
        severity = max(event.severity or 0.0, rec.severity or 0.0) or None
        payload = dedup.merge_payload(event.payload, rec)
        await con.execute(
            """
            UPDATE events SET sources=$1, mentions=$2, sources_count=$3, severity=$4,
                severity_label=COALESCE(NULLIF($5,''), severity_label),
                confidence=$6, payload=$7, updated_at=now(), event_time=LEAST(event_time,$8)
            WHERE id=$9
            """,
            sources,
            mentions,
            len(sources),
            severity,
            rec.severity_label,
            dedup.confidence(mentions, len(sources)),
            json.dumps(payload, default=str),
            rec.event_time,
            event.id,
        )
        await con.execute(
            "INSERT INTO event_mentions(event_id, source, title, url, seen_at, score)"
            " VALUES ($1,$2,$3,$4,now(),$5)",
            event.id,
            rec.source,
            rec.title[:400],
            rec.url,
            round(score, 4),
        )

    # ------------------------------------------------------------------ #
    async def query_bbox(self, bbox, categories=None, since_hours: float = 24.0,
                         limit: int = 5000, search: str | None = None,
                         sources: Sequence[str] | None = None) -> list[Event]:
        w, s, e, n = bbox
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                f"""
                SELECT {COLS} FROM events
                WHERE geom && ST_MakeEnvelope($1,$2,$3,$4,4326)
                  AND event_time >= now() - ($5 || ' hours')::interval
                  AND ($6::text[] IS NULL OR category = ANY($6))
                  AND ($7::text[] IS NULL OR source = ANY($7))
                  AND ($8::text IS NULL OR title ILIKE '%'||$8||'%' OR summary ILIKE '%'||$8||'%')
                ORDER BY event_time DESC
                LIMIT $9
                """,
                w, s, e, n, str(since_hours), list(categories) if categories else None,
                list(sources) if sources else None, search, limit,
            )
        return [_row_to_event(r) for r in rows]

    async def get(self, event_id: str) -> Event | None:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(f"SELECT {COLS} FROM events WHERE id=$1", event_id)
        return _row_to_event(row) if row else None

    async def mentions(self, event_id: str, limit: int = 50) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT source, title, url, seen_at, score FROM event_mentions"
                " WHERE event_id=$1 ORDER BY seen_at DESC LIMIT $2",
                event_id, limit,
            )
        return [dict(r) | {"seen_at": r["seen_at"].isoformat(timespec="seconds")} for r in rows]

    # ------------------------------------------------------------------ #
    async def nearby(self, lat: float, lon: float, radius_m: float = 100_000,
                     kinds=None, limit: int = 40) -> list[InfraHit]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                """
                SELECT id, name, kind, subtype, country, iso3, lat, lon, population,
                       ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint($1,$2),4326)::geography) AS distance_m
                FROM infrastructure
                WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint($1,$2),4326)::geography, $3)
                  AND ($4::text[] IS NULL OR kind = ANY($4))
                ORDER BY distance_m ASC
                LIMIT $5
                """,
                lon, lat, radius_m, list(kinds) if kinds else None, limit,
            )
        return [
            InfraHit(
                id=r["id"], name=r["name"], kind=r["kind"], subtype=r["subtype"] or "",
                country=r["country"] or "", iso3=r["iso3"] or "", lat=r["lat"], lon=r["lon"],
                population=r["population"] or 0, distance_m=round(float(r["distance_m"]), 1),
            )
            for r in rows
        ]

    async def seed_infrastructure(self, items: Sequence[dict[str, Any]]) -> int:
        if not items:
            return 0
        async with self.pool.acquire() as con:
            await con.executemany(
                """
                INSERT INTO infrastructure(id,name,kind,subtype,country,iso3,lat,lon,geom,population)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,ST_SetSRID(ST_MakePoint($8,$7),4326)::geography,$9)
                ON CONFLICT (id) DO NOTHING
                """,
                [
                    (i["id"], i["name"], i["kind"], i.get("subtype", ""), i.get("country", ""),
                     i.get("iso3", ""), i["lat"], i["lon"], i.get("population", 0))
                    for i in items
                ],
            )
        return len(items)

    # ------------------------------------------------------------------ #
    async def stats(self) -> dict[str, Any]:
        async with self.pool.acquire() as con:
            total = await con.fetchval("SELECT count(*) FROM events")
            last24 = await con.fetchval(
                "SELECT count(*) FROM events WHERE event_time >= now() - interval '24 hours'"
            )
            cat = await con.fetch("SELECT category, count(*) c FROM events GROUP BY 1 ORDER BY c DESC")
            sev = await con.fetch(
                "SELECT COALESCE(severity_label,'') s, count(*) c FROM events GROUP BY 1"
            )
            mentions = await con.fetchval("SELECT count(*) FROM event_mentions")
            infra = await con.fetchval("SELECT count(*) FROM infrastructure")
            multi = await con.fetchval("SELECT count(*) FROM events WHERE sources_count > 1")
        return {
            "backend": self.backend,
            "events": total,
            "events_24h": last24,
            "by_category": {r["category"]: r["c"] for r in cat},
            "by_severity": {r["s"]: r["c"] for r in sev},
            "mentions": mentions,
            "infrastructure": infra,
            "multi_source_events": multi,
        }

    async def record_run(self, source: str, ok: bool, items: int, message: str, duration_ms: int) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO ingest_runs(source, started_at, ok, items, message, duration_ms)"
                " VALUES ($1, now(), $2, $3, $4, $5)",
                source, ok, items, message[:500], duration_ms,
            )

    async def runs(self, limit: int = 40) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT source, started_at, ok, items, message, duration_ms FROM ingest_runs"
                " ORDER BY started_at DESC LIMIT $1",
                limit,
            )
        return [dict(r) | {"started_at": r["started_at"].isoformat(timespec="seconds")} for r in rows]

    # ------------------------------------------------------------------ #
    async def add_fence(self, fence: dict[str, Any]) -> dict[str, Any]:
        import time

        fence = dict(fence)
        fence.setdefault("id", f"fence-{int(time.time()*1000)}")
        async with self.pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO fences(id,name,kind,lat,lon,radius_m,geometry_json,rules,active,created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,now())
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, radius_m=EXCLUDED.radius_m,
                    rules=EXCLUDED.rules, active=EXCLUDED.active
                """,
                fence["id"], fence.get("name", "AOI"), fence.get("kind", "circle"),
                fence.get("lat"), fence.get("lon"), fence.get("radius_m"),
                json.dumps(fence["geometry"]) if fence.get("geometry") else None,
                json.dumps(fence.get("rules", [])),
            )
        return fence

    async def list_fences(self) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT id,name,kind,lat,lon,radius_m,geometry_json,rules,active,"
                "created_at::text AS created_at FROM fences ORDER BY created_at ASC"
            )
        return [
            dict(r) | {
                "geometry": json.loads(r["geometry_json"]) if r["geometry_json"] else None,
                "rules": r["rules"] or [],
            }
            for r in rows
        ]

    async def delete_fence(self, fence_id: str) -> bool:
        async with self.pool.acquire() as con:
            res = await con.execute("DELETE FROM fences WHERE id=$1", fence_id)
        return res.endswith("1")

    async def add_alert(self, alert: dict[str, Any]) -> None:
        async with self.pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO alerts(ts,fence_id,actor_id,actor_type,event_type,severity,title,message,lat,lon,payload)
                VALUES (now(),$1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                alert.get("fence_id"), alert.get("actor_id"), alert.get("actor_type"),
                alert.get("event_type"), alert.get("severity"), alert.get("title"),
                alert.get("message"), alert.get("lat"), alert.get("lon"),
                json.dumps(alert.get("payload", {}), default=str),
            )

    async def delete_alerts_for_fence(self, fence_id: str) -> int:
        async with self.pool.acquire() as con:
            res = await con.execute("DELETE FROM alerts WHERE fence_id=$1", fence_id)
        try:
            return int(res.split()[-1])
        except Exception:
            return 0

    async def list_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT ts::text AS ts, fence_id, actor_id, actor_type, event_type, severity,"
                " title, message, lat, lon, payload FROM alerts ORDER BY ts DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]

    async def prune(self, retention_days: int) -> int:
        async with self.pool.acquire() as con:
            res = await con.execute(
                "DELETE FROM events WHERE event_time < now() - ($1 || ' days')::interval"
                " AND mentions < 3 AND COALESCE(severity,0) < 6",
                str(retention_days),
            )
        try:
            return int(res.split()[-1])
        except Exception:
            return 0
