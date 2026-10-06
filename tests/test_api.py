"""API-Smoke-Tests: Rechenendpunkt, Fallback-Kette, Usage-Logging, Artefakte."""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def client(monkeypatch):
    """Frische App-Instanz mit eigenem Datenverzeichnis (keine Testkreuzung)."""
    tmp = tempfile.mkdtemp()
    # leerer Key: load_env() überspringt leere Werte → Demo-Modus, kein Netz nötig
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("SUSMOB_DATA_DIR", tmp)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SUSMOB_DEMO_ONLY", raising=False)

    import importlib

    from fastapi.testclient import TestClient

    from server import db

    db.init(Path(tmp) / "susmob.db")
    from server import main

    importlib.reload(main)
    assert main.DATA_DIR == Path(tmp)
    return TestClient(main.app)


def test_tiles_und_rechenkern(client):
    tiles = client.get("/api/tiles").json()
    assert len(tiles) == 7
    r = client.post("/api/calc/co2-bilanz", json={"params": {"gruppen": [
        {"bezeichnung": "Pkw Diesel", "anzahl": 25, "km_jahr": 28000, "verbrauch_je_100km": 6.8,
         "kraftstoff": "diesel"}]}})
    assert r.status_code == 200
    assert r.json()["summe_t_co2"] == 127.57


def test_schema_endpunkt(client):
    r = client.get("/api/tiles/co2-bilanz/schema")
    assert r.status_code == 200
    assert "gruppen" in r.json()["schema"]["properties"]
    assert r.json()["rechenkern"] is True


def test_fallback_kette_aus_seed(client):
    tiles = client.get("/api/admin/tiles").json()
    beschluss = next(t for t in tiles if t["id"] == "beschlussvorlagen")
    # Qwen hat keinen Endpunkt mehr → Default wurde migriert
    assert beschluss["model"] == "apodex/apodex-1.1-mini:free"
    assert beschluss["fallback_models"]
    for t in tiles:
        assert t["fallback_models"], f"Kachel {t['id']} hat keine Fallback-Kette"


def test_chat_ohne_key_antwortet_mit_hinweis_und_kein_usage_eintrag(client):
    cid = client.post("/api/conversations", json={"tile_id": "co2-bilanz"}).json()["id"]
    with client.stream("POST", f"/api/conversations/{cid}/chat", json={"message": "Test"}) as r:
        body = "".join(r.iter_text())
    assert "Kein OpenRouter-API-Key" in body
    assert "event: done" in body
    conv = client.get(f"/api/conversations/{cid}").json()
    assert conv["kosten"]["calls"] == 0


def test_beispiel_ist_schreibgeschuetzt_und_exportierbar(client):
    convs = client.get("/api/conversations?tile_id=co2-bilanz").json()
    beispiel = next(c for c in convs if c["is_example"])
    assert client.post(f"/api/conversations/{beispiel['id']}/chat", json={"message": "x"}).status_code == 403
    r = client.post(f"/api/conversations/{beispiel['id']}/export/xlsx")
    assert r.status_code == 200
    info = r.json()
    assert info["filename"].endswith(".xlsx")
    download = client.get(info["url"])
    assert download.status_code == 200
    assert len(download.content) > 5000
    artefakte = client.get(f"/api/conversations/{beispiel['id']}").json()["artifacts"]
    assert any(a["kind"] == "xlsx" for a in artefakte)


def test_pdf_export_verweist_auf_druckansicht(client):
    convs = client.get("/api/conversations?tile_id=co2-bilanz").json()
    cid = convs[0]["id"]
    r = client.post(f"/api/conversations/{cid}/export/pdf")
    assert r.status_code == 400
    assert "Druckansicht" in r.json()["detail"]


def test_usage_und_health_admin(client):
    usage = client.get("/api/admin/usage").json()
    assert "gesamt" in usage and "je_modell" in usage
    health = client.get("/api/admin/health").json()
    assert len(health["kacheln"]) == 7
    assert all(len(k["kette"]) >= 2 for k in health["kacheln"])
    audit = client.get("/api/admin/audit").json()
    assert isinstance(audit, list)


def test_admin_tile_update_setzt_fallback_kette(client):
    r = client.put("/api/admin/tiles/co2-bilanz", json={"fallback_models": ["a/b:free", "c/d:free"]})
    assert r.status_code == 200
    tiles = client.get("/api/admin/tiles").json()
    t = next(x for x in tiles if x["id"] == "co2-bilanz")
    assert t["fallback_models"] == '["a/b:free", "c/d:free"]'


def test_tagesbudget_bremst_den_testbetrieb(client, monkeypatch):
    """Öffentliche Test-Instanz: Budget erschöpft → klare 429-Meldung statt Kostenrisiko."""
    monkeypatch.setenv("SUSMOB_DAILY_REQUEST_BUDGET", "1")
    from server import limits
    limits.BREMSE.zuruecksetzen()
    cid = client.post("/api/conversations", json={"tile_id": "co2-bilanz"}).json()["id"]
    r1 = client.post(f"/api/conversations/{cid}/chat", json={"message": "Erster Aufruf"})
    assert r1.status_code == 200
    r2 = client.post(f"/api/conversations/{cid}/chat", json={"message": "Zweiter Aufruf"})
    assert r2.status_code == 429
    assert "Tagesbudget" in r2.json()["detail"]
    status = client.get("/api/status").json()
    assert status["limits"]["tagesbudget"] == 1
    assert status["rest_heute"] == 0
    limits.BREMSE.zuruecksetzen()
    monkeypatch.delenv("SUSMOB_DAILY_REQUEST_BUDGET")


def test_stundenlimit_pro_ip(client, monkeypatch):
    monkeypatch.setenv("SUSMOB_CHAT_LIMIT_PER_HOUR", "2")
    from server import limits
    limits.BREMSE.zuruecksetzen()
    cid = client.post("/api/conversations", json={"tile_id": "argumentation"}).json()["id"]
    codes = [client.post(f"/api/conversations/{cid}/chat", json={"message": f"Frage {i}"}).status_code
             for i in range(3)]
    assert codes == [200, 200, 429]
    limits.BREMSE.zuruecksetzen()
    monkeypatch.delenv("SUSMOB_CHAT_LIMIT_PER_HOUR")


def test_zu_lange_nachricht_wird_abgewiesen(client, monkeypatch):
    monkeypatch.setenv("SUSMOB_MAX_MESSAGE_CHARS", "50")
    from server import limits
    limits.BREMSE.zuruecksetzen()
    cid = client.post("/api/conversations", json={"tile_id": "argumentation"}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/chat", json={"message": "x" * 120})
    assert r.status_code == 413
    limits.BREMSE.zuruecksetzen()
    monkeypatch.delenv("SUSMOB_MAX_MESSAGE_CHARS")
