"""Trenes de España — GTFS-Realtime de Renfe + índice estático.

Además de las posiciones (Cercanías y AVE/Largo Recorrido), este módulo aporta
las **incidencias de servicio** de Renfe (`alerts.json`) como sucesos de la capa
de eventos: tienen hora, línea afectada y texto oficial, así que se pintan en el
mapa con el resto de la inteligencia.

Los otros dos operadores de alta velocidad (Ouigo e Iryo) no publican ni
posiciones ni incidencias: no se inventan.
"""
from __future__ import annotations

import logging
from typing import Any

from ..models import EventRecord, utcnow
from .client import Fetcher

log = logging.getLogger("aegis.trains")

CERCANIAS_URL = "https://gtfsrt.renfe.com/vehicle_positions.json"
# Media distancia: Renfe publica el feed GTFS-RT completo en vehicle_positions.json
# (Cercanías llama al mismo fichero); los MD viajan en él mezclados, así que se
# separan por la línea del índice GTFS, no por el nombre del fichero.
MEDIA_DISTANCIA_MARK = ("Media Distancia", "MD", "Regional", "Proximidad", "TRD")
LARGO_RECORRIDO_URL = "https://gtfsrt.renfe.com/vehicle_positions_LD.json"
# Amtrak (EE. UU.) mantiene un feed público sin clave con todos sus trenes
# en marcha, incluso de madrugada en Europa: es la otra mitad del mundo.
AMTRAK_URL = "https://api-v3.amtraker.com/v3/trains"
TRIP_UPDATES_CER = "https://gtfsrt.renfe.com/trip_updates.json"
TRIP_UPDATES_LD = "https://gtfsrt.renfe.com/trip_updates_LD.json"

# Núcleos de Cercanías por los dos primeros dígitos del trip_id
NUCLEOS = {
    "10": "Madrid", "20": "Sevilla", "30": "Barcelona", "40": "Valencia",
    "50": "Bilbao", "60": "Asturias", "70": "Santander", "71": "Santander",
    "72": "León", "73": "Ferrol", "74": "Cartagena", "75": "Málaga",
    "76": "Zaragoza", "77": "Murcia/Alicante", "78": "San Sebastián",
    "79": "Cádiz", "80": "Cádiz", "81": "San Sebastián",
}

STATUS_ES = {
    "INCOMING_AT": "llegando a parada",
    "STOPPED_AT": "detenido en parada",
    "IN_TRANSIT_TO": "en marcha",
}


def train_service(line_label: str, route_name: str, trip_id: str) -> str:
    """Tipo de servicio del tren a partir de su línea en el GTFS de Renfe.

    Nunca se inventa: si el índice no lo sabe, se devuelve "tren".
    """
    text = f"{line_label} {route_name}".lower()
    if any(k in text for k in ("ave", "avlo", "euromed", "alaris", "talgo")):
        return "alta velocidad" if "avlo" not in text else "bajo coste"
    if "alvia" in text or "avant" in text or "intercity" in text:
        return "larga distancia"
    if any(k.lower() in text for k in MEDIA_DISTANCIA_MARK):
        return "media distancia"
    if line_label and (line_label[0] in "CR" or line_label[:1].isdigit()):
        return "cercanías"
    return "cercanías" if not line_label else "tren"


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delays(payload: dict) -> dict[str, float]:
    """trip_id -> retraso en segundos (primer stopTimeUpdate que lo traiga)."""
    out: dict[str, float] = {}
    for ent in payload.get("entity") or []:
        upd = ent.get("tripUpdate") or {}
        trip = upd.get("trip") or {}
        tid = str(trip.get("tripId") or "")
        if not tid:
            continue
        for stu in upd.get("stopTimeUpdate") or []:
            delay = stu.get("arrival", {}).get("delay", stu.get("departure", {}).get("delay"))
            if delay is not None:
                try:
                    out[tid] = float(delay)
                except (TypeError, ValueError):
                    pass
                break
    return out


