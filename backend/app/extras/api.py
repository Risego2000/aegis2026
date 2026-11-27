"""Endpoints de analista: patrones, watchlists, casos, grafo y productos.

Se montan aparte del router del mapa (`api/routes.py`) para que cada mitad se
lea de un tirón. Todo lo que hay aquí es de solo lectura salvo watchlists y
casos, que son las dos cosas que el analista escribe.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from ..config import settings
from ..live import AIRCRAFT
from . import anomalies, gnss, graph as graph_mod, reports, tradecraft
from .storage import ExtrasStore

router = APIRouter()


def _store(request: Request):
    return request.app.state.store


def _extras(request: Request) -> ExtrasStore:
    return request.app.state.extras


async def _events(
    request: Request,
    hours: float = 24.0,
    bbox: list[float] | None = None,
    limit: int = 600,
):
    box = tuple(float(v) for v in bbox) if bbox and len(bbox) == 4 else (-180.0, -85.0, 180.0, 85.0)
    return await _store(request).query_bbox(box, since_hours=hours, limit=limit)


# --------------------------------------------------------------------------- #
# patrones
# --------------------------------------------------------------------------- #
@router.get("/api/gnss")
async def gnss_quality(
    min_aircraft: int = Query(3, ge=1, le=200),
    min_degraded: int = Query(2, ge=1, le=200),
) -> dict[str, Any]:
    """Calidad GNSS por celda de 1° a partir de NIC/NACp de las aeronaves vivas."""
    return gnss.evaluate(list(AIRCRAFT.items.values()), min_aircraft=min_aircraft, min_degraded=min_degraded)


@router.get("/api/anomalies")
async def anomalies_list(request: Request) -> dict[str, Any]:
    """Huecos AIS, velocidades imposibles y buques parados."""
    return anomalies.evaluate(_extras(request).last_seen("vessels"))


# --------------------------------------------------------------------------- #
# watchlists
# --------------------------------------------------------------------------- #
@router.get("/api/watchlists/hits")
async def watchlist_hits(request: Request, limit: int = Query(60, ge=1, le=500)) -> dict[str, Any]:
    hits = _extras(request).hits(limit)
    return {"count": len(hits), "hits": hits}


@router.get("/api/watchlists")
async def list_watchlists(request: Request) -> dict[str, Any]:
    items = _extras(request).list_watchlists()
    return {"watchlists": items, "count": len(items)}


@router.post("/api/watchlists")
async def create_watchlist(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="cuerpo JSON esperado")
    bbox = payload.get("bbox")
    if bbox is not None and (not isinstance(bbox, list) or len(bbox) != 4):
        raise HTTPException(status_code=422, detail="bbox debe ser [oeste, sur, este, norte]")
    return {"ok": True, "watchlist": _extras(request).add_watchlist(payload)}


@router.delete("/api/watchlists/{watch_id}")
async def delete_watchlist(watch_id: str, request: Request) -> dict[str, Any]:
    if not _extras(request).delete_watchlist(watch_id):
        raise HTTPException(status_code=404, detail="regla desconocida")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# casos + cadena de custodia
# --------------------------------------------------------------------------- #
@router.get("/api/cases")
async def list_cases(request: Request) -> dict[str, Any]:
    items = _extras(request).list_cases()
    return {"cases": items, "count": len(items)}


@router.post("/api/cases")
async def create_case(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    case = _extras(request).create_case(
        str(payload.get("title") or "caso sin título"),
        str(payload.get("summary") or ""),
        str(payload.get("tlp") or "AMBER"),
    )
    return {"ok": True, "case": case}


@router.get("/api/cases/{case_id}")
async def get_case(case_id: str, request: Request) -> dict[str, Any]:
    case = _extras(request).get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="caso desconocido")
    return case


@router.post("/api/cases/{case_id}/items")
async def add_case_item(case_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    item = _extras(request).add_case_item(case_id, payload)
    if item is None:
        raise HTTPException(status_code=404, detail="caso desconocido")
    return {"ok": True, "item": item}


@router.get("/api/cases/{case_id}/verify")
async def verify_case(case_id: str, request: Request) -> dict[str, Any]:
    result = _extras(request).verify_case(case_id)
    if not result.get("ok") and result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/api/cases/{case_id}/report")
async def case_report(case_id: str, request: Request) -> Response:
    case = _extras(request).get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="caso desconocido")
    chain = _extras(request).verify_case(case_id)
    lines = [
        f"# Caso · {case['title']}",
        "",
        f"**TLP:** {case['tlp']} · **Creado:** {case['created_at']} · **Actualizado:** {case['updated_at']}",
        f"**Cadena de custodia:** {'íntegra' if chain['ok'] else 'ALTERADA'} "
        f"({chain['items']} evidencias, cabeza `{chain['head'][:16]}…`)",
        "",
    ]
    if case.get("summary"):
        lines += [case["summary"], ""]
    lines += ["## Evidencias", "", "| # | Hora (UTC) | Tipo | Título | SHA-256 |", "|---|---|---|---|---|"]
    for index, item in enumerate(case["items"], 1):
        lines.append(
            f"| {index} | {item['created_at']} | {item['kind']} | "
            f"{(item.get('title') or item.get('ref') or '—')} | `{item['sha256'][:16]}…` |"
        )
    lines += [
        "",
        "> Cada fila encadena el hash de la anterior: si alguien edita una evidencia,",
        "> `GET /api/cases/{id}/verify` deja de cuadrar.",
        "",
    ]
    return Response("\n".join(lines), media_type="text/markdown; charset=utf-8")


# --------------------------------------------------------------------------- #
# grafo
# --------------------------------------------------------------------------- #
@router.get("/api/graph")
async def graph_view(
    request: Request,
    hours: float = Query(24.0, ge=0.5, le=24 * 30),
    limit: int = Query(300, ge=10, le=2000),
    bbox: str | None = Query(None, description="oeste,sur,este,norte"),
) -> dict[str, Any]:
    box = None
    if bbox:
        try:
            parsed = [float(v) for v in bbox.split(",")]
            if len(parsed) == 4:
                box = parsed
        except ValueError:
            box = None
    events = await _events(request, hours=hours, bbox=box, limit=limit)
    return graph_mod.build_graph(events, limit=limit)


@router.get("/api/graph/export")
async def graph_export(
    request: Request,
    hours: float = Query(24.0, ge=0.5, le=24 * 30),
    limit: int = Query(300, ge=10, le=2000),
    fmt: str = Query("graphml", pattern="^(graphml|json)$"),
) -> Response:
    events = await _events(request, hours=hours, limit=limit)
    graph = graph_mod.build_graph(events, limit=limit)
    if fmt == "json":
        return Response(
            __import__("json").dumps(graph, ensure_ascii=False),
            media_type="application/json",
        )
    xml = graph_mod.to_graphml(graph, title=f"AEGIS {hours:g}h")
    return Response(
        xml,
        media_type="application/graphml+xml",
        headers={"Content-Disposition": 'attachment; filename="aegis.graphml"'},
    )


# --------------------------------------------------------------------------- #
# reproducción histórica
# --------------------------------------------------------------------------- #
@router.get("/api/playback")
async def playback(
    request: Request,
    ts: str | None = Query(None, description="instante ISO-8601; por defecto, hace 5 minutos"),
    window_s: int = Query(150, ge=15, le=900),
) -> dict[str, Any]:
    extras = _extras(request)
    if ts is None:
        from datetime import datetime, timedelta, timezone

        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    rows = extras.positions_at(ts, window_s)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    return {"ts": ts, "count": len(rows), "by_kind": counts, "positions": rows, "stats": extras.stats()}


# --------------------------------------------------------------------------- #
# país y productos
# --------------------------------------------------------------------------- #
@router.get("/api/country/{iso3}")
async def country(iso3: str, request: Request, hours: float = Query(168.0, ge=1, le=24 * 30)) -> dict[str, Any]:
    events = await _events(request, hours=hours, limit=6000)
    profile = reports.country_profile(events, iso3)
    profile["grading"] = tradecraft.grade_summary(
        [e for e in events if str(getattr(e, "iso3", "")).upper() == iso3.upper()]
    )
    return profile


@router.get("/api/report/sitrep")
async def sitrep(
    request: Request,
    hours: float = Query(24.0, ge=1, le=24 * 30),
    limit: int = Query(400, ge=10, le=6000),
    bbox: str | None = Query(None),
    fmt: str = Query("markdown", pattern="^(markdown|json)$"),
) -> Response:
    box = None
    if bbox:
        try:
            parsed = [float(v) for v in bbox.split(",")]
            if len(parsed) == 4:
                box = parsed
        except ValueError:
            box = None
    events = await _events(request, hours=hours, bbox=box, limit=limit)
    if fmt == "json":
        import json

        return Response(json.dumps(graph_mod.build_graph(events, limit=50), ensure_ascii=False), media_type="application/json")
    text = reports.sitrep(events, hours, box)
    return Response(text, media_type="text/markdown; charset=utf-8")


@router.get("/api/export/stix")
async def export_stix(
    request: Request,
    hours: float = Query(24.0, ge=1, le=24 * 30),
    limit: int = Query(500, ge=10, le=5000),
) -> Response:
    import json

    events = await _events(request, hours=hours, limit=limit)
    bundle = reports.stix_bundle(events, tlp=settings.tlp)
    return Response(
        json.dumps(bundle, ensure_ascii=False),
        media_type="application/stix+json",
        headers={"Content-Disposition": 'attachment; filename="aegis-stix.json"'},
    )


@router.get("/api/sources/transparency")
async def transparency(request: Request, limit: int = Query(400, ge=50, le=2000)) -> dict[str, Any]:
    """Latencia, tasa de error y volumen por fuente a partir de `ingest_runs`.

    Ninguna plataforma comercial enseña esto; para una herramienta que se cita
    en un informe es el argumento de confianza: se puede decir qué fuente
    falló, cuándo y cuánto tardó.
    """
    runs = await _store(request).runs(limit=limit)
    per: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = str(run.get("source") or "?")
        row = per.setdefault(
            name,
            {"source": name, "runs": 0, "ok": 0, "items": 0, "duration_ms": 0,
             "last_run": None, "last_ok": None, "last_message": ""},
        )
        row["runs"] += 1
        row["ok"] += 1 if run.get("ok") else 0
        row["items"] += int(run.get("items") or 0)
        row["duration_ms"] += int(run.get("duration_ms") or 0)
        if row["last_run"] is None:
            row["last_run"] = run.get("started_at")
            row["last_ok"] = bool(run.get("ok"))
            row["last_message"] = str(run.get("message") or "")[:200]
    sources = []
    for row in per.values():
        total = max(1, row["runs"])
        sources.append({
            **row,
            "success_rate": round(row["ok"] / total, 3),
            "avg_duration_ms": round(row["duration_ms"] / total),
            "items_avg": round(row["items"] / total, 1),
        })
    sources.sort(key=lambda r: (r["success_rate"], r["source"]))
    return {
        "sources": sources,
        "window_runs": len(runs),
        "method": (
            "Calculado sobre las últimas ingestas registradas en `ingest_runs`: "
            "success_rate = ejecuciones correctas / totales; avg_duration_ms = media "
            "del tiempo de respuesta del origen."
        ),
    }


@router.get("/api/extras/stats")
async def extras_stats(request: Request) -> dict[str, Any]:
    return _extras(request).stats()
