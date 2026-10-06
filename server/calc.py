"""Deterministische Rechenkerne für SusMob (Plan Abschnitt 4.5).

Grundsatz: **Zahlen entstehen im Code, das LLM formuliert.** Jede Funktion hier
ist rein (kein Netz, kein LLM), damit Ergebnisse reproduzierbar, testbar und
exportierbar sind. Das LLM liefert nur die Eingangsdaten (extrahiert aus
Chat/Dateien) und den Erzähltext auf Basis dieser Zahlen.

Alle Funktionen geben ``dict`` zurück (JSON-fähig) und liefern unter
``"annahmen"`` mit, welche Werte gesetzt wurden, und unter ``"pruefungen"``,
was plausibilisiert/verworfen wurde.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

# ---------------------------------------------------------------- Faktoren

# Tank-to-Wheel-Faktoren (Verbrennung) und Well-to-Tank (Vorkette).
# Quellen: UBA/BBU-Standardwerte; Strommix DE 372 g CO₂/kWh (UBA 2023).
FAKTOREN: dict[str, dict[str, Any]] = {
    "diesel": {"ttw": 2.68, "einheit": "kg CO₂/l", "wtt": 0.55, "energie": "l", "energie_je_einheit": 9.8},
    "benzin": {"ttw": 2.38, "einheit": "kg CO₂/l", "wtt": 0.50, "energie": "l", "energie_je_einheit": 8.9},
    "erdgas": {"ttw": 2.00, "einheit": "kg CO₂/m³", "wtt": 0.45, "energie": "m³", "energie_je_einheit": 9.4},
    "hvo": {"ttw": 0.40, "einheit": "kg CO₂/l", "wtt": 0.30, "energie": "l", "energie_je_einheit": 9.4},
    "elektro": {"ttw": 0.372, "einheit": "kg CO₂/kWh", "wtt": 0.037, "energie": "kWh", "energie_je_einheit": 1.0},
    "oekostrom": {"ttw": 0.0, "einheit": "kg CO₂/kWh", "wtt": 0.0, "energie": "kWh", "energie_je_einheit": 1.0},
    "muskel": {"ttw": 0.0, "einheit": "kg CO₂/km", "wtt": 0.021, "energie": "km", "energie_je_einheit": 1.0},
}

STROM_MIX_G_KWH = 372.0         # Standard-Strommix
BESETZUNGSGRAD_PKW = 1.1        # Personen/Pkw (DE-Standard)
HALTESTELLENZEIT_S = 90.0       # Plan-Abschnitt ÖPNV
BUS_KM_KOSTEN = (1.40, 2.60)    # €/km Dieselbus (Betrieb), Band
EBUS_KM_KOSTEN = (1.20, 2.30)


def _num(value: Any, default: float | None = 0.0) -> float | None:
    """Toleranter Zahlenparser: '1.234,5' | '45 l/100 km' | '28.000' → float."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    for token in ("l/100 km", "l/100km", "kWh/100 km", "kwh/100km", "kWh/km", "kg/100 km",
                  "kWh", "km", "l", "%", "€", " ", "ca.", "ca", "≈", "~"):
        s = s.replace(token, "")
    s = s.strip()
    # Bandangaben ("300–800", "1,5 bis 4,0") → erste Zahl verwenden
    band = re.split(r"\s*(?:–|—|\bbis\b)\s*", s)
    if len(band) > 1 and re.search(r"\d", band[0]):
        s = band[0]
    # Längenangabe "1.200 m" / "500 Meter" – metrisches m nur direkt nach einer Zahl
    s = re.sub(r"(?<=\d)\s*(?:meter|m)\s*$", "", s, flags=re.I)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        # Deutsche Tausenderpunkte: "85.000" → 85000, aber "0.372" bleibt Dezimalzahl.
        if re.fullmatch(r"[1-9]\d{0,2}(\.\d{3})+", s):
            s = s.replace(".", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return default


def _r(value: float, digits: int = 2) -> float:
    return round(value + 0.0, digits)


def _anteile(werte: list[float], nachkomma: int = 1) -> list[float]:
    """Anteile in Prozent – mit Restverteilung, damit die Summe exakt 100 % ergibt."""
    total = sum(werte)
    if not total:
        return [0.0] * len(werte)
    roh = [w / total * 100 for w in werte]
    faktor = 10 ** nachkomma
    abgerundet = [math.floor(r * faktor) / faktor for r in roh]
    rest = round(100.0 * faktor - sum(a * faktor for a in abgerundet))
    reihenfolge = sorted(range(len(roh)), key=lambda i: roh[i] - abgerundet[i], reverse=True)
    for i in range(int(max(0, rest))):
        idx = reihenfolge[i % len(roh)]
        abgerundet[idx] = round(abgerundet[idx] + 1 / faktor, nachkomma)
    return [round(a, nachkomma) for a in abgerundet]


# ---------------------------------------------------------------- CO₂-Bilanz


def co2_bilanz(gruppen: Iterable[dict], faktoren: dict[str, float] | None = None,
               well_to_tank: bool = False) -> dict:
    """Emissionsbilanz eines Fuhrparks/Verkehrsträger-Mixes.

    ``gruppen``: je Eintrag ``bezeichnung``, optional ``anzahl``, ``km_jahr``,
    ``verbrauch_je_100km`` (l oder kWh je 100 km), ``kraftstoff``
    (diesel|benzin|erdgas|hvo|elektro|oekostrom), ``fahrgaeste`` (für g CO₂/Pkm),
    ``emissionsfaktor`` + ``faktor_einheit`` (überschreibt den Standardfaktor).

    ``faktoren``: Overrides, z. B. ``{"elektro": 0.372, "diesel": 2.68}`` in kg je Einheit.
    """
    override = dict(faktoren or {})
    rows, annahmen, pruefungen = [], [], []
    if override:
        annahmen.append("Emissionsfaktoren wurden von der Kommune vorgegeben: "
                        + ", ".join(f"{k} = {v}" for k, v in override.items()))
    else:
        annahmen.append("Emissionsfaktoren aus UBA-Standardwerten (Diesel 2,68 kg CO₂/l, "
                        "Benzin 2,38 kg CO₂/l, Strommix 372 g CO₂/kWh).")
    if well_to_tank:
        annahmen.append("Vorkette (Well-to-Tank) wird separat ausgewiesen.")

    for i, g in enumerate(gruppen or [], start=1):
        bez = str(g.get("bezeichnung") or g.get("name") or f"Gruppe {i}").strip()
        anzahl = _num(g.get("anzahl"), 1.0) or 1.0
        km = _num(g.get("km_jahr") or g.get("km") or g.get("fahrleistung"))
        verbrauch = _num(g.get("verbrauch_je_100km") or g.get("verbrauch"))
        kraftstoff = str(g.get("kraftstoff") or "").strip().lower().replace("ö", "oe").replace("ä", "ae")
        kraftstoff = {"strom": "elektro", "e-auto": "elektro", "dieselbus": "diesel",
                      "benzin-pkw": "benzin", "gas": "erdgas"}.get(kraftstoff, kraftstoff) or "diesel"
        f = FAKTOREN.get(kraftstoff)
        if f is None:
            pruefungen.append(f"Unbekannter Kraftstoff „{g.get('kraftstoff')}\" bei „{bez}\" – "
                              f"mit Diesel-Faktor gerechnet.")
            f = FAKTOREN["diesel"]
            kraftstoff = "diesel"
        km_gesamt = (km or 0.0) * anzahl
        if km_gesamt <= 0:
            pruefungen.append(f"„{bez}\": keine Jahresfahrleistung angegeben – Gruppe übersprungen.")
            continue
        faktor = _num(override.get(kraftstoff), None)
        if faktor is None and kraftstoff in ("elektro", "oekostrom") and g.get("emissionsfaktor"):
            faktor = _num(g.get("emissionsfaktor"))
        if faktor is None and str(g.get("faktor_einheit", "")).startswith("g") and g.get("emissionsfaktor"):
            faktor = (_num(g.get("emissionsfaktor")) or 0.0) / 1000.0
        if faktor is None:
            faktor = float(f["ttw"])
        einheit = g.get("faktor_einheit") or f["einheit"]

        if verbrauch is None or verbrauch <= 0:
            # Ohne Verbrauch: Verbrauch aus Verkehrsträger-Fallback rechnen
            fallback = {"diesel": 45.0 if "bus" in bez.lower() else 6.8,
                        "benzin": 7.4, "erdgas": 4.6, "hvo": 45.0,
                        "elektro": 18.0 if "pkw" in bez.lower() else 120.0,
                        "oekostrom": 18.0 if "pkw" in bez.lower() else 120.0,
                        "muskel": 0.0}.get(kraftstoff, 10.0)
            verbrauch = fallback
            annahmen.append(f"„{bez}\": ohne Verbrauchsangabe mit {verbrauch:g} "
                            f"{'kWh' if kraftstoff in ('elektro', 'oekostrom') else 'l'}/100 km gerechnet.")
        energie = km_gesamt * verbrauch / 100.0
        co2_kg = energie * faktor
        wtt_kg = energie * float(f["wtt"]) if well_to_tank else 0.0
        fahrgaeste = _num(g.get("fahrgaeste"), 0.0) or 0.0
        g_pro_pkm = (co2_kg * 1000.0 / (km_gesamt * fahrgaeste)) if fahrgaeste > 0 else None
        rows.append({
            "bezeichnung": bez,
            "anzahl": _r(anzahl, 0),
            "kraftstoff": kraftstoff,
            "km_gesamt": _r(km_gesamt, 0),
            "verbrauch_je_100km": _r(verbrauch, 2),
            "energie_menge": _r(energie, 0),
            "energie_einheit": f["energie"],
            "emissionsfaktor": _r(faktor, 3),
            "faktor_einheit": einheit,
            "t_co2": _r(co2_kg / 1000.0, 2),
            "t_co2_vorkette": _r(wtt_kg / 1000.0, 2),
            "g_co2_pro_pkm": _r(g_pro_pkm, 1) if g_pro_pkm else None,
            "formel": f"{km_gesamt:,.0f} km × {verbrauch:g} {f['energie']}/100 km × {faktor:g} {einheit}",
        })
    anteile = _anteile([r["t_co2"] for r in rows])
    for r, a in zip(rows, anteile):
        r["anteil_pct"] = a
    rows.sort(key=lambda r: -r["t_co2"])
    summe = _r(sum(r["t_co2"] for r in rows), 2)
    summe_wtt = _r(sum(r["t_co2_vorkette"] for r in rows), 2)
    if not rows:
        pruefungen.append("Keine auswertbare Gruppe – bitte Fahrleistung und Verbrauch je Gruppe angeben.")
    return {
        "typ": "co2_bilanz",
        "gruppen": rows,
        "summe_t_co2": summe,
        "summe_t_co2_vorkette": summe_wtt,
        "summe_t_co2_gesamt": _r(summe + summe_wtt, 2),
        "well_to_tank": bool(well_to_tank),
        "faktoren": {k: (override.get(k) or v["ttw"]) for k, v in FAKTOREN.items()},
        "annahmen": annahmen,
        "pruefungen": pruefungen,
        "rechenweg": "Emission [kg] = Fahrleistung [km] × Verbrauch [Einheit/100 km] ÷ 100 × Faktor [kg CO₂/Einheit]",
    }


# ---------------------------------------------------------------- ÖPNV


def opnv_umlauf(laenge_km: float, geschwindigkeit_kmh: float, haltestellen: int = 0,
                wendezeit_min: float = 6.0, takt_hvz_min: float = 30.0, takt_nvz_min: float = 60.0,
                betriebsstunden_tag: float = 16.0, kapazitaet: int = 49,
                fahrgaeste_tag: int | None = None, reserve_pct: float = 10.0,
                haltestellenzeit_s: float = HALTESTELLENZEIT_S) -> dict:
    """Umlaufzeit, Fahrzeugbedarf und Auslastung einer Buslinie."""
    laenge = _num(laenge_km) or 0.0
    tempo = _num(geschwindigkeit_kmh) or 0.0
    if laenge <= 0 or tempo <= 0:
        return {"typ": "opnv_umlauf", "fehler": "Streckenlänge und Reisegeschwindigkeit sind Pflichtangaben.",
                "annahmen": [], "pruefungen": []}
    annahmen = [
        f"Reisegeschwindigkeit {tempo:g} km/h (kommunale Angabe bzw. Fallback Stadtbus 25–30, Landbus 20–25).",
        f"Haltezeit {haltestellenzeit_s:g} s je Haltestelle, Wendezeit {wendezeit_min:g} min je Endpunkt.",
        f"Fahrzeugkapazität {kapazitaet} Plätze, Fahrzeugreserve {reserve_pct:g} %.",
    ]
    fahrzeit_min = laenge / tempo * 60.0
    halte_min = (haltestellen or 0) * haltestellenzeit_s / 60.0
    umlauf_min = 2 * (fahrzeit_min + halte_min) + 2 * wendezeit_min
    fahrzeuge_hvz = math.ceil(umlauf_min / takt_hvz_min) if takt_hvz_min > 0 else 0
    fahrzeuge_nvz = math.ceil(umlauf_min / takt_nvz_min) if takt_nvz_min > 0 else 0
    reserve = math.ceil(fahrzeuge_hvz * reserve_pct / 100.0) if fahrzeuge_hvz else 0

    fahrten_hvz = fahrten_nvz = 0
    if takt_hvz_min and takt_nvz_min:
        stunden_hvz = round(betriebsstunden_tag / 2.5, 2)      # 2,5 h Hauptverkehrszeit je Richtung
        stunden_hvz = min(stunden_hvz, betriebsstunden_tag)
        fahrten_hvz = 2 * int(stunden_hvz * 60 / takt_hvz_min)
        fahrten_nvz = 2 * int(max(0.0, betriebsstunden_tag - stunden_hvz) * 60 / takt_nvz_min)
    fahrten_tag = fahrten_hvz + fahrten_nvz
    km_tag = _r(fahrten_tag * laenge, 0)
    km_jahr = _r(km_tag * 300, 0)                 # 300 Betriebstage (Annahme)
    plaetze_tag = fahrten_tag * kapazitaet
    fahrgaeste = _num(fahrgaeste_tag, None)
    auslastung = _r((fahrgaeste / plaetze_tag * 100.0), 1) if fahrgaeste and plaetze_tag else None
    kosten_min = _r(km_jahr * BUS_KM_KOSTEN[0], 0)
    kosten_max = _r(km_jahr * BUS_KM_KOSTEN[1], 0)
    pruefungen = []
    if auslastung is not None and auslastung < 20:
        pruefungen.append(f"Auslastung nur {auslastung:g} % – Takt oder Fahrzeuggröße prüfen "
                          "(On-Demand/Rufbus als Alternative?).")
    if umlauf_min > takt_hvz_min:
        pruefungen.append(f"Umlaufzeit ({umlauf_min:.0f} min) übersteigt den Takt ({takt_hvz_min:g} min) – "
                          f"{fahrzeuge_hvz} Fahrzeuge je Richtung nötig.")
    return {
        "typ": "opnv_umlauf",
        "fahrzeit_min": _r(fahrzeit_min, 1),
        "haltezeit_min": _r(halte_min, 1),
        "umlaufzeit_min": _r(umlauf_min, 1),
        "fahrzeuge_hvz": fahrzeuge_hvz,
        "fahrzeuge_nvz": fahrzeuge_nvz,
        "fahrzeugreserve": reserve,
        "fahrzeugbedarf_gesamt": fahrzeuge_hvz + reserve,
        "fahrten_tag": fahrten_tag,
        "fahrten_hvz": fahrten_hvz,
        "fahrten_nvz": fahrten_nvz,
        "km_tag": km_tag,
        "km_jahr": km_jahr,
        "kapazitaet": kapazitaet,
        "plaetze_tag": plaetze_tag,
        "fahrgaeste_tag": fahrgaeste,
        "auslastung_pct": auslastung,
        "kosten_jahr_min": kosten_min,
        "kosten_jahr_max": kosten_max,
        "kosten_einheit": "€/a (Betrieb, Band 1,40–2,60 €/km)",
        "annahmen": annahmen + ["300 Betriebstage pro Jahr."],
        "pruefungen": pruefungen,
    }


def tco_vergleich(varianten: Iterable[dict], laufleistung_km_jahr: float = 45_000.0,
                  nutzungsdauer_jahre: float = 12.0, zins_pct: float = 3.0) -> dict:
    """Total-Cost-of-Ownership je Fahrzeugvariante (Anschaffung + Betrieb)."""
    annahmen = [
        f"Nutzungsdauer {nutzungsdauer_jahre:g} Jahre, Jahresfahrleistung {laufleistung_km_jahr:,.0f} km, "
        f"Kalkulationszins {zins_pct:g} % (Kapitaldienst vereinfacht linear).",
        "Kostenbänder sind Annahmen – bitte durch Angebote/Betriebsdaten ersetzen.",
    ]
    rows = []
    for v in varianten or []:
        name = str(v.get("name") or v.get("bezeichnung") or "Variante")
        invest = _num(v.get("investition_eur") or v.get("investition"), 0.0) or 0.0
        energiaufwand = _num(v.get("energie_je_100km"), None)
        energiepreis = _num(v.get("energiepreis_je_einheit"), None)
        energie_kosten = None
        if energiaufwand is not None and energiepreis is not None:
            energie_kosten = laufleistung_km_jahr * energiaufwand / 100.0 * energiepreis
        elif v.get("kosten_je_km") is not None:
            energie_kosten = laufleistung_km_jahr * (_num(v.get("kosten_je_km"), 0.0) or 0.0)
        wartung = _num(v.get("wartung_eur_jahr"), 0.0) or 0.0
        steuer_versicherung = _num(v.get("fixkosten_eur_jahr"), 0.0) or 0.0
        kapitaldienst = invest * (1 + zins_pct / 100.0 * nutzungsdauer_jahre / 2.0) / nutzungsdauer_jahre
        jahr = kapitaldienst + (energie_kosten or 0.0) + wartung + steuer_versicherung
        rows.append({
            "name": name,
            "investition_eur": _r(invest, 0),
            "kapitaldienst_jahr": _r(kapitaldienst, 0),
            "energie_jahr": _r(energie_kosten, 0) if energie_kosten is not None else None,
            "wartung_jahr": _r(wartung, 0),
            "fixkosten_jahr": _r(steuer_versicherung, 0),
            "kosten_jahr": _r(jahr, 0),
            "kosten_je_km": _r(jahr / laufleistung_km_jahr, 3) if laufleistung_km_jahr else None,
            "kosten_ueber_nutzungsdauer": _r(jahr * nutzungsdauer_jahre, 0),
        })
    rows.sort(key=lambda r: r["kosten_ueber_nutzungsdauer"])
    if rows:
        teuerste = max(rows, key=lambda r: r["kosten_ueber_nutzungsdauer"])
        guenstigste = rows[0]
        differenz = teuerste["kosten_ueber_nutzungsdauer"] - guenstigste["kosten_ueber_nutzungsdauer"]
    else:
        differenz = 0.0
    return {"typ": "tco_vergleich", "varianten": rows, "differenz_ueber_nutzungsdauer": _r(differenz, 0),
            "annahmen": annahmen,
            "pruefungen": [] if rows else ["Keine Varianten übergeben."]}


# ---------------------------------------------------------------- Kostenbänder


def kostenband(abschnitte: Iterable[dict], einheit_laenge: str = "m") -> dict:
    """Kostenband über Abschnitte: Länge × €/m (min/max)."""
    rows, pruefungen = [], []
    for a in abschnitte or []:
        name = str(a.get("abschnitt") or a.get("name") or "Abschnitt")
        laenge = _num(a.get("laenge_m") or a.get("laenge"))
        if laenge is None or laenge <= 0:
            pruefungen.append(f"„{name}\": ohne Länge übersprungen.")
            continue
        von = _num(a.get("kosten_min_eur_pro_m") or a.get("kosten_min"), None)
        bis = _num(a.get("kosten_max_eur_pro_m") or a.get("kosten_max"), None)
        if von is None:
            von, bis = 30.0, 80.0
            pruefungen.append(f"„{name}\": ohne Kostenband – Standardband 30–80 €/m (markierte Radinfrastruktur) gerechnet.")
        bis = bis if bis is not None else von
        rows.append({
            "abschnitt": name,
            "laenge_m": _r(laenge, 0),
            "kosten_min_eur_pro_m": _r(von, 0),
            "kosten_max_eur_pro_m": _r(bis, 0),
            "kosten_min_eur": _r(laenge * von, 0),
            "kosten_max_eur": _r(laenge * bis, 0),
        })
    gesamt_min = _r(sum(r["kosten_min_eur"] for r in rows), 0)
    gesamt_max = _r(sum(r["kosten_max_eur"] for r in rows), 0)
    return {"typ": "kostenband", "abschnitte": rows, "laenge_m": _r(sum(r["laenge_m"] for r in rows), 0),
            "kosten_min_eur": gesamt_min, "kosten_max_eur": gesamt_max,
            "kosten_mittel_eur": _r((gesamt_min + gesamt_max) / 2.0, 0), "einheit": "€ brutto (Band)",
            "annahmen": ["Kostenbänder sind Planungswerte (Annahme) – Ausschreibungsergebnis abwarten."],
            "pruefungen": pruefungen}


# ---------------------------------------------------------------- Priorisierung


def massnahmen_priorisierung(massnahmen: Iterable[dict],
                             gewichte: dict[str, float] | None = None) -> dict:
    """Nutzwertanalyse: Wirkung/Sicherheit/Kosten/Aufwand/Akzeptanz → Priorität.

    Erwartet je Maßnahme Werte 1–5 (höher = besser) für ``wirkung``,
    ``sicherheit``, ``akzeptanz`` und inverse Werte für ``kosten``, ``aufwand``
    (5 = sehr günstig/schnell, 1 = sehr teuer/langsam).
    """
    g = {"wirkung": 0.35, "sicherheit": 0.15, "kosten": 0.2, "aufwand": 0.15, "akzeptanz": 0.15}
    g.update({k: float(v) for k, v in (gewichte or {}).items()})
    s = sum(g.values()) or 1.0
    g = {k: v / s for k, v in g.items()}
    rows = []
    for m in massnahmen or []:
        name = str(m.get("name") or m.get("massnahme") or "Maßnahme")
        werte, fehlend = {}, []
        for key in g:
            v = _num(m.get(key), None)
            if v is None:
                v = 3.0
                fehlend.append(key)
            werte[key] = min(5.0, max(1.0, v))
        score = sum(werte[k] * g[k] for k in g)
        rows.append({
            "name": name,
            "werte": werte,
            "score": _r(score, 2),
            "wirkung_text": m.get("wirkung_text") or m.get("wirkung_beschreibung") or "",
            "kosten_band": m.get("kosten_band") or "",
            "zeitrahmen": m.get("zeitrahmen") or "",
            "kpi": m.get("kpi") or "",
            "hinweis": ("Fehlende Bewertung mit 3 (mittel) angenommen: " + ", ".join(fehlend)) if fehlend else "",
        })
    rows.sort(key=lambda r: -r["score"])
    for i, r in enumerate(rows, start=1):
        r["rang"] = i
        r["prioritaet"] = "hoch" if r["score"] >= 3.8 else ("mittel" if r["score"] >= 3.0 else "niedrig")
    return {"typ": "massnahmen_priorisierung", "massnahmen": rows, "gewichte": g,
            "annahmen": [f"Gewichtung: " + ", ".join(f"{k} {v:.0%}" for k, v in g.items())],
            "pruefungen": [] if rows else ["Keine Maßnahmen übergeben."]}


# ---------------------------------------------------------------- Dispatcher


def rechnen(tile_id: str, params: dict) -> dict:
    """Rechner je Kachel aus einem flachen Parameter-Objekt aufrufen."""
    p = dict(params or {})
    if tile_id == "co2-bilanz":
        return co2_bilanz(p.get("gruppen") or [], p.get("faktoren"), bool(p.get("well_to_tank")))
    if tile_id == "opnv-planung":
        return opnv_umlauf(**{k: v for k, v in p.items()
                              if k in {"laenge_km", "geschwindigkeit_kmh", "haltestellen", "wendezeit_min",
                                       "takt_hvz_min", "takt_nvz_min", "betriebsstunden_tag", "kapazitaet",
                                       "fahrgaeste_tag", "reserve_pct"}})
    if tile_id == "wegeplanung":
        return kostenband(p.get("abschnitte") or [])
    if tile_id == "massnahmenplanung":
        return massnahmen_priorisierung(p.get("massnahmen") or [], p.get("gewichte"))
    return {"typ": "kennzahlen", "werte": p, "annahmen": [], "pruefungen": []}


def kennzahlen_tabelle(ergebnis: dict) -> list[tuple[str, str]]:
    """Rechenergebnis als (Bezeichnung, Wert) für Excel/Diagramme aufbereiten."""
    out: list[tuple[str, str]] = []
    if ergebnis.get("typ") == "co2_bilanz":
        out.append(("Summe Emissionen", f"{ergebnis['summe_t_co2']:.1f} t CO₂/a"))
        for r in ergebnis.get("gruppen", []):
            out.append((r["bezeichnung"], f"{r['t_co2']:.1f} t CO₂/a ({r['anteil_pct']:.1f} %)"))
    elif ergebnis.get("typ") == "opnv_umlauf":
        out += [
            ("Umlaufzeit", f"{ergebnis.get('umlaufzeit_min')} min"),
            ("Fahrzeugbedarf Hauptverkehrszeit", str(ergebnis.get("fahrzeugbedarf_gesamt"))),
            ("Fahrten/Tag", str(ergebnis.get("fahrten_tag"))),
            ("Fahrleistung/Jahr", f"{ergebnis.get('km_jahr'):,.0f} km".replace(",", ".")),
            ("Kostenband", f"{ergebnis.get('kosten_jahr_min'):,.0f}–{ergebnis.get('kosten_jahr_max'):,.0f} €/a"
                .replace(",", ".")),
        ]
    elif ergebnis.get("typ") == "massnahmen_priorisierung":
        for r in ergebnis.get("massnahmen", []):
            out.append((f"{r['rang']}. {r['name']}", f"Score {r['score']} → Priorität {r['prioritaet']}"))
    elif ergebnis.get("typ") == "kostenband":
        out.append(("Gesamtkostenband", f"{ergebnis['kosten_min_eur']:,.0f}–{ergebnis['kosten_max_eur']:,.0f} €"
                    .replace(",", ".")))
    return out
