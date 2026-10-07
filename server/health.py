"""Modell-Health-Check und Fallback-Ketten (Phase 0).

Der Plan verlangt: Beim Start und im Admin prüfen, ob das je Kachel konfigurierte
Modell **aktive Endpunkte** hat, und bei Ausfall automatisch auf das nächste Modell
der Kette ausweichen. Genau das passiert hier.

Ablauf:
1. ``fetch_models()`` lädt die Live-Modellliste (Preise, Kontext, Fähigkeiten) und
   schreibt sie nach ``model_health``.
2. ``check_model()`` fragt ``/models/<id>/endpoints`` ab und zählt aktive Anbieter.
3. ``ordered_chain()`` sortiert die Kette einer Kachel: gesunde Modelle zuerst,
   gescheiterte nach hinten – ohne die Konfiguration zu verändern.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from server import db
from server.llm import BASE, HEADERS, chain_for

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
ONLINE: bool | None = None  # letzter bekannter Netzzustand (None = unbekannt)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _save(model: str, **fields) -> None:
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields)
    db.exec(
        f"INSERT INTO model_health (model, {cols}) VALUES (?, {marks}) "
        f"ON CONFLICT(model) DO UPDATE SET {updates}",
        (model, *fields.values()),
    )


async def fetch_models() -> dict:
    """Lädt die Live-Modellliste und aktualisiert ``model_health`` (Preise/Fähigkeiten)."""
    global ONLINE
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(f"{BASE}/models")
            r.raise_for_status()
            data = r.json().get("data", [])
    except Exception as e:  # noqa: BLE001 – offline/Netzsperre
        ONLINE = False
        return {"ok": False, "models": 0, "error": f"OpenRouter nicht erreichbar: {e}"}
    ONLINE = True
    count = 0
    for m in data:
        mid = m.get("id") or ""
        if not mid:
            continue
        arch = m.get("architecture") or {}
        params = set(m.get("supported_parameters") or [])
        p = m.get("pricing") or {}
        top = m.get("top_provider") or {}
        _save(
            mid,
            checked_at=_now(),
            ok=0,  # ok wird erst durch check_model() gesetzt
            endpoints=0,
            active_endpoints=0,
            context_length=m.get("context_length") or top.get("context_length") or 0,
            max_completion=top.get("max_completion_tokens") or 0,
            supports_structured=1 if "structured_outputs" in params else 0,
            supports_json_mode=1 if "response_format" in params else 0,
            supports_tools=1 if "tools" in params else 0,
            supports_vision=1 if "image" in (arch.get("input_modalities") or []) else 0,
            pricing_prompt=_f(p.get("prompt")) or 0.0,
            pricing_completion=_f(p.get("completion")) or 0.0,
            note="",
        )
        count += 1
    return {"ok": True, "models": count, "error": ""}


def _merge(model: str, **fields) -> dict:
    """Bestehende Health-Zeile mit neuen Werten zusammenführen (None = alten Wert behalten)."""
    old = dict(db.query1("SELECT * FROM model_health WHERE model=?", (model,)) or {})
    old.setdefault("model", model)
    merged = {**old}
    for k, v in fields.items():
        if v is not None:
            merged[k] = v
    out = {
        "model": model,
        "checked_at": merged.get("checked_at") or _now(),
        "ok": 1 if merged.get("ok") else 0,
        "endpoints": merged.get("endpoints") or 0,
        "active_endpoints": merged.get("active_endpoints") or 0,
        "uptime": merged.get("uptime") if merged.get("uptime") is not None else None,
        "context_length": merged.get("context_length") or 0,
        "max_completion": merged.get("max_completion") or 0,
        "supports_structured": merged.get("supports_structured") or 0,
        "supports_json_mode": merged.get("supports_json_mode") or 0,
        "supports_tools": merged.get("supports_tools") or 0,
        "supports_vision": merged.get("supports_vision") or 0,
        "pricing_prompt": merged.get("pricing_prompt") if merged.get("pricing_prompt") is not None else 0.0,
        "pricing_completion": merged.get("pricing_completion") if merged.get("pricing_completion") is not None else 0.0,
        "note": merged.get("note") or "",
    }
    _save(**out)
    return out


async def check_model(model: str, *, save: bool = True) -> dict:
    """Prüft, ob ein Modell aktive Endpunkte hat. Ergebnis landet in ``model_health``."""
    global ONLINE
    base_id = model[:-5] if model.endswith(":free") else model
    last_error = ""
    for candidate in dict.fromkeys([model, base_id]):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(f"{BASE}/models/{candidate}/endpoints")
                if r.status_code != 200:
                    last_error = f"HTTP {r.status_code}"
                    continue
                data = r.json().get("data") or {}
        except Exception as e:  # noqa: BLE001 – Offline/Netzsperre
            ONLINE = False
            last_error = f"Netzfehler: {e}"
            break
        ONLINE = True
        endpoints = data.get("endpoints") or []
        # OpenRouter: status -1/0 = down/degraded, 1 = ok. Fehlt status, gilt der Endpunkt als nutzbar.
        active = [e for e in endpoints if e.get("status") in (None, 1)]
        uptime = None
        if active:
            ups = [_f(e.get("uptime_last_30m")) for e in active]
            ups = [u for u in ups if u is not None]
            if ups:
                uptime = round(100.0 * sum(ups) / len(ups), 1)
        best_prompt = best_completion = None
        for e in active:
            pr = e.get("pricing") or {}
            pp, pc = _f(pr.get("prompt")), _f(pr.get("completion"))
            if pp is not None and (best_prompt is None or pp < best_prompt):
                best_prompt = pp
            if pc is not None and (best_completion is None or pc < best_completion):
                best_completion = pc
        notes = []
        if not endpoints:
            notes.append("Endpunktliste leer")
        elif not active:
            notes.append("kein aktiver Anbieter")
        if data.get("context_length"):
            notes.append(f"Kontext {data['context_length']}")
        if data.get("name"):
            notes.append(str(data["name"]))
        if ups_note := (f"{len(active)} aktive Anbieter" if active else ""):
            notes.append(ups_note)
        row = {
            "model": model,
            "ok": bool(active),
            "endpoints": len(endpoints),
            "active_endpoints": len(active),
            "uptime": uptime,
            "note": " · ".join(notes) or last_error,
            "checked_at": _now(),
        }
        if save:
            _merge(
                model,
                checked_at=row["checked_at"],
                ok=1 if row["ok"] else 0,
                endpoints=row["endpoints"],
                active_endpoints=row["active_endpoints"],
                uptime=uptime,
                context_length=data.get("context_length"),
                pricing_prompt=best_prompt,
                pricing_completion=best_completion,
                note=row["note"] + (f" · {last_error}" if last_error and not active else ""),
            )
        return row
    # Offline/Netzfehler ist kein Modellausfall: alten Stand behalten, nur vermerken.
    alt = dict(db.query1("SELECT * FROM model_health WHERE model=?", (model,)) or {})
    if save and alt.get("checked_at"):
        _merge(model, note=f"nicht prüfbar: {last_error or 'unbekannt'} · letzter Stand: "
                           f"{'ok' if alt.get('ok') else 'aus'} ({alt.get('checked_at')})")
        return {**alt, "ok": bool(alt.get("ok")), "note": f"nicht prüfbar: {last_error or 'unbekannt'}"}
    if save:
        _merge(model, checked_at=_now(), ok=0, note=f"nicht geprüft: {last_error or 'unbekannt'}")
    return {
        "model": model, "ok": False, "endpoints": 0, "active_endpoints": 0,
        "uptime": None, "note": last_error or "unbekannt", "checked_at": "",
    }


async def check_models(models: list[str], *, workers: int = 4) -> list[dict]:
    """Prüft mehrere Modelle parallel (schont Rate-Limits durch Begrenzung)."""
    sem = asyncio.Semaphore(workers)
    out: list[dict] = []

    async def one(m: str):
        async with sem:
            out.append(await check_model(m))

    await asyncio.gather(*(one(m) for m in dict.fromkeys(models)))
    return sorted(out, key=lambda r: (not r["ok"], r["model"]))


async def check_tiles(tiles: list[dict]) -> dict:
    """Prüft für jede Kachel Hauptmodell + Fallbacks und liefert einen Report."""
    models: list[str] = []
    for t in tiles:
        models += chain_for(t)
    results = await check_models(models)
    by_model = {r["model"]: r for r in results}
    report = []
    for t in tiles:
        chain = chain_for(t)
        entries = [
            {
                "model": m,
                "ok": bool(by_model.get(m, {}).get("ok")),
                "uptime": by_model.get(m, {}).get("uptime"),
                "active_endpoints": by_model.get(m, {}).get("active_endpoints", 0),
                "note": by_model.get(m, {}).get("note", ""),
            }
            for m in chain
        ]
        report.append({
            "tile_id": t["id"],
            "name": t["name"],
            "model": t["model"],
            "chain": entries,
            "ok": any(e["ok"] for e in entries),
            "primary_ok": entries[0]["ok"] if entries else False,
        })
    return {
        "checked_at": _now(),
        "online": ONLINE,
        "tiles": report,
        "failures": [
            {"model": r["model"], "note": r["note"]}
            for r in results if not r["ok"]
        ],
    }


def model_info(model: str) -> dict:
    row = db.query1("SELECT * FROM model_health WHERE model=?", (model,))
    return dict(row) if row else {}


def is_free(model: str) -> bool:
    if model.endswith(":free"):
        return True
    info = model_info(model)
    if info:
        return (info.get("pricing_prompt") or 0) == 0 and (info.get("pricing_completion") or 0) == 0
    return False


def supports_vision(model: str) -> bool:
    return bool((model_info(model) or {}).get("supports_vision"))


def supports_structured(model: str) -> bool:
    info = model_info(model) or {}
    return bool(info.get("supports_structured")) or bool(info.get("supports_json_mode"))


def ordered_chain(tile: dict, only_healthy: bool = False) -> list[str]:
    """Kette der Kachel – gesunde Modelle zuerst.

    Solange gar kein Health-Check gelaufen ist (``model_health`` leer / Offline),
    bleibt die konfigurierte Reihenfolge erhalten: Wissen > Vermutung.
    """
    chain = chain_for(tile)
    if not chain:
        return []
    infos = {m: model_info(m) for m in chain}
    if not any(i.get("checked_at") for i in infos.values()):
        return chain
    healthy = [m for m in chain if infos.get(m, {}).get("ok")]
    unknown = [m for m in chain if not infos.get(m, {}).get("checked_at")]
    broken = [m for m in chain if infos.get(m, {}).get("checked_at") and not infos.get(m, {}).get("ok")]
    ordered = healthy + unknown + broken
    if only_healthy:
        return healthy or unknown or chain
    return ordered


def summary() -> dict:
    rows = [dict(r) for r in db.query("SELECT * FROM model_health ORDER BY ok DESC, model")]
    used = {m for t in db.query("SELECT model, fallback_models FROM tiles") for m in chain_for(dict(t))}
    rows = [r for r in rows if r["model"] in used]
    checked = [r for r in rows if r["checked_at"]]
    return {
        "online": ONLINE,
        "models_used": len(used),
        "models_checked": len(checked),
        "models_ok": sum(1 for r in checked if r["ok"]),
        "models_broken": [r["model"] for r in checked if not r["ok"]],
        "last_check": max((r["checked_at"] for r in checked), default=""),
        "rows": rows,
    }
