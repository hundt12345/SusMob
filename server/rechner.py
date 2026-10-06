"""Rechenkerne in reinem Python – „Rechnen im Code, formulieren im LLM" (Plan 4.5/Phase 2).

Jede Zahl, die in einem Ergebnisdokument landet, entsteht hier deterministisch,
mit nachvollziehbarem Rechenweg und benannten Annahmen. Das LLM bekommt die
fertigen Zahlen als Kontext und formuliert nur noch.

Alle Funktionen sind ohne Netz und ohne LLM testbar (siehe ``tests/test_rechner.py``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# ------------------------------------------------------------------ Hilfsfunktionen


def num(value, default: float = 0.0) -> float:
    """Robuste Zahlenerkennung: deutsches Komma, Tausenderpunkte, Einheiten, leer."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("€", "").replace("%", "")
    s = s.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    # führende Zahl aus Strings wie "45 l/100 km" oder "300–800" ziehen
    out, seen = "", False
    for ch in s:
        if ch.isdigit() or (ch == "." and out and not out.endswith(".")) or (ch == "-" and not out):
            out += ch
        elif ch in ("e", "E") and seen:
            out += ch
        else:
            if out and not seen:
                break
    try:
        return float(out) if out not in ("", "-", ".") else default
    except ValueError:
        return default


def fnum(value: float, dec: int = 1) -> str:
    """Zahl im deutschen Format (Tausenderpunkt, Komma)."""
    s = f"{value:,.{dec}f}"
    return s.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


@dataclass
class Feld:
    key: str
    label: str
    unit: str = ""
    default: str = ""
    typ: str = "number"  # number | text | csv
    hint: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "unit": self.unit,
                "default": self.default, "typ": self.typ, "hint": self.hint}


@dataclass
class Rechner:
    tile_id: str
    name: str
    beschreibung: str
    felder: list[Feld]
    fn: Callable[[dict], dict]
    annahmen: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ CO₂-Bilanz

CO2_FELDER = [
    Feld("pkw_diesel", "Pkw Diesel – Anzahl", "Stück", "25"),
    Feld("pkw_diesel_km", "Pkw Diesel – km je Fahrzeug und Jahr", "km", "28000"),
    Feld("pkw_diesel_l", "Pkw Diesel – Verbrauch", "l/100 km", "6,8"),
    Feld("pkw_benzin", "Pkw Benzin – Anzahl", "Stück", "0"),
    Feld("pkw_benzin_km", "Pkw Benzin – km je Fahrzeug und Jahr", "km", "15000"),
    Feld("pkw_benzin_l", "Pkw Benzin – Verbrauch", "l/100 km", "7,5"),
    Feld("pkw_e", "Pkw Elektro – Anzahl", "Stück", "4"),
    Feld("pkw_e_km", "Pkw Elektro – km je Fahrzeug und Jahr", "km", "22000"),
    Feld("pkw_e_kwh", "Pkw Elektro – Verbrauch", "kWh/100 km", "18"),
    Feld("bus_diesel", "Busse Diesel – Anzahl", "Stück", "3"),
    Feld("bus_diesel_km", "Bus Diesel – km je Fahrzeug und Jahr", "km", "85000"),
    Feld("bus_diesel_l", "Bus Diesel – Verbrauch", "l/100 km", "45"),
    Feld("bus_e", "Busse Elektro – Anzahl", "Stück", "0"),
    Feld("bus_e_km", "Bus Elektro – km je Fahrzeug und Jahr", "km", "60000"),
    Feld("bus_e_kwh", "Bus Elektro – Verbrauch", "kWh/km", "1,3"),
    Feld("strommix", "Strommix-Faktor", "g CO₂/kWh", "372"),
    Feld("diesel_faktor", "Emissionsfaktor Diesel", "g CO₂/l", "2680"),
    Feld("benzin_faktor", "Emissionsfaktor Benzin", "g CO₂/l", "2380"),
]


