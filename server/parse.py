"""Antworttext-Parser: Zahlen aus der Modellantwort ziehen – ohne LLM-Call.

Zwei Wege führen zu einem Export (Plan Abschnitt 4.1):

1. **Structured Output** (``chat_json`` + Schema) → sauber, Vorrang.
2. **Dieser Parser** → liest die Standard-Tabellen der SusMob-Prompts aus der
   Antwort. Damit funktioniert der Export auch ohne Netz/Key (Demo, Beispiele)
   und ohne zusätzliche Tokens.

Was der Parser liefert, ist **nicht nachgerechnet**. Das wird im Ergebnis mit
``quelle: "antworttext"`` und einem Prüfhinweis gekennzeichnet – Ehrlichkeit vor
Optik (der Rechenkern bleibt die Wahrheit).
"""
from __future__ import annotations

import re

from server.calc import FAKTOREN, _num

def _zahl(zelle: str):
    """Zahl aus einer Tabellenzelle lesen – Text liefert None."""
    return _num(zelle, None)


PRUEFHINWEIS = ("Zahlen unverändert aus dem Antworttext übernommen – NICHT im Rechenkern "
                "nachgerechnet. Für belastbare Zahlen „Auswerten & rechnen“ mit Internet/API-Key nutzen.")


def _tabellen(text: str) -> list[list[list[str]]]:
    """Alle Markdown-Tabellen des Textes als Liste von Zeilen (ohne Trennzeile)."""
    tabellen, aktuell = [], []
    for line in (text or "").splitlines():
        t = line.strip()
        if t.startswith("|") and t.endswith("|") and t.count("|") >= 3:
            zellen = [c.strip().replace("**", "") for c in t.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in zellen):
                continue
            aktuell.append(zellen)
            continue
        if aktuell:
            tabellen.append(aktuell)
            aktuell = []
    if aktuell:
        tabellen.append(aktuell)
    return tabellen


def _spalte(header: list[str], *muster: str) -> int | None:
    """Erste Spalte, deren Titel alle Muster enthält (0 ist ein gültiger Index!)."""
    for i, h in enumerate(header):
        hh = h.lower()
        if all(m in hh for m in muster):
            return i
    return None


def _eine_spalte(header: list[str], *muster_gruppen: tuple[str, ...]) -> int | None:
    """Erste passende Spalte über mehrere Musterkombinationen hinweg."""
    for muster in muster_gruppen:
        i = _spalte(header, *muster)
        if i is not None:
            return i
    return None


def co2_aus_antwort(text: str) -> dict | None:
    """Bilanz-Tabelle (Verkehrsträger | … | t CO₂/a | Anteil %) in ein Rechenobjekt wandeln."""
    for tabelle in _tabellen(text):
        if len(tabelle) < 2:
            continue
        header = tabelle[0]
        i_name = _eine_spalte(header, ("verkehrsträger",), ("gruppe",), ("fahrzeug",)) or 0
        i_t = _eine_spalte(header, ("t co",), ("co₂/a",), ("co2/a",), ("emission",), ("t co₂",))
        if i_t is None:
            continue
        i_anteil = _eine_spalte(header, ("anteil",))
        i_faktor = _eine_spalte(header, ("faktor",), ("emissionsfaktor",))
        i_akt = _eine_spalte(header, ("aktivität",), ("aktivitaet",), ("fahrleistung",), ("km",))
        gruppen, summe = [], 0.0
        for zeile in tabelle[1:]:
            if len(zeile) <= i_t:
                continue
            name = zeile[i_name]
            if not name or name.lower().startswith("summe"):
                continue
            wert = _zahl(zeile[i_t])
            if not isinstance(wert, (int, float)):
                continue
            summe += float(wert)
            gruppen.append({
                "bezeichnung": name,
                "t_co2": round(float(wert), 2),
                "anteil_pct": _zahl(zeile[i_anteil]) if i_anteil is not None and i_anteil < len(zeile) else None,
                "faktor": zeile[i_faktor] if i_faktor is not None and i_faktor < len(zeile) else "",
                "aktivitaet": zeile[i_akt] if i_akt is not None and i_akt < len(zeile) else "",
                "formel": "aus Antworttext übernommen",
            })
        if not gruppen:
            continue
        gesamt = summe or 1.0
        for g in gruppen:
            if g["anteil_pct"] is None:
                g["anteil_pct"] = round(g["t_co2"] / gesamt * 100, 1)
        gruppen.sort(key=lambda g: -g["t_co2"])
        return {
            "typ": "co2_bilanz",
            "gruppen": gruppen,
            "summe_t_co2": round(summe, 2),
            "summe_t_co2_vorkette": 0.0,
            "summe_t_co2_gesamt": round(summe, 2),
            "faktoren": {k: v["ttw"] for k, v in FAKTOREN.items()},
            "annahmen": ["Werte aus dem Antworttext des Modells übernommen."],
            "pruefungen": [PRUEFHINWEIS],
            "quelle": "antworttext",
            "rechenweg": "unbekannt (Antworttext)",
        }
    return None


