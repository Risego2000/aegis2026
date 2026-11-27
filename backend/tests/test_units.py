"""Lógica pura: prioridad social, parseo de bbox y limitador de peticiones."""
from __future__ import annotations

import struct
from types import SimpleNamespace

from app.api import limits
from app.api.routes import _parse_bbox, social_priority
from app.ingest import gtfsrt


def _evento(**overrides):
    base = dict(
        title="Suceso", subtype="", summary="", category="news",
        severity_label="info", sources_count=1, mentions=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_parse_bbox_valido_y_basura():
    assert _parse_bbox("-3,40,-2,41") == (-3.0, 40.0, -2.0, 41.0)
    assert _parse_bbox(None) is None
    assert _parse_bbox("1,2,3") is None
    assert _parse_bbox("a,b,c,d") is None


def test_prioridad_sube_con_muertos_y_categoria():
    tranquilo = social_priority(_evento(category="economy"))
    grave = social_priority(
        _evento(title="Explosión con muertos y evacuados", category="conflict", sources_count=4)
    )
    assert grave["score"] > tranquilo["score"]
    assert grave["population_threat"] is True
    assert grave["reasons"]


def test_prioridad_acotada_entre_0_y_10():
    maximo = social_priority(
        _evento(
            title="Atentado con bomba, muertos, tsunami y evacuación inmediata",
            category="conflict", sources_count=10, mentions=50,
        )
    )
    assert 0 <= maximo["score"] <= 10


def test_limitador_bloquea_al_pasarse():
    limits.LIMITER.reset()
    # /api/export/* tiene un tope de 30 por minuto y cliente
    permitidas = [limits.check("GET", "/api/export/events", "203.0.113.9") is None for _ in range(31)]
    assert all(permitidas[:30])
    assert permitidas[30] is False
    verdict = limits.check("GET", "/api/export/events", "203.0.113.9")
    assert verdict is not None
    retry_after, limit = verdict
    assert limit == 30 and 1 <= retry_after <= 60
    limits.LIMITER.reset()


def test_limitador_no_afecta_a_rutas_normales():
    limits.LIMITER.reset()
    for _ in range(50):
        assert limits.check("GET", "/api/health", "203.0.113.10") is None
    assert limits.check("GET", "/api/events", "203.0.113.10") is None


def test_ventana_deslizante_caduca():
    window = limits.SlidingWindow(window_s=60)
    assert window.hit("k", 2, now=1000.0)[0] is True
    assert window.hit("k", 2, now=1001.0)[0] is True
    assert window.hit("k", 2, now=1002.0)[0] is False          # tercera en el minuto
    assert window.hit("k", 2, now=1061.0)[0] is True            # la primera ya caducó


# --- GTFS-Realtime protobuf (operadores que no publican JSON) ----------------
def _vi(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _ld(field: int, payload: bytes) -> bytes:
    return _vi((field << 3) | 2) + _vi(len(payload)) + payload


def _f32(field: int, value: float) -> bytes:
    return _vi((field << 3) | 5) + struct.pack("<f", value)


def _varint_field(field: int, value: int) -> bytes:
    return _vi(field << 3) + _vi(value)


def test_gtfsrt_lee_posiciones_y_estado():
    trip = _ld(1, b"trip-1") + _ld(5, b"S1")
    pos = _f32(1, 41.5) + _f32(2, 2.25) + _f32(3, 90.0) + _f32(5, 12.5)
    vehicle = _ld(1, b"v-9") + _ld(2, b"etiqueta")
    vp = (_ld(1, trip) + _ld(2, pos) + _varint_field(4, 2)
          + _varint_field(5, 1_700_000_000) + _ld(7, b"PN1") + _ld(8, vehicle))
    feed = _ld(2, _ld(1, b"e-1") + _ld(4, vp))

    assert gtfsrt.parse_vehicles(feed) == [{
        "entity_id": "e-1", "trip_id": "trip-1", "route_id": "S1",
        "vehicle_id": "v-9", "label": "etiqueta", "lat": 41.5, "lon": 2.25,
        "bearing": 90.0, "speed": 12.5, "stop_id": "PN1",
        "status": "IN_TRANSIT_TO", "timestamp": 1_700_000_000,
    }]


def test_gtfsrt_ignora_feeds_corruptos():
    assert gtfsrt.parse_vehicles(b"") == []
    assert gtfsrt.parse_vehicles(b"\x00\x01\xff") == []
    assert gtfsrt.parse_vehicles(_ld(2, b"\xff")) == []
