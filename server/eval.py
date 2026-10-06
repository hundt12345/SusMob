"""Eval-Harness: Testfälle je Kachel automatisch bewerten (Plan Phase 2).

Bewertungsschema (je Testfall, max. 6 Punkte):
  1. Antwort erhalten
  2. ausreichende Tiefe (≥ 600 Zeichen)
  3. Annahmen explizit benannt
  4. Zahlen mi Einheit (keine nackten Zahlen)
  5. Struktur (Überschrift oder Tabelle)
  6. Quellen-/Prüfhinweis („Quelle prüfen“, „Stand:“) – bei Kacheln mit
     Förder-/Rechtsbezug Pflicht

Der Harness ist **kein** Ersatz für fachliche Prüfung, aber ein Regressionsschutz
für Prompt-Änderungen und Modellwechsel: läuft er nach einer Änderung schlechter,
ist die Änderung zu prüfen.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Callable

from server import db

QUELLEN_PFLICHT = {"beschlussvorlagen", "argumentation", "klimaschutzkonzept", "opnv-planung"}

MUSTER = {
    "annahme": re.compile(r"\bannahme|\bgeschätzt|\bschätzung|\bunterstellt|\bfalls\b", re.I),
    "zahl_mit_einheit": re.compile(r"\d[\d.,]*\s*(t CO₂|kg CO₂|g CO₂|km|l/100|kWh|€|%|Plätze|Minuten|min\b|Fahrzeuge)", re.I),
    "struktur": re.compile(r"^\s*(#{1,4}\s|\|)", re.M),
    "quelle": re.compile(r"quelle prüfen|quellenangabe|stand:\s*\d|UBA|BASt|ADFC|KfW|BMDV|Statistisches Bundesamt|"
                         r"Förderrichtlinie|Richtlinie\b", re.I),
    "erfunden": re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b.{0,40}(Frist|Abgabe|Antrag)|"
                           r"garantiert\s+\d|\bexakt\s+\d+\s*%", re.I),
}


def bewerte(tile_id: str, content: str) -> tuple[int, int, list[dict]]:
    """Einzelantwort bewerten → (punkte, maxpunkte, checks)."""
    checks: list[dict] = []
    text = content or ""

    def check(name: str, ok: bool, detail: str = "", punkte: int = 1) -> int:
        checks.append({"name": name, "ok": bool(ok), "punkte": punkte if ok else 0,
                       "max": punkte, "detail": detail})
        return punkte if ok else 0

    punkte = 0
    punkte += check("Antwort erhalten", len(text.strip()) > 0, f"{len(text)} Zeichen")
    punkte += check("Tiefe (≥ 600 Zeichen)", len(text) >= 600, f"{len(text)} Zeichen")
    punkte += check("Annahmen benannt", bool(MUSTER["annahme"].search(text)),
                    "Signalwörter: Annahme/Schätzung/unterstellt")
    treffer = MUSTER["zahl_mit_einheit"].findall(text)
    punkte += check("Zahlen mit Einheit", len(treffer) >= 3, f"{len(treffer)} Treffer")
    punkte += check("Struktur (Überschrift/Tabelle)", bool(MUSTER["struktur"].search(text)),
                    "Markdown-Überschrift oder Tabelle gefunden")
    if tile_id in QUELLEN_PFLICHT:
        punkte += check("Quellen-/Prüfhinweis", bool(MUSTER["quelle"].search(text)),
                        "„Quelle prüfen“ bzw. belastbare Quelle erwartet")
    else:
        punkte += check("Keine Scheinpräzision (Fristen/Garantien)",
                        not MUSTER["erfunden"].search(text),
                        "unerwartete Frist-/Garantieformulierung gefunden")
    # Zusätzliche Warnung (nicht punktrelevant)
    if MUSTER["erfunden"].search(text):
        checks.append({"name": "Warnung: Scheinpräzision (Frist/Garantie)", "ok": False, "punkte": 0,
                       "max": 0, "detail": "Frist-/Garantieformulierung gefunden – fachlich prüfen"})
    return punkte, 6, checks


async def run_tile(
    tile_id: str,
    chat_call: Callable,
    *,
    model: str,
    limit: int | None = None,
) -> dict:
    """Alle Testfälle einer Kachel durchlaufen lassen.

    ``chat_call`` ist eine Coroutine ``(testfall) -> (content, cost_usd, duration_ms)``,
    damit der Harness unabhängig vom Transport bleibt (Testbarkeit).
    """
    faelle = db.query("SELECT id, name, message, file_content FROM test_cases WHERE tile_id=? ORDER BY id", (tile_id,))
    if limit:
        faelle = faelle[:limit]
    gesamt, max_gesamt, rows = 0, 0, []
    for f in faelle:
        t0 = time.time()
        try:
            content, cost, dur = await chat_call(f)
            ok = True
            punkte, maximum, checks = bewerte(tile_id, content)
        except Exception as e:  # noqa: BLE001 – Fehler je Testfall protokollieren
            content, cost, dur, ok = f"FEHLER: {e}", 0.0, int((time.time() - t0) * 1000), False
            punkte, maximum = 0, 6
            checks = [{"name": "Aufruf fehlgeschlagen", "ok": False, "punkte": 0, "max": 6,
                       "detail": str(e)[:300]}]
        gesamt += punkte
        max_gesamt += maximum
        row = {
            "tile_id": tile_id, "model": model, "test_name": f["name"], "score": punkte,
            "max_score": maximum, "checks": checks, "content": content[:4000],
            "cost_usd": float(cost or 0.0), "duration_ms": int(dur or 0),
        }
        rows.append({**row, "ok": ok, "error": "" if ok else content[:300]})
        db.exec(
            "INSERT INTO eval_runs (tile_id, model, test_name, score, max_score, checks, content, cost_usd, "
            "duration_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tile_id, model, f["name"], punkte, maximum,
             json.dumps(checks, ensure_ascii=False), content[:8000],
             float(cost or 0.0), int(dur or 0), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        )
    quote = round(gesamt / max_gesamt * 100, 1) if max_gesamt else 0.0
    return {
        "tile_id": tile_id,
        "model": model,
        "punkte": gesamt,
        "max_punkte": max_gesamt,
        "quote_pct": quote,
        "ziel_erreicht": quote >= 83.0,          # ≥ 5 von 6 Punkten je Testfall im Schnitt
        "testfaelle": rows,
        "kosten_usd": round(sum(r["cost_usd"] for r in rows), 5),
        "dauer_ms": sum(r["duration_ms"] for r in rows),
    }
