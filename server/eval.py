"""Eval-Harness (Phase 2 des Plans): Testfälle automatisch bewerten.

Bewertungsschema (aus dem Plan): Vollständigkeit, markierte Annahmen,
**keine erfundenen Zahlen**, Format. Jede Prüfung liefert 0–1 Punkte, das
Gesamtergebnis ist ein gewichteter Score in Prozent. Erklärungen („findings“)
zeigen konkret, welche Zahl nicht belegt ist – so wird eine Prompt-Änderung
als Regression sichtbar.
"""
from __future__ import annotations

import re

# Zahlen, die ohne Belegquelle zulässig sind (Faktoren, Einheitenumrechnung, Zählwerte)
WHITELIST = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 24, 25, 30, 35, 40, 45, 50, 60, 75, 80, 90, 100,
    120, 130, 140, 150, 180, 200, 240, 250, 300, 360, 365, 400, 500, 600, 700, 800, 900, 1000, 1200,
    2380, 2680, 372, 2.68, 2.38, 3.3, 11, 22, 1.1, 1.3, 18, 45, 55, 92,
}

# Erwartete Abschnitte/Schlüsselbegriffe je Kachel (Vollständigkeit)
ERWARTET: dict[str, list[str]] = {
    "co2-bilanz": ["annahme", "bilanz", "t co", "einsparpotenzial", "nächste schritte"],
    "beschlussvorlagen": ["betreff", "sachstand", "beschlussvorschlag", "finanz", "anlage"],
    "klimaschutzkonzept": ["ausgangslage", "ziel", "maßnahme", "monitoring", "finanzier"],
    "massnahmenplanung": ["maßnahme", "kosten", "wirkung", "phase", "kpi"],
    "wegeplanung": ["abschnitt", "standard", "kosten", "bau", "konflikt"],
    "argumentation": ["argument", "gegenargument", "quelle", "entkräft"],
    "opnv-planung": ["takt", "umlauf", "fahrzeug", "kosten", "annahme"],
    "verkehrssicherheit": ["unfall", "ranking", "gefahrenstelle", "maßnahme", "zuständig"],
    "ladeinfrastruktur": ["ladepunkt", "bedarf", "ausbau", "standort", "förder"],
    "parkraum": ["parkstand", "auslastung", "bewirtschaftung", "einnahme", "amortis"],
}

QUELEN_PFLICHT = {"beschlussvorlagen", "ladeinfrastruktur", "argumentation", "klimaschutzkonzept"}

ZAHL_RE = re.compile(r"(?<![\w/])(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\w])")


def zahlen(text: str) -> list[float]:
    """Alle Zahlen aus einem Text (deutsches Format, ohne Jahreszahlen/Jahresangaben)."""
    out: list[float] = []
    for m in ZAHL_RE.finditer(text or ""):
        raw = m.group(1).replace(" ", "")
        if "," in raw and "." in raw:
            # deutsches Format 1.234,56
            raw = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
            raw = raw.replace(".", "")  # deutsche Tausenderpunkte: 2.680 → 2680
        else:
            raw = raw.replace(",", ".")
        try:
            v = float(raw)
        except ValueError:
            continue
        if 1900 <= v <= 2100 and float(v).is_integer():
            continue  # Jahreszahl
        out.append(v)
    return out


def _trace(value: float, kontext_zahlen: set[float], toleranz: float = 0.02) -> bool:
    if abs(value) < 1e-9 or value in WHITELIST:
        return True
    for k in kontext_zahlen:
        if k == 0 and value == 0:
            return True
        if k != 0 and abs(value - k) <= toleranz * max(abs(k), abs(value)):
            return True
        if abs(value) == abs(k) or abs(value) == round(abs(k), 0):
            return True
    # Auf- und Abrundungen sowie Prozentwerte gelten als belegt, wenn die Basis belegt ist
    if value == round(value) and any(abs(value - round(k)) < 1e-6 for k in kontext_zahlen):
        return True
    return False


