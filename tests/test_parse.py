"""Parser-Tests: aus Antworttexten müssen reproduzierbare Zahlen kommen (ohne LLM)."""
from server import parse

CO2_ANTWORT = """## 2) Bilanz je Verkehrsträger

| Verkehrsträger | Aktivitäten | Emissionsfaktor | t CO₂/a | Anteil % |
| --- | --- | --- | --- | --- |
| Pkw Diesel (25) | 700.000 km, 47.600 l | 2,68 kg/l | 127,6 | 28,9 |
| Pkw Elektro (4) | 88.000 km, 15.840 kWh | 372 g/kWh | 5,9 | 1,3 |
| Busse Diesel (3) | 255.000 km, 114.750 l | 2,68 kg/l | 307,5 | 69,7 |
| **Summe** | | | **441,0** | **100,0** |
"""

MASSNAHMEN_ANTWORT = """| Maßnahme | Wirkung | Kosten (Band) | Aufwand | Priorität |
| --- | --- | --- | --- | --- |
| Geschützte Radwege | hoch | 1,5–4,0 M€ | 3–10 Jahre | hoch |
| Radabstellanlagen | mittel | 18–90 k€ | 1 Jahr | mittel |
| P+R an zwei Lagen | niedrig | 400–1.200 k€ | 3–10 Jahre | niedrig |
"""

WEGE_ANTWORT = """| Abschnitt | Länge | Trennungsform | Kosten (Band) | Hinweis |
| --- | --- | --- | --- | --- |
| A (3.500 Kfz/d) | 1.200 m | Radfahrstreifen | 96–240 k€ | Parkstreifen entfällt |
| B (Ortsrand) | 1.500 m | Getrennter Radweg | 450–1.200 k€ | Böschung nördlich |
"""


def test_co2_aus_antwort():
    e = parse.co2_aus_antwort(CO2_ANTWORT)
    assert e["typ"] == "co2_bilanz"
    assert e["summe_t_co2"] == 441.0
    namen = [g["bezeichnung"] for g in e["gruppen"]]
    assert "Summe" not in " ".join(namen)
    assert e["gruppen"][0]["bezeichnung"].startswith("Busse")     # nach t CO₂ sortiert
    assert e["quelle"] == "antworttext"
    assert "Rechenkern" in e["pruefungen"][0]


def test_massnahmen_aus_antwort_sortiert_nach_prioritaet():
    e = parse.massnahmen_aus_antwort(MASSNAHMEN_ANTWORT)
    # Reihenfolge folgt der Priorität aus dem Antworttext
    assert [m["prioritaet_aus_antwort"] for m in e["massnahmen"]] == ["hoch", "mittel", "niedrig"]
    assert e["massnahmen"][0]["kosten_band"] == "1,5–4,0 M€"
    assert e["massnahmen"][0]["zeitrahmen"] == "3–10 Jahre"
    # Score wird im Rechenkern nachgerechnet und liegt im gültigen Bereich
    assert all(1.0 <= m["score"] <= 5.0 for m in e["massnahmen"])
    assert e["massnahmen"][0]["werte"]["wirkung"] == 4.5      # "hoch" → Stufe 4,5
    assert e["quelle"] == "antworttext"


def test_stufen_und_kosten_mapping():
    assert parse._stufe("hoch") == 4.5
    assert parse._stufe("mittel–hoch") == 3.5
    assert parse._stufe("–") is None
    assert parse._kosten_stufe("18–90 k€") == 5.0             # günstig
    assert parse._kosten_stufe("1,5–4,0 M€") == 2.0            # Bandmitte 2,75 M€
    assert parse._aufwand_stufe("unter 1 Jahr") == 5.0
    assert parse._aufwand_stufe("3–10 Jahre") == 1.5


def test_kostenband_aus_antwort_rechnet_summen():
    e = parse.kostenband_aus_antwort(WEGE_ANTWORT)
    assert e["typ"] == "kostenband"
    assert e["kosten_min_eur"] == 96_000 + 450_000
    assert e["kosten_max_eur"] == 240_000 + 1_200_000
    assert e["abschnitte"][0]["laenge_m"] == 1200.0


def test_kennzahlen_aus_antwort_erst_ab_drei_werten():
    text = "- Umlaufzeit: 118 min\n- Fahrzeugbedarf: 4 Fahrzeuge\n- Fahrten/Tag: 62\n- Auslastung: 18 %"
    e = parse.kennzahlen_aus_antwort(text)
    assert e and len(e["werte"]) >= 3
    assert parse.kennzahlen_aus_antwort("- nur ein Wert: 5") is None


def test_parse_dispatcher():
    assert parse.parse("co2-bilanz", CO2_ANTWORT)["typ"] == "co2_bilanz"
    assert parse.parse("massnahmenplanung", MASSNAHMEN_ANTWORT)["typ"] == "massnahmen_priorisierung"
    assert parse.parse("wegeplanung", WEGE_ANTWORT)["typ"] == "kostenband"
    assert parse.parse("argumentation", "") is None


def test_geld_parst_einheiten():
    assert parse._geld("96–240 k€") == [96_000.0, 240_000.0]
    assert parse._geld("1,5–4,0 M€") == [1_500_000.0, 4_000_000.0]
    assert parse._geld("") == []
