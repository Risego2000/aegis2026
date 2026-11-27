"""Lector mínimo de GTFS-Realtime (protobuf) sin dependencias externas.

Renfe publica sus posiciones en JSON, pero otros operadores (FGC, Euskotren,
Entur…) solo ofrecen el `FeedMessage` binario estándar. Añadir `protobuf` o
`gtfs-realtime-bindings` por dos campos sería desproporcionado: el formato wire
es estable y aquí solo se leen posiciones de vehículo.

Se decodifica el subconjunto necesario de gtfs-realtime.proto:

    FeedMessage      entity = 2
    FeedEntity       id = 1, vehicle = 4
    VehiclePosition  trip = 1, position = 2, current_status = 4, timestamp = 5,
                     stop_id = 7, vehicle = 8
    TripDescriptor   trip_id = 1, route_id = 5
    Position         latitude = 1, longitude = 2, bearing = 3, speed = 5
    VehicleDescriptor id = 1, label = 2

Los campos desconocidos se ignoran, así que el mismo lector sirve para feeds
que añadan extensiones.
"""
from __future__ import annotations

import struct
from typing import Any, Iterator

# VehicleStopStatus de GTFS-Realtime
STATUS = {0: "INCOMING_AT", 1: "STOPPED_AT", 2: "IN_TRANSIT_TO"}


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(buf):
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            break
    raise ValueError("varint truncado")


def _fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    pos = 0
    while pos < len(buf):
        key, pos = _varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 1:
            value = buf[pos:pos + 8]
            pos += 8
        elif wire == 2:
            size, pos = _varint(buf, pos)
            value = buf[pos:pos + size]
            pos += size
        elif wire == 5:
            value = buf[pos:pos + 4]
            pos += 4
        else:  # grupos (3, 4) no se usan en GTFS-RT
            raise ValueError(f"tipo wire no soportado: {wire}")
        yield field, wire, value


def _message(buf: bytes) -> dict[int, Any]:
    out: dict[int, Any] = {}
    for field, _wire, value in _fields(buf):
        out[field] = value
    return out


def _text(value: Any) -> str:
    if not isinstance(value, (bytes, bytearray)):
        return ""
    return bytes(value).decode("utf-8", "replace").strip()


def _number(value: Any, wire: int) -> float | None:
    try:
        if wire == 5 and isinstance(value, (bytes, bytearray)) and len(value) == 4:
            return float(struct.unpack("<f", bytes(value))[0])
        if wire == 1 and isinstance(value, (bytes, bytearray)) and len(value) == 8:
            return float(struct.unpack("<d", bytes(value))[0])
    except (struct.error, TypeError, ValueError):
        return None
    return None


def parse_vehicles(blob: bytes) -> list[dict[str, Any]]:
    """FeedMessage binario → lista de posiciones con nombres de campo legibles."""
    rows: list[dict[str, Any]] = []
    if not blob:
        return rows
    try:
        entities = list(_fields(blob))
    except (ValueError, IndexError):
        return rows

    for field, wire, value in entities:
        if field != 2 or wire != 2:
            continue
        try:
            entity = _message(value)
        except ValueError:
            continue
        raw_vehicle = entity.get(4)
        if not isinstance(raw_vehicle, (bytes, bytearray)):
            continue
        try:
            vp = _message(bytes(raw_vehicle))
        except ValueError:
            continue

        try:
            trip = _message(bytes(vp.get(1) or b""))
            vehicle = _message(bytes(vp.get(8) or b""))
        except ValueError:
            trip, vehicle = {}, {}

        # Position: 1 latitud, 2 longitud, 3 rumbo, 5 velocidad (m/s)
        lat = lon = bearing = speed = None
        try:
            for f, w, v in _fields(bytes(vp.get(2) or b"")):
                if f == 1:
                    lat = _number(v, w)
                elif f == 2:
                    lon = _number(v, w)
                elif f == 3:
                    bearing = _number(v, w)
                elif f == 5:
                    speed = _number(v, w)
        except (ValueError, IndexError):
            continue
        if lat is None or lon is None:
            continue

        status = vp.get(4)
        rows.append({
            "entity_id": _text(entity.get(1)),
            "trip_id": _text(trip.get(1)),
            "route_id": _text(trip.get(5)),
            "vehicle_id": _text(vehicle.get(1)),
            "label": _text(vehicle.get(2)),
            "lat": lat,
            "lon": lon,
            "bearing": bearing,
            "speed": speed,
            "stop_id": _text(vp.get(7)),
            "status": STATUS.get(status, "") if isinstance(status, int) else "",
            "timestamp": vp.get(5) if isinstance(vp.get(5), int) else None,
        })
    return rows
