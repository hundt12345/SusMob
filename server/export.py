"""Artefakt-Erzeugung (Phase 1 des Plans): Excel mit Formeln, CSV, JSON, SVG, Druck-HTML.

Grundsatz: Zahlen entstehen im Rechenkern (``server/rechner.py``) bzw. im
validierten Ergebnis-JSON – der Renderer rechnet nicht, er stellt dar.

* **Excel** – Blätter ``Annahmen`` (editierbare Faktoren), ``Eingangsdaten``,
  ``Bilanz`` (mit **Zellformeln** auf die Annahmen), ``Maßnahmen``, ``Quellen``;
  Zahlen als Zahlen, Einheiten in den Kopfzeilen, Zellkommentare mit Quelle.
* **CSV/JSON/Markdown** – Datenexport für Weiterverarbeitung.
* **SVG** – Donut-/Balkendiagramme ohne Fremdbibliothek (client- und druckfähig).
* **Druck-HTML** – PDF-Weg A aus dem Plan (Druck-CSS, ``window.print()``), ohne
  Systembibliotheken wie Pango/Cairo.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from server import db, schemas

HEAD_FILL = PatternFill("solid", fgColor="1F3B57")
HEAD_FONT = Font(color="FFFFFF", bold=True)
NOTE_FONT = Font(italic=True, color="555555")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ Excel


def build_xlsx(tile_id: str, data: dict, title: str = "") -> bytes:
    """Excel-Arbeitsmappe: Annahmen editierbar, Zahlen per Formel verknüpft."""
    model = schemas.model_for(tile_id)
    obj = model.model_validate(data) if not isinstance(data, model) else data
    d = obj.model_dump()
    wb = Workbook()

    # --- Annahmen zuerst (damit Formeln darauf verweisen können) -----------
    ws_a = wb.active
    ws_a.title = "Annahmen"
    ws_a["A1"] = "Annahmen – hier ändern, alle anderen Blätter rechnen damit"
    ws_a["A1"].font = Font(bold=True, size=12)
    ws_a["A2"] = "Wert"
    ws_a["B2"] = "Einheit"
    ws_a["C2"] = "Hinweis"
    for c in ("A2", "B2", "C2"):
        ws_a[c].fill = HEAD_FILL
        ws_a[c].font = HEAD_FONT
    annahmen = list(d.get("annahmen") or [])
    faktor_zellen: dict[str, str] = {}
    if tile_id == "co2-bilanz":
        rows = [
            ("Emissionsfaktor Diesel", 2680, "g CO₂/l", "Verbrennung ohne Vorkette (UBA-Bandbreite 2.600–2.700)"),
            ("Emissionsfaktor Benzin", 2380, "g CO₂/l", "Verbrennung ohne Vorkette"),
            ("Strommix-Faktor", 372, "g CO₂/kWh", "UBA-Standardwert – in der Kommune prüfen"),
            ("Pkw-Besetzungsgrad", 1.1, "Personen", "DE-Flottenmittelwert"),
        ]
        for i, (name, wert, einheit, hinweis) in enumerate(rows, start=3):
            ws_a.cell(row=i, column=1, value=name)
            ws_a.cell(row=i, column=2, value=wert)
            ws_a.cell(row=i, column=3, value=einheit)
            ws_a.cell(row=i, column=4, value=hinweis)
            if "Diesel" in name:
                faktor_zellen["l-diesel"] = f"Annahmen!$B${i}"
            elif "Benzin" in name:
                faktor_zellen["l-benzin"] = f"Annahmen!$B${i}"
            elif "Strommix" in name:
                faktor_zellen["elektro"] = f"Annahmen!$B${i}"
    start = 3 + (4 if tile_id == "co2-bilanz" else 0)
    ws_a.cell(row=start, column=1, value="Weitere Annahmen (Text, aus dem Ergebnisdokument)")
    ws_a.cell(row=start, column=1).font = Font(bold=True)
    for i, a in enumerate(annahmen, start=start + 1):
        ws_a.cell(row=i, column=1, value=str(a))
    ws_a.column_dimensions["A"].width = 52
    ws_a.column_dimensions["B"].width = 14
    ws_a.column_dimensions["C"].width = 16
    ws_a.column_dimensions["D"].width = 60

    # --- Eingangsdaten ----------------------------------------------------
    ws_e = wb.create_sheet("Eingangsdaten")
    ws_e["A1"] = "Eingangsdaten (Angaben der Kommune)"
    ws_e["A1"].font = Font(bold=True, size=12)
    eingaben = d.get("eingaben") or {}
    ws_e["A2"] = "Größe"
    ws_e["B2"] = "Wert"
    for c in ("A2", "B2"):
        ws_e[c].fill = HEAD_FILL
        ws_e[c].font = HEAD_FONT
    if eingaben:
        for k, v in eingaben.items():
            ws_e.append([k, v])
    else:
        ws_e["A3"] = "Keine expliziten Eingaben übergeben."
    ws_e.column_dimensions["A"].width = 42
    ws_e.column_dimensions["B"].width = 24

    # --- Fachliche Blätter ------------------------------------------------
    rows_by_sheet = schemas.flat_rows(tile_id, d)
    for sheet_name, rows in rows_by_sheet.items():
        if sheet_name == "Annahmen" and "Annahmen" in wb.sheetnames:
            sheet_name = "Annahmen_Texte"  # Faktoren-Blatt nicht überschreiben
        ws = wb.create_sheet(sheet_name[:31])
        if not rows:
            continue
        cols = list(rows[0].keys())
        heads = [c.replace("_", " ") for c in cols]
        ws.append(heads)
        for c in range(1, len(cols) + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = HEAD_FILL
            cell.font = HEAD_FONT
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for r in rows:
            ws.append([r.get(c) for c in cols])
        for idx, c in enumerate(cols, start=1):
            width = max(14, min(48, len(str(c)) + 6))
            ws.column_dimensions[get_column_letter(idx)].width = width
        ws.freeze_panes = "A2"
        if sheet_name == "Bilanz" and tile_id == "co2-bilanz":
            # Formeln statt fester Werte + Anteil + Summe
            col_co2 = cols.index("co2_t_jahr") + 1 if "co2_t_jahr" in cols else None
            col_energie = cols.index("energieverbrauch") + 1 if "energieverbrauch" in cols else None
            col_einheit = cols.index("energie_einheit") + 1 if "energie_einheit" in cols else None
            col_anteil = cols.index("anteil_prozent") + 1 if "anteil_prozent" in cols else None
            col_vt = 1
            for r_i in range(2, len(rows) + 2):
                if col_co2 and col_energie and col_einheit:
                    vt = str(ws.cell(row=r_i, column=col_vt).value or "")
                    ref = faktor_zellen.get("l-benzin" if "Benzin" in vt else
                                            ("l-diesel" if "Diesel" in vt else "elektro"))
                    if ref:
                        ws.cell(row=r_i, column=col_co2).value = (
                            f"={get_column_letter(col_energie)}{r_i}*{ref}/1000000"
                        )
                        ws.cell(row=r_i, column=col_co2).comment = Comment(
                            "Berechnet aus Energieverbrauch × Faktor (Blatt Annahmen)", "SusMob"
                        )
                ws.cell(row=r_i, column=col_co2).number_format = "#,##0.00"
            if col_co2 and col_anteil:
                total_row = len(rows) + 2
                ws.cell(row=total_row, column=col_vt, value="Summe").font = Font(bold=True)
                ws.cell(row=total_row, column=col_co2).value = (
                    f"=SUM({get_column_letter(col_co2)}2:{get_column_letter(col_co2)}{total_row - 1})"
                )
                ws.cell(row=total_row, column=col_co2).font = Font(bold=True)
                ws.cell(row=total_row, column=col_co2).number_format = "#,##0.00"
                for r_i in range(2, len(rows) + 2):
                    ws.cell(row=r_i, column=col_anteil).value = (
                        f"=IF({get_column_letter(col_co2)}${total_row}=0,0,"
                        f"{get_column_letter(col_co2)}{r_i}/{get_column_letter(col_co2)}${total_row}*100)"
                    )
                    ws.cell(row=r_i, column=col_anteil).number_format = "0.0"
                # Balkendiagramm auf Basis der Bilanz
                chart = BarChart()
                chart.title = "CO₂ je Verkehrsträger [t/a]"
                chart.y_axis.title = "t CO₂/a"
                data_ref = Reference(ws, min_col=col_co2, min_row=1, max_row=len(rows) + 1)
                cats = Reference(ws, min_col=col_vt, min_row=2, max_row=len(rows) + 1)
                chart.add_data(data_ref, titles_from_data=True)
                chart.set_categories(cats)
                ws.add_chart(chart, f"{get_column_letter(len(cols) + 2)}2")
    # --- Kopfblatt ---------------------------------------------------------
    ws_i = wb.create_sheet("Ergebnis", 0)
    ws_i["A1"] = title or d.get("titel") or "Ergebnis"
    ws_i["A1"].font = Font(bold=True, size=14)
    meta = [
        ("Kachel", tile_id),
        ("Erzeugt", _now()),
        ("Modell/Quelle", "SusMob – Zahlen aus Rechenkern bzw. validiertem Ergebnisdokument"),
    ]
    r = 3
    for k, v in meta:
        ws_i.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws_i.cell(row=r, column=2, value=v)
        r += 1
    if d.get("zusammenfassung"):
        ws_i.cell(row=r + 1, column=1, value="Zusammenfassung").font = Font(bold=True)
        ws_i.cell(row=r + 2, column=1, value=str(d["zusammenfassung"]))
    for k in ("beschlussvorschlag", "sachstand"):
        if d.get(k):
            r += 2
            ws_i.cell(row=r, column=1, value=k.replace("_", " ").title()).font = Font(bold=True)
            ws_i.cell(row=r + 1, column=1, value=str(d[k]))
    ws_i.column_dimensions["A"].width = 34
    ws_i.column_dimensions["B"].width = 90
    if d.get("hinweis_quellenpruefung"):
        ws_i.cell(row=r + 4, column=1, value="⚠ " + str(d["hinweis_quellenpruefung"])).font = NOTE_FONT

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ CSV / JSON / MD


def build_csv(tile_id: str, data: dict) -> str:
    """CSV-Export: erste Tabelle des Ergebnisdokuments (Semikolon, Excel-DE-tauglich)."""
    rows_by_sheet = schemas.flat_rows(tile_id, data)
    name, rows = next(((k, v) for k, v in rows_by_sheet.items() if v), (None, []))
    buf = io.StringIO()
    if not rows:
        buf.write("keine Tabellendaten\n")
        return buf.getvalue()
    cols = list(rows[0].keys())
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([r.get(c, "") if r.get(c) is not None else "" for c in cols])
    return buf.getvalue()


def build_json(tile_id: str, data: dict, indent: int = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent)


def build_markdown(tile_id: str, data: dict) -> str:
    return schemas.to_markdown(tile_id, data)


# ------------------------------------------------------------------ SVG-Diagramme

FARBEN = ["#1F3B57", "#2E6F95", "#4FA3C7", "#8AC6D1", "#C4E0E5", "#E8A33D", "#C0563B", "#7A8B99"]


def svg_donut(titel: str, items: list[tuple[str, float]], einheit: str = "") -> str:
    """Donutdiagramm als SVG (ohne Fremdbibliothek)."""
    items = [(n, float(v)) for n, v in items if v]
    total = sum(v for _, v in items) or 1.0
    r, cx, cy = 90, 130, 130
    umfang = 2 * 3.141592653589793 * r
    teile, offset = [], 0.0
    for i, (name, value) in enumerate(items):
        anteil = value / total
        dashes = f"{umfang * anteil:.2f} {umfang:.2f}"
        teile.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{FARBEN[i % len(FARBEN)]}" '
            f'stroke-width="46" stroke-dasharray="{dashes}" stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"><title>{name}: {value:g} {einheit} ({anteil * 100:.1f} %)</title></circle>'
        )
        offset += umfang * anteil
    legend = "".join(
        f'<g transform="translate(250,{40 + i * 26})">'
        f'<rect width="14" height="14" fill="{FARBEN[i % len(FARBEN)]}"/>'
        f'<text x="22" y="12" font-family="system-ui,sans-serif" font-size="13" fill="#1F2933">'
        f'{name} – {value:g} {einheit} ({value / total * 100:.1f} %)</text></g>'
        for i, (name, value) in enumerate(items)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="280" viewBox="0 0 640 280">'
        f'<rect width="640" height="280" fill="#ffffff"/>'
        f'<text x="24" y="26" font-family="system-ui,sans-serif" font-size="16" font-weight="600" fill="#1F3B57">{titel}</text>'
        f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-family="system-ui,sans-serif" '
        f'font-size="18" font-weight="600" fill="#1F3B57">{total:g}</text>'
        f'<text x="{cx}" y="{cy + 22}" text-anchor="middle" font-family="system-ui,sans-serif" '
        f'font-size="11" fill="#7A8B99">{einheit}</text>'
        + "".join(teile) + legend + "</svg>"
    )


def svg_bars(titel: str, items: list[tuple[str, float]], einheit: str = "") -> str:
    """Balkendiagramm als SVG."""
    items = [(str(n), float(v)) for n, v in items if v is not None]
    if not items:
        return ""
    maxv = max(abs(v) for _, v in items) or 1.0
    links, oben, breite = 170, 50, 380
    hoehe, gap = 34, 10
    total_h = oben + len(items) * (hoehe + gap) + 30
    bars = []
    for i, (name, value) in enumerate(items):
        y = oben + i * (hoehe + gap)
        w = max(2.0, breite * abs(value) / maxv)
        bars.append(
            f'<text x="{links - 12}" y="{y + 22}" text-anchor="end" font-family="system-ui,sans-serif" '
            f'font-size="13" fill="#1F2933">{name[:28]}</text>'
            f'<rect x="{links}" y="{y}" width="{w:.1f}" height="{hoehe}" rx="3" fill="{FARBEN[i % len(FARBEN)]}"/>'
            f'<text x="{links + w + 8:.1f}" y="{y + 22}" font-family="system-ui,sans-serif" font-size="12" '
            f'fill="#1F3B57">{value:g} {einheit}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="{total_h}" viewBox="0 0 640 {total_h}">'
        f'<rect width="640" height="{total_h}" fill="#ffffff"/>'
        f'<text x="24" y="26" font-family="system-ui,sans-serif" font-size="16" font-weight="600" fill="#1F3B57">{titel}</text>'
        + "".join(bars) + "</svg>"
    )


def diagram_for(tile_id: str, data: dict) -> list[tuple[str, str]]:
    """Passende Diagramme je Kachel: (Dateiname, SVG)."""
    out: list[tuple[str, str]] = []
    try:
        if tile_id == "co2-bilanz" and data.get("bilanz"):
            out.append(("bilanz_donut.svg", svg_donut(
                "CO₂-Bilanz nach Verkehrsträger",
                [(str(r.get("verkehrstraeger", "")), float(r.get("co2_t_jahr") or 0)) for r in data["bilanz"]],
                "t CO₂/a",
            )))
        rows = data.get("massnahmen") or data.get("einsparpotenziale") or data.get("ranking") or []
        if rows and isinstance(rows[0], dict):
            pairs = []
            for r in rows[:8]:
                label = r.get("name") or r.get("ort") or r.get("massnahme") or ""
                wert = r.get("einsparung_t_co2_jahr")
                if wert is None:
                    wert = r.get("kosten_eur") if r.get("kosten_eur") else r.get("punkte")
                if wert is None:
                    wert = r.get("wirkung_t_co2")
                if label and wert is not None:
                    pairs.append((str(label), float(wert)))
            if pairs:
                out.append(("vergleich_balken.svg", svg_bars(
                    "Wirkung/Kosten im Vergleich", pairs,
                    "t CO₂/a" if any(r.get("einsparung_t_co2_jahr") for r in rows) else "",
                )))
        if data.get("bilanz") and isinstance(data["bilanz"], list) and data["bilanz"] and "verkehrstraeger" not in data["bilanz"][0]:
            out.append(("bilanz_balken.svg", svg_bars(
                "Bilanz", [(str(k), v) for k, v in list(data["bilanz"][0].items())[:8] if isinstance(v, (int, float))],
            )))
    except Exception:  # noqa: BLE001 – Diagramm ist Beiwerk, nie kritisch
        pass
    return out


# ------------------------------------------------------------------ Druck-HTML (PDF-Weg A)

PRINT_CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
:root { --ink:#1F2933; --brand:#1F3B57; --line:#D6DEE5; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", system-ui, sans-serif; color: var(--ink); font-size: 10.5pt; line-height: 1.5; margin: 0; }
header.kopf { border-bottom: 2px solid var(--brand); padding-bottom: 8px; margin-bottom: 14px; }
header.kopf .brand { font-weight: 700; color: var(--brand); letter-spacing: .5px; }
header.kopf .meta { font-size: 8.5pt; color: #5B6B7A; margin-top: 4px; }
h1 { font-size: 16pt; color: var(--brand); margin: 6px 0 10px; }
h2 { font-size: 12.5pt; color: var(--brand); margin: 18px 0 6px; border-bottom: 1px solid var(--line); padding-bottom: 3px; }
h3 { font-size: 11pt; margin: 14px 0 4px; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 12px; font-size: 9.5pt; }
th { background: var(--brand); color: #fff; text-align: left; padding: 5px 6px; }
td { border-bottom: 1px solid var(--line); padding: 5px 6px; vertical-align: top; }
tr:nth-child(even) td { background: #F7F9FB; }
blockquote { border-left: 3px solid #E8A33D; margin: 10px 0; padding: 4px 10px; color: #7A5A16; background: #FDF7EA; }
ul, ol { margin: 6px 0 10px 18px; }
.fuss { margin-top: 22px; border-top: 1px solid var(--line); font-size: 8.5pt; color: #5B6B7A; }
.fuss .blatt { float: right; }
.diagramm { max-width: 100%; margin: 10px 0; }
@media screen { body { max-width: 840px; margin: 24px auto; padding: 0 16px; }
  .druckhinweis { background:#EAF3F9; border:1px solid #BCD8E8; padding:10px 12px; border-radius:6px; margin-bottom:14px; font-size:9.5pt; } }
@media print { .druckhinweis { display: none; } }
"""


