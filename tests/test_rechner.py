"""Tests der Rechenkerne – Zahlen müssen ohne LLM reproduzierbar sein (Plan 4.5)."""
from server import rechner


def test_num_parst_deutsches_format():
    assert rechner.num("1.234,5") == 1234.5
    assert rechner.num("45 l/100 km") == 45
    assert rechner.num("") == 0
    assert rechner.num(None, 7) == 7
    assert rechner.num("0,35") == 0.35


def test_co2_bilanz_rechnet_formel_korrekt():
    r = rechner.co2_bilanz({
        "pkw_diesel": "10", "pkw_diesel_km": "20000", "pkw_diesel_l": "7",
        "pkw_benzin": "0", "pkw_benzin_km": "0", "pkw_benzin_l": "0",
        "pkw_e": "0", "pkw_e_km": "0", "pkw_e_kwh": "0",
        "bus_diesel": "0", "bus_diesel_km": "0", "bus_diesel_l": "0",
        "bus_e": "0", "bus_e_km": "0", "bus_e_kwh": "0",
        "strommix": "372", "diesel_faktor": "2680", "benzin_faktor": "2380",
    })
    # 10 Pkw × 20.000 km = 200.000 km; 7 l/100 km → 14.000 l; × 2,68 kg/l = 37.520 kg
    assert r["bilanz"][0]["fahrleistung_km_jahr"] == 200000
    assert r["bilanz"][0]["energieverbrauch"] == 14000
    assert r["bilanz"][0]["co2_t_jahr"] == 37.52
    assert r["summe_t_co2_jahr"] == 37.52
    assert r["bilanz"][0]["anteil_prozent"] == 100.0


def test_co2_bilanz_elektro_nutzt_strommix():
    r = rechner.co2_bilanz({
        "pkw_diesel": "0", "pkw_diesel_km": "0", "pkw_diesel_l": "0",
        "pkw_benzin": "0", "pkw_benzin_km": "0", "pkw_benzin_l": "0",
        "pkw_e": "1", "pkw_e_km": "10000", "pkw_e_kwh": "20",
        "bus_diesel": "0", "bus_diesel_km": "0", "bus_diesel_l": "0",
        "bus_e": "0", "bus_e_km": "0", "bus_e_kwh": "0",
        "strommix": "400", "diesel_faktor": "2680", "benzin_faktor": "2380",
    })
    # 10.000 km × 20 kWh/100 km = 2.000 kWh × 400 g/kWh = 800 kg = 0,8 t
    assert r["summe_t_co2_jahr"] == 0.8
    assert "annahmen" in r and r["rechenweg"]


def test_opnv_umlauf_fahrzeugbedarf():
    r = rechner.opnv_umlauf({
        "laenge_km": "12", "geschwindigkeit_kmh": "24", "takt_min": "30", "wendezeit_min": "10",
        "betriebsstunden_tag": "18", "betriebstage_jahr": "300", "fahrgast_km": "400",
        "kosten_km": "3", "bus_e_kwh_km": "1,3", "diesel_l_100km": "45", "strommix": "372",
    })
    # Fahrzeit = 12/24*60 = 30 min; Umlauf = 2*30 + 2*10 = 80 min; 80/30 → 3 Fahrzeuge
    assert r["fahrzeit_min"] == 30.0
    assert r["umlaufzeit_min"] == 80.0
    assert r["fahrzeuge_je_takt"] == 3
    assert r["fahrten_je_tag"] == 36.0
    assert r["fahrleistung_km_jahr"] == 36 * 2 * 12 * 300  # 259.200 km
    assert r["betriebskosten_eur_jahr"] == 259200 * 3
    # Taktstufen enthalten den Ziel-Takt und Varianten
    takte = [t["takt_min"] for t in r["taktstufen"]]
    assert 30.0 in takte


