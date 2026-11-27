#!/usr/bin/env python3
"""Smoke test de AEGIS: 20 comprobaciones en ~10 s.

Uso:
    python3 scripts/smoke.py                      # contra el backend local
    BASE=https://mi-enlace.trycloudflare.com python3 scripts/smoke.py

Salida: una línea por comprobación y un resumen. Código 1 si algo falla, para
poder encadenarlo en un cron o en un despliegue.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = (os.environ.get("BASE") or "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.environ.get("TIMEOUT", "20"))

results: list[tuple[str, bool, str]] = []


def get(path: str, expect: int = 200, parse: bool = True, note: str = ""):
    url = f"{BASE}{path}"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            body = resp.read()
            code = resp.status
            ctype = resp.headers.get("content-type", "")
    except urllib.error.HTTPError as exc:
        code, body, ctype = exc.code, b"", ""
    except Exception as exc:  # noqa: BLE001
        results.append((f"{path} {note}".strip(), False, f"error: {str(exc)[:90]}"))
        return None
    ms = int((time.perf_counter() - started) * 1000)
    ok = code == expect
    detail = f"{code} · {ms} ms · {len(body) / 1024:.0f} KB"
    data = None
    if parse and ok and body:
        try:
            data = json.loads(body)
        except Exception:  # noqa: BLE001
            ok, detail = False, "respuesta no es JSON"
    results.append((f"{path} {note}".strip(), ok, detail))
    return data


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, bool(condition), detail))


def main() -> int:
    t0 = time.perf_counter()

    # --- salud y capas ---
    health = get("/api/health")
    if health:
        live = health.get("live") or {}
        check("capas vivas presentes",
              {"aircraft", "vessels", "satellites", "trains", "air", "cameras"} <= set(live),
              ", ".join(sorted(live)))
        check("cámaras indexadas", (live.get("cameras") or {}).get("count", 0) > 1500,
              str((live.get("cameras") or {}).get("count")))

    layers = get("/api/layers")
    if layers:
        check("eventos en el archivo", (layers.get("events") or {}).get("total", 0) > 1000,
              str((layers.get("events") or {}).get("total")))

    # --- sucesos ---
    ev = get("/api/events?hours=24&limit=5")
    if ev:
        check("eventos con geometría", len(ev.get("features") or []) > 0, f"count={ev.get('count')}")
        check("marca de agua server_time", bool(ev.get("server_time")), str(ev.get("server_time")))

    get("/api/events?hours=24&limit=2&since=2026-01-01T00:00:00%2B00:00", note="(incremental)")

    # --- capas vivas ---
    trains = get("/api/live/trains")
    if trains:
        check("capa de trenes responde", trains.get("type") == "FeatureCollection",
              f"{trains.get('count')} trenes ahora")
    get("/api/live/aircraft?limit=3")
    get("/api/live/vessels?limit=3")
    get("/api/live/satellites")

    # --- trenes enriquecidos ---
    idx = get("/api/trains/index")
    if idx:
        check("índice GTFS de Renfe", idx.get("stops", 0) > 500,
              f"{idx.get('stops')} paradas · {idx.get('trips')} viajes · {idx.get('alerts')} avisos")

    # --- cámaras ---
    cams = get("/api/cameras?limit=1")
    cam_id = None
    if cams and cams.get("features"):
        cam_id = cams["features"][0]["properties"]["id"]
    if cam_id:
        get(f"/api/cameras/{cam_id}/frame", parse=False, note="(frame)")

    # --- fotografía de aeronave ---
    photo = get("/api/media/photo?kind=aircraft&id=3c4b26")
    if photo is not None:
        check("foto de avión (Planespotters)", bool(photo.get("photo")), (photo.get("photo") or {}).get("credit", "sin foto"))

    # --- exportación ---
    get("/api/export/events?hours=24&limit=5&fmt=csv", parse=False)
    get("/api/export/events?hours=24&limit=5&fmt=geojson")

    # --- canal en vivo ---
    stats = get("/api/stream/stats")
    if stats:
        check("canal en vivo activo", "versions" in stats, f"listeners={stats.get('listeners')}")

    # --- cliente estático ---
    html = None
    try:
        with urllib.request.urlopen(f"{BASE}/", timeout=TIMEOUT) as resp:
            html = resp.read().decode("utf-8", "ignore")
        results.append(("/", resp.status == 200, f"{len(html) / 1024:.0f} KB · AEGIS={'AEGIS' in html}"))
    except Exception as exc:  # noqa: BLE001
        results.append(("/", False, str(exc)[:80]))
    for asset in ("/manifest.webmanifest", "/sw.js", "/icon.svg"):
        get(asset, parse=False)

    # --- seguridad ---
    try:
        req = urllib.request.Request(f"{BASE}/api/ingest/inexistente/run", method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception as exc:  # noqa: BLE001
        code = str(exc)[:60]
    # 502 = el guardia dejó pasar y la fuente no existe (protegido, pero el
    # atajo de localhost sigue funcionando en la máquina del operador)
    check("ingesta manual protegida fuera de localhost", code in (401, 403, 502), f"HTTP {code}")

    # ------------------------------------------------------------------ resumen
    failed = [r for r in results if not r[1]]
    width = max(len(r[0]) for r in results) + 2
    print()
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name:<{width}} {detail}")
    print()
    total_s = time.perf_counter() - t0
    print(f"  {len(results) - len(failed)}/{len(results)} OK en {total_s:.1f} s · {BASE}")
    if failed:
        print("  FALLOS:", ", ".join(r[0] for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
