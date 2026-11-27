#!/usr/bin/env python3
"""Ejecuta un ciclo de ingesta + deduplicación sin levantar el servidor.

Útil para cron externo, backfills o para inspeccionar la calidad del pipeline:

    python3 scripts/ingest_once.py            # todas las fuentes
    python3 scripts/ingest_once.py gdelt gdacs
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.ingest import gdacs, gdelt, usgs  # noqa: E402
from app.ingest.client import Fetcher  # noqa: E402
from app.storage import make_store  # noqa: E402

SOURCES = {"usgs": usgs.fetch, "gdacs": gdacs.fetch, "gdelt": gdelt.fetch}


async def main(names: list[str]) -> None:
    store = make_store()
    await store.init()
    fetcher = Fetcher()
    for name in names:
        fn = SOURCES.get(name)
        if not fn:
            print(f"· fuente desconocida: {name}")
            continue
        try:
            records = await fn(fetcher)
        except Exception as exc:  # noqa: BLE001
            print(f"· {name}: FALLO {exc}")
            continue
        result = await store.upsert(records)
        print(
            f"· {name}: {len(records)} items → {result.inserted} nuevos, "
            f"{result.merged} fusionados, {result.skipped} descartados"
        )
    print("\nstats:", await store.stats())
    await fetcher.close()
    await store.close()


if __name__ == "__main__":
    args = sys.argv[1:] or list(SOURCES)
    asyncio.run(main(args))