def co2_bilanz(v: dict) -> dict:
    """Emissionsbilanz eines kommunalen Fuhrparks – jede Zeile mit Rechenweg."""
    strommix = num(v.get("strommix"), 372)
    diesel_f = num(v.get("diesel_faktor"), 2680)
    benzin_f = num(v.get("benzin_faktor"), 2380)

    def pkw_diesel(vv):
        km = num(vv["pkw_diesel"]) * num(vv["pkw_diesel_km"])
        liter = km / 100 * num(vv["pkw_diesel_l"])
        kg = liter * diesel_f / 1000
        return km, liter, kg

    def pkw_benzin(vv):
        km = num(vv["pkw_benzin"]) * num(vv["pkw_benzin_km"])
        liter = km / 100 * num(vv["pkw_benzin_l"])
        kg = liter * benzin_f / 1000
        return km, liter, kg

    def pkw_e(vv):
        km = num(vv["pkw_e"]) * num(vv["pkw_e_km"])
        kwh = km / 100 * num(vv["pkw_e_kwh"])
        kg = kwh * strommix / 1000
        return km, kwh, kg

    def bus_diesel(vv):
        km = num(vv["bus_diesel"]) * num(vv["bus_diesel_km"])
        liter = km / 100 * num(vv["bus_diesel_l"])
        kg = liter * diesel_f / 1000
        return km, liter, kg

    def bus_e(vv):
        km = num(vv["bus_e"]) * num(vv["bus_e_km"])
        kwh = km * num(vv["bus_e_kwh"])
        kg = kwh * strommix / 1000
        return km, kwh, kg

    zeilen = []
    for name, energie, einheit, fn in (
        ("Pkw Diesel", "Liter", "l", pkw_diesel),
        ("Pkw Benzin", "Liter", "l", pkw_benzin),
        ("Pkw Elektro", "Strom", "kWh", pkw_e),
        ("Bus Diesel", "Liter", "l", bus_diesel),
        ("Bus Elektro", "Strom", "kWh", bus_e),
    ):
        km, verbrauch, kg = fn(v)
        if km <= 0:
            continue
        zeilen.append({
            "verkehrstraeger": name,
            "fahrleistung_km_jahr": round(km, 0),
            "energieverbrauch": round(verbrauch, 0),
            "energie_einheit": einheit,
            "co2_kg_jahr": round(kg, 0),
            "co2_t_jahr": round(kg / 1000, 2),
        })
    sum_kg = sum(z["co2_kg_jahr"] for z in zeilen) or 1.0
    for z in zeilen:
        z["anteil_prozent"] = round(100 * z["co2_kg_jahr"] / sum_kg, 1)

    # Einsparpotenziale deterministisch rechnen
    swap_km = num(v.get("bus_diesel")) * num(v.get("bus_diesel_km"))
    einsparung_bus = swap_km / 100 * num(v.get("bus_diesel_l")) * diesel_f / 1000 / 1000
    einsparung_bus -= swap_km * num(v.get("bus_e_kwh"), 1.3) * strommix / 1000 / 1000
    pkw_diesel_km_total = num(v["pkw_diesel"]) * num(v["pkw_diesel_km"])
    einsparung_pkw = pkw_diesel_km_total / 100 * num(v["pkw_diesel_l"]) * diesel_f / 1000 / 1000
    einsparung_pkw -= pkw_diesel_km_total / 100 * num(v.get("pkw_e_kwh"), 18) * strommix / 1000 / 1000

    return {
        "titel": "CO₂-Bilanz Fuhrpark",
        "summe_t_co2_jahr": round(sum(z["co2_t_jahr"] for z in zeilen), 2),
        "summe_km_jahr": round(sum(z["fahrleistung_km_jahr"] for z in zeilen), 0),
        "bilanz": zeilen,
        "einsparpotenziale": [
            {"massnahme": "Diesel-Busse → E-Busse", "einsparung_t_co2_jahr": round(max(0.0, einsparung_bus), 2),
             "annahme": f"gleiche Fahrleistung, {fnum(num(v.get('bus_e_kwh'), 1.3), 2)} kWh/km, Strommix {fnum(strommix, 0)} g/kWh"},
            {"massnahme": "Diesel-Pkw → E-Pkw", "einsparung_t_co2_jahr": round(max(0.0, einsparung_pkw), 2),
             "annahme": f"gleiche Fahrleistung, {fnum(num(v.get('pkw_e_kwh'), 18), 1)} kWh/100 km, Strommix {fnum(strommix, 0)} g/kWh"},
        ],
        "annahmen": [
            f"Diesel {fnum(diesel_f, 0)} g CO₂/l, Benzin {fnum(benzin_f, 0)} g CO₂/l (Verbrennung, ohne Vorkette)",
            f"Strommix {fnum(strommix, 0)} g CO₂/kWh",
            "Fahrleistungen und Verbräuche sind Angaben der Kommune, keine Messwerte",
            "Emissionen des Stroms werden voll dem Verbraucher zugerechnet (kein Vorketten-Abschlag)",
        ],
        "rechenweg": [
            "Emission [kg CO₂] = Fahrleistung [km] ÷ 100 × Verbrauch [l/100 km bzw. kWh/100 km] × Faktor [g/kWh bzw. g/l] ÷ 1000",
            f"Summe Fuhrpark: {fnum(sum_kg / 1000, 2)} t CO₂/a über {fnum(sum(z['fahrleistung_km_jahr'] for z in zeilen), 0)} km/a",
        ],
        "tabellen": {"bilanz": ["verkehrstraeger", "fahrleistung_km_jahr", "energieverbrauch", "energie_einheit",
                                "co2_t_jahr", "anteil_prozent"]},
    }


# ------------------------------------------------------------------ ÖPNV-Umlauf

OPNV_FELDER = [
    Feld("laenge_km", "Streckenlänge je Richtung", "km", "12"),
    Feld("geschwindigkeit_kmh", "Reisegeschwindigkeit", "km/h", "22"),
    Feld("takt_min", "Ziel-Takt", "min", "30"),
    Feld("wendezeit_min", "Wendezeit an den Enden", "min", "10"),
    Feld("betriebsstunden_tag", "Betriebsstunden je Tag", "h", "18"),
    Feld("betriebstage_jahr", "Betriebstage je Jahr", "Tage", "300"),
    Feld("fahrgast_km", "Fahrgäste je Tag (Hin- und Rückrichtung)", "Fahrgäste", "400"),
    Feld("kosten_km", "Kostensatz Betrieb", "€/km", "3,10"),
    Feld("bus_e_kwh_km", "Bus Elektro – Verbrauch", "kWh/km", "1,3"),
    Feld("diesel_l_100km", "Bus Diesel – Verbrauch", "l/100 km", "45"),
    Feld("strommix", "Strommix-Faktor", "g CO₂/kWh", "372"),
]


