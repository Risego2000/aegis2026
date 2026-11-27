"""Fondos de mapa de AEGIS: una base por pregunta, todas sin clave.

El mapa sirve para vigilar cinco cosas (sucesos, vuelos, buques, trenes y
cámaras), y cada una se lee mejor sobre un fondo distinto. En vez de acumular
variantes del mismo mapa, este catálogo ofrece solo las bases que aportan algo:

  · detalle     → Esri Dark Gray Canvas: callejero oscuro para trabajo urbano
  · detalle_ref → etiquetas de ese callejero (capa transparente)
  · imagen      → Esri World Imagery: ortofoto real
  · imagen_ref  → límites y lugares para la ortofoto (capa transparente)
  · relieve     → Esri World Hillshade: sombreado del terreno
  · maritimo    → Esri World Ocean Base: batimetría y costa
  · calles      → Esri World Street Map: callejero claro con nombres
  · claro       → Esri Light Gray Canvas: base mínima para informes
  · claro_ref   → etiquetas claras (capa transparente)
  · transporte  → Esri World Transportation: carreteras y ferrocarril

El fondo «operativo» lo dibuja el propio cliente con Natural Earth y las
etiquetas oscuras de este catálogo, así que no necesita teselas propias.

Servirlas en proxy tiene tres ventajas: el cliente no habla con terceros (nada
de CORS ni de fugas de referrer), el navegador cachea una sola vez y nosotros
cacheamos en disco para no abusar de la cortesía del proveedor. Los `maxzoom`
son los que devuelven contenido real (por encima, el proveedor repite una
tesela vacía): MapLibre reescala la última buena.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("aegis.tiles")

# Orden de subdominios de CARTO/OSM: reparte la carga entre sus CDN.
STYLES: dict[str, dict[str, Any]] = {
    # --- callejero oscuro: el urbano que no deslumbra ---------------------
    "detalle": {
        "label": "Detalle urbano (oscuro)",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 16,
        "ext": "jpg",
        "attribution": "Esri · HERE · OpenStreetMap",
    },
    # CARTO pasó a exigir clave (marca de agua «API KEY REQUIRED»), por eso los
    # grises se sirven con Esri, que sigue siendo público y sin registro.
    "detalle_ref": {
        "label": "Etiquetas (oscuras)",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 14,       # z15+ devuelve teselas vacías
        "ext": "png",
        "attribution": "Esri · HERE",
    },
    # --- ortofoto con su capa de referencia ------------------------------
    "imagen": {
        "label": "Imagen satelital",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 19,
        "ext": "jpg",
        "attribution": "Esri · Maxar · Earthstar Geographics",
    },
    "imagen_ref": {
        "label": "Límites y lugares",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 15,       # z16+ devuelve teselas vacías
        "ext": "png",
        "attribution": "Esri · HERE",
    },
    # --- terreno: lo que explica sismos, volcanes, incendios e inundaciones
    "relieve": {
        "label": "Relieve",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 16,
        "ext": "jpg",
        "attribution": "Esri · GEBCO · USGS",
    },
    # --- mar: batimetría para buques y derrotas -------------------------
    "maritimo": {
        "label": "Marítimo",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 10,       # z11+ repite una tesela plana
        "ext": "jpg",
        "attribution": "Esri · GEBCO",
    },
    # --- callejero claro: nombres, sentidos y detalle urbano -------------
    "calles": {
        "label": "Calles",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 19,
        "ext": "jpg",
        "attribution": "Esri · HERE · OpenStreetMap",
    },
    # --- base mínima para informes y proyecciones -----------------------
    "claro": {
        "label": "Claro",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 16,
        "ext": "jpg",
        "attribution": "Esri · HERE · OpenStreetMap",
    },
    "claro_ref": {
        "label": "Etiquetas (claras)",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 14,       # z15+ devuelve teselas vacías
        "ext": "png",
        "attribution": "Esri · HERE",
    },
    # --- red de transporte que usan los medios que vigilamos -------------
    # Esri World Transportation: carreteras (autovías y comarcales) y
    # ferrocarril en la misma capa transparente. Se pinta ENCIMA de la
    # ortofoto, que no trae ninguna de las dos.
    "transporte": {
        "label": "Carreteras y ferrocarril",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 19,
        "ext": "png",
        "attribution": "Esri · HERE · OpenStreetMap",
    },
}
DEFAULT_STYLE = "detalle"

UA = "AegisOSINT/1.0 (+https://github.com/; visor OSINT de fuentes abiertas)"

CACHE_DIR = Path(os.environ.get("TILE_CACHE", "data/tiles"))
MAX_BYTES = int(os.environ.get("TILE_CACHE_MB", "400")) * 1024 * 1024
TTL_S = 60 * 60 * 24 * 30          # las teselas de calle cambian poco
_last_evict = 0.0


class UnknownStyle(KeyError):
    """El estilo pedido no existe."""


def _cache_path(style: str, z: int, x: int, y: int) -> Path:
    return CACHE_DIR / style / str(z) / str(x) / f"{y}.{STYLES[style]['ext']}"


def _evict_if_needed() -> None:
    """Recorta la caché de disco por antigüedad cuando pasa del límite."""
    global _last_evict
    now = time.time()
    if now - _last_evict < 600:      # como mucho una pasada cada 10 min
        return
    _last_evict = now
    if not CACHE_DIR.exists():
        return
    total = 0
    files: list[tuple[float, int, Path]] = []
    for path in CACHE_DIR.rglob("*.*"):
        try:
            st = path.stat()
        except OSError:
            continue
        total += st.st_size
        files.append((st.st_mtime, st.st_size, path))
    if total <= MAX_BYTES:
        return
    files.sort()
    for _, size, path in files:
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        if total <= MAX_BYTES * 0.8:
            break
    log.info("caché de teselas recortada a %.0f MB", total / 1024 / 1024)


def cached(style: str, z: int, x: int, y: int) -> bytes | None:
    path = _cache_path(style, z, x, y)
    try:
        if time.time() - path.stat().st_mtime < TTL_S:
            return path.read_bytes()
    except OSError:
        return None
    return None


def store(style: str, z: int, x: int, y: int, body: bytes) -> None:
    path = _cache_path(style, z, x, y)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(path)
    except OSError:
        return
    _evict_if_needed()


def tile_url(style: str, z: int, x: int, y: int) -> str:
    spec = STYLES[style]
    subs = spec.get("subdomains")
    sub = subs[(x + y) % len(subs)] if subs else ""
    return spec["url"].format(z=z, x=x, y=y, s=sub)


async def fetch_tile(style: str, z: int, x: int, y: int) -> bytes:
    """Descarga una tesela del proveedor (o la devuelve de la caché de disco)."""
    if style not in STYLES:
        raise UnknownStyle(style)
    hit = cached(style, z, x, y)
    if hit is not None:
        return hit
    url = tile_url(style, z, x, y)
    headers = {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*",
        "Accept-Encoding": "gzip, deflate",
    }
    headers.update(STYLES[style].get("headers") or {})
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0),
                                 follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        body = resp.content
    if len(body) < 100:
        raise RuntimeError(f"tesela vacía ({len(body)} B) de {url}")
    store(style, z, x, y, body)
    return body


def catalogue() -> dict[str, Any]:
    return {
        "default": DEFAULT_STYLE,
        "styles": [
            {
                "id": key,
                "label": spec["label"],
                "maxzoom": spec["maxzoom"],
                "attribution": spec["attribution"],
                "url": f"/api/tiles/{key}/{{z}}/{{x}}/{{y}}.{spec['ext']}",
            }
            for key, spec in STYLES.items()
        ],
    }
