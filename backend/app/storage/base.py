"""Storage contract shared by the SQLite (default, zero-dependency) backend and
the PostGIS (production) backend.

A radius/proximity query MUST be index-backed: an R-Tree (SQLite) or GiST
(PostGIS) bounding-box probe followed by an exact great-circle residual
predicate. Never `ST_Buffer(...) && ST_Intersects(...)`, which silently
sequential-scans because the buffer is built per row.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..models import Event, EventRecord, InfraHit


@dataclass
class UpsertResult:
    inserted: int = 0
    merged: int = 0
    skipped: int = 0
    # ids de los sucesos que acaban de entrar (para el canal en vivo)
    fresh: list[str] = field(default_factory=list)

    def add(self, other: "UpsertResult") -> "UpsertResult":
        self.inserted += other.inserted
        self.merged += other.merged
        self.skipped += other.skipped
        self.fresh.extend(other.fresh)
        return self


class Store(ABC):
    backend: str = "unknown"

    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    # -- events ------------------------------------------------------------
    @abstractmethod
    async def upsert(self, records: Sequence[EventRecord]) -> UpsertResult: ...

    @abstractmethod
    async def query_bbox(
        self,
        bbox: tuple[float, float, float, float],
        categories: Sequence[str] | None = None,
        since_hours: float = 24.0,
        limit: int = 5000,
        search: str | None = None,
        sources: Sequence[str] | None = None,
    ) -> list[Event]: ...

    @abstractmethod
    async def get(self, event_id: str) -> Event | None: ...

    @abstractmethod
    async def mentions(self, event_id: str, limit: int = 50) -> list[dict[str, Any]]: ...

    # -- proximity ---------------------------------------------------------
    @abstractmethod
    async def nearby(
        self,
        lat: float,
        lon: float,
        radius_m: float = 100_000,
        kinds: Sequence[str] | None = None,
        limit: int = 40,
    ) -> list[InfraHit]: ...

    @abstractmethod
    async def seed_infrastructure(self, items: Sequence[dict[str, Any]]) -> int: ...

    # -- observability -----------------------------------------------------
    @abstractmethod
    async def stats(self) -> dict[str, Any]: ...

    @abstractmethod
    async def record_run(
        self, source: str, ok: bool, items: int, message: str, duration_ms: int
    ) -> None: ...

    @abstractmethod
    async def runs(self, limit: int = 40) -> list[dict[str, Any]]: ...

    # -- geofences ---------------------------------------------------------
    @abstractmethod
    async def add_fence(self, fence: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    async def list_fences(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def delete_fence(self, fence_id: str) -> bool: ...

    @abstractmethod
    async def add_alert(self, alert: dict[str, Any]) -> None: ...

    @abstractmethod
    async def delete_alerts_for_fence(self, fence_id: str) -> int: ...

    @abstractmethod
    async def list_alerts(self, limit: int = 100) -> list[dict[str, Any]]: ...

    # -- maintenance -------------------------------------------------------
    @abstractmethod
    async def prune(self, retention_days: int) -> int: ...