# Reihenfolge = Prüfreihenfolge: spezifische Kombinationen zuerst („mittel–hoch" ≠ „hoch")
STUFEN = {"sehr hoch": 5.0, "mittel-hoch": 3.5, "mittel–hoch": 3.5, "niedrig-mittel": 2.0,
          "niedrig–mittel": 2.0, "sehr niedrig": 1.0, "hoch": 4.5, "mittel": 3.0, "niedrig": 1.5}


def _stufe(text: str) -> float | None:
    """Qualitative Bewertung („hoch", „mittel–hoch") in eine 1–5-Stufe übersetzen."""
    t = (text or "").lower()
    if not t.strip() or t.strip() in ("–", "-", "n/a"):
        return None
    for wort, wert in STUFEN.items():
        if wort in t:
            return wert
    return None


def _kosten_stufe(band: str) -> float | None:
    """Kostenband in eine 1–5-Stufe (5 = sehr günstig) übersetzen."""
    werte = _geld(band)
    if not werte:
        return None
    mitte = (werte[0] + werte[-1]) / 2.0
    for grenze, stufe in [(100_000, 5.0), (500_000, 4.0), (1_500_000, 3.0), (5_000_000, 2.0)]:
        if mitte < grenze:
            return stufe
    return 1.0


def _aufwand_stufe(text: str) -> float | None:
    """Zeitrahmen in eine 1–5-Stufe (5 = sehr schnell) übersetzen."""
    t = (text or "").lower()
    if not t:
        return None
    if "sofort" in t or "unter 1" in t or "< 1" in t:
        return 5.0
    jahre = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", t)]
    if "laufend" in t:
        return 3.0
    if not jahre:
        return 3.0
    gross = max(jahre)
    for grenze, stufe in [(1, 4.5), (2, 3.5), (3, 2.5), (5, 2.0), (10, 1.5)]:
        if gross <= grenze:
            return stufe
    return 1.0


