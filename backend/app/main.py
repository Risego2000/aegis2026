"""AEGIS — OSINT Super App · FastAPI entrypoint.

Serves:
  /api/*        REST + WebSocket surface
  /             the statically exported Next.js client (frontend/out)

One process, one port, zero external services required. Designed to fit the
Oracle Cloud ARM Always-Free instance (4 vCPU / 24 GB) — or a laptop.
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import routes as routes_mod
from .api.routes import router
from .config import ROOT, settings
from .fence.engine import GeofenceEngine
from .ingest import satellites as sats_mod
from .ingest.client import Fetcher
from .ingest.gtfs import GtfsIndex
from .ingest.registry import Registry
from .storage import make_store

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)   # keep the console readable
log = logging.getLogger("aegis")


def load_infrastructure() -> list[dict]:
    """Seed the proximity index from Natural Earth populated places.

    These are the `infrastructure` rows used by the ST_DWithin queries that
    answer "what is inside the impact radius of this event".
    """
    items = _load_places() + _load_airports()
    return items


def _load_airports() -> list[dict]:
    """Aeropuertos para el índice de proximidad (OurAirports, dominio público).

    Se generan con `python3 scripts/seed_airports.py`. Si el fichero no existe,
    la proximidad sigue funcionando solo con ciudades.
    """
    path = Path(settings.geo_dir) / "ourairports.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("ourairports ilegible: %s", exc)
        return []
    log.info("infraestructura: %d aeropuertos", len(data))
    return data


def _load_places() -> list[dict]:
    candidates = [
        Path(settings.geo_dir) / "ne_10m_populated_places.geojson",
        Path(settings.geo_dir) / "ne_110m_populated_places.geojson",
    ]
    path = next((p for p in candidates if p.exists()), candidates[-1])
    if not path.exists():
        log.warning("no se encontró %s; proximidad sin datos base", path)
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for idx, feature in enumerate(data.get("features", [])):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        name = props.get("NAME") or props.get("name") or f"place-{idx}"
        pop = props.get("POP_MAX") or props.get("pop_max") or 0
        iso3 = props.get("ADM0_A3") or props.get("SOV_A3") or ""
        items.append(
            {
                "id": f"place:{props.get('NE_ID') or idx}",
                "name": name,
                "kind": "city",
                "subtype": props.get("FEATURECLA") or "populated place",
                "country": props.get("ADM0NAME") or props.get("SOV0NAME") or "",
                "iso3": iso3,
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "population": float(pop or 0),
            }
        )
    return items


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("AEGIS arrancando · storage=%s", settings.database_url or "sqlite")
    store = make_store()
    await store.init()

    seeded = await store.seed_infrastructure(load_infrastructure())
    if seeded:
        log.info("infraestructura sembrada: %d puntos", seeded)

    engine = GeofenceEngine(store)
    await engine.load()

    fetcher = Fetcher()
    registry = Registry(store, engine, fetcher)

    # Índice GTFS de Renfe (paradas, destinos, itinerarios). Se carga del
    # disco (0,2 s) y, si no existe, se construye una sola vez.
    gtfs_index = GtfsIndex(ROOT)
    try:
        if not gtfs_index.load():
            await gtfs_index.build(fetcher)
    except Exception as exc:  # noqa: BLE001 - sin índice la app sigue completa
        log.warning("índice GTFS de Renfe no disponible: %s", exc)
    registry.gtfs = gtfs_index
    routes_mod.APP_STATE["gtfs"] = gtfs_index

    app.state.store = store
    app.state.engine = engine
    app.state.fetcher = fetcher
    app.state.registry = registry
    app.state.gtfs = gtfs_index

    # Warm the orbital catalogue off the critical path.
    try:
        await sats_mod.refresh_tles(fetcher)
        sats_mod.propagate_all()
    except Exception as exc:  # noqa: BLE001
        log.warning("catálogo orbital no disponible al arrancar: %s", exc)

    await registry.start()

    # periodic retention prune
    import asyncio

    async def pruner():
        # primera pasada al minuto de arrancar: poda + adelgaza + compacta
        await asyncio.sleep(60)
        while True:
            try:
                removed = await store.prune(settings.retention_days)
                log.info("prune: %d eventos antiguos eliminados y base compactada", removed)
            except Exception as exc:  # noqa: BLE001
                log.warning("prune failed: %s", exc)
            await asyncio.sleep(24 * 3600)

    prune_task = asyncio.create_task(pruner())

    async def guardian_memoria():
        """Tope de memoria del propio servidor.

        La caja donde vive esto tiene ~2 GB y comparte sitio con el navegador
        del operador. Antes de que el sistema operativo mate el proceso (lo que
        deja el visor sin backend), se sueltan las cachés que se pueden volver a
        construir: teselas en disco, índices en RAM y compactación de SQLite.
        """
        while True:
            await asyncio.sleep(45)
            try:
                import resource

                rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
                if rss_mb < 620:
                    continue
                log.warning("memoria alta (%.0f MB): liberando cachés", rss_mb)
                try:
                    from . import tiles as _tiles

                    _tiles._last_evict = 0.0
                    _tiles._evict_if_needed()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from .api import routes as _routes

                    _routes._GEO_CACHE.clear()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    import gc

                    gc.collect()
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                log.warning("guardian memoria: %s", exc)

    mem_task = asyncio.create_task(guardian_memoria())

    log.info("AEGIS listo — http://%s:%s", settings.host, settings.port)
    try:
        yield
    finally:
        prune_task.cancel()
        mem_task.cancel()
        await registry.stop()
        await fetcher.close()
        await store.close()


app = FastAPI(
    title="AEGIS · OSINT Super App",
    version="1.0.0",
    description="Telemetría global, inteligencia geopolítica y desastres en un mapa 3D.",
    lifespan=lifespan,
)

# Compresión en tránsito: /api/events devuelve varios MB de GeoJSON
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")] or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def production_headers(request: Request, call_next):
    """Cabeceras de producción: caché larga para assets con hash, corta para API.

    No se envían X-Frame-Options/CSP a propósito: la app debe poder mostrarse
    dentro de visores embebidos (paneles, iframes corporativos).
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/_next/static/") or path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif path.endswith((".html", "/")) or path == "":
        response.headers["Cache-Control"] = "no-cache"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-AEGIS", "osint")
    return response


