"""Almacén auxiliar: watchlists, casos con cadena de custodia y posiciones.

Vive en el mismo fichero SQLite que el resto (WAL permite dos conexiones sin
drama) pero con tablas propias y un esquema que se crea al arrancar. Nada de
esto toca el camino crítico de la ingesta: si fallara, el mapa sigue vivo.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlists (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'event',
    query        TEXT DEFAULT '',
    bbox         TEXT,
    min_severity REAL DEFAULT 0,
    webhook      TEXT DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    last_hit     TEXT
);

CREATE TABLE IF NOT EXISTS watch_hits (
    seq       INTEGER PRIMARY KEY,
    watch_id  TEXT NOT NULL,
    event_id  TEXT NOT NULL,
    ts        TEXT NOT NULL,
    title     TEXT,
    payload   TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS watch_hits_idx ON watch_hits(ts DESC);

CREATE TABLE IF NOT EXISTS cases (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    summary    TEXT DEFAULT '',
    tlp        TEXT DEFAULT 'AMBER',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_items (
    seq        INTEGER PRIMARY KEY,
    id         TEXT UNIQUE NOT NULL,
    case_id    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    ref        TEXT DEFAULT '',
    title      TEXT DEFAULT '',
    note       TEXT DEFAULT '',
    sha256     TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload    TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS case_items_idx ON case_items(case_id, created_at);

CREATE TABLE IF NOT EXISTS positions (
    seq      INTEGER PRIMARY KEY,
    ts       TEXT NOT NULL,
    kind     TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL,
    alt      REAL DEFAULT 0,
    speed    REAL DEFAULT 0,
    track    REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS positions_ts_idx ON positions(ts DESC);
CREATE INDEX IF NOT EXISTS positions_actor_idx ON positions(kind, actor_id, ts DESC);
"""

GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash(payload: Any, prev_hash: str) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(b"\x1f")
    h.update(_canonical(payload).encode("utf-8"))
    return h.hexdigest()