def massnahmen_aus_antwort(text: str) -> dict | None:
    """Maßnahmenkatalog-Tabelle (Maßnahme | Wirkung | Kosten | Priorität) erfassen."""
    for tabelle in _tabellen(text):
        if len(tabelle) < 2:
            continue
        header = tabelle[0]
        i_name = _eine_spalte(header, ("maßnahme",), ("massnahme",), ("maßnahmen",), ("massnahmen",))
        if i_name is None:
            continue
        i_wirkung = _eine_spalte(header, ("wirkung",))
        i_kosten = _eine_spalte(header, ("kosten",))
        i_prio = _eine_spalte(header, ("priorit",))
        i_zeit = _eine_spalte(header, ("aufwand",), ("phase",), ("zeit",))
        i_kpi = _eine_spalte(header, ("kpi",), ("indikator",))
        i_score = _eine_spalte(header, ("score",), ("nutzwert",), ("punkte",))
        eintraege = []
        for zeile in tabelle[1:]:
            if len(zeile) <= i_name or not zeile[i_name]:
                continue
            def zelle(idx: int | None) -> str:
                return zeile[idx].strip() if idx is not None and idx < len(zeile) else ""

            eintraege.append({
                "name": zeile[i_name].strip(),
                "wirkung_text": zelle(i_wirkung),
                "kosten_band": zelle(i_kosten),
                "zeitrahmen": zelle(i_zeit),
                "kpi": zelle(i_kpi),
                "prioritaet_aus_antwort": zelle(i_prio).lower(),
                "score_aus_antwort": _zahl(zelle(i_score)),
            })
        if not eintraege:
            continue
        def rang(e):
            return {"hoch": 0, "mittel": 1, "niedrig": 2}.get(e["prioritaet_aus_antwort"], 3)
        eintraege.sort(key=rang)
        # Bewertungen aus dem Text ableiten und die Priorisierung im Rechenkern
        # durchführen (Zahlen entstehen im Code, nicht im Modell).
        from server.calc import massnahmen_priorisierung

        eingabe = []
        for e in eintraege:
            wirkung = _stufe(e["wirkung_text"])
            eingabe.append({
                "name": e["name"],
                "wirkung": wirkung if wirkung is not None else 3.0,
                "sicherheit": wirkung if wirkung is not None else 3.0,
                "kosten": _kosten_stufe(e["kosten_band"]) or 3.0,
                "aufwand": _aufwand_stufe(e["zeitrahmen"]) or 3.0,
                "akzeptanz": 3.0,
                "kosten_band": e["kosten_band"],
                "zeitrahmen": e["zeitrahmen"],
                "kpi": e["kpi"],
                "wirkung_text": e["wirkung_text"],
            })
        ergebnis = massnahmen_priorisierung(eingabe)
        nach_name = {e["name"]: e for e in eintraege}
        for m in ergebnis["massnahmen"]:
            e = nach_name.get(m["name"], {})
            aus_text = e.get("prioritaet_aus_antwort") or ""
            m["prioritaet_aus_antwort"] = aus_text
            if aus_text and aus_text != m["prioritaet"]:
                prio_kern = m["prioritaet"]
                m["hinweis"] = ("Modell nennt Priorität „" + aus_text + "“, Rechenkern „"
                                + prio_kern + "“ – Bewertungen prüfen.")
        # Reihenfolge: Priorität aus dem Antworttext (dort steckt der Kontext des Modells),
        # bei Gleichstand entscheidet der nachgerechnete Score.
        rang_prio = {"hoch": 0, "mittel": 1, "niedrig": 2}
        ergebnis["massnahmen"].sort(key=lambda m: (rang_prio.get(m.get("prioritaet_aus_antwort", ""), 3),
                                                   -float(m.get("score") or 0)))
        for i, m in enumerate(ergebnis["massnahmen"], start=1):
            m["rang"] = i
        ergebnis["annahmen"] = [
            "Reihenfolge folgt der Priorität aus dem Antworttext; der Score ist eine im Rechenkern "
            "nachgerechnete Nutzwertanalyse zur Kontrolle (Wirkung/Kosten/Aufwand aus dem Text in "
            "1–5-Stufen übersetzt).",
            "Fehlende Einzelbewertungen (Sicherheit, Akzeptanz) sind mit 3 = mittel angesetzt.",
        ]
        ergebnis["pruefungen"] = [PRUEFHINWEIS]
        ergebnis["quelle"] = "antworttext"
        return ergebnis
    return None


def _geld(text: str) -> list[float]:
    """Kostenband aus Text lesen: '96–240 k€' → [96000, 240000] (in €)."""
    if not text:
        return []
    faktor = 1.0
    if re.search(r"mio|m€", text, re.I):
        faktor = 1_000_000.0
    elif re.search(r"k€|tsd", text, re.I):
        faktor = 1_000.0
    zahlen = re.findall(r"\d+(?:[.,]\d+)?", text)
    werte = []
    for z in zahlen[:2]:
        wert = _num(z, None)
        if wert is not None:
            werte.append(float(wert) * faktor)
    return werte