def parse(payload: dict, *, operator: str, network: str,
          delays: dict[str, float] | None = None, index=None) -> list[dict[str, Any]]:
    """GTFS-RT `vehicle` → actores de la capa viva (con nombres si hay índice)."""
    delays = delays or {}
    rows: list[dict[str, Any]] = []
    for ent in payload.get("entity") or []:
        veh = ent.get("vehicle") or {}
        pos = veh.get("position") or {}
        lat = _f(pos.get("latitude"))
        lon = _f(pos.get("longitude"))
        if lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        trip = veh.get("trip") or {}
        trip_id = str(trip.get("tripId") or ent.get("id") or "")
        route = str(trip.get("routeId") or "")
        vehicle = veh.get("vehicle") or {}
        vid = str(vehicle.get("id") or trip_id or f"{lat:.4f}{lon:.4f}")
        label = str(vehicle.get("label") or "").strip()

        line = route or (label.split("-")[0].strip() if "-" in label else "")
        nucleo = NUCLEOS.get(trip_id[:2]) or NUCLEOS.get(route[:2]) or ""
        speed_ms = _f(pos.get("speed"))
        bearing = _f(pos.get("bearing"))
        status = str(veh.get("currentStatus") or "")
        delay = delays.get(trip_id)

        name = label or (f"{line} · {trip_id}" if line else trip_id)

        stop_id = str(veh.get("stopId") or "")
        info = index.trip_info(trip_id) if index else {}
        stop_name = index.stop_name(stop_id) if (index and stop_id) else ""
        headsign = str(info.get("headsign") or "")
        route_obj = (index.routes.get(info.get("route")) or {}) if (index and info.get("route")) else {}
        route_name = route_obj.get("long", "")
        line_label = route_obj.get("short") or line
        service = train_service(str(route_obj.get("short") or ""), str(route_name or ""), trip_id)

        rows.append(
            {
                "id": f"{network}:{vid}",
                "name": name,
                "label": label,
                "line": line,
                "line_label": line_label,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "speed_kmh": round(speed_ms * 3.6, 1) if speed_ms is not None else None,
                "track": bearing,
                "status": STATUS_ES.get(status, status or "sin estado"),
                "nucleo": nucleo,
                "next_stop": stop_id,
                "next_stop_name": stop_name,
                "destination": headsign,
                "route_name": route_name,
                "service": service,
                "delay_s": delay,
                "operator": operator,
                "network": network,
                "kind": "tren",
                "country": "ES",
                "source": "gtfsrt.renfe.com",
            }
        )
    return rows


def parse_amtrak(payload: dict) -> list[dict[str, Any]]:
    """Feed de Amtrak: un objeto por tren con estaciones y estado.

    Trae lat/lon, rumbo y velocidad en millas por hora; el retraso se calcula
    con la hora real y la prevista de la próxima parada.
    """
    rows: list[dict[str, Any]] = []
    for train_id, units in (payload or {}).items():
        if not isinstance(units, list):
            continue
        for unit in units:
            lat = _f(unit.get("lat"))
            lon = _f(unit.get("lon"))
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            stations = unit.get("stations") or []
            nxt = next((st for st in stations if st.get("arr") and not st.get("bus")), {})
            delay_s = None
            try:
                from datetime import datetime
                if nxt.get("arr") and nxt.get("schArr"):
                    a = datetime.fromisoformat(str(nxt["arr"]))
                    b = datetime.fromisoformat(str(nxt["schArr"]))
                    delay_s = max(0.0, (a - b).total_seconds())
            except Exception:  # noqa: BLE001 - el retraso es opcional
                pass
            speed = _f(unit.get("velocity"))
            heading = _f(unit.get("heading"))
            num = str(unit.get("trainNum") or train_id)
            route = str(unit.get("routeName") or "")
            rows.append({
                "id": f"amtrak:{train_id}:{unit.get('trainID') or ''}",
                "name": f"Amtrak {num} · {route}".strip(" ·"),
                "label": num,
                "line": route,
                "line_label": route,
                "trip_id": str(unit.get("trainID") or train_id),
                "lat": lat,
                "lon": lon,
                "speed_kmh": round(speed * 1.60934, 1) if speed is not None else None,
                "track": heading if heading is not None else None,
                "status": str(unit.get("trainState") or unit.get("statusMsg") or "en marcha"),
                "nucleo": "",
                "next_stop": str(unit.get("destCode") or ""),
                "next_stop_name": str(nxt.get("name") or unit.get("eventName") or ""),
                "destination": str(unit.get("destName") or unit.get("eventName") or ""),
                "route_name": route,
                "service": "larga distancia",
                "delay_s": delay_s,
                "operator": "Amtrak",
                "network": "amtrak",
                "kind": "tren",
                "country": "US",
                "source": "amtraker.com",
            })
    return rows


