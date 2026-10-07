"""Messbarkeit & Nachvollziehbarkeit (Phase 0 des Plans).

* ``llm_calls`` – jeder OpenRouter-Request mit Modell, Tokens, Kosten, Dauer, Fehler.
* ``audit_log`` – wer hat wann welches Ergebnis erzeugt (Voraussetzung für Kommunen).
* ``metrics()``  – Auswertung für den Admin-Bereich: Schätzungen werden Messwerte.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from server import db
from server.llm import LLMResult


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def log_call(
    *,
    kind: str,
    tile_id: str = "",
    conversation_id: str = "",
    chain: list[str] | None = None,
    result: LLMResult | None = None,
    error: Exception | str | None = None,
    status_code: int = 0,
    chars_in: int = 0,
    chars_out: int = 0,
    duration_ms: int = 0,
    attempt: int = 1,
    used_fallback: bool = False,
) -> int:
    """Schreibt einen LLM-Call in ``llm_calls`` (auch Fehlversuche)."""
    chain = chain or []
    u = result.usage if result else None
    db.exec(
        "INSERT INTO llm_calls (ts, kind, tile_id, conversation_id, requested_model, model, attempt, "
        "used_fallback, ok, status_code, error, prompt_tokens, completion_tokens, cached_tokens, "
        "total_tokens, cost_usd, cost_estimated, duration_ms, chars_in, chars_out) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            _now(), kind, tile_id, conversation_id,
            (chain[0] if chain else ""), (result.model if result else (chain[0] if chain else "")),
            attempt, 1 if used_fallback else 0, 0 if error else 1, status_code,
            (str(error)[:500] if error else ""),
            (u.prompt_tokens if u else 0), (u.completion_tokens if u else 0),
            (u.cached_tokens if u else 0), (u.total_tokens if u else 0),
            (u.cost_usd if u else 0.0), (1 if (u.cost_estimated if u else True) else 0),
            (result.duration_ms if result else duration_ms), chars_in, chars_out,
        ),
    )
    row = db.query1("SELECT last_insert_rowid() AS id")
    return int(row["id"]) if row else 0


def audit(
    action: str,
    *,
    object_type: str = "",
    object_id: str = "",
    detail: str = "",
    actor: str = "anonym",
    ip: str = "",
) -> None:
    db.exec(
        "INSERT INTO audit_log (ts, actor, action, object_type, object_id, detail, ip) VALUES (?,?,?,?,?,?,?)",
        (_now(), actor, action, object_type, object_id, detail[:1000], ip),
    )


def audit_list(limit: int = 100, action: str = "") -> list[dict]:
    if action:
        rows = db.query(
            "SELECT * FROM audit_log WHERE action=? ORDER BY id DESC LIMIT ?", (action, limit)
        )
    else:
        rows = db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def metrics(days: int = 30) -> dict:
    """Kosten-/Token-Auswertung über die letzten ``days`` Tage."""
    since = _days_ago(days)
    rows = [dict(r) for r in db.query("SELECT * FROM llm_calls WHERE ts>=? ORDER BY ts DESC", (since,))]
    all_time = dict(db.query1(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS cost, "
        "COALESCE(SUM(total_tokens),0) AS tokens FROM llm_calls"
    ) or {})

    def blank() -> dict:
        return {"calls": 0, "ok": 0, "errors": 0, "fallbacks": 0,
                "tokens_in": 0, "tokens_out": 0, "tokens_total": 0,
                "cached_tokens": 0, "cost_usd": 0.0, "duration_ms": 0,
                "estimated_calls": 0}

    total = blank()
    per_tile: dict[str, dict] = {}
    per_model: dict[str, dict] = {}
    per_day: dict[str, dict] = {}

    for r in rows:
        for bucket, key in ((total, None), (per_tile, r["tile_id"] or "(ohne Kachel)"),
                            (per_model, r["requested_model"] or "(unbekannt)"), (per_day, r["ts"][:10])):
            if key is not None:
                bucket = bucket.setdefault(key, blank())
            bucket["calls"] += 1
            bucket["ok"] += 1 if r["ok"] else 0
            bucket["errors"] += 0 if r["ok"] else 1
            bucket["fallbacks"] += 1 if r["used_fallback"] else 0
            bucket["tokens_in"] += r["prompt_tokens"]
            bucket["tokens_out"] += r["completion_tokens"]
            bucket["tokens_total"] += r["total_tokens"]
            bucket["cached_tokens"] += r["cached_tokens"]
            bucket["cost_usd"] += r["cost_usd"]
            bucket["duration_ms"] += r["duration_ms"]
            bucket["estimated_calls"] += 1 if r["cost_estimated"] else 0

    # Kosten je Unterhaltung (Grundlage: „Kosten je qualifiziertem Chat")
    conv: dict[str, dict] = {}
    for r in rows:
        cid = r["conversation_id"] or ""
        if not cid:
            continue
        c = conv.setdefault(cid, {"conversation_id": cid, "tile_id": r["tile_id"], "calls": 0,
                                  "cost_usd": 0.0, "tokens_total": 0})
        c["calls"] += 1
        c["cost_usd"] += r["cost_usd"]
        c["tokens_total"] += r["total_tokens"]
    conv_list = sorted(conv.values(), key=lambda c: -c["cost_usd"])[:20]
    qualified = [c for c in conv.values() if c["calls"] >= 3]

    def rounded(d: dict) -> dict:
        out = dict(d)
        out["cost_usd"] = round(d["cost_usd"], 6)
        out["avg_duration_ms"] = int(d["duration_ms"] / d["calls"]) if d["calls"] else 0
        return out

    return {
        "days": days,
        "since": since,
        "total": rounded(total),
        "all_time": {
            "calls": int(all_time.get("calls") or 0),
            "cost_usd": round(float(all_time.get("cost") or 0.0), 6),
            "tokens_total": int(all_time.get("tokens") or 0),
        },
        "per_tile": {k: rounded(v) for k, v in sorted(per_tile.items())},
        "per_model": {k: rounded(v) for k, v in sorted(per_model.items())},
        "per_day": {k: rounded(v) for k, v in sorted(per_day.items())},
        "conversations": conv_list,
        "cost_per_qualified_chat": round(
            sum(c["cost_usd"] for c in qualified) / len(qualified), 6
        ) if qualified else 0.0,
        "qualified_chats": len(qualified),
        "kennzahlen": {
            # KPI-Tabelle aus dem Plan
            "kosten_je_chat_usd": round(sum(c["cost_usd"] for c in qualified) / len(qualified), 6) if qualified else 0.0,
            "fehlerquote_prozent": round(100.0 * total["errors"] / total["calls"], 1) if total["calls"] else 0.0,
            "fallback_quote_prozent": round(100.0 * total["fallbacks"] / total["calls"], 1) if total["calls"] else 0.0,
            "kosten_geschaetzt_anteil_prozent": round(100.0 * total["estimated_calls"] / total["calls"], 1) if total["calls"] else 0.0,
        },
    }
