#!/usr/bin/env python3
"""Añade aeropuertos (OurAirports, dominio público) al índice de proximidad.

Las consultas de proximidad responden «qué hay en el radio de impacto». Con
Natural Earth solo había ciudades; con esta capa entran también aeropuertos
grandes y medios, que es lo que de verdad se consulta en una crisis
(evacuaciones, cierre de espacio aéreo, ayuda humanitaria).

Descarga el CSV completo (12 MB) y guarda un JSON compacto en `data/geo/`:

    python3 scripts/seed_airports.py
    python3 scripts/seed_airports.py --include-small   # +3.500 aeródromos
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUT = ROOT / "data" / "geo" / "ourairports.json"

KEEP_BASE = {"large_airport", "medium_airport"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-small", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    keep = set(KEEP_BASE)
    if args.include_small:
        keep.add("small_airport")

    print("· descargando OurAirports…")
    req = urllib.request.Request(CSV_URL, headers={"User-Agent": "AEGIS-OSINT/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(raw))
    items = []
    for row in reader:
        if row.get("type") not in keep:
            continue
        try:
            lat = float(row["latitude_deg"])
            lon = float(row["longitude_deg"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        items.append(
            {
                "id": f"airport:{row['ident']}",
                "name": row.get("name") or row["ident"],
                "kind": "airport",
                "subtype": row.get("type", "").replace("_", " "),
                "country": row.get("municipality") or "",
                "iso3": row.get("iso_country") or "",
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "population": 0,
                "iata": row.get("iata_code") or "",
                "icao": row.get("gps_code") or "",
                "elevation_ft": row.get("elevation_ft") or "",
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_mb = out.stat().st_size / 1e6
    print(f"· {len(items)} aeropuertos → {out} ({size_mb:.2f} MB)")
    print("· reinicia el backend para que entren en el índice de proximidad")


if __name__ == "__main__":
    main()