async def refresh(fetcher: Fetcher, index=None) -> int:
    """Descarga ambas familias de feeds y alimenta la capa TRAINS."""
    from ..live import TRAINS

    total = 0
    rows: list[dict[str, Any]] = []
    for url, updates_url, operator, network in (
        (CERCANIAS_URL, TRIP_UPDATES_CER, "Renfe Cercanías", "renfe-cercanias"),
        (LARGO_RECORRIDO_URL, TRIP_UPDATES_LD, "Renfe AVE/LD/MD", "renfe-ld"),
    ):
        try:
            payload = await fetcher.get_json(url, retries=2, timeout=25)
        except Exception as exc:  # noqa: BLE001 - un feed caído no tumba el otro
            log.warning("trenes %s: %s", network, exc)
            continue
        delays: dict[str, float] = {}
        try:
            delays = _delays(await fetcher.get_json(updates_url, retries=1, timeout=20))
        except Exception:  # noqa: BLE001 - el retraso es opcional
            pass
        parsed = parse(payload, operator=operator, network=network, delays=delays, index=index)
        TRAINS.upsert_many(parsed)
        rows.extend(parsed)
        total += len(parsed)
        log.info("trenes %s: %d unidades", network, len(parsed))

    # Amtrak: sigue aunque Renfe esté de madrugada, así la capa enseña trenes
    try:
        amtrak = await fetcher.get_json(AMTRAK_URL, retries=2, timeout=30)
        amtrak_rows = parse_amtrak(amtrak)
        TRAINS.upsert_many(amtrak_rows)
        rows.extend(amtrak_rows)
        total += len(amtrak_rows)
        log.info("trenes Amtrak: %d unidades", len(amtrak_rows))
    except Exception as exc:  # noqa: BLE001 - un feed caído no tumba al otro
        log.warning("trenes Amtrak: %s", exc)

    if total == 0:
        log.info("trenes: sin servicio en este momento (los feeds están vacíos)")
    # la lista se devuelve porque el registry vuelca la capa con ella
    return rows


def alerts_to_events(alertas: list[dict[str, Any]], index=None,
                     max_events: int = 60) -> list[EventRecord]:
    """Incidencias de servicio de Renfe → sucesos de la capa de eventos.

    Se colocan en el centro geográfico de las paradas de la línea afectada; si
    la línea no está en el índice, no se inventa una posición: el suceso se
    descarta (queda en la lista de alertas del panel de trenes).
    """
    out: list[EventRecord] = []
    for al in alertas[:max_events]:
        text = str(al.get("text") or "").strip()
        if not text:
            continue
        lat = lon = None
        line_name = ""
        for rid in al.get("routes") or []:
            if not index:
                break
            points = [index.stops[s] for s in _stops_of_route(index, rid) if s in index.stops]
            if not points:
                continue
            lat = sum(p["lat"] for p in points) / len(points)
            lon = sum(p["lon"] for p in points) / len(points)
            route = index.routes.get(rid) or {}
            line_name = route.get("short") or route.get("long") or rid
            break
        if lat is None or lon is None:
            continue
        try:
            start = int(al.get("start") or 0)
        except (TypeError, ValueError):
            start = 0
        when = utcnow()
        if start:
            from datetime import datetime, timezone

            when = datetime.fromtimestamp(start, tz=timezone.utc)
        uid = f"renfe:alerta:{abs(hash(text)) % (10 ** 12)}"
        out.append(
            EventRecord(
                uid=uid,
                source="renfe",
                category="transporte",
                title=f"Renfe · incidencia en {line_name}" if line_name else "Renfe · incidencia de servicio",
                lat=round(lat, 4),
                lon=round(lon, 4),
                event_time=when,
                summary=text[:600],
                subtype="servicio ferroviario",
                severity=2.5,
                severity_label="info",
                country="Spain",
                iso3="ESP",
                url="https://www.renfe.com/es/es/viajar/prepara-tu-viaje/avisos",
                payload={"linea": line_name, "routes": al.get("routes") or []},
            )
        )
    return out


def _stops_of_route(index, route_id: str, limit: int = 40) -> list[str]:
    """Paradas de una línea, de la más céntrica a la más lejana.

    Cercanías no guarda itinerarios (serían 1,8 M de filas), así que la línea
    se sitúa con las paradas que aparecen en `stops.txt` y que el feed de
    posiciones ha visto en viajes de esa línea. Si no hay ninguna, se usa el
    centro de todas las paradas del índice como posición de la incidencia.
    """
    seen: dict[str, int] = {}
    for tid, t in index.trips.items():
        if t.get("route") != route_id:
            continue
        for sid in t.get("stops") or []:
            seen[sid] = seen.get(sid, 0) + 1
    return sorted(seen, key=seen.get, reverse=True)[:limit]
