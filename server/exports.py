"""Artefakt-Erzeugung: Excel (openpyxl), JSON und Markdown-Fallback.

Plan Abschnitt 4.2: Zahlen als Zahlen, Einheiten in den Kopfzeilen, Quellen und
Annahmen als Kommentar, **Zellformeln statt fester Werte** – die Kommune muss
Faktoren selbst ändern können. Deshalb:

  Blatt ``Annahmen``   – editierbare Faktoren und Gewichte (Eingabezellen, gelb)
  Blatt ``Bilanz``     – rechnet mit ``=VLOOKUP(...)`` auf die Annahmen
  Blatt ``Maßnahmen``  – Score als gewichtete Summe der Annahmen-Gewichte
  Blatt ``Hinweise``   – Annahmen, Datenlücken, Quellen (Quelle prüfen!)
  Blatt ``Antworttext``– vollständiger Modelltext (Nachvollziehbarkeit)

Zusätzlich: ``markdown_tabelle_zu_zeilen`` als Fallback für Kacheln ohne
strukturierte Daten und ``json_artefakt`` für die Maschinenweiterverarbeitung.
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from typing import Any

HINWEIS = ("Diese Datei wurde mit SusMob erzeugt (Modell-Entwurf + Rechenkern). "
           "Gelbe Zellen sind Eingaben/Annahmen – alle übrigen Zahlen sind Formeln "
           "darauf. Prüfpflicht: Annahmen, Quellen und Kostenbänder vor Verwendung kontrollieren.")

GELB = "FFF6D5"
GRAU = "EEF2F7"
BLAU = "DCEAFB"


def _sheet_name(name: str, maxlen: int = 31) -> str:
    return re.sub(r"[\[\]:*?/\\]", "-", name)[:maxlen]


def markdown_tabelle_zu_zeilen(text: str) -> list[list[str]]:
    """Markdown-Tabellen aus einer Modellantwort ziehen (Fallback ohne Schema)."""
    rows: list[list[str]] = []
    for line in (text or "").splitlines():
        t = line.strip()
        if not (t.startswith("|") and t.endswith("|") and t.count("|") >= 3):
            continue
        cells = [c.strip().replace("**", "") for c in t.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
            continue
        rows.append(cells)
    return rows


def _md_abschnitte(text: str) -> list[tuple[str, list[str]]]:
    """Antworttext in (Überschrift, Zeilen) zerlegen – für gut lesbare Blätter."""
    out: list[tuple[str, list[str]]] = []
    head, buf = "Zusammenfassung", []
    for line in (text or "").splitlines():
        m = re.match(r"^#{1,4}\s+(.*)", line.strip())
        if m:
            if buf:
                out.append((head, buf))
                buf = []
            head = m.group(1).strip()
            continue
        buf.append(line.rstrip())
    if buf:
        out.append((head, buf))
    return out


def _zahlenwert(zelle: str) -> float | str:
    """'1.234,5' → 1234.5 ; '28,9 %' → 28.9 ; sonst Text."""
    s = str(zelle).strip().replace("**", "")
    if not re.search(r"\d", s):
        return s
    s2 = re.sub(r"[^\d,.\-–]", "", s).replace("–", "-")
    if not s2 or s2 in ("-",):
        return s
    if "," in s2 and "." in s2:
        s2 = s2.replace(".", "").replace(",", ".")
    elif "," in s2:
        s2 = s2.replace(",", ".")
    try:
        return float(s2)
    except ValueError:
        return s


def build_workbook(
    *,
    tile_name: str,
    conversation_title: str = "",
    calc: dict | None = None,
    structured: dict | None = None,
    answer: str = "",
    model: str = "",
    created_at: str | None = None,
) -> bytes:
    """Erzeugt die .xlsx-Datei und gibt sie als Bytes zurück."""
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, PieChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    ts = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    wb = Workbook()
    fett = Font(bold=True)
    titel = Font(bold=True, size=13)
    klein = Font(size=9, color="55606E")
    gelb = PatternFill("solid", fgColor=GELB)
    grau = PatternFill("solid", fgColor=GRAU)
    blau = PatternFill("solid", fgColor=BLAU)
    seite = Side(style="thin", color="B9C3D2")
    rahmen = Border(left=seite, right=seite, top=seite, bottom=seite)
    umbruch = Alignment(wrap_text=True, vertical="top")

    def kopf(ws, zeile: int, werte: list[str], breite: int | None = None) -> None:
        for i, w in enumerate(werte, start=1):
            c = ws.cell(row=zeile, column=i, value=w)
            c.font = fett
            c.fill = grau
            c.border = rahmen
            c.alignment = umbruch
        if breite:
            for i in range(1, breite + 1):
                if not ws.column_dimensions[get_column_letter(i)].width:
                    ws.column_dimensions[get_column_letter(i)].width = 18

    # ---------------------------------------------------------------- Deckblatt
    ws = wb.active
    ws.title = "Ergebnis"
    ws["A1"] = f"SusMob – Ergebnis: {tile_name}"
    ws["A1"].font = titel
    ws["A2"] = conversation_title or "Unterhaltung"
    ws["A3"] = f"Stand: {ts}"
    ws["A4"] = f"Modell: {model or 'n/a'}"
    ws["A6"] = HINWEIS
    ws["A6"].alignment = umbruch
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 60
    zeile = 8
    if calc:
        ws.cell(row=zeile, column=1, value="Berechnete Kennzahlen (Rechenkern, nicht LLM)").font = fett
        zeile += 1
        kopf(ws, zeile, ["Kennzahl", "Wert"])
        zeile += 1
        from server.calc import kennzahlen_tabelle

        for label, wert in kennzahlen_tabelle(calc):
            ws.cell(row=zeile, column=1, value=label)
            ws.cell(row=zeile, column=2, value=wert)
            zeile += 1
        zeile += 1
    zusammenfassung = (structured or {}).get("zusammenfassung") or ""
    if zusammenfassung:
        ws.cell(row=zeile, column=1, value="Zusammenfassung (Modell)").font = fett
        ws.cell(row=zeile + 1, column=1, value=zusammenfassung).alignment = umbruch
        zeile += 3

    # ---------------------------------------------------------------- Annahmen
    wa = wb.create_sheet("Annahmen")
    wa["A1"] = "Annahmen & Faktoren – gelbe Zellen sind Eingaben, alle Ergebnisse hängen per Formel daran"
    wa["A1"].font = fett
    wa.column_dimensions["A"].width = 40
    wa.column_dimensions["B"].width = 16
    wa.column_dimensions["C"].width = 44
    r = 3
    wa.cell(row=r, column=1, value="Emissionsfaktoren (kg CO₂ je Einheit)").font = fett
    r += 1
    kopf(wa, r, ["Kraftstoff/Schlüssel", "Faktor", "Einheit / Hinweis"])
    r += 1
    from server.calc import FAKTOREN

    faktor_start = r
    for key, f in FAKTOREN.items():
        wa.cell(row=r, column=1, value=key)
        zelle = wa.cell(row=r, column=2, value=float(f["ttw"]))
        zelle.fill = gelb
        zelle.border = rahmen
        zelle.number_format = "0.000"
        wa.cell(row=r, column=3, value=f"{f['einheit']} (Tank-to-Wheel; Vorkette {f['wtt']})")
        r += 1
    faktor_ende = r - 1
    r += 1
    wa.cell(row=r, column=1, value="Rechenparameter").font = fett
    r += 1
    for label, val, hint in [
        ("Betriebstage pro Jahr", 300, "für Hochrechnung Tag → Jahr"),
        ("Fahrzeugreserve", 10, "% Aufschlag auf den Fahrzeugbedarf"),
        ("Kalkulationszins", 3.0, "% für Kapitaldienst im TCO-Vergleich"),
    ]:
        wa.cell(row=r, column=1, value=label)
        c = wa.cell(row=r, column=2, value=val)
        c.fill = gelb
        c.border = rahmen
        wa.cell(row=r, column=3, value=hint)
        r += 1
    gewicht_start = None
    if calc and calc.get("typ") == "massnahmen_priorisierung":
        r += 1
        wa.cell(row=r, column=1, value="Gewichtung der Bewertungskriterien").font = fett
        r += 1
        kopf(wa, r, ["Kriterium", "Gewicht"])
        r += 1
        gewicht_start = r
        for k, v in (calc.get("gewichte") or {}).items():
            wa.cell(row=r, column=1, value=k)
            c = wa.cell(row=r, column=2, value=float(v))
            c.fill = gelb
            c.number_format = "0%"
            r += 1
    annahmen = list((structured or {}).get("annahmen") or []) + list((calc or {}).get("annahmen") or [])
    if annahmen:
        r += 1
        wa.cell(row=r, column=1, value="Benannte Annahmen (Modell + Rechenkern)").font = fett
        r += 1
        for a in annahmen:
            wa.cell(row=r, column=1, value=f"• {a}").alignment = umbruch
            r += 1
    pruefungen = list((calc or {}).get("pruefungen") or [])
    if pruefungen:
        r += 1
        wa.cell(row=r, column=1, value="Plausibilitätsprüfungen").font = fett
        r += 1
        for p in pruefungen:
            wa.cell(row=r, column=1, value=f"⚠ {p}").alignment = umbruch
            r += 1

    # ---------------------------------------------------------------- Bilanz (CO₂)
    if calc and calc.get("typ") == "co2_bilanz" and calc.get("gruppen"):
        wb_ = wb.create_sheet("Bilanz")
        wb_["A1"] = "Emissionsbilanz – Faktor wird per VLOOKUP aus dem Blatt „Annahmen“ geholt"
        wb_["A1"].font = fett
        kopf(wb_, 3, ["Gruppe", "Anzahl", "km/Jahr gesamt", "Verbrauch/100 km", "Energie [l/kWh]",
                      "Faktor [kg/Einheit]", "t CO₂/a", "Anteil %", "Formel/Nachweis"])
        zeile = 4
        erste = zeile
        aus_text = calc.get("quelle") == "antworttext"
        for g in calc["gruppen"]:
            km = g.get("km_gesamt")
            verbrauch = g.get("verbrauch_je_100km")
            kraftstoff = g.get("kraftstoff") or ""
            wb_.cell(row=zeile, column=1, value=g.get("bezeichnung", ""))
            wb_.cell(row=zeile, column=2, value=g.get("anzahl"))
            if km is not None:
                wb_.cell(row=zeile, column=3, value=km).number_format = "#,##0"
            if verbrauch is not None:
                wb_.cell(row=zeile, column=4, value=verbrauch).number_format = "0.00"
            if km and verbrauch:
                wb_.cell(row=zeile, column=5, value=f"=C{zeile}*D{zeile}/100").number_format = "#,##0"
            elif g.get("energie_menge") is not None:
                wb_.cell(row=zeile, column=5, value=g.get("energie_menge")).number_format = "#,##0"
            if kraftstoff in FAKTOREN:
                wb_.cell(row=zeile, column=6,
                         value=f'=IFERROR(VLOOKUP("{kraftstoff}",Annahmen!$A${faktor_start}:$C${faktor_ende},2,FALSE),'
                               f'Annahmen!$B${faktor_start})').number_format = "0.000"
            elif g.get("faktor"):
                text = str(g["faktor"])
                zahl = re.search(r"\d+[.,]?\d*", text)
                if zahl:
                    wert = float(zahl.group(0).replace(",", "."))
                    if re.search(r"\bg(/|\b)", text, re.I) or "g co" in text.lower():
                        wert /= 1000.0      # "372 g CO₂/kWh" → 0,372 kg CO₂/kWh
                    wb_.cell(row=zeile, column=6, value=wert).number_format = "0.000"
                    wb_.cell(row=zeile, column=9, value=f"Quelle im Antworttext: {text}").alignment = umbruch
            if not aus_text and km:
                wb_.cell(row=zeile, column=7, value=f"=E{zeile}*F{zeile}/1000").number_format = "#,##0.0"
            elif g.get("t_co2") is not None:
                wb_.cell(row=zeile, column=7, value=g["t_co2"]).number_format = "#,##0.0"
            if g.get("anteil_pct") is not None:
                if aus_text:
                    wb_.cell(row=zeile, column=8, value=float(g["anteil_pct"]) / 100.0).number_format = "0.0%"
                else:
                    wb_.cell(row=zeile, column=8,
                             value=f"=G{zeile}/SUM($G${erste}:$G${erste + len(calc['gruppen']) - 1})").number_format = "0.0%"
            if not aus_text:
                wb_.cell(row=zeile, column=9, value=g.get("formel", "")).alignment = umbruch
            zeile += 1
        summe = zeile
        wb_.cell(row=summe, column=1, value="Summe").font = fett
        if aus_text:
            wb_.cell(row=summe, column=7, value=calc.get("summe_t_co2")).font = fett
        else:
            wb_.cell(row=summe, column=7, value=f"=SUM(G{erste}:G{zeile - 1})").font = fett
        wb_.cell(row=summe, column=7).number_format = "#,##0.0"
        wb_.cell(row=summe, column=8, value=f"=SUM(H{erste}:H{zeile - 1})").number_format = "0.0%"
        wb_.cell(row=summe + 2, column=1,
                 value="Ändere einen Faktor im Blatt „Annahmen“ – alle t CO₂/a und Anteile rechnen sich neu.")
        wb_.cell(row=summe + 2, column=1).font = klein
        if calc.get("well_to_tank"):
            wb_.cell(row=summe, column=9,
                     value=f"Vorkette gesamt: {calc.get('summe_t_co2_vorkette')} t CO₂/a (separat ausgewiesen)")
        for i, w in enumerate([30, 8, 16, 16, 14, 16, 12, 10, 46], start=1):
            wb_.column_dimensions[get_column_letter(i)].width = w
        chart = BarChart()
        chart.title = "t CO₂/a je Gruppe"
        chart.height, chart.width = 8, 16
        chart.add_data(Reference(wb_, min_col=7, min_row=3, max_row=summe - 1), titles_from_data=True)
        chart.set_categories(Reference(wb_, min_col=1, min_row=erste, max_row=summe - 1))
        wb_.add_chart(chart, f"A{summe + 5}")
        pie = PieChart()
        pie.title = "Anteile"
        pie.height, pie.width = 8, 12
        pie.add_data(Reference(wb_, min_col=7, min_row=3, max_row=summe - 1), titles_from_data=True)
        pie.set_categories(Reference(wb_, min_col=1, min_row=erste, max_row=summe - 1))
        wb_.add_chart(pie, f"J{summe + 5}")

    # ---------------------------------------------------------------- Maßnahmen
    if calc and calc.get("typ") == "massnahmen_priorisierung" and calc.get("massnahmen"):
        wm = wb.create_sheet("Maßnahmen")
        wm["A1"] = "Maßnahmenkatalog – Score ist eine gewichtete Summe der Gewichte aus „Annahmen“"
        wm["A1"].font = fett
        kopf(wm, 3, ["Rang", "Maßnahme", "Wirkung", "Sicherheit", "Kosten", "Aufwand", "Akzeptanz",
                     "Score", "Priorität", "Kostenband", "Zeitrahmen", "KPI", "Hinweis"])
        zeile = 4
        erste = zeile
        for m in calc["massnahmen"]:
            w = m["werte"]
            wm.cell(row=zeile, column=1, value=m["rang"])
            wm.cell(row=zeile, column=2, value=m["name"])
            for i, key in enumerate(["wirkung", "sicherheit", "kosten", "aufwand", "akzeptanz"], start=3):
                c = wm.cell(row=zeile, column=i, value=w.get(key))
                c.fill = gelb
            if gewicht_start:
                wm.cell(row=zeile, column=8, value=(
                    f"=C{zeile}*Annahmen!$B${gewicht_start}+D{zeile}*Annahmen!$B${gewicht_start + 1}"
                    f"+E{zeile}*Annahmen!$B${gewicht_start + 2}+F{zeile}*Annahmen!$B${gewicht_start + 3}"
                    f"+G{zeile}*Annahmen!$B${gewicht_start + 4}")).number_format = "0.00"
            else:
                wm.cell(row=zeile, column=8, value=m["score"]).number_format = "0.00"
            wm.cell(row=zeile, column=9, value=f'=IF(H{zeile}>=3.8,"hoch",IF(H{zeile}>=3,"mittel","niedrig"))')
            wm.cell(row=zeile, column=10, value=m.get("kosten_band", ""))
            wm.cell(row=zeile, column=11, value=m.get("zeitrahmen", ""))
            wm.cell(row=zeile, column=12, value=m.get("kpi", ""))

            zelle = wm.cell(row=zeile, column=13, value=m.get("hinweis", ""))
            zelle.alignment = umbruch
            if m.get("wirkung_text"):
                from openpyxl.comments import Comment

                zelle.comment = Comment(str(m["wirkung_text"])[:900], "SusMob")
            zeile += 1
        for i, w in enumerate([6, 34, 9, 11, 8, 9, 10, 8, 10, 18, 14, 24, 30], start=1):
            wm.column_dimensions[get_column_letter(i)].width = w
        from openpyxl.chart import BarChart, Reference

        chart = BarChart()
        chart.title = "Score je Maßnahme"
        chart.add_data(Reference(wm, min_col=8, min_row=3, max_row=zeile - 1), titles_from_data=True)
        chart.set_categories(Reference(wm, min_col=2, min_row=erste, max_row=zeile - 1))
        chart.height, chart.width = 9, 20
        wm.add_chart(chart, f"B{zeile + 2}")

    # ---------------------------------------------------------------- Kostenband
    if calc and calc.get("typ") == "kostenband" and calc.get("abschnitte"):
        wk = wb.create_sheet("Kosten")
        wk["A1"] = "Kostenband je Abschnitt – €/m sind Eingabezellen"
        wk["A1"].font = fett
        kopf(wk, 3, ["Abschnitt", "Länge [m]", "€/m min", "€/m max", "Kosten min [€]", "Kosten max [€]", "Mittel [€]",
                      "Trennungsform", "Hinweis"])
        zeile = 4
        erste = zeile
        je_meter = bool(calc["abschnitte"] and calc["abschnitte"][0].get("kosten_min_eur_pro_m") is not None)
        for a in calc["abschnitte"]:
            wk.cell(row=zeile, column=1, value=a.get("abschnitt", ""))
            if a.get("laenge_m") is not None:
                wk.cell(row=zeile, column=2, value=a["laenge_m"]).number_format = "#,##0"
            if je_meter:
                wk.cell(row=zeile, column=3, value=a["kosten_min_eur_pro_m"]).fill = gelb
                wk.cell(row=zeile, column=4, value=a["kosten_max_eur_pro_m"]).fill = gelb
                wk.cell(row=zeile, column=5, value=f"=B{zeile}*C{zeile}").number_format = "#,##0 €"
                wk.cell(row=zeile, column=6, value=f"=B{zeile}*D{zeile}").number_format = "#,##0 €"
            else:
                # Band kam bereits als Summe (z. B. "96–240 k€") – Eingabezellen, damit änderbar
                wk.cell(row=zeile, column=5, value=a.get("kosten_min_eur")).fill = gelb
                wk.cell(row=zeile, column=6, value=a.get("kosten_max_eur")).fill = gelb
                wk.cell(row=zeile, column=5).number_format = "#,##0 €"
                wk.cell(row=zeile, column=6).number_format = "#,##0 €"
            wk.cell(row=zeile, column=7, value=f"=(E{zeile}+F{zeile})/2").number_format = "#,##0 €"
            wk.cell(row=zeile, column=8, value=a.get("trennungsform", ""))
            wk.cell(row=zeile, column=9, value=a.get("hinweis", "")).alignment = umbruch
            zeile += 1
        wk.cell(row=zeile, column=1, value="Summe").font = fett
        for col in (5, 6, 7):
            wk.cell(row=zeile, column=col, value=f"=SUM({get_column_letter(col)}{erste}:{get_column_letter(col)}{zeile - 1})"
                    ).number_format = "#,##0 €"
        for i, w in enumerate([30, 14, 12, 12, 16, 16, 16, 30, 46], start=1):
            wk.column_dimensions[get_column_letter(i)].width = w

    # ---------------------------------------------------------------- Hinweise
    wh = wb.create_sheet("Hinweise")
    wh["A1"] = "Prüfpflichten, Annahmen und Quellen"
    wh["A1"].font = fett
    wh.column_dimensions["A"].width = 120
    zeile = 3
    for titel_text, eintraege in [
        ("Annahmen", annahmen),
        ("Datenlücken / Plausibilität", pruefungen + list((structured or {}).get("datenluecken") or [])),
        ("Quellen („Quelle prüfen“ = ungeprüft)", list((structured or {}).get("quellen") or [])),
        ("Nächste Schritte", list((structured or {}).get("naechste_schritte") or [])),
    ]:
        if not eintraege:
            continue
        wh.cell(row=zeile, column=1, value=titel_text).font = fett
        zeile += 1
        for e in eintraege:
            c = wh.cell(row=zeile, column=1, value=f"• {e}")
            c.alignment = umbruch
            zeile += 1
        zeile += 1

    # ---------------------------------------------------------------- Antworttext
    if answer:
        wt = wb.create_sheet("Antworttext")
        wt["A1"] = "Vollständige Modellantwort (Nachvollziehbarkeit)"
        wt["A1"].font = fett
        wt.column_dimensions["A"].width = 130
        zeile = 3
        for head, lines in _md_abschnitte(answer):
            wt.cell(row=zeile, column=1, value=head).font = fett
            zeile += 1
            tabelle = [l for l in lines if l.strip().startswith("|")]
            rest = [l for l in lines if not l.strip().startswith("|")]
            for line in rest:
                if line.strip():
                    c = wt.cell(row=zeile, column=1, value=line.strip())
                    c.alignment = umbruch
                    zeile += 1
            if tabelle:
                zeile += 1
                for row in markdown_tabelle_zu_zeilen("\n".join(tabelle)):
                    for i, zelle in enumerate(row, start=1):
                        c = wt.cell(row=zeile, column=i, value=_zahlenwert(zelle))
                        c.border = rahmen
                    zeile += 1
                zeile += 1
        # Fallback: Markdown-Tabelle, falls keine erkannt wurde
        tabellen = markdown_tabelle_zu_zeilen(answer)
        if tabellen:
            wt.cell(row=zeile + 1, column=1, value="Tabelle(n) aus der Antwort (maschinenlesbar)").font = fett
            zeile += 2
            for row in tabellen:
                for i, zelle in enumerate(row, start=1):
                    c = wt.cell(row=zeile, column=i, value=_zahlenwert(zelle))
                    c.border = rahmen
                zeile += 1

    for ws_ in wb.worksheets:
        ws_.sheet_view.showGridLines = False
        ws_.freeze_panes = "A2" if ws_.title in ("Ergebnis",) else ws_.freeze_panes

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def json_artefakt(tile_name: str, calc: dict | None, structured: dict | None, answer: str = "",
                  model: str = "") -> bytes:
    payload = {
        "erzeugt_mit": "SusMob",
        "kachel": tile_name,
        "stand": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "modell": model,
        "rechenkern": calc or {},
        "strukturierte_daten": structured or {},
        "antworttext": answer,
        "hinweis": HINWEIS,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def dateiname(tile_id: str, kind: str, titel: str = "") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{tile_id}-{titel}".strip("-")).strip("-")[:60] or tile_id
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"{safe}-{stamp}.{kind}"