def build_print_html(tile_id: str, data: dict, title: str = "", kommune: str = "",

                     diagramme: list[tuple[str, str]] | None = None) -> str:
    """Eigenständige HTML-Druckansicht (A4) – im Browser per Drucken → PDF speichern."""
    body_md = schemas.to_markdown(tile_id, data)
    html_body = _md_to_html(body_md)
    diagramme = diagramme or diagram_for(tile_id, data)
    diagram_html = "".join(
        f'<div class="diagramm">{svg}</div>' for _, svg in diagramme[:2]
    )
    kopf = kommune or "Kommune"
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<title>{(title or data.get('titel') or 'Ergebnis')} – SusMob</title>
<style>{PRINT_CSS}</style>
</head><body>
<div class="druckhinweis">🖨️ <b>PDF erzeugen:</b> Strg/Cmd + P → „Als PDF speichern“. Kopfzeile, Seitenzahlen und Layout sind druckoptimiert.</div>
<header class="kopf">
  <div class="brand">SusMob · Kommunales Mobilitätsmanagement</div>
  <div class="meta">{kopf} · Kachel: {tile_id} · Stand: {_now()} (UTC) · Dokument erzeugt aus validiertem Ergebnisdokument</div>
</header>
{html_body}
{diagram_html}
<div class="fuss">Angaben zu Förderprogrammen, Fristen und Rechtsgrundlagen sind Annahmen und vor Verwendung zu prüfen.
<span class="blatt">SusMob · {kopf}</span></div>
</body></html>"""


def _md_to_html(md_text: str) -> str:
    """Minimaler Markdown-Renderer für die Druckansicht (Überschriften, Listen, Tabellen)."""
    import html as _html

    lines = md_text.split("\n")
    out: list[str] = []
    in_ul = in_ol = False
    table: list[list[str]] = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def flush_table():
        nonlocal table
        if table:
            head, *rows = table
            html = ["<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"]
            for r in rows:
                html.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            html.append("</tbody></table>")
            out.append("".join(html))
            table = []

    for raw in lines:
        t = raw.strip()
        if t.startswith("|") and t.endswith("|"):
            cells = [c.strip() for c in t.strip("|").split("|")]
            if all(set(c) <= set("-: ") and c for c in cells) and table:
                continue
            table.append(cells)
            continue
        flush_table()
        if not t:
            close_lists()
            continue
        if t.startswith("#"):
            close_lists()
            lvl = len(t) - len(t.lstrip("#"))
            out.append(f"<h{min(4, max(1, lvl))}>{_inline(t[lvl:].strip())}</h{min(4, max(1, lvl))}>")
            continue
        if t.startswith("> "):
            close_lists()
            out.append(f"<blockquote>{_inline(t[2:])}</blockquote>")
            continue
        if t.startswith(("- ", "* ")):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(t[2:])}</li>")
            continue
        if len(t) > 2 and t[0].isdigit() and t[1] in ".)":
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline(t[2:].strip())}</li>")
            continue
        close_lists()
        out.append(f"<p>{_inline(t)}</p>")
    flush_table()
    close_lists()
    return "\n".join(out)


def _inline(text: str) -> str:
    import html as _html
    import re

    s = _html.escape(text)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?:[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


# ------------------------------------------------------------------ Artefakte


def store_artifact(
    *, conversation_id: str, tile_id: str, kind: str, filename: str,
    content: bytes | str, payload: dict | None = None, artifacts_dir: Path,
) -> dict:
    aid = uuid.uuid4().hex
    data = content.encode("utf-8") if isinstance(content, str) else content
    directory = Path(artifacts_dir) / conversation_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{aid}_{filename}"
    path.write_bytes(data)
    db.exec(
        "INSERT INTO artifacts (id, conversation_id, tile_id, kind, filename, size, stored_path, payload, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, conversation_id, tile_id, kind, filename, len(data), str(path),
         json.dumps(payload or {}, ensure_ascii=False)[:200_000], _now()),
    )
    return {"id": aid, "filename": filename, "kind": kind, "size": len(data), "created_at": _now()}


def artifact_bytes(artifact_id: str) -> tuple[Path, str]:
    row = db.query1("SELECT stored_path, filename FROM artifacts WHERE id=?", (artifact_id,))
    if not row:
        raise KeyError(artifact_id)
    p = Path(row["stored_path"])
    if not p.exists():
        raise KeyError(artifact_id)
    return p, row["filename"]


def build_and_store(
    *, conversation_id: str, tile_id: str, data: dict, artifacts_dir: Path, titel: str = "",
    kommune: str = "",
) -> list[dict]:
    """Erzeugt aus einem validierten Ergebnisdokument alle Artefakte (xlsx, csv, json, md, svg, html)."""
    out: list[dict] = []
    base = (titel or data.get("titel") or "ergebnis").strip().replace("/", "-")[:60].replace(" ", "_")
    out.append(store_artifact(
        conversation_id=conversation_id, tile_id=tile_id, kind="xlsx",
        filename=f"{base}.xlsx", content=build_xlsx(tile_id, data, titel), payload=data, artifacts_dir=artifacts_dir,
    ))
    out.append(store_artifact(
        conversation_id=conversation_id, tile_id=tile_id, kind="csv",
        filename=f"{base}.csv", content=build_csv(tile_id, data), payload={"tile_id": tile_id}, artifacts_dir=artifacts_dir,
    ))
    out.append(store_artifact(
        conversation_id=conversation_id, tile_id=tile_id, kind="json",
        filename=f"{base}.json", content=build_json(tile_id, data), payload={"tile_id": tile_id}, artifacts_dir=artifacts_dir,
    ))
    out.append(store_artifact(
        conversation_id=conversation_id, tile_id=tile_id, kind="md",
        filename=f"{base}.md", content=build_markdown(tile_id, data), payload={"tile_id": tile_id}, artifacts_dir=artifacts_dir,
    ))
    diagramme = diagram_for(tile_id, data)
    for name, svg in diagramme:
        out.append(store_artifact(
            conversation_id=conversation_id, tile_id=tile_id, kind="svg",
            filename=f"{base}_{name}", content=svg, payload={"tile_id": tile_id}, artifacts_dir=artifacts_dir,
        ))
    out.append(store_artifact(
        conversation_id=conversation_id, tile_id=tile_id, kind="html",
        filename=f"{base}_druck.html",
        content=build_print_html(tile_id, data, titel, kommune, diagramme),
        payload={"tile_id": tile_id}, artifacts_dir=artifacts_dir,
    ))
    return out