def test_tco_vergleich_foerderung_und_breakeven():
    r = rechner.tco_vergleich({})
    diesel, e = r["varianten"]
    assert diesel["variante"] == "Dieselbus" and e["variante"] == "E-Bus"
    assert e["foerderung_eur"] > 0
    assert r["km_gesamt"] == 60000 * 10
    assert r["co2_vergleich"]["einsparung_t"] > 0
    # Nur bei Mehrinvestition und jährlichem Vorteil gibt es einen Break-even
    if e["tco_gesamt_eur"] > diesel["tco_gesamt_eur"]:
        assert r["breakeven_jahr"] is None or r["breakeven_jahr"] > 0
    else:
        assert r["guenstiger"] == "E-Bus"


def test_wege_kostenband_rechnet_anteile():
    r = rechner.wege_kostenband({
        "laenge_m": "1000", "anteil_getrennt": "50",
        "kosten_getrennt_min": "300", "kosten_getrennt_max": "800",
        "kosten_markiert_min": "30", "kosten_markiert_max": "200", "budget": "1000",
    })
    # 500 m × 300–800 € + 500 m × 30–200 € = 165.000–500.000 €
    assert r["kosten_min_eur"] == 165000
    assert r["kosten_max_eur"] == 500000
    assert r["budget_luecke_max_eur"] == 0  # Budget 1.000 k€ deckt 500 k€
    assert r["budget_deckung_prozent_mittel"] > 0


def test_unfall_csv_ranking_und_kategorien():
    rows = rechner.parse_unfall_csv(
        "ort;schwere;art;anzahl;verletzte\n"
        "Hauptstraße;schwer;Fußgänger;2;2\n"
        "Hauptstraße;leicht;Rad;3;0\n"
        "Kreuzung;leicht;Rad;1;0\n"
    )
    assert len(rows) == 3
    r = rechner.schulweg_ranking({"unfaelle_csv": (
        "ort;schwere;art;anzahl;verletzte\n"
        "Hauptstraße;schwer;Fußgänger;2;2\n"
        "Hauptstraße;leicht;Rad;3;0\n"
        "Kreuzung;leicht;Rad;1;0\n"
    ), "gewerte": "5", "schwellenwert": "6"})
    assert r["anzahl_stellen"] == 2
    assert r["ranking"][0]["ort"] == "Hauptstraße"
    # Punkte = 2×5 + 2×2 (schwer) + 3×1 = 17
    assert r["ranking"][0]["punkte"] == 17.0
    assert r["ranking"][0]["kategorie"] == "Gefahrenstelle (vordringlich)"
    assert r["ranking"][1]["kategorie"] == "Beobachtung"


def test_ladeinfrastruktur_waechst_mit_zielquote():
    r = rechner.ladeinfrastruktur({})
    assert r["zielbild"]["ladepunkte_gesamt"] > r["heute"]["ladepunkte_gesamt"]
    assert r["zielbild"]["leistungsbedarf_kw"] > 0
    assert len(r["ausbaustufen"]) == 3


def test_parkraum_wirtschaftlichkeit():
    r = rechner.parkraum({})
    assert r["einnahmen_jahr_eur"] == 300 * 620
    assert r["ueberschuss_jahr_eur"] == r["einnahmen_jahr_eur"] - r["kosten_jahr_eur"]
    assert r["vergleich_ohne_bewirtschaftung"]["einnahmen_jahr_eur"] == 0


def test_registry_deckt_kacheln_ab():
    for tid in ("co2-bilanz", "opnv-planung", "wegeplanung", "verkehrssicherheit",
                "ladeinfrastruktur", "parkraum", "beschlussvorlagen", "argumentation"):
        assert rechner.has_rechner(tid)
        res = rechner.compute(tid, {})
        assert res["rechner"]
        assert res["eingaben"], "Defaults müssen vorbelegt sein"


def test_kontext_block_enthaelt_zahlen_und_hinweis():
    block = rechner.kontext_block("co2-bilanz", {})
    assert "Vorberechnete Werte" in block
    assert "verbindlich" in block