def kostenband_aus_antwort(text: str) -> dict | None:
    """Trassen-/Abschnittstabelle mit Kostenband in ein Rechenobjekt wandeln."""
    for tabelle in _tabellen(text):
        if len(tabelle) < 2:
            continue
        header = tabelle[0]
        i_name = _eine_spalte(header, ("abschnitt",), ("trasse",), ("bauabschnitt",))
        if i_name is None:
            continue
        i_laenge = _eine_spalte(header, ("länge",), ("laenge",))
        i_kosten = _eine_spalte(header, ("kosten",), ("kostenband",), ("preis",))
        i_form = _eine_spalte(header, ("trennungsform",), ("ausführung",), ("ausfuehrung",))
        i_hinweis = _eine_spalte(header, ("hinweis",), ("anmerkung",), ("bemerkung",))
        if i_kosten is None and i_laenge is None:
            continue
        abschnitte, min_summe, max_summe = [], 0.0, 0.0
        for zeile in tabelle[1:]:
            def zelle(idx):
                return zeile[idx].strip() if idx is not None and idx < len(zeile) else ""
            name = zelle(i_name)
            if not name:
                continue
            laenge = _zahl(zelle(i_laenge)) if i_laenge is not None else None
            band = _geld(zelle(i_kosten))
            if not band and laenge is None:
                continue
            if band:
                min_summe += band[0]
                max_summe += band[-1]
            abschnitte.append({
                "abschnitt": name,
                "laenge_m": laenge,
                "trennungsform": zelle(i_form),
                "kosten_min_eur": band[0] if band else None,
                "kosten_max_eur": band[-1] if len(band) > 1 else (band[0] if band else None),
                "hinweis": zelle(i_hinweis),
            })
        if not abschnitte:
            continue
        return {
            "typ": "kostenband",
            "abschnitte": abschnitte,
            "kosten_min_eur": round(min_summe, 0),
            "kosten_max_eur": round(max_summe, 0),
            "kosten_mittel_eur": round((min_summe + max_summe) / 2.0, 0),
            "einheit": "€ (Band aus dem Antworttext)",
            "annahmen": ["Kostenbänder aus dem Antworttext übernommen."],
            "pruefungen": [PRUEFHINWEIS],
            "quelle": "antworttext",
        }
    return None


def kennzahlen_aus_antwort(text: str) -> dict | None:
    """Kennzahlen-Zeilen („- Umlaufzeit: 118 min“) für Kacheln ohne Tabellenschema."""
    werte: dict[str, str] = {}
    for m in re.finditer(r"^[\-\*•\s]*\*{0,2}([A-ZÄÖÜ][^:\n]{2,60})\*{0,2}:\s*\*{0,2}([^\n]{1,80})", text or "", re.M):
        label, wert = m.group(1).strip(), m.group(2).strip().rstrip("*").strip()
        if re.search(r"\d", wert) or re.search(r"\d", label):
            werte.setdefault(label, wert)
    if len(werte) < 3:
        return None
    return {"typ": "kennzahlen_aus_text", "werte": werte,
            "annahmen": ["Werte aus dem Antworttext des Modells übernommen."],
            "pruefungen": [PRUEFHINWEIS], "quelle": "antworttext"}


def parse(tile_id: str, text: str) -> dict | None:
    """Passenden Parser für die Kachel wählen."""
    if not text:
        return None
    if tile_id == "co2-bilanz":
        return co2_aus_antwort(text)
    if tile_id == "massnahmenplanung":
        return massnahmen_aus_antwort(text)
    if tile_id == "wegeplanung":
        return kostenband_aus_antwort(text) or kennzahlen_aus_antwort(text)
    return kennzahlen_aus_antwort(text)
