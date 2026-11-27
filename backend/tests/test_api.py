"""Contrato HTTP: los endpoints que consume el mapa responden con su forma.

No comprueban datos concretos (los tests no salen a la red): comprueban que la
API arranca, que cada capa devuelve una colección válida y que las rutas
protegidas siguen cerradas. Es la red que faltaba: el sitio publicado llevaba
horas sin backend y nada lo detectaba.
"""
from __future__ import annotations


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["storage"]["backend"].startswith("sqlite")
    assert {"aircraft", "vessels", "satellites", "trains", "air", "cameras"} <= set(data["live"])


def test_config_expone_categorias_y_geovallas(client):
    data = client.get("/api/config").json()
    assert data["categories"]
    assert data["fence_engine"] in {"in-process", "tile38"}
    assert data["storage"].startswith("sqlite")
    assert "hotspots" in data


def test_events_vacio_es_una_coleccion_valida(client):
    data = client.get("/api/events?hours=24&limit=5").json()
    assert data["type"] == "FeatureCollection"
    assert data["features"] == []
    assert data["server_time"]


def test_layers_cuenta_todas_las_capas(client):
    data = client.get("/api/layers").json()
    assert {"events", "aircraft", "vessels", "satellites", "trains", "cameras", "air"} <= set(data)
    assert data["events"]["total"] == 0


def test_capas_vivas_vacias_pero_validas(client):
    for layer in ("aircraft", "vessels", "trains", "air", "satellites"):
        res = client.get(f"/api/live/{layer}")
        assert res.status_code == 200, layer
        data = res.json()
        assert data["type"] == "FeatureCollection", layer
        assert data["features"] == [], layer


def test_camaras_sin_ingesta(client):
    res = client.get("/api/cameras?limit=10")
    assert res.status_code == 200
    assert res.json()["type"] == "FeatureCollection"


def test_exportaciones_no_revientan_sin_datos(client):
    assert client.get("/api/export/events?hours=24&fmt=csv").status_code == 200
    geo = client.get("/api/export/events?hours=24&fmt=geojson")
    assert geo.status_code == 200
    assert geo.json()["type"] == "FeatureCollection"


def test_ingesta_desconocida_se_rechaza(client):
    res = client.post("/api/ingest/inexistente/run")
    assert res.status_code == 502
    assert res.json()["detail"]["ok"] is False


def test_ia_local_sin_claves(client):
    data = client.get("/api/ai/status").json()
    assert data["provider"] == "local"
    assert data["available"] is True


def test_canal_en_vivo_responde(client):
    data = client.get("/api/poll?since=0&wait=1").json()
    assert isinstance(data.get("layers"), list)
    assert "cursor" in data


def test_poll_senala_sucesos_nuevos(client):
    """Un suceso nuevo debe pedir al cliente que recargue la capa events."""
    from app.livehub import HUB

    before = HUB.event_seq
    HUB.push_events([{"id": "test:evento", "title": "evento de prueba"}])
    data = client.get(f"/api/poll?since={before}&as={HUB.alert_seq}&wait=0").json()
    assert "events" in data["layers"]
    assert data["cursor"] > before


def test_fences_crud(client):
    created = client.post("/api/fences", json={"name": "test", "lat": 40.4, "lon": -3.7, "radius_m": 5000})
    assert created.status_code == 200
    fence_id = created.json()["fence"]["id"]
    assert fence_id in {f["id"] for f in client.get("/api/fences").json()["definitions"]}
    assert client.delete(f"/api/fences/{fence_id}").status_code == 200
    assert client.delete(f"/api/fences/{fence_id}").status_code == 404
