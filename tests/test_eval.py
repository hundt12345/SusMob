"""Tests des Eval-Harness (Phase 2): erfundene Zahlen müssen auffallen."""
from server import eval as ev


def test_erfundene_zahl_wird_erkannt():
    antwort = ("## Bilanz\n\n| Verkehrsträger | t CO₂/a |\n|---|---|\n| Pkw | 47123 |\n\n"
               "**Annahmen:** Faktor 2.680 g CO₂/l. Die Zahl 47123 stammt aus keiner Quelle.")
    b = ev.bewerte("co2-bilanz", antwort, kontext="Diesel 2.680 g/l, 12.000 Pkw")
    assert 47123.0 in b["unbelegte_zahlen"]
    assert b["checks"]["keine_erfundenen_zahlen"]["ok"] is False
    assert b["score"] < 100


def test_belegte_zahlen_ergeben_hohen_score():
    kontext = "Fahrleistung 700000 km, Verbrauch 47600 l, Summe 127.6 t, Faktor 2680 g/l"
    antwort = (
        "## Datenbasis & Annahmen\n- Annahme: Diesel 2.680 g CO₂/l (Vorgabe der Kommune).\n"
        "## Bilanz\n\n| Verkehrsträger | Fahrleistung [km/a] | Energie [l] | t CO₂/a |\n|---|---|---|---|\n"
        "| Pkw Diesel | 700.000 | 47.600 | 127,60 |\n\n"
        "**Summe: 127,6 t CO₂/a**\n\n## Einsparpotenziale\n- Annahme: Umstellung spart 0 t.\n"
        "## Nächste Schritte\n- Quelle prüfen.\n" + "Text " * 40)
    b = ev.bewerte("co2-bilanz", antwort, kontext)
    assert b["checks"]["keine_erfundenen_zahlen"]["ok"] is True
    assert b["checks"]["format"]["ok"] is True
    assert b["score"] >= 70


def test_annahmen_und_quellenhinweis_werden_geprueft():
    ohne = ev.bewerte("beschlussvorlagen", "# Beschlussvorlage\nBetreff: X\nSachstand: Y", "")
    assert ohne["checks"]["annahmen_markiert"]["ok"] is False
    mit = ev.bewerte(
        "beschlussvorlagen",
        "## Betreff\nA\n## Sachstand\nAngabe der Kommune, Annahme: Kosten 1000 €.\n"
        "## Beschlussvorschlag\nes wird beschlossen.\n## Finanzplan\n| a |\n|---|\n| 1 |\n"
        "## Anlagenverzeichnis\n- Anlage 1\nStand: heute, Konditionen vor Antragstellung prüfen.",
        "Kosten 1000 €",
    )
    assert mit["checks"]["quellenhinweis"]["ok"] is True
    assert mit["checks"]["vollstaendigkeit"]["ok"] is True


def test_jahreszahlen_zaehlen_nicht_als_erfundene_zahlen():
    b = ev.bewerte("klimaschutzkonzept", "Zieljahr 2040, Basisjahr 1990, Bilanz 2024.", "")
    assert b["unbelegte_zahlen"] == []
