"""Rechenkern-Tests: Zahlen müssen reproduzierbar sein (Plan Phase 2)."""
from server import calc


def test_co2_bilanz_fuhrpark_beispiel():
    """Beispiel aus der Beispiel-Unterhaltung: 25 Diesel-Pkw, 4 E-Pkw, 3 Dieselbusse."""
    ergebnis = calc.co2_bilanz([
        {"bezeichnung": "Pkw Diesel", "anzahl": 25, "km_jahr": 28000, "verbrauch_je_100km": 6.8,
         "kraftstoff": "diesel"},
        {"bezeichnung": "Pkw Elektro", "anzahl": 4, "km_jahr": 22000, "verbrauch_je_100km": 18.0,
         "kraftstoff": "elektro"},
        {"bezeichnung": "Busse Diesel", "anzahl": 3, "km_jahr": 85000, "verbrauch_je_100km": 45.0,
         "kraftstoff": "diesel"},
    ])
    werte = {g["bezeichnung"]: g for g in ergebnis["gruppen"]}
    assert werte["Pkw Diesel"]["t_co2"] == 127.57          # 700.000 km × 6,8 l/100km × 2,68 kg/l
    assert werte["Busse Diesel"]["t_co2"] == 307.53        # 255.000 km × 45 l/100km × 2,68 kg/l
    assert werte["Pkw Elektro"]["t_co2"] == 5.89           # 88.000 km × 18 kWh/100km × 372 g/kWh
    assert ergebnis["summe_t_co2"] == 440.99
    assert round(sum(g["anteil_pct"] for g in ergebnis["gruppen"]), 1) == 100.0
    # Summe der Anteile und Sortierung nach Größe
    assert ergebnis["gruppen"][0]["bezeichnung"] == "Busse Diesel"


def test_co2_bilanz_faktoren_override_und_wtt():
    ohne = calc.co2_bilanz([{"bezeichnung": "Test", "anzahl": 1, "km_jahr": 10000,
                             "verbrauch_je_100km": 6.0, "kraftstoff": "diesel"}])
    mit = calc.co2_bilanz([{"bezeichnung": "Test", "anzahl": 1, "km_jahr": 10000,
                            "verbrauch_je_100km": 6.0, "kraftstoff": "diesel"}],
                          faktoren={"diesel": 1.0}, well_to_tank=True)
    assert mit["summe_t_co2"] < ohne["summe_t_co2"]          # Faktor 1,0 statt 2,68
    assert mit["summe_t_co2_vorkette"] > 0                    # Vorkette separat
    assert any("vorgegeben" in a for a in mit["annahmen"])


def test_co2_bilanz_toleranter_zahlenparser():
    e = calc.co2_bilanz([{"bezeichnung": "Bus", "anzahl": "3", "km_jahr": "85.000",
                          "verbrauch_je_100km": "45 l/100 km", "kraftstoff": "Diesel"}])
    assert e["summe_t_co2"] == 307.53


def test_co2_bilanz_meldet_datenluecken():
    e = calc.co2_bilanz([{"bezeichnung": "Ohne km", "anzahl": 2, "kraftstoff": "diesel"}])
    assert e["summe_t_co2"] == 0.0
    assert e["pruefungen"], "fehlende Fahrleistung muss als Prüfhinweis erscheinen"


def test_opnv_umlauf_landbus():
    e = calc.opnv_umlauf(laenge_km=12, geschwindigkeit_kmh=22, haltestellen=14, wendezeit_min=6,
                         takt_hvz_min=30, takt_nvz_min=60, fahrgaeste_tag=400, kapazitaet=49)
    # Fahrzeit 32,7 min + 14×1,5 min Haltezeit = 53,7 min je Richtung; Umlauf 119,4 min
    assert 115 < e["umlaufzeit_min"] < 125
    assert e["fahrzeuge_hvz"] == 4                      # ceil(119,4 / 30)
    assert e["fahrzeugbedarf_gesamt"] >= e["fahrzeuge_hvz"]
    assert e["kosten_jahr_min"] > 0 and e["kosten_jahr_max"] > e["kosten_jahr_min"]
    assert e["auslastung_pct"] is not None


def test_opnv_umlauf_warnung_bei_geringer_auslastung():
    e = calc.opnv_umlauf(laenge_km=25, geschwindigkeit_kmh=22, haltestellen=5, wendezeit_min=5,
                         takt_hvz_min=30, takt_nvz_min=60, fahrgaeste_tag=30, kapazitaet=49)
    assert any("Auslastung" in p for p in e["pruefungen"])


def test_tco_vergleich_reihenfolge_und_differenz():
    e = calc.tco_vergleich([
        {"name": "Dieselbus", "investition_eur": 250000, "energie_je_100km": 45, "energiepreis_je_einheit": 1.70,
         "wartung_eur_jahr": 9000, "fixkosten_eur_jahr": 2500},
        {"name": "E-Bus", "investition_eur": 430000, "energie_je_100km": 120, "energiepreis_je_einheit": 0.30,
         "wartung_eur_jahr": 6500, "fixkosten_eur_jahr": 1500},
    ], laufleistung_km_jahr=45000)
    assert len(e["varianten"]) == 2
    assert e["varianten"][0]["kosten_ueber_nutzungsdauer"] <= e["varianten"][1]["kosten_ueber_nutzungsdauer"]
    assert e["differenz_ueber_nutzungsdauer"] >= 0


def test_massnahmen_priorisierung_ranking():
    e = calc.massnahmen_priorisierung([
        {"name": "Fahrradstraße", "wirkung": 4, "sicherheit": 5, "kosten": 4, "aufwand": 4, "akzeptanz": 3},
        {"name": "Stadtbahn", "wirkung": 5, "sicherheit": 3, "kosten": 1, "aufwand": 1, "akzeptanz": 2},
    ])
    assert e["massnahmen"][0]["name"] == "Fahrradstraße"
    assert e["massnahmen"][0]["prioritaet"] == "hoch"
    assert e["massnahmen"][1]["prioritaet"] == "niedrig"
    assert round(sum(e["gewichte"].values()), 6) == 1.0


def test_kostenband_summiert_min_max():
    e = calc.kostenband([
        {"abschnitt": "A", "laenge_m": 1200, "kosten_min_eur_pro_m": 300, "kosten_max_eur_pro_m": 800},
        {"abschnitt": "B", "laenge_m": 1500, "kosten_min_eur_pro_m": 80, "kosten_max_eur_pro_m": 200},
    ])
    assert e["kosten_min_eur"] == 1200 * 300 + 1500 * 80
    assert e["kosten_max_eur"] == 1200 * 800 + 1500 * 200
    assert e["laenge_m"] == 2700


def test_rechnen_dispatcher():
    assert calc.rechnen("co2-bilanz", {"gruppen": []})["typ"] == "co2_bilanz"
    assert calc.rechnen("opnv-planung", {"laenge_km": 12, "geschwindigkeit_kmh": 22})["typ"] == "opnv_umlauf"
    assert calc.rechnen("wegeplanung", {"abschnitte": [{"laenge_m": 100}]})["typ"] == "kostenband"
    assert calc.rechnen("argumentation", {"irgendwas": 1})["typ"] == "kennzahlen"
