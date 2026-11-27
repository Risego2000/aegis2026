"""Lógica pura: prioridad social, parseo de bbox y limitador de peticiones."""
from __future__ import annotations

from types import SimpleNamespace

from app.api import limits
from app.api.routes import _parse_bbox, social_priority


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