def opnv_umlauf(v: dict) -> dict:
    laenge = num(v.get("laenge_km"), 12)
    v_kmh = num(v.get("geschwindigkeit_kmh"), 22)
    takt = num(v.get("takt_min"), 30) or 30
    wende = num(v.get("wendezeit_min"), 10)
    std_tag = num(v.get("betriebsstunden_tag"), 18)
    tage = num(v.get("betriebstage_jahr"), 300)
    fahrgaeste = num(v.get("fahrgast_km"), 400)
    kosten_km = num(v.get("kosten_km"), 3.10)

    fahrzeit = laenge / v_kmh * 60 if v_kmh else 0.0
    umlauf = 2 * fahrzeit + 2 * wende
    fahrzeuge = max(1, int(umlauf / takt) + (1 if umlauf % takt else 0))
    fahrten_pro_tag = std_tag * 60 / takt
    km_jahr = fahrten_pro_tag * 2 * laenge * tage
    betriebskosten = km_jahr * kosten_km
    fahrer_je_tag = fahrzeuge * max(1.0, std_tag / 8.0)
    kosten_je_fahrgast = betriebskosten / (fahrgaeste * tage) if fahrgaeste * tage else 0.0
    diesel_l = km_jahr / 100 * num(v.get("diesel_l_100km"), 45)
    co2_diesel_t = diesel_l * 2680 / 1_000_000
    co2_e_t = km_jahr * num(v.get("bus_e_kwh_km"), 1.3) * num(v.get("strommix"), 372) / 1_000_000
    takt_stufen = []
    for t in sorted({takt, max(10.0, takt / 2), min(120.0, takt * 2)}):
        n = max(1, int(umlauf / t) + (1 if umlauf % t else 0))
        takt_stufen.append({
            "takt_min": round(t, 0),
            "fahrzeuge": n,
            "fahrten_tag": round(std_tag * 60 / t, 1),
            "km_jahr": round(std_tag * 60 / t * 2 * laenge * tage, 0),
            "kosten_jahr_eur": round(std_tag * 60 / t * 2 * laenge * tage * kosten_km, 0),
        })
    return {
        "titel": "ÖPNV-Umlauf- und Taktberechnung",
        "fahrzeit_min": round(fahrzeit, 1),
        "umlaufzeit_min": round(umlauf, 1),
        "fahrzeuge_je_takt": fahrzeuge,
        "fahrten_je_tag": round(fahrten_pro_tag, 1),
        "fahrleistung_km_jahr": round(km_jahr, 0),
        "betriebskosten_eur_jahr": round(betriebskosten, 0),
        "fahrer_je_tag": round(fahrer_je_tag, 1),
        "kosten_je_fahrgast_eur": round(kosten_je_fahrgast, 2),
        "co2_diesel_t_jahr": round(co2_diesel_t, 1),
        "co2_elektro_t_jahr": round(co2_e_t, 1),
        "taktstufen": takt_stufen,
        "annahmen": [
            f"Reisegeschwindigkeit {fnum(v_kmh, 0)} km/h inkl. Haltestellenzeit, Wendezeit {fnum(wende, 0)} min je Ende",
            f"Betrieb {fnum(std_tag, 0)} h/Tag an {fnum(tage, 0)} Tagen, Kostensatz {fnum(kosten_km, 2)} €/km",
            f"Fahrgäste {fnum(fahrgaeste, 0)}/Tag als Annahme der Kommune (keine Messung)",
            "Emissionsvergleich Diesel 2.680 g CO₂/l gegen Strommix",
        ],
        "rechenweg": [
            "Umlaufzeit [min] = 2 × Strecke ÷ Geschwindigkeit × 60 + 2 × Wendezeit",
            f"Umlaufzeit = 2 × {fnum(laenge, 1)} km ÷ {fnum(v_kmh, 0)} km/h × 60 + 2 × {fnum(wende, 0)} min = {fnum(umlauf, 1)} min",
            f"Fahrzeugbedarf = aufgerundet(Umlaufzeit ÷ Takt) = aufgerundet({fnum(umlauf, 1)} ÷ {fnum(takt, 0)}) = {fahrzeuge}",
            f"Fahrleistung = Fahrten/Tag × 2 × Strecke × Betriebstage = {fnum(km_jahr, 0)} km/a",
        ],
        "tabellen": {"taktstufen": ["takt_min", "fahrzeuge", "fahrten_tag", "km_jahr", "kosten_jahr_eur"]},
    }


# ------------------------------------------------------------------ TCO / Kostenbänder

TCO_FELDER = [
    Feld("bus_diesel_preis", "Preis Dieselbus", "€", "300000"),
    Feld("bus_e_preis", "Preis E-Bus", "€", "450000"),
    Feld("foerderung_e", "Fördersatz E-Bus", "%", "40"),
    Feld("ladepunkt_preis", "Ladeinfrastruktur je E-Bus", "€", "60000"),
    Feld("jahre", "Betrachtungszeitraum", "Jahre", "10"),
    Feld("km_jahr", "Fahrleistung je Fahrzeug und Jahr", "km", "60000"),
    Feld("diesel_l_100km", "Dieselverbrauch", "l/100 km", "45"),
    Feld("diesel_preis_l", "Dieselpreis", "€/l", "1,75"),
    Feld("strom_kwh_100km", "Stromverbrauch", "kWh/100 km", "130"),
    Feld("strom_preis_kwh", "Strompreis", "€/kWh", "0,35"),
    Feld("wartung_diesel", "Wartung Diesel", "ct/km", "28"),
    Feld("wartung_e", "Wartung Elektro", "ct/km", "16"),
    Feld("restwert_diesel", "Restwert Diesel nach Laufzeit", "%", "15"),
    Feld("restwert_e", "Restwert Elektro nach Laufzeit", "%", "20"),
]


