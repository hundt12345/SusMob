"""Eval-Harness testen – ohne Netz, mit Stub-Modellantworten."""
import asyncio
import tempfile
from pathlib import Path

from server import db, eval as eval_mod


def _db(tmp: str) -> None:
    db.init(Path(tmp) / "eval.db")
    db.exec("INSERT OR REPLACE INTO tiles (id, emoji, name, short, model, temperature, sort) "
            "VALUES ('co2-bilanz','🌍','CO₂-Bilanz','Test','m',0.2,1)")
    db.exec("INSERT INTO test_cases (tile_id, name, message, file_content, created_at) VALUES (?,?,?,?,?)",
            ("co2-bilanz", "Testfall A", "Rechne die Bilanz", "", "2026-01-01 00:00:00"))


GUTE_ANTWORT = """## 1) Datenbasis und Annahmen
- Annahme: Strommix 372 g CO₂/kWh (UBA) – von der Kommune zu bestätigen.

## 2) Bilanz je Verkehrsträger
| Verkehrsträger | t CO₂/a | Anteil % |
| --- | --- | --- |
| Busse Diesel | 307,5 | 69,7 |
| Pkw Diesel | 127,6 | 28,9 |

Summe: 441,0 t CO₂/a bei 255.000 km Fahrleistung.
""" + ("Fachliche Erläuterung. " * 30)


def test_bewerte_gute_antwort():
    punkte, maximum, checks = eval_mod.bewerte("co2-bilanz", GUTE_ANTWORT)
    assert maximum == 6
    assert punkte >= 5, checks
    namen = {c["name"]: c["ok"] for c in checks}
    assert namen["Annahmen benannt"] is True
    assert namen["Struktur (Überschrift/Tabelle)"] is True


def test_bewerte_schlechte_antwort():
    punkte, _, checks = eval_mod.bewerte("co2-bilanz", "Ja, das kann man machen.")
    assert punkte <= 2, checks


def test_quellenpflicht_bei_beschlussvorlagen():
    _, _, mit = eval_mod.bewerte("beschlussvorlagen", GUTE_ANTWORT)
    assert any(c["name"] == "Quellen-/Prüfhinweis" for c in mit)
    _, _, ohne = eval_mod.bewerte("co2-bilanz", GUTE_ANTWORT)
    assert any(c["name"] == "Keine Scheinpräzision (Fristen/Garantien)" for c in ohne)


def test_run_tile_schreibt_historie():
    tmp = tempfile.mkdtemp()
    _db(tmp)

    async def stub(testfall):
        return GUTE_ANTWORT, 0.0021, 1234

    ergebnis = asyncio.run(eval_mod.run_tile("co2-bilanz", stub, model="m", limit=1))
    assert ergebnis["quote_pct"] >= 83.0
    assert ergebnis["ziel_erreicht"] is True
    assert ergebnis["kosten_usd"] > 0
    zeilen = db.query("SELECT tile_id, score, max_score FROM eval_runs")
    assert len(zeilen) == 1 and zeilen[0]["score"] == ergebnis["testfaelle"][0]["score"]


def test_run_tile_faengt_fehler_ab():
    tmp = tempfile.mkdtemp()
    _db(tmp)

    async def stub(testfall):
        raise RuntimeError("Modell nicht erreichbar")

    ergebnis = asyncio.run(eval_mod.run_tile("co2-bilanz", stub, model="m", limit=1))
    assert ergebnis["punkte"] == 0
    assert ergebnis["testfaelle"][0]["ok"] is False
    assert "Modell nicht erreichbar" in ergebnis["testfaelle"][0]["error"]
