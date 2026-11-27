#!/usr/bin/env python3
"""Descarga los datos geográficos que no se versionan (son grandes).

    python3 scripts/fetch_geo.py

Deja en `data/geo/`:
  · roads.geojson.gz      red viaria mundial (Natural Earth 1:10m, 56 600 vías)
  · railroads.geojson     ferrocarril mundial (Natural Earth 1:10m, 25 413 líneas)

Se descargan de las fuentes originales, sin claves. El ferrocarril son unos
15 MB zanjados en un GeoJSON propio; la red viaria se simplifica a 3 decimales
(~110 m) y se comprime, que es lo que sirve el endpoint `/api/basemap/infra_view`.
"""
from __future__ import annotations

import gzip
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "geo"

RAILROADS_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_railroads.zip"
ROADS_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_roads.geojson"
)


def descargar(url: str, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"· descargando {url}")
    with urllib.request.urlopen(url, timeout=300) as resp, open(destino, "wb") as out:
        while True:
            trozo = resp.read(1 << 16)
            if not trozo:
                break
            out.write(trozo)
    print(f"  → {destino} ({destino.stat().st_size / 1048576:.1f} MB)")
    return destino


def ferrocarril() -> None:
    destino = GEO / "railroads.geojson"
    if destino.exists():
        print(f"· ferrocarril ya presente ({destino.stat().st_size / 1048576:.1f} MB)")
        return
    zip_path = descargar(RAILROADS_URL, Path("/tmp/ne_10m_railroads.zip"))
    import shapefile  # pyshp: pip install pyshp
    import zipfile

    print("· convirtiendo shapefile → GeoJSON")
    # el ZIP trae .shp/.dbf/.shx: se descomprime en /tmp (el .shp pesa 56 MB)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall("/tmp/ne_10m_railroads")
    reader = shapefile.Reader("/tmp/ne_10m_railroads/ne_10m_rails.shp")
    feats = []
    for sr in reader.iterShapeRecords():
        props = sr.record.as_dict()
        pts = [[round(x, 3), round(y, 3)] for x, y in sr.shape.points]
        if len(pts) < 2:
            continue
        # Natural Earth: category 1 = troncal principal; 2 = secundaria
        clase = 1 if int(props.get("category") or 3) <= 2 else 2
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": pts},
                "properties": {"c": clase},
            }
        )
    destino.write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"  → {destino} ({len(feats)} líneas, {destino.stat().st_size / 1048576:.1f} MB)")


def carreteras() -> None:
    destino = GEO / "roads.geojson.gz"
    if destino.exists():
        print(f"· carreteras ya presentes ({destino.stat().st_size / 1048576:.1f} MB)")
        return
    crudo = descargar(ROADS_URL, Path("/tmp/ne_10m_roads.geojson"))
    print("· simplificando a 3 decimales y comprimiendo")
    data = json.loads(crudo.read_text(encoding="utf-8"))

    def redondear(coords):
        if isinstance(coords[0], (int, float)):
            return [round(coords[0], 3), round(coords[1], 3)]
        return [redondear(c) for c in coords]

    feats = []
    for f in data.get("features") or []:
        p = f.get("properties") or {}
        tipo = p.get("type") or ""
        clase = 1 if (tipo == "Major Highway" or p.get("expressway") == 1) else (
            2 if tipo in ("Secondary Highway", "Beltway") else 3
        )
        feats.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": f["geometry"]["type"],
                    "coordinates": redondear(f["geometry"]["coordinates"]),
                },
                "properties": {"c": clase},
            }
        )
    bruto = json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")).encode()
    with gzip.open(destino, "wb", compresslevel=9) as g:
        g.write(bruto)
    print(f"  → {destino} ({len(feats)} vías, {destino.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    GEO.mkdir(parents=True, exist_ok=True)
    carreteras()
    ferrocarril()
    print("\nlisto. Arranca el backend y la capa de infraestructura ya tiene datos.")
    sys.exit(0)