def tco_vergleich(v: dict) -> dict:
    jahre = num(v.get("jahre"), 10) or 10
    km = num(v.get("km_jahr"), 60000)
    km_gesamt = km * jahre

    def variante(bez: str, preis: float, foerder: float, ladeinfra: float, energie_je_km: float,
                 wartung_ct: float, restwert_p: float) -> dict:
        invest = preis + ladeinfra
        zuschuss = min(invest, invest * foerder / 100)
        energie = km_gesamt * energie_je_km
        wartung = km_gesamt * wartung_ct / 100
        restwert = preis * restwert_p / 100
        total = invest - zuschuss + energie + wartung - restwert
        return {
            "variante": bez,
            "anschaffung_eur": round(preis, 0),
            "ladeinfrastruktur_eur": round(ladeinfra, 0),
            "foerderung_eur": round(zuschuss, 0),
            "energiekosten_eur": round(energie, 0),
            "wartung_eur": round(wartung, 0),
            "restwert_eur": round(restwert, 0),
            "tco_gesamt_eur": round(total, 0),
            "tco_je_km_eur": round(total / km_gesamt, 3) if km_gesamt else 0.0,
            "tco_je_jahr_eur": round(total / jahre, 0) if jahre else 0.0,
        }

    diesel = variante(
        "Dieselbus", num(v.get("bus_diesel_preis"), 300000), 0, 0,
        num(v.get("diesel_l_100km"), 45) / 100 * num(v.get("diesel_preis_l"), 1.75),
        num(v.get("wartung_diesel"), 28), num(v.get("restwert_diesel"), 15),
    )
    elektro = variante(
        "E-Bus", num(v.get("bus_e_preis"), 450000), num(v.get("foerderung_e"), 40),
        num(v.get("ladepunkt_preis"), 60000),
        num(v.get("strom_kwh_100km"), 130) / 100 * num(v.get("strom_preis_kwh"), 0.35),
        num(v.get("wartung_e"), 16), num(v.get("restwert_e"), 20),
    )
    differenz = elektro["tco_gesamt_eur"] - diesel["tco_gesamt_eur"]
    # Break-even: ab welchem Jahr ist der E-Bus kumuliert günstiger?
    breakeven = None
    if differenz > 0 and jahre:
        jaehrlicher_vorteil = diesel["tco_je_jahr_eur"] - elektro["tco_je_jahr_eur"]
        mehrinvest = (elektro["anschaffung_eur"] + elektro["ladeinfrastruktur_eur"] - elektro["foerderung_eur"]) - \
                     (diesel["anschaffung_eur"] - diesel["foerderung_eur"])
        if jaehrlicher_vorteil > 0:
            breakeven = round(mehrinvest / jaehrlicher_vorteil, 1)
    co2_diesel = km_gesamt / 100 * num(v.get("diesel_l_100km"), 45) * 2680 / 1_000_000
    co2_e = km_gesamt * num(v.get("strom_kwh_100km"), 130) / 100 * 372 / 1_000_000
    return {
        "titel": "TCO-Vergleich Diesel- vs. E-Bus",
        "laufzeit_jahre": jahre,
        "km_gesamt": round(km_gesamt, 0),
        "varianten": [diesel, elektro],
        "differenz_tco_eur": round(differenz, 0),
        "guenstiger": "Dieselbus" if differenz > 0 else "E-Bus",
        "breakeven_jahr": breakeven,
        "co2_vergleich": {
            "diesel_t": round(co2_diesel, 1), "elektro_t": round(co2_e, 1),
            "einsparung_t": round(co2_diesel - co2_e, 1),
            "einsparung_prozent": round(100 * (co2_diesel - co2_e) / co2_diesel, 1) if co2_diesel else 0.0,
        },
        "annahmen": [
            "Förderung als Zuschuss auf die Investition (Anschaffung + Ladeinfrastruktur), gekappt auf 100 %",
            f"Energiepreise konstant über {fnum(jahre, 0)} Jahre, keine Preissteigerung gerechnet",
            "Restwert am Ende der Laufzeit linear als Prozentsatz des Anschaffungspreises",
            "Wartung als ct/km; keine Werkstatt-/Personalunterschiede",
            "Fördersätze sind Annahmen der Kommune und vor Beschluss zu prüfen",
        ],
        "rechenweg": [
            "TCO = (Preis + Ladeinfrastruktur − Förderung) + Energiekosten + Wartung − Restwert",
            f"km gesamt = {fnum(km, 0)} km/a × {fnum(jahre, 0)} Jahre = {fnum(km_gesamt, 0)} km",
            f"E-Bus Break-even gegenüber Diesel: " + (f"{fnum(breakeven, 1)} Jahre" if breakeven else "innerhalb des Zeitraums nicht erreicht"),
        ],
        "tabellen": {"varianten": ["variante", "anschaffung_eur", "foerderung_eur", "energiekosten_eur",
                                   "wartung_eur", "tco_gesamt_eur", "tco_je_km_eur"]},
    }


# ------------------------------------------------------------------ Wegeplanung / Kostenband

WEGE_FELDER = [
    Feld("laenge_m", "Länge des Abschnitts", "m", "3200"),
    Feld("kosten_getrennt_min", "Kosten getrennter Radweg – von", "€/m", "300"),
    Feld("kosten_getrennt_max", "Kosten getrennter Radweg – bis", "€/m", "800"),
    Feld("anteil_getrennt", "Anteil im getrennten Standard", "%", "60"),
    Feld("kosten_markiert_min", "Kosten markierte Lösung – von", "€/m", "30"),
    Feld("kosten_markiert_max", "Kosten markierte Lösung – bis", "€/m", "200"),
    Feld("budget", "Budgetrahmen", "k€", "400"),
]