app.include_router(router)


@app.get("/api")
async def api_root() -> dict:
    return {
        "name": "AEGIS OSINT API",
        "version": app.version,
        "docs": "/docs",
        "endpoints": [
            "/api/health", "/api/stats", "/api/events", "/api/live/aircraft",
            "/api/live/vessels", "/api/live/satellites", "/api/fences", "/api/alerts",
            "/api/ai/briefing", "/api/ai/status", "/ws/alerts",
        ],
    }


# --------------------------------------------------------------------------- #
# Static client (Next.js `output: export`)
# --------------------------------------------------------------------------- #
FRONTEND_DIR = Path(settings.frontend_dir)
if FRONTEND_DIR.exists() and (FRONTEND_DIR / "index.html").exists():
    app.mount("/_next", StaticFiles(directory=FRONTEND_DIR / "_next"), name="next-assets")
    if (FRONTEND_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
    async def spa(full_path: str):
        candidate = (FRONTEND_DIR / full_path).resolve()
        # sin fugas fuera del directorio del cliente
        if full_path and str(candidate).startswith(str(FRONTEND_DIR.resolve())) and candidate.is_file():
            return FileResponse(candidate)
        if "." in Path(full_path).name:      # asset inexistente: 404 real, no HTML
            return JSONResponse({"error": "not found", "path": full_path}, status_code=404)
        return FileResponse(FRONTEND_DIR / "index.html")

else:  # pragma: no cover
    @app.get("/")
    async def not_built() -> JSONResponse:
        return JSONResponse(
            {
                "error": "cliente no compilado",
                "hint": "cd frontend && npm install && npm run build",
                "api": "/api",
            },
            status_code=503,
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
