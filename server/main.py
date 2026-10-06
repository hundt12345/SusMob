"""SusMob – FastAPI-Backend.

Kacheln → Upload + Chat (OpenRouter, Streaming) + Standardwerte.
Admin → System-Prompts pflegen, testen (mit Testdaten), Versionen.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from server import calc, db, eval as eval_mod, exports, limits, llm, parse as parse_mod, schema as schema_mod
from server.envfile import load as load_env
from server.examples import EXAMPLES, replace_messages, seed_examples
from server.files import extract_text, SUPPORTED
from server.llm import chat_once, chat_json, check_health, models_catalog, stream_chat
from server.seed import EMPFEHLUNG_MODELLE, FALLBACK_KETTEN, FREE_MODELS, seed_all

ROOT = Path(__file__).resolve().parent.parent
load_env(ROOT / ".env")  # OPENROUTER_API_KEY / ADMIN_PASSWORD aus .env

# Datenverzeichnis: per SUSMOB_DATA_DIR übersteuerbar (z. B. gemountetes Volume beim Hosting)
DATA_DIR = Path(os.environ.get("SUSMOB_DATA_DIR") or (ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = DATA_DIR / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_TOTAL_FILE_CHARS = 48_000
HISTORY_LIMIT = 30  # Nachrichten im LLM-Kontext

db.init(DATA_DIR / "susmob.db")
seed_all()
seed_examples(UPLOAD_DIR)

app = FastAPI(title="SusMob API")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
_admin_tokens: set[str] = set()

# Datenschutz-Flag (Plan Phase 4): Im Demo-Betrieb dürfen nur unkritische Daten
# verarbeitet werden, weil Gratis-Provider Prompts zum Training nutzen dürfen.
DEMO_ONLY = os.environ.get("SUSMOB_DEMO_ONLY", "0").strip() not in ("", "0", "false", "no")

MODELS = [
    "anthropic/claude-sonnet-4",
    "anthropic/claude-opus-4",
    "anthropic/claude-3.5-haiku",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/o3-mini",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3-70b-instruct",
    "mistralai/mistral-large",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _tile_or_404(tid: str) -> dict:
    row = db.query1("SELECT * FROM tiles WHERE id=?", (tid,))
    if not row:
        raise HTTPException(404, f"Unbekannte Kachel: {tid}")
    return dict(row)


def _conv_or_404(cid: str) -> dict:
    row = db.query1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not row:
        raise HTTPException(404, "Unterhaltung nicht gefunden")
    return dict(row)


def _check_admin(request: Request) -> None:
    if not ADMIN_PASSWORD:
        return
    tok = request.headers.get("X-Admin-Token", "")
    if not tok or tok not in _admin_tokens:
        raise HTTPException(401, "Admin-Zugang fehlt")


def _llm_error_text(err: Exception) -> str:
    """Verständliche Fehlermeldung – unterscheidet Netz-/Verbindungsproblem von Modellfehler."""
    text = str(err)
    net = any(k in text for k in ("SSL", "EOF", "Connect", "Timeout", "timed out", "getaddrinfo", "Name or service"))
    if net:
        return (
            "**OpenRouter ist von diesem Server aus nicht erreichbar.**\n\n"
            f"Technische Ursache: {text}\n\n"
            "Wenn du diese Vorschau in einer abgeschotteten Sandbox ansiehst: dort ist der ausgehende "
            "Zugriff auf `openrouter.ai` gesperrt – auf einem eigenen Server oder lokal mit Internetzugang "
            "antwortet das Modell normal. Prüfen lässt sich das unter `#/admin` → Modellliste aktualisieren "
            "oder über `/api/models/status`."
        )
    return f"OpenRouter-Fehler: {text}"


def audit(event: str, tile_id: str | None = None, conversation_id: str | None = None,
          detail: str = "", actor: str = "lokal") -> None:
    """Audit-Log (Phase 0): wer/wann/was – ohne Personenbezug, nur Ereignis + Kontext."""
    try:
        db.exec(
            "INSERT INTO audit_log (ts, actor, event, tile_id, conversation_id, detail) VALUES (?,?,?,?,?,?)",
            (_now(), actor, event, tile_id, conversation_id, str(detail)[:1000]),
        )
    except Exception:  # noqa: BLE001 – Audit darf den Betrieb nie stoppen
        pass


def _fallbacks(tile: dict) -> list[str]:
    """Fallback-Kette der Kachel (Admin-Einstellung, sonst Seed-Vorschlag)."""
    raw = (tile.get("fallback_models") or "").strip()
    if raw:
        try:
            chain = json.loads(raw)
            if isinstance(chain, list):
                return [str(m) for m in chain if m]
        except json.JSONDecodeError:
            return [m.strip() for m in raw.split(",") if m.strip()]
    return FALLBACK_KETTEN.get(tile["id"], [m for m in FREE_MODELS if m != tile["model"]][:2])


def _bremse_pruefen(request: Request, zeichen: int = 0) -> str:
    """Limit-/Budgetprüfung vor jedem LLM-Call (öffentliche Test-Instanzen)."""
    ip = limits.client_ip(request)
    try:
        limits.BREMSE.pruefen(ip, zeichen)
    except limits.LimitError as e:
        audit("limit_erreicht", None, None, f"{ip}: {e}")
        raise HTTPException(e.status, str(e)) from e
    limits.BREMSE.notieren(ip)
    return ip


def _health_map() -> dict[str, dict]:
    return {r["model"]: dict(r) for r in db.query("SELECT * FROM model_health")}


def _config_lines(tid: str) -> list[str]:
    """Standardwerte: Nutzerwert (falls gesetzt) sonst Default."""
    rows = db.query(
        "SELECT key, label, description, default_value, unit FROM standardwerte WHERE tile_id=? ORDER BY sort",
        (tid,),
    )
    vals = {r["key"]: r["value"] for r in db.query("SELECT key, value FROM settings WHERE tile_id=?", (tid,))}
    lines = []
    for r in rows:
        val = vals.get(r["key"], r["default_value"])
        unit = f" ({r['unit']})" if r["unit"] else ""
        if val:
            lines.append(f"- {r['label']}: {val}{unit}")
    return lines


def _file_blocks(cid: str) -> str:
    rows = db.query(
        "SELECT filename, extracted_text, extracted_chars FROM files WHERE conversation_id=? ORDER BY created_at",
        (cid,),
    )
    blocks, total = [], 0
    for r in rows:
        if r["extracted_chars"]:
            total += len(r["extracted_text"])
            blocks.append(
                f"### {r['filename']} ({r['extracted_chars']} Zeichen)\n```\n{r['extracted_text']}\n```"
            )
        else:
            blocks.append(f"### {r['filename']} – Inhalt konnte nicht extrahiert werden. Bitte als .txt/.csv/.xlsx/.docx/.pdf hochladen.")
        if total > MAX_TOTAL_FILE_CHARS:
            blocks.append("… (weitere Dateien wegen Kontextgrenze nicht mitgerechnet)")
            break
    return "\n\n".join(blocks)


def build_system(tile: dict, prompt: str, cid: str | None = None, test_file: str = "") -> str:
    parts = [prompt.strip()]
    cfg = _config_lines(tile["id"])
    if cfg:
        parts.append("## Konfiguration der Kommune (Nutzer-Werte – haben Vorrang vor deinen Fallback-Werten)\n" + "\n".join(cfg))
    file_block = _file_blocks(cid) if cid else ""
    if test_file:
        file_block = (file_block + "\n\n" if file_block else "") + f"### Test-Dateikontext\n```\n{test_file[:12000]}\n```"
    if file_block:
        parts.append("## Hochgeladene Dateien der Kommune\nNutze sie als Datenbasis; wo Daten fehlen, benenne es als Annahme.\n" + file_block)
    parts.append(
        "## Gesprächsregeln\n"
        "- Antworte auf Deutsch, präzise und ohne Füllfloskeln.\n"
        "- Stell im ersten Schritt gezielt Rückfragen, bevor du Endergebnisse lieferst – max. 4 Fragen pro Nachricht.\n"
        "- Liefert die Kommune Daten nach, rechne/entwirfe direkt; wiederhole keine geklärten Punkte.\n"
        "- Markiere alle Annahmen explizit. Erfinde niemals Messdaten, Fristen oder Fördersätze."
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------- public API


class ConvIn(BaseModel):
    tile_id: str
    title: Optional[str] = None


class ChatIn(BaseModel):
    message: str


class SettingsIn(BaseModel):
    values: dict


class TestCaseIn(BaseModel):
    name: str
    message: str
    file_content: str = ""


class TestIn(BaseModel):
    message: str
    file_content: str = ""


class TileIn(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    system_prompt: Optional[str] = None
    fallback_models: Optional[list[str]] = None


class LoginIn(BaseModel):
    password: str


@app.get("/api/tiles")
def list_tiles():
    rows = db.query("SELECT id, emoji, name, short, model FROM tiles ORDER BY sort")
    from server.seed import SUGGESTIONS

    return [
        {**dict(r), "suggestions": SUGGESTIONS.get(r["id"], [])}
        for r in rows
    ]


_MODEL_CACHE: dict = {"ts": 0.0, "items": []}
MODEL_CACHE_SECONDS = 900


async def _fetch_models() -> list[dict]:
    """Live-Liste von OpenRouter (öffentlich, ohne Key) – Gratis-Modelle zuerst."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            r = await client.get("https://openrouter.ai/api/v1/models")
            r.raise_for_status()
            data = r.json().get("data", [])
    except Exception:  # noqa: BLE001 – offline/Netzsperre → statische Liste
        return []
    free, paid = [], []
    for m in data:
        mid = m.get("id", "")
        arch = m.get("architecture", {}) or {}
        if "text" not in (arch.get("output_modalities") or ["text"]):
            continue
        p = m.get("pricing") or {}
        gratis = (
            float(p.get("prompt") or 0) == 0 and float(p.get("completion") or 0) == 0
        )
        if mid in FREE_MODELS or mid.endswith(":free") or gratis:
            free.append({"id": mid, "free": True, "label": f"🆓 {mid}"})
        elif mid in MODELS:
            paid.append({"id": mid, "free": False, "label": mid})
    free.sort(key=lambda m: (m["id"] not in FREE_MODELS, m["id"]))  # kuratierte zuerst
    return free + paid