def wege_kostenband(v: dict) -> dict:
    laenge = num(v.get("laenge_m"), 3200)
    anteil = min(100.0, max(0.0, num(v.get("anteil_getrennt"), 60))) / 100
    g_min, g_max = num(v.get("kosten_getrennt_min"), 300), num(v.get("kosten_getrennt_max"), 800)
    m_min, m_max = num(v.get("kosten_markiert_min"), 30), num(v.get("kosten_markiert_max"), 200)
    laenge_g, laenge_m = laenge * anteil, laenge * (1 - anteil)
    gesamt_min = laenge_g * g_min + laenge_m * m_min
    gesamt_max = laenge_g * g_max + laenge_m * m_max
    budget = num(v.get("budget"), 400) * 1000
    return {
        "titel": "Kostenband und Budgetdeckung",
        "laenge_gesamt_m": round(laenge, 0),
        "laenge_getrennt_m": round(laenge_g, 0),
        "laenge_markiert_m": round(laenge_m, 0),
        "kosten_min_eur": round(gesamt_min, 0),
        "kosten_max_eur": round(gesamt_max, 0),
        "kosten_je_m_mittel_eur": round((gesamt_min + gesamt_max) / 2 / laenge, 2) if laenge else 0.0,
        "budget_eur": round(budget, 0),
        "budget_deckung_prozent_mittel": round(100 * (gesamt_min + gesamt_max) / 2 / budget, 1) if budget else 0.0,
        "budget_luecke_max_eur": round(max(0.0, gesamt_max - budget), 0),
        "annahmen": [
            "Kostenbänder sind Erfahrungswerte (Planung inkl. Grunderwerb, Entwässerung, Beleuchtung) – keine Angebote",
            f"Aufteilung: {fnum(anteil * 100, 0)} % getrennter Standard, {fnum((1 - anteil) * 100, 0)} % markierte Lösung",
            "Keine Baupreissteigerung, keine Preissteigerungsrate gerechnet",
        ],
        "rechenweg": [
            "Gesamtkosten = Länge_getrennt × Kostenband + Länge_markiert × Kostenband",
            f"{fnum(laenge_g, 0)} m × {fnum(g_min, 0)}–{fnum(g_max, 0)} €/m + {fnum(laenge_m, 0)} m × {fnum(m_min, 0)}–{fnum(m_max, 0)} €/m = "
            f"{fnum(gesamt_min, 0)}–{fnum(gesamt_max, 0)} €",
        ],
        "tabellen": {},
    }


# ------------------------------------------------------------------ Verkehrssicherheit / Schulweg

def parse_unfall_csv(text: str) -> list[dict]:
    """Liest Unfallzeilen (CSV oder Semikolon) – tolerant gegenüber Spaltennamen."""
    rows: list[dict] = []
    if not text:
        return rows
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return rows
    sep = ";" if lines[0].count(";") >= lines[0].count(",") else ","
    header = [h.strip().lower() for h in lines[0].split(sep)]
    aliases = {
        "ort": ("ort", "stelle", "strasse", "straße", "knotenpunkt", "abschnitt"),
        "schwere": ("schwere", "schweregrad", "kategorie", "unfallkategorie"),
        "art": ("art", "unfallart", "typ"),
        "anzahl": ("anzahl", "unfaelle", "unfälle", "n"),
        "verletzte": ("verletzte", "verletzte_personen"),
        "datum": ("datum", "jahr"),
    }
    idx: dict[str, int] = {}
    for key, names in aliases.items():
        for i, h in enumerate(header):
            if h in names:
                idx[key] = i
                break
    if "ort" not in idx:
        return rows
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(sep)]
        if len(cells) <= idx["ort"]:
            continue
        schwer = cells[idx["schwere"]].lower() if "schwere" in idx else ""
        rows.append({
            "ort": cells[idx["ort"]],
            "schwere": schwer,
            "art": cells[idx["art"]] if "art" in idx else "",
            "anzahl": num(cells[idx["anzahl"]], 1) if "anzahl" in idx else 1,
            "verletzte": num(cells[idx["verletzte"]], 0) if "verletzte" in idx else 0,
        })
    return rows


SCHULWEG_FELDER = [
    Feld("unfaelle_csv", "Unfallliste (CSV: ort;schwere;art;anzahl;verletzte)", "CSV",
         "ort;schwere;art;anzahl;verletzte\nHauptstraße/Schulweg;schwer;Fußgänger;2;2\n"
         "Kreuzung Bahnhof;leicht;Rad;5;1\nHauptstraße/Schulweg;leicht;Rad;3;0\n"
         "Grundschule Nord;schwer;Schulweg;1;1\nKreuzung Bahnhof;schwer;Rad;1;1", typ="csv"),
    Feld("gewerte", "Gewichtung schwerer Unfälle", "Faktor", "5"),
    Feld("schwellenwert", "Schwellenwert Rankingeintrag", "Punkte", "6"),
]


