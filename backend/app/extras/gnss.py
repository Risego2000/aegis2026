"""Calidad de la señal GNSS a partir de ADS-B (NIC / NACp).

Las aeronaves emiten con cada posición su **NIC** (integridad de navegación) y,
con menos frecuencia, su **NACp** (precisión estimada). Cuando un jammer de GPS
entra en escena, esos indicadores caen a 0 y el avión sigue transmitiendo
posiciones malas: es la forma en que la literatura operativa (LVNL, ION,
Stanford GPS Lab) detecta interferencia sin acceso a señal.

Aquí no se localiza el jammer: se agrupa por celdas de 1° para que el analista
vea **dónde** hay varios aviones degradados a la vez, que es la señal útil.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

# Umbrales operativos: NIC 7 equivale a un radio de contención < 0,2 NM; por
# debajo de 5 el dato no sirve para navegar. NACp 8-9 es lo normal.
NIC_DEGRADED = 4
NAC_P_DEGRADED = 4
NIC_WATCH = 6
NAC_P_WATCH = 6


def aircraft_status(actor: dict[str, Any]) -> str:
    """'ok' | 'watch' | 'degraded' | 'unknown'."""
    nic = actor.get("nic")
    nacp = actor.get("nac_p") if actor.get("nac_p") is not None else actor.get("nacp")
    if nic is None and nacp is None:
        return "unknown"
    try:
        nic = int(nic) if nic is not None else None
        nacp = int(nacp) if nacp is not None else None
    except (TypeError, ValueError):
        return "unknown"
    if (nic is not None and nic <= NIC_DEGRADED) or (nacp is not None and nacp <= NAC_P_DEGRADED):
        return "degraded"
    if (nic is not None and nic <= NIC_WATCH) or (nacp is not None and nacp <= NAC_P_WATCH):
        return "watch"
    return "ok"


def annotate(actor: dict[str, Any]) -> dict[str, Any]:
    actor["gnss"] = aircraft_status(actor)
    return actor


def evaluate(aircraft: Iterable[dict[str, Any]], min_aircraft: int = 3, min_degraded: int = 2) -> dict[str, Any]:
    """Celdas de 1° con varios aviones degradados + resumen global."""
    cells: dict[tuple[int, int], dict[str, int]] = {}
    counts = {"ok": 0, "watch": 0, "degraded": 0, "unknown": 0}
    for actor in aircraft:
        lat, lon = actor.get("lat"), actor.get("lon")
        if lat is None or lon is None:
            continue
        status = aircraft_status(actor)
        counts[status] += 1
        key = (math.floor(float(lat)), math.floor(float(lon)))
        cell = cells.setdefault(key, {"total": 0, "ok": 0, "watch": 0, "degraded": 0, "unknown": 0})
        cell["total"] += 1
        cell[status] += 1

    features = []
    for (clat, clon), cell in cells.items():
        evaluated = cell["total"] - cell["unknown"]
        if evaluated < min_aircraft or cell["degraded"] < min_degraded:
            continue
        ratio = cell["degraded"] / evaluated
        # con dos aviones degradados y un cuarto de la celda afectada ya huele a
        # interferencia; por debajo se marca para observar
        level = "alert" if ratio >= 0.25 else "watch"
        features.append(
            {
                "cell": f"{clat},{clon}",
                "lat": clat + 0.5,
                "lon": clon + 0.5,
                "level": level,
                "index": round(ratio, 3),
                "total": cell["total"],
                "evaluated": evaluated,
                "degraded": cell["degraded"],
                "watch": cell["watch"],
                "ok": cell["ok"],
                "detail": (
                    f"{cell['degraded']} de {evaluated} aeronaves con NIC/NACp degradado "
                    f"en la celda {clat},{clon} (posible interferencia GNSS)"
                ),
            }
        )
    features.sort(key=lambda f: (-f["index"], -f["degraded"]))
    return {
        "aircraft": counts,
        "cells": features,
        "status": "alert" if any(f["level"] == "alert" for f in features) else (
            "watch" if features else "ok"
        ),
        "thresholds": {"nic_degraded": NIC_DEGRADED, "nac_p_degraded": NAC_P_DEGRADED},
    }