@app.get("/api/models")
async def list_models(refresh: int = 0):
    """Modell-Liste für den Admin-Bereich: live von OpenRouter, sonst Fallback."""
    now = time.time()
    if refresh or not _MODEL_CACHE["items"] or now - _MODEL_CACHE["ts"] > MODEL_CACHE_SECONDS:
        items = await _fetch_models()
        if items:
            _MODEL_CACHE.update(ts=now, items=items)
    if _MODEL_CACHE["items"]:
        return _MODEL_CACHE["items"]
    return [{"id": m, "free": m.endswith(":free"), "label": f"🆓 {m}" if m.endswith(":free") else m} for m in (FREE_MODELS + MODELS)]


@app.get("/api/models/status")
def models_status():
    """Diagnose: Ist OpenRouter erreichbar und ist ein Key gesetzt?"""
    return {
        "api_key": bool(os.environ.get("OPENROUTER_API_KEY", "")),
        "live_liste": bool(_MODEL_CACHE["items"]),
        "anzahl": len(_MODEL_CACHE["items"]),
        "geprueft_am": datetime.fromtimestamp(_MODEL_CACHE["ts"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if _MODEL_CACHE["ts"] else "",
    }


@app.get("/api/status")
def app_status(request: Request):
    """Betriebsstatus für die Oberfläche: Demo-Flag (Datenschutz), Limits, Key."""
    ip = limits.client_ip(request)
    st = limits.BREMSE.status(ip)
    return {
        "demo_only": DEMO_ONLY,
        "api_key": bool(os.environ.get("OPENROUTER_API_KEY", "")),
        "live_liste": bool(_MODEL_CACHE["items"]),
        "admin_geschuetzt": bool(ADMIN_PASSWORD),
        "limits": st,
        "rest_heute": max(0, (st["tagesbudget"] - st["verbraucht_heute"])) if st["tagesbudget"] else None,
        "version": "SusMob 0.4 (Phase 0+1)",
    }


@app.get("/api/tiles/{tid}/standardwerte")
def get_std(tid: str):
    _tile_or_404(tid)
    rows = db.query(
        "SELECT key, label, description, default_value, unit FROM standardwerte WHERE tile_id=? ORDER BY sort",
        (tid,),
    )
    vals = {r["key"]: r["value"] for r in db.query("SELECT key, value FROM settings WHERE tile_id=?", (tid,))}
    return [
        {**dict(r), "value": vals.get(r["key"], r["default_value"]), "custom": r["key"] in vals}
        for r in rows
    ]


@app.put("/api/tiles/{tid}/standardwerte")
def set_std(tid: str, body: SettingsIn):
    _tile_or_404(tid)
    for k, v in body.values.items():
        db.exec(
            "INSERT INTO settings (tile_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT(tile_id, key) DO UPDATE SET value=excluded.value",
            (tid, k, str(v)),
        )
    return {"ok": True}


@app.post("/api/conversations")
def new_conversation(body: ConvIn):
    tile = _tile_or_404(body.tile_id)
    cid = uuid.uuid4().hex
    ts = _now()
    db.exec(
        "INSERT INTO conversations (id, tile_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
        (cid, tile["id"], body.title or "Neue Unterhaltung", ts, ts),
    )
    return {"id": cid}


@app.get("/api/conversations")
def list_conversations(tile_id: str | None = None):
    """Eigene Unterhaltungen zuerst, Beispiele ans Ende der Liste."""
    if tile_id:
        return [
            dict(r)
            for r in db.query(
                "SELECT * FROM conversations WHERE tile_id=? ORDER BY is_example, updated_at DESC",
                (tile_id,),
            )
        ]
    return [
        dict(r)
        for r in db.query("SELECT * FROM conversations ORDER BY is_example, updated_at DESC LIMIT 200")
    ]


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str):
    conv = _conv_or_404(cid)
    conv["messages"] = [
        dict(r) for r in db.query(
            "SELECT role, content, created_at, model, prompt_tokens, completion_tokens, cost_usd, duration_ms "
            "FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    ]
    conv["files"] = [
        {"id": r["id"], "filename": r["filename"], "size": r["size"], "extracted_chars": r["extracted_chars"]}
        for r in db.query("SELECT id, filename, size, extracted_chars FROM files WHERE conversation_id=? ORDER BY created_at", (cid,))
    ]
    conv["artifacts"] = [
        {"id": r["id"], "kind": r["kind"], "filename": r["filename"], "size": r["size"],
         "created_at": r["created_at"], "meta": json.loads(r["meta"] or "{}")}
        for r in db.query(
            "SELECT id, kind, filename, size, created_at, meta FROM artifacts WHERE conversation_id=? "
            "ORDER BY created_at DESC", (cid,))
    ]
    conv["kosten"] = dict(db.query1(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS tokens, "
        "COALESCE(SUM(cost_usd),0) AS kosten_usd, COALESCE(SUM(tokens_estimated),0) AS geschaetzt "
        "FROM llm_calls WHERE conversation_id=?", (cid,)) or {}) if _has_table("llm_calls") else {}
    return conv


def _has_table(name: str) -> bool:
    try:
        return bool(db.query1("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)))
    except Exception:  # noqa: BLE001
        return False


@app.post("/api/conversations/{cid}/duplicate")
def duplicate_conversation(cid: str):
    """Übernimmt ein (Beispiel-)Gespräch als eigene, bearbeitbare Unterhaltung."""
    src = _conv_or_404(cid)
    new_id = uuid.uuid4().hex
    ts = _now()
    base_title = src["title"].replace("📘 Beispiel:", "").strip() or "Unterhaltung"
    db.exec(
        "INSERT INTO conversations (id, tile_id, title, created_at, updated_at, is_example) VALUES (?,?,?,?,?,0)",
        (new_id, src["tile_id"], f"{base_title} (eigene Kopie)", ts, ts),
    )
    for m in db.query(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id", (cid,)
    ):
        db.exec(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
            (new_id, m["role"], m["content"], ts),
        )
    dest_dir = UPLOAD_DIR / new_id
    for f in db.query("SELECT * FROM files WHERE conversation_id=? ORDER BY created_at", (cid,)):
        fid = uuid.uuid4().hex
        src_path = Path(f["stored_path"])
        stored_path = ""
        if src_path.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
            stored = dest_dir / f"{fid}_{f['filename']}"
            shutil.copyfile(src_path, stored)
            stored_path = str(stored)
        db.exec(
            "INSERT INTO files (id, conversation_id, tile_id, filename, size, stored_path, "
            "extracted_chars, extracted_text, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (fid, new_id, src["tile_id"], f["filename"], f["size"], stored_path,
             f["extracted_chars"], f["extracted_text"], ts),
        )
    return {"id": new_id}


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str):
    conv = _conv_or_404(cid)
    if conv.get("is_example"):
        raise HTTPException(403, "Beispiel-Unterhaltungen sind schreibgeschützt")
    for r in db.query("SELECT stored_path FROM files WHERE conversation_id=?", (cid,)):
        p = Path(r["stored_path"])
        if p.exists():
            p.unlink()
    db.exec("DELETE FROM files WHERE conversation_id=?", (cid,))
    db.exec("DELETE FROM messages WHERE conversation_id=?", (cid,))
    db.exec("DELETE FROM conversations WHERE id=?", (cid,))
    d = UPLOAD_DIR / cid
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@app.post("/api/conversations/{cid}/files")
async def upload_file(cid: str, file: UploadFile = File(...)):
    conv = _conv_or_404(cid)
    if len(file.filename or "") > 200:
        raise HTTPException(400, "Dateiname zu lang")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Datei zu groß (max. 25 MB)")
    fid = uuid.uuid4().hex
    safe = Path(file.filename or "datei").name
    dest = UPLOAD_DIR / cid
    dest.mkdir(parents=True, exist_ok=True)
    stored = dest / f"{fid}_{safe}"
    stored.write_bytes(data)
    text = extract_text(stored)
    db.exec(
        "INSERT INTO files (id, conversation_id, tile_id, filename, size, stored_path, extracted_chars, extracted_text, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (fid, cid, conv["tile_id"], safe, len(data), str(stored), len(text), text, _now()),
    )
    return {"id": fid, "filename": safe, "size": len(data), "extracted_chars": len(text)}


@app.delete("/api/conversations/{cid}/files/{fid}")
def delete_file(cid: str, fid: str):
    _conv_or_404(cid)
    row = db.query1("SELECT * FROM files WHERE id=? AND conversation_id=?", (fid, cid))
    if not row:
        raise HTTPException(404, "Datei nicht gefunden")
    p = Path(row["stored_path"])
    if p.exists():
        p.unlink()
    db.exec("DELETE FROM files WHERE id=?", (fid,))
    return {"ok": True}


@app.post("/api/conversations/{cid}/chat")
async def chat(request: Request, cid: str, body: ChatIn):
    conv = _conv_or_404(cid)
    if conv.get("is_example"):
        raise HTTPException(
            403,
            "Das ist eine Beispiel-Unterhaltung (schreibgeschützt). Bitte über „Als eigene "
            "Unterhaltung übernehmen“ weiterarbeiten.",
        )
    tile = _tile_or_404(conv["tile_id"])
    prompt_row = db.query1("SELECT system_prompt FROM prompts WHERE tile_id=?", (tile["id"],))
    prompt = prompt_row["system_prompt"] if prompt_row else "Du bist ein hilfsbereiter Experte."

    text = body.message.strip()
    if not text:
        raise HTTPException(400, "Leere Nachricht")
    _bremse_pruefen(request, len(text))

    ts = _now()
    db.exec(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
        (cid, "user", text, ts),
    )
    db.exec("UPDATE conversations SET updated_at=? WHERE id=?", (ts, cid))
    if conv["title"] == "Neue Unterhaltung":
        title = text[:50] + ("…" if len(text) > 50 else "")
        db.exec("UPDATE conversations SET title=? WHERE id=?", (title, cid))

    # Alle Nachrichten VOR der aktuellen User-Nachricht (chronologisch, begrenzt)
    history = db.query(
        "SELECT role, content FROM messages WHERE conversation_id=? AND id < (SELECT MAX(id) FROM messages WHERE conversation_id=?) ORDER BY id DESC LIMIT ?",
        (cid, cid, HISTORY_LIMIT),
    )
    history = [dict(r) for r in reversed(history)]

    system = build_system(tile, prompt, cid)
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": text})

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if DEMO_ONLY:
        audit("chat_demo_betrieb", tile["id"], cid,
              "SUSMOB_DEMO_ONLY aktiv – Anfrage über Gratis-Modell (Training mit Prompts möglich)")

    async def gen():
        full: list[str] = []
        if not api_key:
            note = (
                "⚠️ **Kein OpenRouter-API-Key hinterlegt.**\n\n"
                "Setze die Umgebungsvariable `OPENROUTER_API_KEY` und starte den Server neu, "
                "damit der Chat mit echten Modellen funktioniert.\n\n"
                "Die Konfiguration, die Standardwerte und der Upload laufen bereits korrekt – "
                "diese Nachricht wäre an das Modell `__MODEL__` gegangen.\n\n"
                "*(Demo-Modus: die Antwort kommt nicht von einem LLM.)*"
            ).replace("__MODEL__", tile["model"])
            yield _sse("token", {"t": note})
            db.exec(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                (cid, "assistant", note, _now()),
            )
            yield _sse("done", {})
            return
        try:
            async for ev, data in stream_chat(
                tile["model"], messages, api_key, tile["temperature"],
                fallbacks=_fallbacks(tile), feature="chat", tile_id=tile["id"], conversation_id=cid,
            ):
                if ev == "token":
                    full.append(data["t"])
                    yield _sse("token", data)
                elif ev == "notice":
                    yield _sse("notice", data)
                elif ev == "usage":
                    db.exec(
                        "INSERT INTO messages (conversation_id, role, content, created_at, model, "
                        "prompt_tokens, completion_tokens, cost_usd, duration_ms) VALUES (?,?,?,?,?,?,?,?,?)",
                        (cid, "assistant", "".join(full), _now(), data.get("model"),
                         data.get("prompt_tokens", 0), data.get("completion_tokens", 0),
                         data.get("cost_usd", 0.0), data.get("duration_ms", 0)),
                    )
                    audit("chat", tile["id"], cid, f"Modell {data.get('model')} · "
                          f"{data.get('prompt_tokens', 0)}/{data.get('completion_tokens', 0)} Tokens · "
                          f"{data.get('cost_usd', 0.0):.5f} $ · {data.get('duration_ms', 0)} ms"
                          + (" (Fallback)" if data.get("degraded") else ""))
                    yield _sse("usage", data)
        except Exception as e:  # noqa: BLE001
            if full:
                db.exec(
                    "INSERT INTO messages (conversation_id, role, content, created_at, model) VALUES (?,?,?,?,?)",
                    (cid, "assistant", "".join(full), _now(), tile["model"]),
                )
            audit("chat_error", tile["id"], cid, _llm_error_text(e)[:400])
            yield _sse("error", {"error": _llm_error_text(e)})
            return
        if not full:
            yield _sse("error", {"error": "Das Modell hat eine leere Antwort geliefert – bitte erneut senden."})
            return
        yield _sse("done", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------- Rechenkern, Auswertung & Exporte


class CalcIn(BaseModel):
    params: dict = {}


@app.post("/api/calc/{tid}")
def calc_stateless(tid: str, body: CalcIn):
    """Deterministische Rechnung ohne LLM (Phase 2) – testbar, reproduzierbar."""
    _tile_or_404(tid)
    return calc.rechnen(tid, body.params)


def _letzte_assistenz(cid: str) -> str:
    row = db.query1(
        "SELECT content FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",
        (cid,),
    )
    return row["content"] if row else ""


def _artefakt_anlegen(cid: str, tile_id: str, kind: str, filename: str, data: bytes,
                      meta: dict | None = None) -> dict:
    aid = uuid.uuid4().hex
    dest = ARTIFACT_DIR / cid
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{aid}_{filename}"
    path.write_bytes(data)
    db.exec(
        "INSERT INTO artifacts (id, conversation_id, tile_id, kind, filename, stored_path, size, meta, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, cid, tile_id, kind, filename, str(path), len(data),
         json.dumps(meta or {}, ensure_ascii=False), _now()),
    )
    audit("artefakt", tile_id, cid, f"{kind}: {filename} ({len(data)} Bytes)")
    return {"id": aid, "kind": kind, "filename": filename, "size": len(data),
            "url": f"/api/artifacts/{aid}", "meta": meta or {}}


async def _auswertung(cid: str, tile: dict, *, frisch: bool = False, extrahieren: bool = True) -> dict:
    """Strukturierte Auswertung des Gesprächs: LLM extrahiert, Code rechnet.

    Ergebnis wird als JSON-Artefakt (``kind='daten'``) gespeichert und beim
    Export wiederverwendet – so bleibt der Export reproduzierbar und spart Tokens.
    """
    if not frisch:
        row = db.query1(
            "SELECT meta FROM artifacts WHERE conversation_id=? AND kind='daten' ORDER BY created_at DESC LIMIT 1",
            (cid,),
        )
        if row:
            try:
                cached = json.loads(row["meta"] or "{}")
                # Nur verwenden, wenn wirklich etwas berechnet wurde bzw. Schema-Daten vorliegen
                if cached.get("berechnet") or cached.get("strukturiert"):
                    return cached
            except json.JSONDecodeError:
                pass
    strukturiert: dict = {}
    modell = ""
    fehler = ""
    extraktion_fehler = ""
    if extrahieren:
        j_schema = schema_mod.SCHEMAS.get(tile["id"])
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if j_schema and api_key:
            system = build_system(tile, db.query1(
                "SELECT system_prompt FROM prompts WHERE tile_id=?", (tile["id"],))["system_prompt"], cid)
            system += ("\n\n## Aufgabe: Datenextraktion\n"
                       f"{schema_mod.FELDER.get(tile['id'], '')}\n"
                       "Übernimm nur Angaben aus dem Gespräch und den Dateien. Was fehlt, bleibt weg – "
                       "nichts schätzen, nichts ergänzen.")
            hist = db.query(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 12", (cid,))
            messages = [{"role": "system", "content": system}]
            messages += [{"role": r["role"], "content": r["content"]} for r in reversed(hist)]
            messages.append({"role": "user", "content":
                             "Gib die strukturierten Daten dieses Gesprächs als JSON aus."})
            try:
                daten, result = await chat_json(
                    tile["model"], messages, api_key, j_schema, fallbacks=_fallbacks(tile),
                    feature="extract", tile_id=tile["id"], conversation_id=cid)
                strukturiert = daten
                modell = result.model
            except Exception as e:  # noqa: BLE001 – Extraktion darf den Export nicht blockieren
                fehler = f"Extraktion fehlgeschlagen: {e}"
        elif not api_key:
            fehler = "Kein OPENROUTER_API_KEY – Auswertung ohne strukturierte Extraktion (nur Antworttext)."
        else:
            fehler = "Für diese Kachel ist kein Structured-Output-Schema definiert – nur Antworttext."
    ergebnis = calc.rechnen(tile["id"], strukturiert) if strukturiert else {}
    if not ergebnis or ergebnis.get("typ") == "kennzahlen":
        # Kein Schema/kein Netz: Zahlen deterministisch aus dem Antworttext ziehen
        aus_text = parse_mod.parse(tile["id"], _letzte_assistenz(cid))
        if aus_text:
            ergebnis = aus_text
            extraktion_fehler = fehler
            fehler = aus_text["pruefungen"][0] if aus_text.get("pruefungen") else ""
        else:
            extraktion_fehler = fehler
    payload = {
        "tile_id": tile["id"],
        "strukturiert": strukturiert,
        "berechnet": ergebnis,
        "modell": modell,
        "fehler": fehler,
        "extraktion_fehler": extraktion_fehler,
        "erstellt": _now(),
    }
    _artefakt_anlegen(cid, tile["id"], "daten", f"{tile['id']}-auswertung.json",
                      json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                      {"strukturiert": strukturiert, "berechnet": ergebnis, "modell": modell, "fehler": fehler})
    return payload


@app.post("/api/conversations/{cid}/auswertung")
async def auswertung(request: Request, cid: str, frisch: int = 0):
    """Strukturierte Auswertung (Phase 1): Schema-Extraktion + Rechenkern."""
    _bremse_pruefen(request)
    conv = _conv_or_404(cid)
    tile = _tile_or_404(conv["tile_id"])
    result = await _auswertung(cid, tile, frisch=bool(frisch))
    result["antwort"] = _letzte_assistenz(cid)
    return result


class ExportIn(BaseModel):
    titel: str = ""


@app.post("/api/conversations/{cid}/export/{fmt}")
async def export_artifact(request: Request, cid: str, fmt: str, body: ExportIn | None = None, frisch: int = 0):
    """Export: ``xlsx`` (Formeln + Annahmen-Blatt) oder ``json`` (Maschinendaten)."""
    fmt = fmt.lower().strip()
    if fmt in ("xls", "excel"):
        fmt = "xlsx"
    if fmt == "pdf":
        # PDF entsteht bewusst clientseitig über Druck-CSS (Plan 4.3, Weg A)
        raise HTTPException(400, "PDF wird über die Druckansicht erzeugt (🖨️ im Chat).")
    if fmt not in ("xlsx", "json"):
        raise HTTPException(400, "Unbekanntes Format – erlaubt: xlsx, json (PDF = Druckansicht).")
    conv = _conv_or_404(cid)
    tile = _tile_or_404(conv["tile_id"])
    if frisch:
        _bremse_pruefen(request)
    aus = await _auswertung(cid, tile, frisch=bool(frisch))
    antwort = _letzte_assistenz(cid)
    titel = (body.titel if body else "") or conv["title"]
    model_row = db.query1(
        "SELECT model FROM messages WHERE conversation_id=? AND model IS NOT NULL AND model != '' "
        "ORDER BY id DESC LIMIT 1", (cid,))
    modell = (model_row["model"] if model_row else "") or tile["model"]
    if fmt == "xlsx":
        daten = exports.build_workbook(
            tile_name=tile["name"], conversation_title=titel, calc=aus.get("berechnet") or None,
            structured=aus.get("strukturiert") or None, answer=antwort, model=modell, created_at=_now())
    else:
        daten = exports.json_artefakt(tile["name"], aus.get("berechnet"), aus.get("strukturiert"), antwort, modell)
    info = _artefakt_anlegen(cid, tile["id"], fmt, exports.dateiname(tile["id"], fmt, titel), daten,
                             {"rechenkern": (aus.get("berechnet") or {}).get("typ", ""),
                              "modell": modell, "warnung": aus.get("fehler", "")})
    info["hinweis"] = aus.get("fehler", "")
    return info


@app.get("/api/artifacts/{aid}")
def download_artifact(aid: str):
    row = db.query1("SELECT * FROM artifacts WHERE id=?", (aid,))
    if not row:
        raise HTTPException(404, "Artefakt nicht gefunden")
    path = Path(row["stored_path"])
    if not path.exists():
        raise HTTPException(410, "Datei ist nicht mehr vorhanden")
    typen = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "json": "application/json", "daten": "application/json"}
    return FileResponse(path, filename=row["filename"],
                        media_type=typen.get(row["kind"], "application/octet-stream"))


@app.delete("/api/artifacts/{aid}")
def delete_artifact(aid: str):
    row = db.query1("SELECT stored_path FROM artifacts WHERE id=?", (aid,))
    if not row:
        raise HTTPException(404, "Artefakt nicht gefunden")
    p = Path(row["stored_path"])
    if p.exists():
        p.unlink()
    db.exec("DELETE FROM artifacts WHERE id=?", (aid,))
    return {"ok": True}


@app.get("/api/tiles/{tid}/schema")
def tile_schema(tid: str):
    """Structured-Output-Schema der Kachel (transparent für Admin & Export)."""
    _tile_or_404(tid)
    return {
        "tile_id": tid,
        "schema": schema_mod.SCHEMAS.get(tid),
        "felder": schema_mod.FELDER.get(tid, ""),
        "rechenkern": tid in ("co2-bilanz", "opnv-planung", "wegeplanung", "massnahmenplanung"),
    }


# ---------------------------------------------------------------- admin API


@app.post("/api/admin/login")
def admin_login(body: LoginIn):
    if not ADMIN_PASSWORD:
        return {"token": "offen", "open": True}
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(401, "Falsches Passwort")
    tok = secrets.token_urlsafe(24)
    _admin_tokens.add(tok)
    return {"token": tok, "open": False}


@app.get("/api/admin/status")
def admin_status():
    return {"protected": bool(ADMIN_PASSWORD)}


@app.get("/api/admin/tiles")
def admin_tiles(request: Request):
    _check_admin(request)
    rows = db.query("SELECT * FROM tiles ORDER BY sort")
    out = []
    for r in rows:
        d = dict(r)
        p = db.query1("SELECT system_prompt, updated_at FROM prompts WHERE tile_id=?", (r["id"],))
        d["system_prompt"] = p["system_prompt"] if p else ""
        d["prompt_updated_at"] = p["updated_at"] if p else ""
        out.append(d)
    return out


@app.put("/api/admin/tiles/{tid}")
def admin_update_tile(request: Request, tid: str, body: TileIn):
    _check_admin(request)
    _tile_or_404(tid)
    sets, params = [], []
    if body.model is not None:
        sets.append("model=?"); params.append(body.model)
    if body.temperature is not None:
        sets.append("temperature=?"); params.append(body.temperature)
    if body.fallback_models is not None:
        sets.append("fallback_models=?"); params.append(json.dumps(body.fallback_models, ensure_ascii=False))
    if sets:
        db.exec(f"UPDATE tiles SET {', '.join(sets)} WHERE id=?", (*params, tid))
    if body.system_prompt is not None:
        old = db.query1("SELECT system_prompt FROM prompts WHERE tile_id=?", (tid,))
        if old and old["system_prompt"] != body.system_prompt:
            model = db.query1("SELECT model FROM tiles WHERE id=?", (tid,))["model"]
            db.exec(
                "INSERT INTO prompt_versions (tile_id, system_prompt, model, created_at) VALUES (?,?,?,?)",
                (tid, old["system_prompt"], model, _now()),
            )
        ts = _now()
        db.exec(
            "INSERT INTO prompts (tile_id, system_prompt, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(tile_id) DO UPDATE SET system_prompt=excluded.system_prompt, updated_at=excluded.updated_at",
            (tid, body.system_prompt, ts),
        )
        audit("prompt_geaendert", tid, None, f"{len(body.system_prompt)} Zeichen")
    if body.model is not None or body.temperature is not None or body.fallback_models is not None:
        audit("modell_geaendert", tid, None,
              f"model={body.model} temp={body.temperature} kette={body.fallback_models}")
    return {"ok": True}


@app.get("/api/admin/tiles/{tid}/versions")
def admin_versions(request: Request, tid: str):
    _check_admin(request)
    rows = db.query(
        "SELECT id, model, created_at, length(system_prompt) AS chars FROM prompt_versions WHERE tile_id=? ORDER BY id DESC LIMIT 15",
        (tid,),
    )
    return [dict(r) for r in rows]


@app.post("/api/admin/tiles/{tid}/versions/{vid}/restore")
def admin_restore(request: Request, tid: str, vid: int):
    _check_admin(request)
    row = db.query1("SELECT * FROM prompt_versions WHERE id=? AND tile_id=?", (vid, tid))
    if not row:
        raise HTTPException(404, "Version nicht gefunden")
    db.exec("UPDATE tiles SET model=? WHERE id=?", (row["model"], tid))
    db.exec(
        "INSERT INTO prompts (tile_id, system_prompt, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(tile_id) DO UPDATE SET system_prompt=excluded.system_prompt, updated_at=excluded.updated_at",
        (tid, row["system_prompt"], _now()),
    )
    return {"ok": True}


@app.get("/api/admin/tiles/{tid}/test-cases")
def admin_test_cases(request: Request, tid: str):
    _check_admin(request)
    return [dict(r) for r in db.query("SELECT id, name, message, file_content FROM test_cases WHERE tile_id=? ORDER BY id", (tid,))]


@app.post("/api/admin/tiles/{tid}/test-cases")
def admin_add_test_case(request: Request, tid: str, body: TestCaseIn):
    _check_admin(request)
    _tile_or_404(tid)
    db.exec(
        "INSERT INTO test_cases (tile_id, name, message, file_content, created_at) VALUES (?,?,?,?,?)",
        (tid, body.name, body.message, body.file_content, _now()),
    )
    return {"ok": True}


@app.delete("/api/admin/tiles/{tid}/test-cases/{cid}")
def admin_del_test_case(request: Request, tid: str, cid: int):
    _check_admin(request)
    db.exec("DELETE FROM test_cases WHERE id=? AND tile_id=?", (cid, tid))
    return {"ok": True}


@app.post("/api/admin/tiles/{tid}/test")
async def admin_test_run(request: Request, tid: str, body: TestIn):
    _check_admin(request)
    tile = _tile_or_404(tid)
    prompt_row = db.query1("SELECT system_prompt FROM prompts WHERE tile_id=?", (tile["id"],))
    prompt = prompt_row["system_prompt"] if prompt_row else ""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Kein OPENROUTER_API_KEY hinterlegt – Testlauf nicht möglich.")
    system = build_system(tile, prompt, test_file=body.file_content)
    system += "\n\n## Testmodus\nDies ist ein Testlauf in der Admin-Oberfläche. Behandle den Input als Testdaten der Beispiel-Kommune."
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": body.message},
    ]
    try:
        result = await chat_once(tile["model"], messages, api_key, tile["temperature"],
                                 fallbacks=_fallbacks(tile), feature="admin_test", tile_id=tile["id"])
        audit("admin_test", tile["id"], None, f"Modell {result.model}")
        return {"ok": True, "content": result.content, "model": result.model,
                "angefragt": result.model_requested, "fallback": result.degraded,
                "usage": result.usage.as_dict, "dauer_ms": result.duration_ms}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, _llm_error_text(e)) from e


@app.get("/api/admin/examples")
def admin_examples(request: Request):
    """Status der Beispiel-Unterhaltungen je Kachel."""
    _check_admin(request)
    out = []
    for tid, ex in EXAMPLES.items():
        cid = f"ex-{tid}"
        n = db.query1("SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?", (cid,))
        tile = db.query1("SELECT emoji, name, model FROM tiles WHERE id=?", (tid,))
        out.append({
            "tile_id": tid,
            "conversation_id": cid,
            "title": ex["title"],
            "note": ex["note"],
            "messages": n["n"] if n else 0,
            "model": tile["model"] if tile else "",
            "name": f"{tile['emoji']} {tile['name']}" if tile else tid,
        })
    return out


@app.post("/api/admin/examples/regenerate")
async def admin_examples_regenerate(request: Request, tile_id: str | None = None):
    """Erzeugt Beispielantworten mit dem echten, je Kachel konfigurierten Modell neu.

    Ohne ``tile_id`` werden alle Beispiele neu erzeugt (Achtung: Free-Tier-Limit
    von ca. 50 Requests/Tag – pro Kachel fallen so viele Requests an wie
    Assistenten-Antworten im Beispiel enthalten sind).
    """
    _check_admin(request)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Kein OPENROUTER_API_KEY hinterlegt – Neuerzeugung nicht möglich.")

    tiles = [tile_id] if tile_id else list(EXAMPLES.keys())
    results = []
    for tid in tiles:
        ex = EXAMPLES.get(tid)
        if not ex:
            raise HTTPException(404, f"Kein Beispiel für Kachel: {tid}")
        tile = _tile_or_404(tid)
        row = db.query1("SELECT system_prompt FROM prompts WHERE tile_id=?", (tid,))
        prompt = row["system_prompt"] if row else ""
        cid = f"ex-{tid}"
        system = build_system(tile, prompt, cid)
        system += (
            "\n\n## Beispielmodus\n"
            "Dies ist ein Beispiellauf für die Anschauung im Produkt. Antworte so, wie du einer "
            "Kommune in der echten Nutzung antworten würdest – mit Tabellen, benannten Annahmen "
            "und ohne erfundene Messdaten."
        )
        messages: list[dict] = [{"role": "system", "content": system}]
        neu: list[tuple[str, str]] = []
        try:
            for role, content in ex["messages"]:
                if role == "user":
                    neu.append((role, content))
                    messages.append({"role": "user", "content": content})
                else:
                    res = await chat_once(tile["model"], messages, api_key, tile["temperature"],
                                          fallbacks=_fallbacks(tile), feature="example_regenerate",
                                          tile_id=tid)
                    out = res.content
                    neu.append(("assistant", out))
                    messages.append({"role": "assistant", "content": out})
            replace_messages(cid, neu)
            results.append({
                "tile_id": tid, "ok": True, "model": tile["model"],
                "chars": sum(len(c) for _, c in neu),
            })
        except Exception as e:  # noqa: BLE001 – Fehler je Kachel zurückmelden
            results.append({"tile_id": tid, "ok": False, "model": tile["model"], "error": str(e)})
    return {"results": results}


# ------------------------------------------------- Kosten, Health, Eval, Audit


@app.get("/api/admin/usage")
def admin_usage(request: Request, days: int = 30):
    """Token-/Kostenmessung (Phase 0): Messwerte statt Schätzungen."""
    _check_admin(request)
    seit = f"datetime('now', '-{max(1, min(days, 365))} days')"
    gesamt = db.query1(
        f"SELECT COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, "
        f"COALESCE(SUM(completion_tokens),0) AS completion_tokens, COALESCE(SUM(total_tokens),0) AS total_tokens, "
        f"COALESCE(SUM(cost_usd),0) AS kosten_usd, COALESCE(AVG(duration_ms),0) AS dauer_ms, "
        f"COALESCE(SUM(tokens_estimated),0) AS geschaetzt, "
        f"COALESCE(SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END),0) AS fehler "
        f"FROM llm_calls WHERE created_at >= {seit}")
    je_kachel = db.query(
        f"SELECT tile_id, COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS tokens, "
        f"COALESCE(SUM(cost_usd),0) AS kosten_usd, COALESCE(AVG(duration_ms),0) AS dauer_ms "
        f"FROM llm_calls WHERE created_at >= {seit} GROUP BY tile_id ORDER BY tokens DESC")
    je_modell = db.query(
        f"SELECT model, COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS tokens, "
        f"COALESCE(SUM(cost_usd),0) AS kosten_usd, "
        f"COALESCE(SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END),0) AS fehler, "
        f"COALESCE(SUM(CASE WHEN attempt>1 THEN 1 ELSE 0 END),0) AS fallbacks "
        f"FROM llm_calls WHERE created_at >= {seit} GROUP BY model ORDER BY calls DESC")
    je_tag = db.query(
        f"SELECT substr(created_at,1,10) AS tag, COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS kosten_usd, "
        f"COALESCE(SUM(total_tokens),0) AS tokens FROM llm_calls WHERE created_at >= {seit} "
        f"GROUP BY tag ORDER BY tag DESC LIMIT 60")
    je_feature = db.query(
        f"SELECT feature, COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS kosten_usd, "
        f"COALESCE(AVG(duration_ms),0) AS dauer_ms FROM llm_calls WHERE created_at >= {seit} "
        f"GROUP BY feature ORDER BY calls DESC")
    gesamt = dict(gesamt or {})
    calls = gesamt.get("calls") or 0
    return {
        "zeitraum_tage": days,
        "gesamt": {
            **gesamt,
            "kosten_pro_call_usd": round((gesamt.get("kosten_usd") or 0) / calls, 6) if calls else 0.0,
            "anteil_geschaetzt_pct": round((gesamt.get("geschaetzt") or 0) / calls * 100, 1) if calls else 0.0,
        },
        "je_kachel": [dict(r) for r in je_kachel],
        "je_modell": [dict(r) for r in je_modell],
        "je_tag": [dict(r) for r in je_tag],
        "je_feature": [dict(r) for r in je_feature],
        "hinweis": "Kosten stammen aus der OpenRouter-usage; bei „geschätzt“ war keine usage im Response "
                   "(Schätzung über Zeichen/3,3 – siehe Plan Abschnitt 3.1).",
    }


@app.get("/api/admin/health")
async def admin_health(request: Request, refresh: int = 0):
    """Modell-Health-Check + Fallback-Kette je Kachel (Plan Phase 0)."""
    _check_admin(request)
    tiles = [dict(r) for r in db.query("SELECT * FROM tiles ORDER BY sort")]
    kette: list[str] = []
    for t in tiles:
        for m in [t["model"], *_fallbacks(t)]:
            if m and m not in kette:
                kette.append(m)
    gespeichert = _health_map()
    if refresh or not gespeichert:
        frisch = await check_health(kette, persist=True)
        gespeichert = {r["model"]: dict(r) for r in db.query("SELECT * FROM model_health")}
    ausgabe = []
    for t in tiles:
        fallbacks = _fallbacks(t)
        eintraege = []
        for i, m in enumerate([t["model"], *fallbacks]):
            h = gespeichert.get(m, {})
            caps = llm.capabilities(m)
            eintraege.append({
                "rolle": "primär" if i == 0 else f"fallback {i}",
                "model": m,
                "ok": bool(h.get("ok")),
                "endpunkte": h.get("endpoints", 0),
                "uptime": round(float(h.get("uptime") or 0) * 100, 1),
                "geprueft": h.get("checked_at", ""),
                "hinweis": h.get("note", ""),
                "kontext": caps.get("context_length", h.get("context_length", 0)),
                "structured": bool(caps.get("structured_outputs") or h.get("structured")),
                "vision": bool(caps.get("vision") or h.get("vision")),
                "gratis": bool(caps.get("free", m.endswith(":free"))),
            })
        ausgabe.append({"tile_id": t["id"], "name": f"{t['emoji']} {t['name']}", "kette": eintraege,
                        "kette_ok": all(e["ok"] or not e["endpunkte"] for e in eintraege),
                        "empfehlung": EMPFEHLUNG_MODELLE.get(t["id"], ""),
                        "folgt_empfehlung": EMPFEHLUNG_MODELLE.get(t["id"], t["model"]) == t["model"]})
    return {
        "kacheln": ausgabe,
        "modelle_geprueft": len(kette),
        "hinweis": "„Endpunkte 0“ heißt: das Modell hat aktuell keinen aktiven Provider – genau der "
                   "Qwen-Fall aus dem Plan. Die Fallback-Kette fängt das ab; im Admin änderbar.",
    }


@app.get("/api/admin/audit")
def admin_audit(request: Request, limit: int = 100, event: str | None = None):
    _check_admin(request)
    if event:
        rows = db.query("SELECT * FROM audit_log WHERE event=? ORDER BY id DESC LIMIT ?", (event, min(limit, 500)))
    else:
        rows = db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 500),))
    return [dict(r) for r in rows]