def schulweg_ranking(v: dict) -> dict:
    rows = parse_unfall_csv(str(v.get("unfaelle_csv") or ""))
    gewicht = num(v.get("gewerte"), 5)
    def punkte(r: dict) -> float:
        schwer = "schwer" in r["schwere"] or "getötet" in r["schwere"] or "tödlich" in r["schwere"]
        return (r["anzahl"] or 1) * (gewicht if schwer else 1) + 2 * (r["verletzte"] or 0)

    agg: dict[str, dict] = {}
    for r in rows:
        e = agg.setdefault(r["ort"], {"ort": r["ort"], "unfaelle": 0, "schwere_unfaelle": 0,
                                      "verletzte": 0, "punkte": 0.0, "arten": set()})
        e["unfaelle"] += r["anzahl"] or 1
        e["schwere_unfaelle"] += (r["anzahl"] or 1) if ("schwer" in r["schwere"] or "töd" in r["schwere"]) else 0
        e["verletzte"] += r["verletzte"] or 0
        e["punkte"] += punkte(r)
        if r["art"]:
            e["arten"].add(r["art"])
    liste = sorted(agg.values(), key=lambda e: -e["punkte"])
    schwellwert = num(v.get("schwellenwert"), 6)
    for e in liste:
        e["arten"] = ", ".join(sorted(e["arten"]))
        e["punkte"] = round(e["punkte"], 1)
        e["kategorie"] = "Gefahrenstelle (vordringlich)" if e["punkte"] >= schwellwert * 2 else (
            "Prüfstelle" if e["punkte"] >= schwellwert else "Beobachtung")
    return {
        "titel": "Gefahrenstellen-Ranking (Schulweg/Verkehrssicherheit)",
        "anzahl_unfaelle": int(sum(e["unfaelle"] for e in liste)),
        "anzahl_stellen": len(liste),
        "schwere_unfaelle": int(sum(e["schwere_unfaelle"] for e in liste)),
        "verletzte": int(sum(e["verletzte"] for e in liste)),
        "ranking": liste,
        "massnahmenvorschlaege": [
            {"kategorie": "vordringlich", "massnahme": "Querungssicherung, Sichtfelder freihalten, Temporeduktion prüfen"},
            {"kategorie": "prüfen", "massnahme": "Schulwegsicherung mit Ordnungsamt/Polizei begehen, Elternbrief"},
            {"kategorie": "beobachten", "massnahme": "Regelmäßige Auswertung, Aufnahme ins Unfallmonitoring"},
        ],
        "annahmen": [
            f"Punkte = Anzahl × (Gewicht {fnum(gewicht, 0)} bei schweren Unfällen, sonst 1) + 2 × Verletzte",
            "Unfallliste ist eine Angabe der Kommune; amtliche Quelle ist die Unfallstatistik der Polizei",
            "Keine Verortung/Georeferenzierung – Ranking erfolgt über die Bezeichnung der Stelle",
        ],
        "rechenweg": [
            "Punkte je Stelle = Σ [ Anzahl × Gewicht(schwer=5) + 2 × Verletzte ] über alle Unfallzeilen der Stelle",
            f"Einordnung: ≥ {fnum(schwellwert * 2, 0)} Punkte = vordringlich, ≥ {fnum(schwellwert, 0)} Punkte = Prüfstelle",
        ],
        "tabellen": {"ranking": ["ort", "unfaelle", "schwere_unfaelle", "verletzte", "punkte", "kategorie", "arten"]},
    }


# ------------------------------------------------------------------ Ladeinfrastruktur

LADE_FELDER = [
    Feld("pkw_bestand", "Pkw-Bestand der Kommune", "Pkw", "12000"),
    Feld("quote_laternenparker", "Anteil ohne eigene Lademöglichkeit", "%", "55"),
    Feld("quote_start_2026", "E-Anteil heute", "%", "4"),
    Feld("ziel_anteil_2030", "Ziel-E-Anteil 2030", "%", "22"),
    Feld("ladepunkte_start", "Vorhandene öffentliche Ladepunkte", "Ladepunkte", "14"),
    Feld("pkw_je_ladepunkt_ac", "Pkw je AC-Ladepunkt (Zielbild)", "Pkw", "12"),
    Feld("pkw_je_ladepunkt_dc", "Pkw je DC-Ladepunkt (Zielbild)", "Pkw", "80"),
    Feld("leistung_ac_kw", "Leistung AC-Ladepunkt", "kW", "11"),
    Feld("leistung_dc_kw", "Leistung DC-Ladepunkt", "kW", "150"),
    Feld("gleichzeitigkeit", "Gleichzeitigkeitsfaktor", "%", "35"),
    Feld("invest_ac", "Investition je AC-Ladepunkt", "€", "6000"),
    Feld("invest_dc", "Investition je DC-Ladepunkt (Standort)", "€", "65000"),
]