class ExtrasStore:
    """Tablas de analista. Síncrono a propósito: son consultas pequeñas."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings.sqlite_path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    def init(self) -> None:
        with self._lock:
            # Esquema previo del desarrollo (columna `rowid_`): se rehace. Son
            # tablas nuevas y sin datos de usuario, así que recrear es seguro.
            legacy = self._conn.execute(
                "SELECT name FROM pragma_table_info('case_items') WHERE name='rowid_'"
            ).fetchone()
            if legacy:
                for table in ("positions", "case_items", "cases", "watch_hits", "watchlists"):
                    self._conn.execute(f"DROP TABLE IF EXISTS {table}")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # watchlists
    # ------------------------------------------------------------------ #
    def list_watchlists(self, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM watchlists"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["bbox"] = json.loads(item["bbox"]) if item["bbox"] else None
            item["active"] = bool(item["active"])
            out.append(item)
        return out

    def add_watchlist(self, data: dict[str, Any]) -> dict[str, Any]:
        watcher = {
            "id": f"wl:{uuid.uuid4().hex[:12]}",
            "name": (data.get("name") or "vigilancia").strip()[:120],
            "kind": (data.get("kind") or "event").strip(),
            "query": (data.get("query") or "").strip()[:200],
            "bbox": json.dumps(data["bbox"]) if data.get("bbox") else None,
            "min_severity": float(data.get("min_severity") or 0),
            "webhook": (data.get("webhook") or "").strip()[:500],
            "created_at": _now(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO watchlists (id, name, kind, query, bbox, min_severity, webhook, active, created_at)"
                " VALUES (:id, :name, :kind, :query, :bbox, :min_severity, :webhook, 1, :created_at)",
                watcher,
            )
            self._conn.commit()
        watcher["bbox"] = data.get("bbox")
        watcher["active"] = True
        watcher["last_hit"] = None
        return watcher

    def delete_watchlist(self, watch_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM watchlists WHERE id=?", (watch_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def record_hit(self, watch_id: str, event_id: str, title: str, payload: dict[str, Any]) -> None:
        ts = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO watch_hits (watch_id, event_id, ts, title, payload) VALUES (?,?,?,?,?)",
                (watch_id, event_id, ts, title[:300], json.dumps(payload, default=str)[:8000]),
            )
            self._conn.execute("UPDATE watchlists SET last_hit=? WHERE id=?", (ts, watch_id))
            self._conn.commit()

    def hits(self, limit: int = 60) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM watch_hits ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item["payload"] or "{}")
            out.append(item)
        return out

    # ------------------------------------------------------------------ #
    # casos + cadena de custodia
    # ------------------------------------------------------------------ #
    def create_case(self, title: str, summary: str = "", tlp: str = "AMBER") -> dict[str, Any]:
        case = {
            "id": f"case:{uuid.uuid4().hex[:10]}",
            "title": title.strip()[:200] or "caso sin título",
            "summary": summary.strip()[:4000],
            "tlp": (tlp or "AMBER").upper()[:10],
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO cases (id, title, summary, tlp, created_at, updated_at)"
                " VALUES (:id, :title, :summary, :tlp, :created_at, :updated_at)",
                case,
            )
            self._conn.commit()
        return case

    def list_cases(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM cases ORDER BY created_at DESC").fetchall()
            out = []
            for row in rows:
                item = dict(row)
                item["items"] = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM case_items WHERE case_id=?", (item["id"],)
                ).fetchone()["n"]
                out.append(item)
        return out

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                return None
            case = dict(row)
            items = [dict(r) for r in self._conn.execute(
                "SELECT * FROM case_items WHERE case_id=? ORDER BY seq", (case_id,)
            ).fetchall()]
        for item in items:
            item["payload"] = json.loads(item["payload"] or "{}")
        case["items"] = items
        return case

    def add_case_item(self, case_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Añade evidencia con hash encadenado (append-only)."""
        with self._lock:
            case = self._conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
            if case is None:
                return None
            last = self._conn.execute(
                "SELECT sha256 FROM case_items WHERE case_id=? ORDER BY seq DESC LIMIT 1", (case_id,)
            ).fetchone()
            prev_hash = last["sha256"] if last else GENESIS
            payload = data.get("payload") or {}
            item = {
                "id": f"ev:{uuid.uuid4().hex[:10]}",
                "case_id": case_id,
                "kind": (data.get("kind") or "note").strip()[:40],
                "ref": str(data.get("ref") or "")[:300],
                "title": (data.get("title") or "").strip()[:300],
                "note": (data.get("note") or "").strip()[:4000],
                "sha256": _hash(payload, prev_hash),
                "prev_hash": prev_hash,
                "created_at": _now(),
                "payload": json.dumps(payload, default=str)[:20000],
            }
            self._conn.execute(
                "INSERT INTO case_items (id, case_id, kind, ref, title, note, sha256, prev_hash, created_at, payload)"
                " VALUES (:id, :case_id, :kind, :ref, :title, :note, :sha256, :prev_hash, :created_at, :payload)",
                item,
            )
            self._conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (item["created_at"], case_id))
            self._conn.commit()
        item["payload"] = payload
        return item

    def verify_case(self, case_id: str) -> dict[str, Any]:
        """Recalcula la cadena completa: detecta cualquier edición posterior."""
        case = self.get_case(case_id)
        if case is None:
            return {"ok": False, "error": "caso desconocido"}
        prev = GENESIS
        broken: list[str] = []
        for item in case["items"]:
            expected = _hash(item["payload"], prev)
            if item["prev_hash"] != prev or item["sha256"] != expected:
                broken.append(item["id"])
            prev = item["sha256"]
        return {
            "ok": not broken,
            "case_id": case_id,
            "items": len(case["items"]),
            "broken": broken,
            "head": prev if case["items"] else GENESIS,
        }

    # ------------------------------------------------------------------ #
    # posiciones (reproducción histórica)
    # ------------------------------------------------------------------ #
    def save_positions(self, rows: Iterable[tuple[str, str, float, float, float, float, float]]) -> int:
        values = [
            (_now(), kind, actor_id, lat, lon, alt or 0, speed or 0, track or 0)
            for kind, actor_id, lat, lon, alt, speed, track in rows
        ]
        if not values:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT INTO positions (ts, kind, actor_id, lat, lon, alt, speed, track)"
                " VALUES (?,?,?,?,?,?,?,?)",
                values,
            )
            self._conn.commit()
        return len(values)

    def prune_positions(self, hours: int = 6) -> int:
        limit = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        with self._lock:
            cur = self._conn.execute("DELETE FROM positions WHERE ts < ?", (limit,))
            self._conn.commit()
        return cur.rowcount

    def positions_at(self, ts: str, window_s: int = 150) -> list[dict[str, Any]]:
        try:
            moment = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        except ValueError:
            return []
        lo = (moment - timedelta(seconds=window_s)).isoformat(timespec="seconds")
        hi = (moment + timedelta(seconds=window_s)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT kind, actor_id, lat, lon, alt, speed, track, MAX(ts) AS ts
                FROM positions WHERE ts BETWEEN ? AND ?
                GROUP BY kind, actor_id
                """,
                (lo, hi),
            ).fetchall()
        return [dict(r) for r in rows]

    def last_seen(self, kind: str, hours: int = 3) -> dict[str, str]:
        limit = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                "SELECT actor_id, MAX(ts) AS ts FROM positions"
                " WHERE kind=? AND ts >= ? GROUP BY actor_id",
                (kind, limit),
            ).fetchall()
        return {row["actor_id"]: row["ts"] for row in rows}

    def stats(self) -> dict[str, int]:
        with self._lock:
            out = {}
            for table in ("watchlists", "watch_hits", "cases", "case_items", "positions"):
                out[table] = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        return out

    def close(self) -> None:
        with self._lock:
            self._conn.close()
