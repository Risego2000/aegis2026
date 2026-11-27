#!/usr/bin/env python3
"""Diagnóstico de IODA: ¿responde la API desde *esta* máquina?

En el sandbox de desarrollo la API devolvía cuerpo vacío (proxy saliente), así
que la fuente está implementada y probada con datos de muestra, pero no
validada contra el servicio real. Este script cierra esa duda en tu servidor:

    python3 scripts/check_ioda.py            # prueba el endpoint de alertas
    python3 scripts/check_ioda.py --json     # vuelca la respuesta cruda

Códigos de salida: 0 si hay datos parseables, 1 si responde pero vacío,
2 si no se puede ni conectar. Nada de claves: la API es abierta.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

ALERTS = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/alerts"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="imprime la respuesta cruda")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    url = f"{ALERTS}?limit={args.limit}"
    print(f"GET {url}")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310
            raw = response.read()
            status = response.status
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"sin conexión: {type(exc).__name__}: {exc}")
        print("→ bloqueo de red del host (no es un fallo del código).")
        return 2

    print(f"HTTP {status} · {len(raw)} bytes")
    if args.json:
        print(raw.decode("utf-8", "replace")[:4000])
    if not raw.strip():
        print("→ cuerpo vacío: la API responde sin datos (proxy o mantenimiento).")
        return 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"→ respuesta no JSON: {exc}")
        return 1

    from app.ingest import ioda   # importa la configuración de la app

    records = ioda.parse(payload)
    print(f"→ {len(records)} cortes parseados")
    for record in records[:5]:
        print(f"  {record.iso3 or '??'} · {record.event_time:%Y-%m-%d %H:%M}Z · {record.title} ({record.severity})")
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