def ladeinfrastruktur(v: dict) -> dict:
    pkw = num(v.get("pkw_bestand"), 12000)
    quote = num(v.get("quote_laternenparker"), 55) / 100
    start = num(v.get("quote_start_2026"), 4) / 100
    ziel = num(v.get("ziel_anteil_2030"), 22) / 100
    vorhanden = num(v.get("ladepunkte_start"), 14)
    je_ac = max(1.0, num(v.get("pkw_je_ladepunkt_ac"), 12))
    je_dc = max(1.0, num(v.get("pkw_je_ladepunkt_dc"), 80))
    p_ac = num(v.get("leistung_ac_kw"), 11)
    p_dc = num(v.get("leistung_dc_kw"), 150)
    glz = num(v.get("gleichzeitigkeit"), 35) / 100
    i_ac, i_dc = num(v.get("invest_ac"), 6000), num(v.get("invest_dc"), 65000)

    def bedarf(anteil: float) -> dict:
        e_pkw = pkw * anteil
        oeffentlich = e_pkw * quote  # ohne eigene Lademöglichkeit
        ac = oeffentlich * 0.75 / je_ac
        dc = oeffentlich * 0.25 / je_dc
        return {
            "e_pkw": round(e_pkw, 0),
            "ohne_eigene_lademoeglichkeit": round(oeffentlich, 0),
            "ladepunkte_ac": round(ac, 0),
            "ladepunkte_dc": round(dc, 0),
            "ladepunkte_gesamt": round(ac + dc, 0),
            "zusatz_gegenueber_heute": round(max(0.0, ac + dc - vorhanden), 0),
            "leistungsbedarf_kw": round((ac * p_ac + dc * p_dc) * glz, 0),
            "investition_eur": round(max(0.0, ac + dc - vorhanden) * ((i_ac * max(0.0, ac - vorhanden * 0.75) + i_dc * max(0.0, dc - vorhanden * 0.25)) / max(1.0, ac + dc - vorhanden)) if (ac + dc - vorhanden) > 0 else 0.0, 0),
        }

    heute = bedarf(start)
    zielbild = bedarf(ziel)
    return {
        "titel": "Ladeinfrastruktur-Bedarfsrechnung",
        "heute": heute,
        "zielbild": zielbild,
        "ausbaustufen": [
            {"stufe": "Sofort (0–12 Monate)", "ladepunkte": round(max(0.0, heute["ladepunkte_gesamt"] - vorhanden) if heute["ladepunkte_gesamt"] > vorhanden else max(3.0, zielbild["ladepunkte_gesamt"] * 0.25), 0),
             "massnahme": "Bestandslücken schließen, AC an Zentren, 2 Schnellladestandorte prüfen"},
            {"stufe": "Ausbau bis 2028", "ladepunkte": round(zielbild["ladepunkte_gesamt"] * 0.6, 0),
             "massnahme": "Flächendeckung AC, DC an Bundesstraße/Bahnhof, Satzung/Standortkonzept"},
            {"stufe": "Zielbild 2030", "ladepunkte": round(zielbild["ladepunkte_gesamt"], 0),
             "massnahme": "Bedarfsdeckung Zielquote, Anpassung alle 2 Jahre an reale Zulassungszahlen"},
        ],
        "foerderhinweis": (
            "Förderkulisse prüfen: Bundesprogramme (u. a. Ladeinfrastruktur vor Ort), Länderprogramme und "
            "KDG-/AFID-Vorgaben – Fördersätze sind Annahmen und vor Antragstellung zu verifizieren."
        ),
        "annahmen": [
            f"{fnum(quote * 100, 0)} % der E-Pkw haben keine eigene Lademöglichkeit (Laternenparker) – öffentliche Ladeinfrastruktur nötig",
            "Aufteilung 75 % AC-/22 kW-Klasse und 25 % DC-Schnellladen",
            f"Gleichzeitigkeitsfaktor {fnum(glz * 100, 0)} % für den Leistungsbedarf",
            "Zielquote 2030 ist eine Setzung der Kommune, keine Prognose",
            "Investitionskosten sind Richtwerte inkl. Tiefbauanteil, ohne Netzanschlussausbau",
        ],
        "rechenweg": [
            "öffentlich benötigt [Pkw] = Pkw-Bestand × E-Anteil × Anteil ohne eigene Lademöglichkeit",
            "Ladepunkte AC = öffentlich × 0,75 ÷ Pkw je AC-Ladepunkt; DC = öffentlich × 0,25 ÷ Pkw je DC-Ladepunkt",
            f"Heute: {fnum(heute['e_pkw'], 0)} E-Pkw → {fnum(heute['ladepunkte_gesamt'], 0)} Ladepunkte; "
            f"2030: {fnum(zielbild['e_pkw'], 0)} E-Pkw → {fnum(zielbild['ladepunkte_gesamt'], 0)} Ladepunkte",
        ],
        "tabellen": {"ausbaustufen": ["stufe", "ladepunkte", "massnahme"]},
    }


# ------------------------------------------------------------------ Parkraum

PARK_FELDER = [
    Feld("parkstaende", "Öffentliche Parkstände im Gebiet", "Stück", "850"),
    Feld("auslastung", "Auslastung Hauptzeit", "%", "92"),
    Feld("kosten_je_stellplatz", "Bewirtschaftungskosten je Stellplatz", "€/Jahr", "260"),
    Feld("gebuehr_stunde", "Bewirtschaftungsgebühr", "€/Stunde", "1,00"),
    Feld("bewirtschaftete_stellplaetze", "Bewirtschaftete Stellplätze", "Stück", "300"),
    Feld("einnahmen_je_stellplatz", "Einnahmen je bewirtschaftetem Stellplatz", "€/Jahr", "620"),
    Feld("anteil_bewohnerparken", "Anteil Bewohnerparken", "%", "25"),
]


def parkraum(v: dict) -> dict:
    staende = num(v.get("parkstaende"), 850)
    auslastung = num(v.get("auslastung"), 92)
    kosten_je = num(v.get("kosten_je_stellplatz"), 260)
    bewirtschaftet = min(staende, num(v.get("bewirtschaftete_stellplaetze"), 300))
    einnahmen_je = num(v.get("einnahmen_je_stellplatz"), 620)
    invest = bewirtschaftet * 1200  # Parkscheinautomat/Schilder/Umzeichnung als Richtwert
    einnahmen = bewirtschaftet * einnahmen_je
    kosten_heute = staende * kosten_je
    kosten_neu = (staende - bewirtschaftet) * kosten_je * 0.6 + bewirtschaftet * kosten_je
    return {
        "titel": "Parkraumbilanz und Bewirtschaftung",
        "parkstaende": round(staende, 0),
        "auslastung_prozent": round(auslastung, 1),
        "freie_parkstaende_hauptzeit": round(staende * (1 - auslastung / 100), 0),
        "ueberlast_empfehlung": "Bewirtschaftung/Erweiterung prüfen" if auslastung >= 85 else "Bestand ausreichend",
        "einnahmen_jahr_eur": round(einnahmen, 0),
        "kosten_jahr_eur": round(kosten_neu, 0),
        "ueberschuss_jahr_eur": round(einnahmen - kosten_neu, 0),
        "investition_erstausstattung_eur": round(invest, 0),
        "amortisation_jahre": round(invest / (einnahmen - kosten_neu), 1) if einnahmen - kosten_neu > 0 else None,
        "vergleich_ohne_bewirtschaftung": {
            "kosten_jahr_eur": round(kosten_heute, 0),
            "einnahmen_jahr_eur": 0,
            "saldo_jahr_eur": round(-kosten_heute, 0),
        },
        "annahmen": [
            "Bewirtschaftungskosten je Stellplatz (Unterhalt, Kontrolle, Verwaltung) als Erfahrungswert",
            "Einnahmen je bewirtschaftetem Stellplatz sind eine Setzung und hängen von Tarif und Kontrolldichte ab",
            "Erstausstattung 1.200 € je Stellplatz (Automat, Beschilderung, Umzeichnung) – Richtwert",
            "Bewohnerparken ist im Modell nicht separat bepreist",
        ],
        "rechenweg": [
            "Freie Parkstände Hauptzeit = Parkstände × (1 − Auslastung)",
            "Überschuss = bewirtschaftete Stellplätze × Einnahmen/Stellplatz − Betriebskosten",
            f"{fnum(bewirtschaftet, 0)} × {fnum(einnahmen_je, 0)} € − {fnum(kosten_neu, 0)} € = {fnum(einnahmen - kosten_neu, 0)} €/a",
        ],
        "tabellen": {},
    }


