"""Trenes en vivo de todos los operadores que publican datos abiertos.

· Renfe: GTFS-Realtime JSON de Cercanías y AVE/Largo Recorrido, más las
  **incidencias de servicio** (`alerts.json`) como sucesos geolocalizados.
· FGC (Ferrocarrils de la Generalitat de Catalunya): GTFS-Realtime protobuf.
· Amtrak: feed JSON de amtraker.com.

Ouigo e Iryo, los otros dos operadores de alta velocidad en España, no
publican posiciones ni incidencias: no se inventan. Euskotren anuncia GTFS-RT
en el NAP, pero su fichero llega vacío y el SIRI exige sesión, así que tampoco
se muestra.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

from ..models import EventRecord, utcnow
from . import gtfsrt
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

# --- FGC (Ferrocarrils de la Generalitat de Catalunya) ---------------------
# Publica posiciones GTFS-Realtime solo en protobuf, como fichero de un dataset
# de Opendatasoft: primero se resuelve la URL del fichero y luego se descarga.
# Los viajes, líneas y paradas se resuelven con sus datasets estáticos, que se
# cachean 24 h (los service_id cambian a diario).
FGC_DATASET = ("https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets/"
               "vehicle-positions-gtfs_realtime/records?limit=1")
FGC_TRIPS = ("https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets/"
             "trips/exports/json?select=trip_id,route_id,trip_headsign"
             "&where=service_id%3D%22{sid}%22")
FGC_ROUTES = ("https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets/"
              "gtfs_routes/exports/json?select=route_id,route_long_name")
FGC_STOPS = ("https://dadesobertes.fgc.cat/api/explore/v2.1/catalog/datasets/"
             "gtfs_stops/exports/json?select=stop_id,stop_name")
FGC_MIN_INTERVAL_S = 45.0
FGC_META_TTL_S = 24 * 3600

_fgc_last_run = 0.0
_fgc_trips: dict[str, tuple[float, dict[str, dict]]] = {}
_fgc_routes: tuple[float, dict[str, str]] = (0.0, {})
_fgc_stops: tuple[float, dict[str, str]] = (0.0, {})

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


async def _fgc_trip_table(fetcher: Fetcher, service_id: str) -> dict[str, dict]:
    """trip_id → línea y destino para un service_id (se cachea un día)."""
    now = time.time()
    cached = _fgc_trips.get(service_id)
    if cached and now - cached[0] < FGC_META_TTL_S:
        return cached[1]
    data = await fetcher.get_json(FGC_TRIPS.format(sid=quote(service_id, safe="")),
                                  retries=1, timeout=45)
    table: dict[str, dict] = {}
    for row in data if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        trip_id = str(row.get("trip_id") or "")
        if trip_id:
            table[trip_id] = {
                "route": str(row.get("route_id") or ""),
                "headsign": str(row.get("trip_headsign") or ""),
            }
    _fgc_trips[service_id] = (now, table)
    for sid in [k for k, (ts, _) in _fgc_trips.items() if now - ts > 2 * FGC_META_TTL_S]:
        _fgc_trips.pop(sid, None)
    return table


async def _fgc_routes_table(fetcher: Fetcher) -> dict[str, str]:
    global _fgc_routes
    now = time.time()
    if _fgc_routes[1] and now - _fgc_routes[0] < FGC_META_TTL_S:
        return _fgc_routes[1]
    data = await fetcher.get_json(FGC_ROUTES, retries=1, timeout=30)
    table = {
        str(r.get("route_id")): str(r.get("route_long_name") or "")
        for r in (data if isinstance(data, list) else [])
        if isinstance(r, dict) and r.get("route_id")
    }
    _fgc_routes = (now, table)
    return table


async def _fgc_stops_table(fetcher: Fetcher) -> dict[str, str]:
    global _fgc_stops
    now = time.time()
    if _fgc_stops[1] and now - _fgc_stops[0] < FGC_META_TTL_S:
        return _fgc_stops[1]
    data = await fetcher.get_json(FGC_STOPS, retries=1, timeout=30)
    table = {
        str(r.get("stop_id")): str(r.get("stop_name") or "")
        for r in (data if isinstance(data, list) else [])
        if isinstance(r, dict) and r.get("stop_id")
    }
    _fgc_stops = (now, table)
    return table


def parse_fgc(vehicles: list[dict[str, Any]], trips: dict[str, dict],
              routes: dict[str, str], stops: dict[str, str]) -> list[dict[str, Any]]:
    """Posiciones GTFS-RT de FGC → actores de la capa viva."""
    rows: list[dict[str, Any]] = []
    for vp in vehicles:
        lat, lon = vp.get("lat"), vp.get("lon")
        if lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        trip_id = str(vp.get("trip_id") or "")
        info = trips.get(trip_id) or {}
        route = str(info.get("route") or vp.get("route_id") or "")
        headsign = str(info.get("headsign") or "")
        stop_id = str(vp.get("stop_id") or "")
        vid = str(vp.get("vehicle_id") or vp.get("label") or trip_id or f"{lat:.4f}{lon:.4f}")
        speed = vp.get("speed")
        bearing = vp.get("bearing")
        status = str(vp.get("status") or "")
        # Las líneas L* son el metro de Barcelona (L6, L7, L8, L12); R* y S*
        # son cercanías. El icono del mapa cambia con este campo.
        service = "metro" if route[:1].upper() == "L" else "cercanías"
        name = f"FGC {route} · {headsign}".strip(" ·") if route else f"FGC {vid}"

        rows.append({
            "id": f"fgc:{vid}",
            "name": name,
            "label": vid,
            "line": route,
            "line_label": route,
            "trip_id": trip_id,
            "lat": lat,
            "lon": lon,
            "speed_kmh": round(float(speed) * 3.6, 1) if speed is not None else None,
            "track": bearing,
            "status": STATUS_ES.get(status, status or "sin estado"),
            "nucleo": "Catalunya",
            "next_stop": stop_id,
            "next_stop_name": stops.get(stop_id, ""),
            "destination": headsign,
            "route_name": routes.get(route, ""),
            "service": service,
            "delay_s": None,
            "operator": "FGC",
            "network": "fgc",
            "kind": "tren",
            "country": "ES",
            "source": "dadesobertes.fgc.cat",
        })
    return rows


async def _refresh_fgc(fetcher: Fetcher) -> list[dict[str, Any]]:
    """Feed de FGC: resuelve el fichero del dataset y lo decodifica."""
    global _fgc_last_run
    now = time.time()
    if now - _fgc_last_run < FGC_MIN_INTERVAL_S:
        return []
    _fgc_last_run = now

    listing = await fetcher.get_json(FGC_DATASET, retries=1, timeout=25)
    url = ""
    for record in (listing or {}).get("results") or []:
        file = (record or {}).get("file") or {}
        if file.get("url"):
            url = str(file["url"])
            break
    if not url:
        return []
    blob = await fetcher.get_bytes(url, retries=1, timeout=30)
    vehicles = gtfsrt.parse_vehicles(blob)
    if not vehicles:
        log.info("trenes FGC: el feed no trae posiciones ahora mismo")
        return []

    service_ids = {str(v.get("trip_id") or "").split("|", 1)[0] for v in vehicles}
    trips: dict[str, dict] = {}
    for sid in sorted(s for s in service_ids if s):
        try:
            trips.update(await _fgc_trip_table(fetcher, sid))
        except Exception as exc:  # noqa: BLE001 - sin índice se muestra igual
            log.warning("trenes FGC: viajes de %s: %s", sid, exc)
    try:
        routes = await _fgc_routes_table(fetcher)
    except Exception:  # noqa: BLE001 - el nombre largo es opcional
        routes = _fgc_routes[1]
    try:
        stops = await _fgc_stops_table(fetcher)
    except Exception:  # noqa: BLE001 - el nombre de parada es opcional
        stops = _fgc_stops[1]
    return parse_fgc(vehicles, trips, routes, stops)


async def refresh(fetcher: Fetcher, index=None) -> int:
    """Descarga los feeds de todos los operadores y alimenta la capa TRAINS."""
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

    # FGC (Cataluña): junto a Renfe, el único operador ferroviario español con
    # posiciones abiertas. Ouigo e Iryo no las publican.
    try:
        fgc_rows = await _refresh_fgc(fetcher)
        if fgc_rows:
            TRAINS.upsert_many(fgc_rows)
            rows.extend(fgc_rows)
            total += len(fgc_rows)
            log.info("trenes FGC: %d unidades", len(fgc_rows))
    except Exception as exc:  # noqa: BLE001 - un feed caído no tumba al resto
        log.warning("trenes FGC: %s", exc)

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
