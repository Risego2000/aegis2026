"""Fondo de mapa detallado (calles y satélite) sin claves.

El mapa de AEGIS nace con una base vectorial propia (Natural Earth) que da
contexto global, pero para situar un elemento con precisión hace falta calle a
calle. Este módulo sirve teselas ráster de tres proveedores públicos y sin
clave, **desde el propio backend**:

  · calles   → OpenStreetMap estándar (calles, nombres, sentidos)
  · oscuro   → Esri Dark Gray Canvas (callejero oscuro con etiquetas)
  · claro    → Esri Light Gray Canvas
  · satelite → Esri World Imagery (orto­foto)

Servirlas en proxy tiene tres ventajas: el cliente no habla con terceros (nada
de CORS ni de fugas de referrer), el navegador cachea una sola vez y nosotros
cacheamos en disco para no abusar de la cortesía de los proveedores. El
proveedor se elige por configuración y se respeta su política de uso.
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
    "calles": {
        "label": "Calles",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "maxzoom": 19,
        "ext": "png",
        "attribution": "© OpenStreetMap contributors",
        "headers": {"Referer": "https://aegis.local/"},
    },
    # CARTO pasó a exigir clave (marca de agua «API KEY REQUIRED» en la tesela),
    # así que el callejero oscuro/claro se sirve con los mapas grises de Esri,
    # que siguen siendo públicos y sin registro.
    "oscuro": {
        "label": "Oscuro",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 16,
        "ext": "jpg",
        "attribution": "Esri · HERE · OpenStreetMap",
    },
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
    "calles_esri": {
        "label": "Calles (Esri)",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 19,
        "ext": "jpg",
        "attribution": "Esri · HERE · OpenStreetMap",
    },
    # capas transparentes de etiquetas que acompañan a los mapas grises
    "oscuro_ref": {
        "label": "Etiquetas (oscuro)",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 16,
        "ext": "png",
        "attribution": "Esri · HERE",
    },
    "claro_ref": {
        "label": "Etiquetas (claro)",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 16,
        "ext": "png",
        "attribution": "Esri · HERE",
    },
    "satelite": {
        "label": "Satélite",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 19,
        "ext": "jpg",
        "attribution": "Esri · Maxar · Earthstar Geographics",
    },
    # --- red de transporte que usan los medios que vigilamos -------------
    # Esri World Transportation: carreteras (autovías y comarcales) y
    # ferrocarril en la misma capa transparente. Se pinta ENCIMA del fondo
    # elegido, así que está disponible con todos los estilos.
    "transporte": {
        "label": "Red de carreteras y ferrocarril",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 19,
        "ext": "png",
        "attribution": "Esri · HERE · OpenStreetMap",
    },
    # Esri Ocean Reference: derrotas marítimas con escala y batimetría
    # (transparente; pensada para superponerse a un fondo claro).
    "oceanoref": {
        "label": "Derrotas marítimas (Esri)",
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}"
        ),
        "maxzoom": 13,
        "ext": "png",
        "attribution": "Esri · GEBCO",
    },
}
DEFAULT_STYLE = "calles"

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
