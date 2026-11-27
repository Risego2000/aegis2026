"""Tests de la capa de analista: graduación, patrones, casos, grafo y productos.

Todo se prueba con datos fabricados: ni red ni fuentes externas. Lo que se
verifica es la lógica (reglas explícitas, cadena de hashes, parseo tolerante),
que es justo lo que no se puede comprobar a ojo en el mapa.
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.extras import anomalies, gnss, graph, reports, tradecraft
from app.extras.storage import ExtrasStore
from app.ingest import ioda
from app.live import VESSELS


def _event(**kw):
    base = dict(
        id="ev:1",
        source="usgs",
        sources=["usgs"],
        category="earthquake",
        title="Sismo M6.1 frente a la costa",
        summary="",
        lat=10.0,
        lon=20.0,
        severity=6.0,
        severity_label="orange",
        event_time=datetime.now(timezone.utc).isoformat(),
        iso3="ESP",
        country="España",
        mentions=1,
        sources_count=1,
        confidence=0.5,
        url="https://example.org/event",
        payload={},
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# graduación
# --------------------------------------------------------------------------- #
def test_admiralty_single_source_is_probable():
    grade = tradecraft.grade_event(_event())
    assert grade["admiralty"] == "A3"
    assert grade["source_reliability"] == "A"
    assert grade["tlp"]


def test_admiralty_corroborated_is_confirmed():
    grade = tradecraft.grade_event(_event(sources_count=3, sources=["usgs", "emsc", "gdacs"]))
    assert grade["admiralty"] == "A1"


def test_admiralty_unknown_source_is_unjudgeable():
    grade = tradecraft.grade_event(_event(source="blog-desconocido", sources=[]))
    assert grade["admiralty"] == "F6"
    assert grade["info_credibility"] == 6


def test_admiralty_old_single_source_is_doubtful():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert tradecraft.grade_event(_event(event_time=old))["admiralty"] == "A4"


# --------------------------------------------------------------------------- #
# GNSS
# --------------------------------------------------------------------------- #
def test_gnss_flags_cell_with_degraded_aircraft():
    aircraft = [
        {"lat": 40.1, "lon": -3.1, "nic": 0, "nac_p": 0},
        {"lat": 40.4, "lon": -3.4, "nic": 1, "nac_p": 2},
        {"lat": 40.7, "lon": -3.7, "nic": 8, "nac_p": 9},
        {"lat": 40.9, "lon": -3.9, "nic": 8, "nac_p": 9},
    ]
    result = gnss.evaluate(aircraft, min_aircraft=3, min_degraded=2)
    assert result["status"] in ("watch", "alert")
    assert result["cells"]
    assert result["cells"][0]["degraded"] == 2
    assert result["aircraft"]["degraded"] == 2


def test_gnss_healthy_traffic_is_ok():
    aircraft = [{"lat": 1.0, "lon": 1.0, "nic": 8, "nac_p": 9} for _ in range(5)]
    assert gnss.evaluate(aircraft)["status"] == "ok"


# --------------------------------------------------------------------------- #
# anomalías AIS
# --------------------------------------------------------------------------- #
def _trail(now, points):
    return [(now + offset, lat, lon, 0.0, 10.0, 90.0) for offset, lat, lon in points]


def test_impossible_speed_is_flagged(monkeypatch):
    now = datetime.now(timezone.utc).timestamp()
    history = {"mmsi:1": _trail(now, [(0, 40.0, -3.0), (600, 41.5, -3.0)])}
    monkeypatch.setattr(VESSELS, "history", history)
    monkeypatch.setattr(VESSELS, "items", {"mmsi:1": {"name": "BUQUE PRUEBA"}})
    found = anomalies.impossible_speeds()
    assert len(found) == 1
    assert found[0]["kind"] == "ais_impossible_speed"


def test_stationary_boat_is_flagged(monkeypatch):
    now = datetime.now(timezone.utc).timestamp()
    points = [(i * 300, 36.0, -5.0) for i in range(8)]   # 35 min quieto
    monkeypatch.setattr(VESSELS, "history", {"mmsi:2": _trail(now, points)})
    monkeypatch.setattr(VESSELS, "items", {"mmsi:2": {"name": "FONDEADO"}})
    kinds = {item["kind"] for item in anomalies.evaluate()["items"]}
    assert "ais_stationary" in kinds


# --------------------------------------------------------------------------- #
# IODA
# --------------------------------------------------------------------------- #
def test_ioda_parse_reads_country_alerts():
    payload = {
        "data": [
            {"entityCode": "ESP", "entityType": "country", "score": 0.8,
             "time": "2026-03-01T10:00:00Z", "datasource": "bgp"},
            {"entityCode": "ZZZ", "entityType": "country", "score": 0.2},   # sin centroide
            {"entityCode": "AS123", "entityType": "asn", "score": 0.9},     # no es país
        ]
    }
    records = ioda.parse(payload)
    assert len(records) == 1
    event = records[0]
    assert event.category == "network"
    assert event.source == "ioda"
    assert event.iso3 == "ESP"
    assert event.severity >= 6
    assert event.lat and event.lon


def test_ioda_parse_survives_garbage():
    assert ioda.parse({"data": [None, {}, {"foo": 1}, "texto"]}) == []
    assert ioda.parse({}) == []


# --------------------------------------------------------------------------- #
# grafo y productos
# --------------------------------------------------------------------------- #
def test_graph_has_sources_countries_and_graphml():
    result = graph.build_graph([_event(), _event(id="ev:2", source="gdelt", iso3="FRA")])
    assert result["counts"]["nodes"] >= 5
    kinds = {node["kind"] for node in result["nodes"]}
    assert {"event", "source", "country"} <= kinds
    xml = graph.to_graphml(result)
    root = ET.fromstring(xml)
    assert root.tag.endswith("graphml")
    assert len(root.findall(".//{http://graphml.graphdrawing.org/xmlns}node")) == result["counts"]["nodes"]


def test_sitrep_contains_grades_and_events():
    text = reports.sitrep([_event()], hours=24)
    assert "# SITREP" in text
    assert "A3" in text
    assert "Sismo" in text


def test_country_profile_pmesii():
    profile = reports.country_profile([_event(), _event(id="ev:2", category="conflict")], "esp")
    assert profile["iso3"] == "ESP"
    assert profile["events"] == 2
    assert profile["dimensions"]["military"]["events"] == 1
    assert 0 <= profile["stability_index"] <= 100


def test_stix_bundle_is_valid_shape():
    bundle = reports.stix_bundle([_event()], tlp="AMBER")
    assert bundle["type"] == "bundle"
    incident = [o for o in bundle["objects"] if o["type"] == "incident"][0]
    assert incident["x_aegis_admiralty"] == "A3"
    assert incident["x_aegis_tlp"] == "AMBER"
    assert incident["external_references"][0]["url"].startswith("https://")


# --------------------------------------------------------------------------- #
# almacén: watchlists y cadena de custodia
# --------------------------------------------------------------------------- #
def test_case_chain_detects_tampering(tmp_path):
    store = ExtrasStore(str(tmp_path / "extras.db"))
    store.init()
    case = store.create_case("Caso de prueba", tlp="AMBER")
    store.add_case_item(case["id"], {"kind": "event", "ref": "ev:1", "title": "Sismo"})
    store.add_case_item(case["id"], {"kind": "note", "note": "Análisis preliminar"})
    assert store.verify_case(case["id"])["ok"] is True

    conn = sqlite3.connect(str(tmp_path / "extras.db"))
    conn.execute("UPDATE case_items SET payload='{\"kind\": \"event\", \"ref\": \"ev:1\", \"title\": \"Otro\"}'")
    conn.commit()
    conn.close()

    verdict = store.verify_case(case["id"])
    assert verdict["ok"] is False
    # editar un eslabón rompe ese y todos los posteriores: es el sentido de la cadena
    assert len(verdict["broken"]) == 2
    store.close()


def test_watchlists_crud(tmp_path):
    store = ExtrasStore(str(tmp_path / "watch.db"))
    store.init()
    watch = store.add_watchlist({"name": "Sismos España", "query": "sismo espana", "min_severity": 5})
    assert store.list_watchlists()[0]["id"] == watch["id"]
    store.record_hit(watch["id"], "ev:1", "Sismo", {"severity": 6})
    assert store.hits()[0]["event_id"] == "ev:1"
    assert store.delete_watchlist(watch["id"]) is True
    assert store.list_watchlists() == []
    store.close()


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_api_extras_are_mounted(client):
    for path in ("/api/gnss", "/api/anomalies", "/api/watchlists", "/api/cases",
                 "/api/playback", "/api/extras/stats", "/api/graph", "/api/report/sitrep"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} → {response.status_code}"


def test_api_watchlist_validation(client):
    bad = client.post("/api/watchlists", json={"name": "x", "bbox": [1, 2, 3]})
    assert bad.status_code == 422
    good = client.post("/api/watchlists", json={"name": "Cortes", "query": "corte"})
    assert good.status_code == 200
    watch_id = good.json()["watchlist"]["id"]
    assert client.delete(f"/api/watchlists/{watch_id}").status_code == 200
    assert client.delete("/api/watchlists/wl:inexistente").status_code == 404


def test_api_case_flow_and_report(client):
    created = client.post("/api/cases", json={"title": "Caso API", "tlp": "GREEN"})
    case_id = created.json()["case"]["id"]
    added = client.post(f"/api/cases/{case_id}/items",
                        json={"kind": "event", "ref": "ev:1", "title": "Sismo"})
    assert added.status_code == 200
    assert client.get(f"/api/cases/{case_id}/verify").json()["ok"] is True
    report = client.get(f"/api/cases/{case_id}/report")
    assert report.status_code == 200
    assert "Cadena de custodia" in report.text
    assert client.get("/api/cases/case:inexistente").status_code == 404


def test_patrones_squawk_y_retraso(monkeypatch):
    from app.extras import patterns
    from app.live import AIRCRAFT, TRAINS

    patterns._seen.clear()
    monkeypatch.setattr(AIRCRAFT, "items", {
        "abc123": {"id": "abc123", "callsign": "TEST123", "squawk": "7700",
                   "lat": 40.0, "lon": -3.0, "altitude_ft": 30000, "speed_kn": 420},
    })
    monkeypatch.setattr(TRAINS, "items", {
        "t1": {"id": "t1", "name": "C-1", "delay_s": 2400, "lat": 40.4, "lon": -3.7},
    })

    alerts = patterns.scan([], None, None)
    titles = [a["title"] for a in alerts]
    assert any("Emergencia" in t for t in titles)
    assert any("Retraso de 40 min" in t for t in titles)
    assert all(a["event_type"] == "pattern" for a in alerts)

    # enfriamiento: el mismo patrón no vuelve a avisar en la siguiente pasada
    again = [a["title"] for a in patterns.scan([], None, None)]
    assert not any("Emergencia" in t for t in again)


def test_patrones_repunte_de_focos(monkeypatch):
    import math
    from app.extras import patterns

    patterns._seen.clear()
    now = datetime.now(timezone.utc)
    events = [
        _event(id=f"wf:{i}", category="wildfire", source="firms", lat=39.2, lon=-3.4,
               event_time=(now - timedelta(minutes=20)).isoformat())
        for i in range(15)
    ]
    alerts = patterns.scan(events, None, None)
    assert any(a["actor_type"] == "wildfire" for a in alerts)


def test_poll_entrega_avisos_de_patron(client):
    from app.livehub import HUB

    before = HUB.alert_seq
    HUB.push_alert({"ts": "2026-01-01T00:00:00+00:00", "title": "aviso de prueba",
                    "severity": "high", "event_type": "pattern"})
    data = client.get(f"/api/poll?since=0&as={before}&wait=0").json()
    assert data["alert_cursor"] > before
    assert any(a.get("title") == "aviso de prueba" for a in data["alerts"])

    # repetir la petición con el cursor nuevo no vuelve a entregar el aviso
    again = client.get(f"/api/poll?since=0&as={data['alert_cursor']}&wait=0").json()
    assert not any(a.get("title") == "aviso de prueba" for a in again["alerts"])


def test_api_transparencia_de_fuentes(client):
    response = client.get("/api/sources/transparency")
    assert response.status_code == 200
    payload = response.json()
    assert "sources" in payload and isinstance(payload["sources"], list)
    assert "method" in payload


def test_api_stix_and_graph_export(client):
    stix = client.get("/api/export/stix")
    assert stix.status_code == 200
    assert stix.json()["type"] == "bundle"
    graphml = client.get("/api/graph/export?fmt=graphml")
    assert graphml.status_code == 200
    assert b"<graphml" in graphml.content