def bewerte(tile_id: str, antwort: str, kontext: str = "", extra_zahlen: list[float] | None = None) -> dict:
    """Bewertet eine Modellantwort. Rückgabe: score (0–100), checks, findings."""
    text = antwort or ""
    low = text.lower()
    kontext_zahlen = set(zahlen(kontext)) | set(extra_zahlen or [])
    checks: dict[str, dict] = {}

    # 1) Annahmen markiert
    treffer = len(re.findall(r"annahme|schätzung|gesetzt|unterstellt", low))
    checks["annahmen_markiert"] = {
        "ok": treffer >= 2, "punkte": min(1.0, treffer / 2), "gewicht": 1.0,
        "detail": f"{treffer} Nennungen von „Annahme/Schätzung“",
    }
    # 2) Keine erfundenen Zahlen – der Kern des Plans
    zahlen_liste = zahlen(text)
    unbelegt = sorted({z for z in zahlen_liste if not _trace(z, kontext_zahlen)})
    anteil_belegt = 1.0 if not zahlen_liste else 1 - len(unbelegt) / len(zahlen_liste)
    checks["keine_erfundenen_zahlen"] = {
        "ok": anteil_belegt >= 0.9, "punkte": max(0.0, (anteil_belegt - 0.5) / 0.5), "gewicht": 2.0,
        "detail": f"{len(zahlen_liste) - len(unbelegt)} von {len(zahlen_liste)} Zahlen belegt"
                  + (f" · unbelegt: {', '.join(f'{u:g}' for u in unbelegt[:8])}" if unbelegt else ""),
    }
    # 3) Vollständigkeit (erwartete Abschnitte)
    erwartet = ERWARTET.get(tile_id, [])
    da = [k for k in erwartet if k in low]
    checks["vollstaendigkeit"] = {
        "ok": (len(da) / len(erwartet) >= 0.8) if erwartet else True,
        "punkte": (len(da) / len(erwartet)) if erwartet else 1.0, "gewicht": 1.5,
        "detail": f"{len(da)}/{len(erwartet)} erwartete Abschnitte: {', '.join(da)}" if erwartet else "keine Vorgabe",
    }
    # 4) Format: Tabelle + Struktur
    hat_tabelle = "|" in text and text.count("|") >= 6
    hat_listen = bool(re.search(r"(?m)^\s*[-*\d]", text))
    checks["format"] = {
        "ok": hat_tabelle, "punkte": (0.6 if hat_listen else 0) + (0.4 if hat_tabelle else 0), "gewicht": 1.0,
        "detail": f"Tabelle: {'ja' if hat_tabelle else 'nein'}, Listen: {'ja' if hat_listen else 'nein'}",
    }
    # 5) Quellen-/Prüfhinweis bei sensiblen Kacheln
    if tile_id in QUELEN_PFLICHT:
        hat_hinweis = bool(re.search(r"prüf|quelle|stand:|verifizier", low))
        checks["quellenhinweis"] = {
            "ok": hat_hinweis, "punkte": 1.0 if hat_hinweis else 0.0, "gewicht": 1.0,
            "detail": "Hinweis auf Quellenprüfung vorhanden" if hat_hinweis else "Quellenprüfungs-Hinweis fehlt",
        }
    # 6) Länge / Substanz
    checks["substanz"] = {
        "ok": len(text) >= 1200, "punkte": min(1.0, len(text) / 1200), "gewicht": 0.5,
        "detail": f"{len(text)} Zeichen Ausgabe",
    }

    gesamt_gewicht = sum(c["gewicht"] for c in checks.values())
    score = int(round(100 * sum(c["punkte"] * c["gewicht"] for c in checks.values()) / gesamt_gewicht)) if gesamt_gewicht else 0
    findings = [f"{k}: {v['detail']}" for k, v in checks.items() if not v["ok"]]
    return {
        "score": score,
        "checks": checks,
        "findings": " | ".join(findings) or "alle Prüfungen bestanden",
        "unbelegte_zahlen": unbelegt[:20],
        "anzahl_zahlen": len(zahlen_liste),
    }


def speichere(tile_id: str, model: str, case_id: int | None, case_name: str, ergebnis: dict,
              duration_ms: int = 0, chars_out: int = 0) -> None:
    import json

    from server import db
    from server.telemetry import _now

    db.exec(
        "INSERT INTO eval_runs (ts, tile_id, model, test_case_id, test_case_name, score, checks, findings, "
        "duration_ms, chars_out) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (_now(), tile_id, model, case_id, case_name, ergebnis["score"],
         json.dumps(ergebnis["checks"], ensure_ascii=False), ergebnis["findings"][:2000],
         duration_ms, chars_out),
    )


def uebersicht(tile_id: str | None = None, limit: int = 50) -> dict:
    from server import db

    if tile_id:
        rows = [dict(r) for r in db.query(
            "SELECT * FROM eval_runs WHERE tile_id=? ORDER BY id DESC LIMIT ?", (tile_id, limit))]
    else:
        rows = [dict(r) for r in db.query("SELECT * FROM eval_runs ORDER BY id DESC LIMIT ?", (limit,))]
    per_tile: dict[str, dict] = {}
    for r in rows:
        e = per_tile.setdefault(r["tile_id"], {"tile_id": r["tile_id"], "runs": 0, "score_sum": 0,
                                               "letzter": "", "bester": 0})
        e["runs"] += 1
        e["score_sum"] += r["score"]
        e["letzter"] = r["ts"]
        e["bester"] = max(e["bester"], r["score"])
    for e in per_tile.values():
        e["score_mittel"] = round(e["score_sum"] / e["runs"], 1) if e["runs"] else 0
    return {"runs": rows, "per_tile": per_tile}