# ------------------------------------------------------------------ Registry

RECHNER: dict[str, Rechner] = {
    "co2-bilanz": Rechner(
        "co2-bilanz", "Fuhrpark-Bilanzrechner",
        "Rechnet die CO₂-Bilanz des kommunalen Fuhrparks aus Fahrleistungen und Verbräuchen.",
        CO2_FELDER, co2_bilanz,
    ),
    "opnv-planung": Rechner(
        "opnv-planung", "Umlauf- und Taktplanung",
        "Umlaufzeit, Fahrzeugbedarf, Fahrleistung und Kosten je Taktstufe.",
        OPNV_FELDER, opnv_umlauf,
    ),
    "beschlussvorlagen": Rechner(
        "beschlussvorlagen", "TCO-Rechner Diesel vs. Elektro",
        "Gesamtkostenvergleich über die Laufzeit inkl. Förderung, Energie und Wartung.",
        TCO_FELDER, tco_vergleich,
    ),
    "argumentation": Rechner(
        "argumentation", "TCO-Rechner Diesel vs. Elektro",
        "Zahlen für die Argumentationshilfe – dieselbe Rechnung wie bei den Beschlussvorlagen.",
        TCO_FELDER, tco_vergleich,
    ),
    "wegeplanung": Rechner(
        "wegeplanung", "Kostenband-Rechner",
        "Kostenband und Budgetdeckung für Radinfrastruktur nach Standard und Länge.",
        WEGE_FELDER, wege_kostenband,
    ),
    "verkehrssicherheit": Rechner(
        "verkehrssicherheit", "Gefahrenstellen-Ranking",
        "Rangfolge der Unfallstellen mit Gewichtung schwerer Unfälle und Maßnahmenliste.",
        SCHULWEG_FELDER, schulweg_ranking,
    ),
    "ladeinfrastruktur": Rechner(
        "ladeinfrastruktur", "Ladebedarfs-Rechner",
        "Bedarf an AC-/DC-Ladepunkten heute und im Zielbild inklusive Ausbaustufen.",
        LADE_FELDER, ladeinfrastruktur,
    ),
    "parkraum": Rechner(
        "parkraum", "Parkraumbilanz-Rechner",
        "Auslastung, Bewirtschaftungssaldo und Amortisation.",
        PARK_FELDER, parkraum,
    ),
}


def has_rechner(tile_id: str) -> bool:
    return tile_id in RECHNER


def describe(tile_id: str) -> dict | None:
    r = RECHNER.get(tile_id)
    if not r:
        return None
    return {
        "tile_id": r.tile_id,
        "name": r.name,
        "beschreibung": r.beschreibung,
        "felder": [f.as_dict() for f in r.felder],
        "annahmen": r.annahmen,
    }


def fields(tile_id: str) -> list[dict]:
    r = RECHNER.get(tile_id)
    return [f.as_dict() for f in r.felder] if r else []


def compute(tile_id: str, values: dict) -> dict:
    r = RECHNER.get(tile_id)
    if not r:
        raise KeyError(tile_id)
    # Defaults der Felder vorbelegen, übergebene Werte überschreiben sie
    merged = {f.key: f.default for f in r.felder}
    merged.update({k: v for k, v in (values or {}).items() if v not in (None, "")})
    result = r.fn(merged)
    result["rechner"] = r.name
    result["tile_id"] = tile_id
    result["eingaben"] = {k: (v if isinstance(v, str) else num(v)) for k, v in merged.items()}
    return result


def kontext_block(tile_id: str, values: dict) -> str:
    """Markdown-Block mit vorberechneten, verbindlichen Zahlen für den System-Prompt."""
    try:
        res = compute(tile_id, values)
    except KeyError:
        return ""
    lines = [
        "## Vorberechnete Werte (Python-Rechenkern – verbindlich, nicht nachrechnen)",
        f"Rechner: {res['rechner']} · Ergebnis: {res.get('titel', '')}",
        "Übernimm diese Zahlen unverändert in das Ergebnis. Rechne keine eigenen Werte; wenn dir eine Zahl fehlt, benenne die Lücke.",
    ]
    for key, value in res.items():
        if key in ("eingaben", "rechenweg", "annahmen", "tabellen", "bilanz", "varianten",
                   "ranking", "taktstufen", "ausbaustufen", "zielbild", "heute") or isinstance(value, (dict, list)):
            continue
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)
