"""Storage factory: PostGIS when DATABASE_URL is set, SQLite otherwise."""
from __future__ import annotations

from ..config import settings
from .base import Store, UpsertResult


def make_store() -> Store:
    if settings.database_url.startswith(("postgres://", "postgresql://")):
        from .postgis import PostgisStore

        return PostgisStore(settings.database_url)
    from .sqlite import SqliteStore

    return SqliteStore(settings.sqlite_path)


__all__ = ["Store", "UpsertResult", "make_store"]
