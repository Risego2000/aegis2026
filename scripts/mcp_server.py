#!/usr/bin/env python3
"""Servidor MCP para AEGIS — stdio, sin dependencias.

Expone el archivo de AEGIS a cualquier cliente MCP (Claude Desktop, Cursor,
Continue, n8n) para que el modelo consulte sucesos, SITREP, países, anomalías y
calidad GNSS **desde los datos**, no de memoria. Solo lectura y solo stdlib.

Uso (el cliente lanza este proceso):

    {"mcpServers": {"aegis": {"command": "python3",
      "args": ["scripts/mcp_server.py"],
      "env": {"AEGIS_API": "https://tu-aegis.example"}}}}

Variables:
    AEGIS_API   base de la API (por defecto http://127.0.0.1:8000)
    AEGIS_TOKEN opcional, si algún día pones la API detrás de un proxy con token
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("AEGIS_API", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("AEGIS_TOKEN", "")
PROTOCOL = "2024-11-05"


def _get(path: str, params: dict | None = None) -> str:
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if TOKEN:
        request.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(request, timeout=25) as response:  # noqa: S310 - URL propia
        body = response.read().decode("utf-8", "replace")
    return body


TOOLS = [
    {
        "name": "aegis_events",
        "description": (
            "Sucesos geolocalizados del archivo AEGIS (sismos, desastres, conflicto, "
            "protestas, cortes de internet…) con grado de fuente OTAN A-F/1-6."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {"type": "number", "description": "ventana en horas (máx. 720)", "default": 24},
                "bbox": {"type": "string", "description": "oeste,sur,este,norte", "default": ""},
                "category": {"type": "string", "description": "p. ej. earthquake, conflict, network", "default": ""},
                "limit": {"type": "number", "default": 40},
            },
        },
    },
    {
        "name": "aegis_sitrep",
        "description": "Informe de situación en Markdown para una ventana temporal (con grados y fuentes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {"type": "number", "default": 24},
                "bbox": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "aegis_country",
        "description": "Perfil PMESII de un país (ISO3) con índice de estabilidad y reparto por dimensión.",
        "inputSchema": {
            "type": "object",
            "properties": {"iso3": {"type": "string"}, "hours": {"type": "number", "default": 168}},
            "required": ["iso3"],
        },
    },
    {
        "name": "aegis_anomalies",
        "description": "Anomalías marítimas: huecos AIS, velocidades imposibles y buques parados.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "aegis_gnss",
        "description": "Calidad GNSS por celda de 1° (NIC/NACp de ADS-B): posible interferencia.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "aegis_graph",
        "description": "Grafo de vínculos suceso↔fuente↔país en JSON (nodos y aristas).",
        "inputSchema": {
            "type": "object",
            "properties": {"hours": {"type": "number", "default": 24}, "limit": {"type": "number", "default": 200}},
        },
    },
]


def _tool_call(name: str, args: dict) -> str:
    if name == "aegis_events":
        raw = _get("/api/events", {
            "hours": args.get("hours", 24),
            "bbox": args.get("bbox") or None,
            "limit": args.get("limit", 40),
        })
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        events = payload.get("events") or payload.get("features") or payload
        category = (args.get("category") or "").lower()
        if isinstance(events, list):
            if category:
                events = [e for e in events if str(e.get("category", "")).lower() == category]
            keep = ("id", "title", "category", "severity", "event_time", "iso3",
                    "source", "sources", "admiralty", "grading", "url")
            events = [{k: e.get(k) for k in keep if k in e} for e in events[: int(args.get("limit", 40))]]
        return json.dumps(events, ensure_ascii=False, indent=1)
    if name == "aegis_sitrep":
        return _get("/api/report/sitrep", {"hours": args.get("hours", 24), "bbox": args.get("bbox") or None})
    if name == "aegis_country":
        iso3 = str(args.get("iso3") or "").upper()
        if not iso3:
            raise ValueError("falta iso3")
        return _get(f"/api/country/{urllib.parse.quote(iso3)}", {"hours": args.get("hours", 168)})
    if name == "aegis_anomalies":
        return _get("/api/anomalies")
    if name == "aegis_gnss":
        return _get("/api/gnss")
    if name == "aegis_graph":
        return _get("/api/graph", {"hours": args.get("hours", 24), "limit": args.get("limit", 200)})
    raise ValueError(f"herramienta desconocida: {name}")


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(request: dict) -> None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        _send({"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "aegis", "version": "1.0.0"},
        }})
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            text = _tool_call(str(name), args)
            _send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }})
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            _send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": f"AEGIS no disponible: {exc}"}],
                "isError": True,
            }})
    elif request_id is not None:
        _send({"jsonrpc": "2.0", "id": request_id,
               "error": {"code": -32601, "message": f"método no soportado: {method}"}})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        # las notificaciones (sin id) no llevan respuesta
        if isinstance(message, dict):
            _handle(message)


if __name__ == "__main__":
    main()