class EvalIn(BaseModel):
    tile_id: Optional[str] = None
    limit: Optional[int] = None


@app.post("/api/admin/eval/run")
async def admin_eval_run(request: Request, body: EvalIn | None = None):
    """Eval-Harness (Phase 2): Testfälle automatisch bewerten – Regressionsschutz."""
    _check_admin(request)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Kein OPENROUTER_API_KEY – Eval-Lauf nicht möglich.")
    tile_ids = [body.tile_id] if (body and body.tile_id) else [r["id"] for r in db.query("SELECT id FROM tiles ORDER BY sort")]
    limit = (body.limit if body else None)
    ergebnisse = []
    for tid in tile_ids:
        tile = _tile_or_404(tid)
        row = db.query1("SELECT system_prompt FROM prompts WHERE tile_id=?", (tid,))
        prompt = row["system_prompt"] if row else ""

        async def call(testfall, tile=tile, prompt=prompt):
            system = build_system(tile, prompt, test_file=testfall["file_content"] or "")
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": testfall["message"]}]
            res = await chat_once(tile["model"], messages, api_key, tile["temperature"],
                                  fallbacks=_fallbacks(tile), feature="eval", tile_id=tid)
            return res.content, res.usage.cost_usd, res.duration_ms

        ergebnisse.append(await eval_mod.run_tile(tid, call, model=tile["model"], limit=limit))
    audit("eval_lauf", None, None, f"{len(ergebnisse)} Kacheln")
    return {"ergebnisse": ergebnisse,
            "quote_pct": round(sum(e["punkte"] for e in ergebnisse) /
                               max(1, sum(e["max_punkte"] for e in ergebnisse)) * 100, 1),
            "kosten_usd": round(sum(e["kosten_usd"] for e in ergebnisse), 5)}


@app.get("/api/admin/eval/results")
def admin_eval_results(request: Request, tile_id: str | None = None, limit: int = 50):
    _check_admin(request)
    if tile_id:
        rows = db.query("SELECT * FROM eval_runs WHERE tile_id=? ORDER BY id DESC LIMIT ?", (tile_id, min(limit, 200)))
    else:
        rows = db.query("SELECT * FROM eval_runs ORDER BY id DESC LIMIT ?", (min(limit, 200),))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["checks"] = json.loads(d.get("checks") or "[]")
        except json.JSONDecodeError:
            d["checks"] = []
        d.pop("content", None)
        out.append(d)
    return out


# ---------------------------------------------------------------- static


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}
