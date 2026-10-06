"""SusMob – FastAPI-Backend.

Kacheln → Upload + Chat (OpenRouter, Streaming, Fallback-Kette) + Standardwerte
+ Rechenkerne + Ergebnis-/Exportstrecke.
Admin → Prompts pflegen, testen, Kosten/Health/Audit/Eval einsehen.

Umsetzung des Plans:
* Phase 0: ``llm_calls``-Messung, Health-Check + Fallback-Kette, Audit-Log, klare Fehlerbilder.
* Phase 1: Structured-Output-Schema je Kachel, Artefakt-System (Excel/CSV/JSON/MD/SVG/Druck-HTML).
* Phase 2: Rechenkerne im Code, Eval-Harness, Token-/Kostenmessung.
* Phase 3: neue Kacheln (Seed).
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
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from server import db, eval as eval_mod, export, health, rechner, schemas, telemetry
from server.envfile import load as load_env
from server.examples import EXAMPLES, replace_messages, seed_examples
from server.files import extract_text, image_data_url, is_image, SUPPORTED
from server.llm import LLMError, chain_for, chat_chain, stream_chat_chain
from server.seed import FREE_MODELS, seed_all

ROOT = Path(__file__).resolve().parent.parent
load_env(ROOT / ".env")  # OPENROUTER_API_KEY / ADMIN_PASSWORD aus .env

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
ARTIFACT_DIR = DATA_DIR / "artifacts"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_TOTAL_FILE_CHARS = 48_000
MAX_IMAGES = 6  # Bilder je Request (Vision)
HISTORY_LIMIT = 30  # Nachrichten im LLM-Kontext
SUMMARY_AFTER = 26  # ab so vielen Nachrichten: Rolling Summary der alten Turns

db.init(DATA_DIR / "susmob.db")
seed_all()
seed_examples(UPLOAD_DIR)

app = FastAPI(title="SusMob API")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# "demo" (Default) erlaubt Gratis-Modelle für Demodaten; "produktion" sperrt sie,
# solange SUSMOB_ALLOW_FREE_FOR_DATA nicht ausdrücklich auf 1 steht (Datenschutz, Plan Phase 4).
SUSMOB_MODE = os.environ.get("SUSMOB_MODE", "demo").strip().lower()
ALLOW_FREE_FOR_DATA = os.environ.get("SUSMOB_ALLOW_FREE_FOR_DATA", "1" if SUSMOB_MODE != "produktion" else "0") == "1"
_admin_tokens: set[str] = set()

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


def _actor(request: Request) -> str:
    return (request.headers.get("X-SusMob-User") or "anonym")[:60]


def _ip(request: Request) -> str:
    return (request.client.host if request.client else "")[:60]


def _audit(request: Request, action: str, object_type: str = "", object_id: str = "", detail: str = "") -> None:
    telemetry.audit(action, object_type=object_type, object_id=object_id, detail=detail,
                    actor=_actor(request), ip=_ip(request))


def _llm_error_text(err: Exception) -> str:
    """Verständliche Fehlermeldung – unterscheidet Netz-/Verbindungsproblem von Modellfehler."""
    text = str(err)
    net = any(k in text for k in ("SSL", "EOF", "Connect", "Timeout", "timed out", "getaddrinfo",
                                  "Name or service", "Alle Modelle der Kette"))
    if net:
        return (
            "**OpenRouter ist von diesem Server aus nicht erreichbar.**\n\n"
            f"Technische Ursache: {text}\n\n"
            "Die Fallback-Kette hat alle Modelle der Kachel versucht. Wenn du diese Vorschau in einer "
            "abgeschotteten Sandbox ansiehst: dort ist der ausgehende Zugriff auf `openrouter.ai` gesperrt – "
            "auf einem eigenen Server oder lokal mit Internetzugang antwortet das Modell normal. "
            "Prüfen lässt sich das im Admin unter „📈 Kosten, Health & Eval“ (🩺 Jetzt prüfen) oder über `/api/models/status`."
        )
    return f"OpenRouter-Fehler: {text}"


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


def _file_rows(cid: str) -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM files WHERE conversation_id=? ORDER BY created_at", (cid,))]


def _file_blocks(cid: str) -> str:
    blocks, total = [], 0
    for r in _file_rows(cid):
        if r.get("kind") == "image":
            blocks.append(
                f"### {r['filename']} – Bilddatei ({r['size']} Byte). Das Bild wird dem Modell direkt "
                "übergeben, sofern es Bild-Input unterstützt; andernfalls beschreibe die Lücke."
            )
            continue
        if r["extracted_chars"]:
            total += len(r["extracted_text"])
            blocks.append(f"### {r['filename']} ({r['extracted_chars']} Zeichen)\n```\n{r['extracted_text']}\n```")
        else:
            blocks.append(
                f"### {r['filename']} – Inhalt konnte nicht extrahiert werden. "
                "Bitte als .txt/.csv/.xlsx/.docx/.pdf oder als Bild hochladen."
            )
        if total > MAX_TOTAL_FILE_CHARS:
            blocks.append("… (weitere Dateien wegen Kontextgrenze nicht mitgerechnet)")
            break
    return "\n\n".join(blocks)


def _image_parts(cid: str) -> list[dict]:
    """Bilder der Unterhaltung als multimodale Content-Teile (OpenRouter/OpenAI-Format)."""
    parts = []
    for r in _file_rows(cid):
        if r.get("kind") != "image":
            continue
        p = Path(r["stored_path"])
        if p.exists():
            parts.append({
                "type": "image_url",
                "image_url": {"url": image_data_url(p, r.get("mime") or "")},
            })
        if len(parts) >= MAX_IMAGES:
            break
    return parts


def _rechner_werte(tid: str) -> dict:
    row = db.query1("SELECT value FROM settings WHERE tile_id=? AND key='rechner_werte'", (tid,))
    if not row or not row["value"]:
        return {}
    try:
        return json.loads(row["value"])
    except Exception:  # noqa: BLE001
        return {}


def _summary_block(cid: str) -> str:
    """Rolling Summary: alte Turns zusammenfassen statt mitsenden (Plan 3.5)."""
    rows = db.query("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    if len(rows) < SUMMARY_AFTER:
        return ""
    aeltere = [dict(r) for r in rows[: len(rows) - 10]]
    text = "\n".join(f"{r['role']}: {r['content'][:400]}" for r in aeltere)[-6000:]
    return (
        "## Früherer Gesprächsverlauf (verdichtet)\n"
        "Ältere Turns wurden zusammengefasst, um Kontext und Kosten zu sparen:\n"
        f"```\n{text}\n```"
    )


def build_system(tile: dict, prompt: str, cid: str | None = None, test_file: str = "") -> str:
    parts = [prompt.strip()]
    cfg = _config_lines(tile["id"])
    if cfg:
        parts.append("## Konfiguration der Kommune (Nutzer-Werte – haben Vorrang vor deinen Fallback-Werten)\n" + "\n".join(cfg))
    werte = _rechner_werte(tile["id"])
    if werte and rechner.has_rechner(tile["id"]):
        block = rechner.kontext_block(tile["id"], werte)
        if block:
            parts.append(block)
    file_block = _file_blocks(cid) if cid else ""
    if test_file:
        file_block = (file_block + "\n\n" if file_block else "") + f"### Test-Dateikontext\n```\n{test_file[:12000]}\n```"
    if file_block:
        parts.append("## Hochgeladene Dateien der Kommune\nNutze sie als Datenbasis; wo Daten fehlen, benenne es als Annahme.\n" + file_block)
    if cid:
        summ = _summary_block(cid)
        if summ:
            parts.append(summ)
    parts.append(
        "## Gesprächsregeln\n"
        "- Antworte auf Deutsch, präzise und ohne Füllfloskeln.\n"
        "- Stell im ersten Schritt gezielt Rückfragen, bevor du Endergebnisse lieferst – max. 4 Fragen pro Nachricht.\n"
        "- Liefert die Kommune Daten nach, rechne/entwirf direkt; wiederhole keine geklärten Punkte.\n"
        "- Markiere alle Annahmen explizit. Erfinde niemals Messdaten, Fristen oder Fördersätze.\n"
        "- **Rechne keine Zahlen im Kopf.** Wenn im Abschnitt „Vorberechnete Werte“ Zahlen stehen, übernimm sie "
        "unverändert; fehlt eine Zahl, benenne die Lücke statt zu schätzen.\n"
        "- Struktur: Tabellen für Zahlen, Listen für Annahmen und nächste Schritte."
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


class RechnerIn(BaseModel):
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
    fallback_models: Optional[str] = None
    temperature: Optional[float] = None
    system_prompt: Optional[str] = None


class LoginIn(BaseModel):
    password: str


class ErgebnisIn(BaseModel):
    message: str = "Fasse den Gesprächsstand zum Ergebnisdokument zusammen."


class EvalIn(BaseModel):
    tile_id: Optional[str] = None
    limit: int = 3


@app.get("/api/tiles")
def list_tiles():
    rows = db.query("SELECT id, emoji, name, short, model, fallback_models, rechner FROM tiles ORDER BY sort")
    from server.seed import SUGGESTIONS

    return [
        {
            **dict(r),
            "suggestions": SUGGESTIONS.get(r["id"], []),
            "hat_rechner": bool(r["rechner"]),
        }
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
    """Diagnose: Ist OpenRouter erreichbar, ist ein Key gesetzt, was sagt der Health-Check?"""
    return {
        "api_key": bool(os.environ.get("OPENROUTER_API_KEY", "")),
        "live_liste": bool(_MODEL_CACHE["items"]),
        "anzahl": len(_MODEL_CACHE["items"]),
        "geprueft_am": datetime.fromtimestamp(_MODEL_CACHE["ts"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if _MODEL_CACHE["ts"] else "",
        "mode": SUSMOB_MODE,
        "free_modelle_erlaubt": ALLOW_FREE_FOR_DATA,
        "health": health.summary(),
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
def set_std(request: Request, tid: str, body: SettingsIn):
    _tile_or_404(tid)
    for k, v in body.values.items():
        db.exec(
            "INSERT INTO settings (tile_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT(tile_id, key) DO UPDATE SET value=excluded.value",
            (tid, k, str(v)),
        )
    _audit(request, "standardwerte.geaendert", "tile", tid, ", ".join(sorted(body.values))[:400])
    return {"ok": True}


# ---------------------------------------------------------------- Rechner


@app.get("/api/tiles/{tid}/rechner")
def rechner_info(tid: str):
    """Rechner einer Kachel: Felder (mit Defaults aus den Standardwerten) + zuletzt gespeicherte Werte."""
    tile = _tile_or_404(tid)
    info = rechner.describe(tid)
    if not info:
        return {"verfuegbar": False}
    std = {r["key"]: r["default_value"]
           for r in db.query("SELECT key, default_value FROM standardwerte WHERE tile_id=?", (tid,))}
    vals = {r["key"]: r["value"] for r in db.query("SELECT key, value FROM settings WHERE tile_id=?", (tid,))}
    gespeichert = _rechner_werte(tid)
    for f in info["felder"]:
        f["wert"] = gespeichert.get(f["key"], vals.get(f["key"]) or f["default"] or std.get(f["key"], ""))
    info["verfuegbar"] = True
    info["rechner_id"] = tile["rechner"]
    return info


@app.post("/api/tiles/{tid}/rechner")
def rechner_run(request: Request, tid: str, body: RechnerIn):
    """Rechnet deterministisch und speichert die Werte – sie fließen in jeden Chat ein."""
    _tile_or_404(tid)
    if not rechner.has_rechner(tid):
        raise HTTPException(400, "Für diese Kachel gibt es keinen Rechenkern.")
    try:
        ergebnis = rechner.compute(tid, body.values)
    except Exception as e:  # noqa: BLE001 – Eingabefehler klar melden
        raise HTTPException(400, f"Rechnung nicht möglich: {e}") from e
    db.exec(
        "INSERT INTO settings (tile_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(tile_id, key) DO UPDATE SET value=excluded.value",
        (tid, "rechner_werte", json.dumps(body.values, ensure_ascii=False)),
    )
    _audit(request, "rechner.gerechnet", "tile", tid, json.dumps(ergebnis.get("eingaben", {}), ensure_ascii=False)[:400])
    return ergebnis


@app.get("/api/rechner")
def rechner_liste():
    return [{"tile_id": tid, **{k: v for k, v in (rechner.describe(tid) or {}).items() if k != "tile_id"}}
            for tid in rechner.RECHNER]


# ---------------------------------------------------------------- Konversationen


@app.post("/api/conversations")
def new_conversation(request: Request, body: ConvIn):
    tile = _tile_or_404(body.tile_id)
    cid = uuid.uuid4().hex
    ts = _now()
    db.exec(
        "INSERT INTO conversations (id, tile_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
        (cid, tile["id"], body.title or "Neue Unterhaltung", ts, ts),
    )
    _audit(request, "unterhaltung.erstellt", "conversation", cid, f"Kachel {tile['id']}")
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
        dict(r) for r in db.query("SELECT id, role, content, created_at FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
    ]
    conv["files"] = [
        {"id": r["id"], "filename": r["filename"], "size": r["size"], "extracted_chars": r["extracted_chars"],
         "kind": r["kind"], "mime": r["mime"]}
        for r in db.query(
            "SELECT id, filename, size, extracted_chars, kind, mime FROM files WHERE conversation_id=? ORDER BY created_at",
            (cid,))
    ]
    conv["artifacts"] = [
        {"id": r["id"], "kind": r["kind"], "filename": r["filename"], "size": r["size"], "created_at": r["created_at"]}
        for r in db.query(
            "SELECT id, kind, filename, size, created_at FROM artifacts WHERE conversation_id=? ORDER BY created_at DESC",
            (cid,))
    ]
    row = db.query1("SELECT value FROM settings WHERE tile_id=? AND key=?", (conv["tile_id"], f"ergebnis:{cid}"))
    if row and row["value"]:
        conv["ergebnis_vorhanden"] = True
    return conv


@app.post("/api/conversations/{cid}/duplicate")
def duplicate_conversation(request: Request, cid: str):
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
            "extracted_chars, extracted_text, created_at, kind, mime) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (fid, new_id, src["tile_id"], f["filename"], f["size"], stored_path,
             f["extracted_chars"], f["extracted_text"], ts, f["kind"], f["mime"]),
        )
    _audit(request, "unterhaltung.dupliziert", "conversation", new_id, f"von {cid}")
    return {"id": new_id}


@app.delete("/api/conversations/{cid}")
def delete_conversation(request: Request, cid: str):
    conv = _conv_or_404(cid)
    if conv.get("is_example"):
        raise HTTPException(403, "Beispiel-Unterhaltungen sind schreibgeschützt")
    for r in db.query("SELECT stored_path FROM files WHERE conversation_id=?", (cid,)):
        p = Path(r["stored_path"])
        if p.exists():
            p.unlink()
    for r in db.query("SELECT stored_path FROM artifacts WHERE conversation_id=?", (cid,)):
        p = Path(r["stored_path"])
        if p.exists():
            p.unlink()
    db.exec("DELETE FROM artifacts WHERE conversation_id=?", (cid,))
    db.exec("DELETE FROM files WHERE conversation_id=?", (cid,))
    db.exec("DELETE FROM messages WHERE conversation_id=?", (cid,))
    db.exec("DELETE FROM conversations WHERE id=?", (cid,))
    d = UPLOAD_DIR / cid
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    _audit(request, "unterhaltung.geloescht", "conversation", cid)
    return {"ok": True}


@app.post("/api/conversations/{cid}/files")
async def upload_file(request: Request, cid: str, file: UploadFile = File(...)):
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
    mime = file.content_type or ""
    kind = "image" if is_image(stored, mime) else "text"
    text = "" if kind == "image" else extract_text(stored)
    db.exec(
        "INSERT INTO files (id, conversation_id, tile_id, filename, size, stored_path, extracted_chars, "
        "extracted_text, created_at, kind, mime) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (fid, cid, conv["tile_id"], safe, len(data), str(stored), len(text), text, _now(), kind, mime),
    )
    _audit(request, "datei.hochgeladen", "file", fid, f"{safe} ({len(data)} B, {kind})")
    return {"id": fid, "filename": safe, "size": len(data), "extracted_chars": len(text), "kind": kind}


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

    ts = _now()
    db.exec(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
        (cid, "user", text, ts),
    )
    db.exec("UPDATE conversations SET updated_at=? WHERE id=?", (ts, cid))
    if conv["title"] == "Neue Unterhaltung":
        title = text[:50] + ("…" if len(text) > 50 else "")
        db.exec("UPDATE conversations SET title=? WHERE id=?", (title, cid))

    history = db.query(
        "SELECT role, content FROM messages WHERE conversation_id=? AND id < (SELECT MAX(id) FROM messages WHERE conversation_id=?) ORDER BY id DESC LIMIT ?",
        (cid, cid, HISTORY_LIMIT),
    )
    history = [dict(r) for r in reversed(history)]

    system = build_system(tile, prompt, cid)
    chain = health.ordered_chain(tile)
    images = _image_parts(cid)
    vision = images and any(health.supports_vision(m) for m in chain)
    if images and not vision:
        system += (
            "\n\n## Hinweis zu Bildanhängen\nEs liegen Bilddateien vor, aber das konfigurierte Modell unterstützt keinen "
            "Bild-Input. Benenne diese Lücke und bitte um eine Beschreibung oder Textextraktion."
        )
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    if vision:
        messages.append({"role": "user", "content": ([{"type": "text", "text": text}] + images)})
    else:
        messages.append({"role": "user", "content": text})

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    chars_in = len(system) + sum(len(m["content"]) if isinstance(m["content"], str) else 0 for m in history) + len(text)

    async def gen():
        full: list[str] = []
        if not api_key:
            note = (
                "⚠️ **Kein OpenRouter-API-Key hinterlegt.**\n\n"
                "Setze die Umgebungsvariable `OPENROUTER_API_KEY` und starte den Server neu, "
                "damit der Chat mit echten Modellen funktioniert.\n\n"
                "Die Konfiguration, die Standardwerte, der Rechenkern und der Upload laufen bereits korrekt – "
                "diese Nachricht wäre an die Kette `__CHAIN__` gegangen.\n\n"
                "*(Demo-Modus: die Antwort kommt nicht von einem LLM.)*"
            ).replace("__CHAIN__", " → ".join(chain))
            yield _sse("token", {"t": note})
            db.exec(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                (cid, "assistant", note, _now()),
            )
            telemetry.log_call(kind="chat", tile_id=tile["id"], conversation_id=cid, chain=chain,
                               error="kein API-Key", status_code=0)
            yield _sse("done", {})
            return
        if not ALLOW_FREE_FOR_DATA and any(health.is_free(m) for m in chain):
            note = (
                "⛔ **Dieser Server läuft im Produktionsmodus und Gratis-Modelle sind für echte Daten gesperrt.**\n\n"
                "Gratis-Anbieter dürfen Prompts zum Training nutzen (Plan, Abschnitt 2.1). Für vertrauliche Kommunaldaten "
                "ist ein bezahltes Modell mit Auftragsverarbeitungsvertrag vorgesehen.\n\n"
                "Zum Umstellen: bezahltes Modell im Admin-Bereich wählen – oder bewusst "
                "`SUSMOB_ALLOW_FREE_FOR_DATA=1` setzen (nur für Demodaten)."
            )
            yield _sse("token", {"t": note})
            db.exec(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                (cid, "assistant", note, _now()),
            )
            yield _sse("done", {})
            return
        try:
            async for ev in stream_chat_chain(chain, messages, api_key, tile["temperature"]):
                if ev["type"] == "token":
                    full.append(ev["t"])
                    yield _sse("token", {"t": ev["t"]})
                elif ev["type"] == "retry":
                    telemetry.log_call(kind="chat", tile_id=tile["id"], conversation_id=cid, chain=chain,
                                       error=ev.get("reason", ""), attempt=ev.get("attempt", 1))
                    yield _sse("retry", {"model": ev.get("model", ""), "reason": str(ev.get("reason", ""))[:300],
                                         "wait": ev.get("wait", 0), "attempt": ev.get("attempt", 1)})
                elif ev["type"] == "done":
                    result = ev["result"]
                    telemetry.log_call(kind="chat", tile_id=tile["id"], conversation_id=cid, chain=chain,
                                       result=result, chars_in=chars_in, chars_out=len(result.content),
                                       attempt=result.attempt, used_fallback=result.used_fallback)
                    yield _sse("meta", {
                        "model": result.model, "fallback": result.used_fallback,
                        "tokens": result.usage.total_tokens, "cost_usd": round(result.usage.cost_usd, 8),
                        "duration_ms": result.duration_ms,
                    })
        except LLMError as e:  # noqa: BLE001 – Kette erschöpft
            telemetry.log_call(kind="chat", tile_id=tile["id"], conversation_id=cid, chain=chain,
                               error=str(e), status_code=e.status_code)
            if full:
                db.exec(
                    "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                    (cid, "assistant", "".join(full), _now()),
                )
            yield _sse("error", {"error": _llm_error_text(e)})
            return
        except Exception as e:  # noqa: BLE001
            telemetry.log_call(kind="chat", tile_id=tile["id"], conversation_id=cid, chain=chain, error=str(e))
            if full:
                db.exec(
                    "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
                    (cid, "assistant", "".join(full), _now()),
                )
            yield _sse("error", {"error": _llm_error_text(e)})
            return
        db.exec(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
            (cid, "assistant", "".join(full), _now()),
        )
        _audit(request, "chat.antwort", "conversation", cid, f"Kachel {tile['id']}, {len(''.join(full))} Zeichen")
        yield _sse("done", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- Ergebnis & Export


def _chat_kontext(cid: str, limit: int = 24, max_chars: int = 24_000) -> str:
    rows = db.query(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?", (cid, limit)
    )
    text = "\n\n".join(f"### {'Kommune' if r['role'] == 'user' else 'Assistent'}\n{r['content']}" for r in reversed(rows))
    return text[-max_chars:]


def _ergebnis_speichern(cid: str, tile_id: str, data: dict) -> None:
    db.exec(
        "INSERT INTO settings (tile_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(tile_id, key) DO UPDATE SET value=excluded.value",
        (tile_id, f"ergebnis:{cid}", json.dumps(data, ensure_ascii=False)),
    )


def _ergebnis_laden(cid: str, tile_id: str) -> dict | None:
    row = db.query1("SELECT value FROM settings WHERE tile_id=? AND key=?", (tile_id, f"ergebnis:{cid}"))
    if not row or not row["value"]:
        return None
    try:
        return json.loads(row["value"])
    except Exception:  # noqa: BLE001
        return None


@app.get("/api/conversations/{cid}/ergebnis")
def get_ergebnis(cid: str):
    conv = _conv_or_404(cid)
    data = _ergebnis_laden(cid, conv["tile_id"])
    if not data:
        raise HTTPException(404, "Noch kein Ergebnisdokument vorhanden – bitte zuerst erzeugen.")
    return {"tile_id": conv["tile_id"], "data": data, "markdown": schemas.to_markdown(conv["tile_id"], data)}


@app.post("/api/conversations/{cid}/ergebnis")
async def erzeuge_ergebnis(request: Request, cid: str, body: ErgebnisIn):
    """Erzeugt das strukturierte Ergebnisdokument (JSON-Schema + Pydantic-Validierung + Reparaturpfad)."""
    conv = _conv_or_404(cid)
    if conv.get("is_example"):
        raise HTTPException(403, "Beispiel-Unterhaltungen sind schreibgeschützt.")
    tile = _tile_or_404(conv["tile_id"])
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Kein OPENROUTER_API_KEY hinterlegt – Ergebnisdokument nicht möglich.")

    prompt_row = db.query1("SELECT system_prompt FROM prompts WHERE tile_id=?", (tile["id"],))
    prompt = prompt_row["system_prompt"] if prompt_row else ""
    kontext = _chat_kontext(cid)
    werte = _rechner_werte(tile["id"])
    extra = rechner.compute(tile["id"], werte) if (werte and rechner.has_rechner(tile["id"])) else None
    msgs = schemas.extraktion_messages(tile["id"], prompt, build_system(tile, prompt, cid), kontext + "\n\n" + body.message)
    if extra:
        msgs[1]["content"] += "\n\n## Verbindliche Rechenkern-Werte\n" + json.dumps(extra, ensure_ascii=False)[:8000]

    chain = health.ordered_chain(tile)
    payload = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": f"ergebnis_{tile['id'][:20]}", "strict": True,
                            "schema": schemas.schema_for(tile["id"])},
        }
    }
    try:
        result = await chat_chain(chain, msgs, api_key, tile["temperature"], extra_payload=payload)
    except LLMError as e:
        # Manche Anbieter kennen `response_format: json_schema` nicht → zweiter Versuch ohne,
        # das Schema steht dann im Prompt (Abschnitt „Zielschema“).
        if e.status_code in (400, 404, 422):
            msgs[1]["content"] += (
                "\n\n## Zielschema (JSON Schema) – Ausgabe muss exakt dazu passen\n"
                + json.dumps(schemas.schema_for(tile["id"]), ensure_ascii=False)[:6000]
            )
            try:
                result = await chat_chain(chain, msgs, api_key, tile["temperature"])
                telemetry.log_call(kind="ergebnis_ohne_schema", tile_id=tile["id"],
                                   conversation_id=cid, chain=chain, result=result)
            except LLMError as e2:
                telemetry.log_call(kind="ergebnis", tile_id=tile["id"], conversation_id=cid,
                                   chain=chain, error=str(e2))
                raise HTTPException(502, _llm_error_text(e2)) from e2
        else:
            telemetry.log_call(kind="ergebnis", tile_id=tile["id"], conversation_id=cid, chain=chain, error=str(e))
            raise HTTPException(502, _llm_error_text(e)) from e
    telemetry.log_call(kind="ergebnis", tile_id=tile["id"], conversation_id=cid, chain=chain, result=result,
                       chars_out=len(result.content), used_fallback=result.used_fallback)

    data = schemas.extract_json(result.content)
    obj, errors = schemas.validate(tile["id"], data)
    repair_attempts = 0
    if errors:
        repair_attempts = 1
        try:
            fix = await chat_chain(chain, schemas.repair_messages(tile["id"], msgs, result.content, errors),
                                   api_key, 0.0, extra_payload=payload)
            telemetry.log_call(kind="ergebnis_reparatur", tile_id=tile["id"], conversation_id=cid, chain=chain,
                               result=fix, chars_out=len(fix.content))
            obj2, errors2 = schemas.validate(tile["id"], schemas.extract_json(fix.content))
            if not errors2:
                obj, errors = obj2, []
        except LLMError as e:
            telemetry.log_call(kind="ergebnis_reparatur", tile_id=tile["id"], conversation_id=cid, chain=chain,
                               error=str(e))
        if errors:
            raise HTTPException(
                502,
                "Das Modell hat kein schema-konformes Ergebnisdokument geliefert. Bitte erneut versuchen oder "
                "im Admin-Bereich ein Modell mit `structured_outputs` wählen (z. B. Nemotron 3 Super oder Apodex). "
                f"Fehler: {'; '.join(errors[:5])}",
            )
    data = obj.model_dump()
    _ergebnis_speichern(cid, tile["id"], data)
    artefakte = export.build_and_store(
        conversation_id=cid, tile_id=tile["id"], data=data, artifacts_dir=ARTIFACT_DIR,
        titel=data.get("titel") or conv["title"], kommune=_kommune_name(tile["id"]),
    )
    _audit(request, "ergebnis.erzeugt", "conversation", cid,
           f"Kachel {tile['id']}, {len(artefakte)} Artefakte, Modell {result.model}, Reparatur {repair_attempts}")
    return {
        "ok": True,
        "tile_id": tile["id"],
        "model": result.model,
        "repair_attempts": repair_attempts,
        "data": data,
        "markdown": schemas.to_markdown(tile["id"], data),
        "artifacts": artefakte,
    }


def _kommune_name(tid: str) -> str:
    row = db.query1(
        "SELECT value FROM settings WHERE tile_id=? AND key IN ('kommune_name','kommune','gebiet') "
        "AND value<>'' ORDER BY key LIMIT 1", (tid,))
    return row["value"] if row else ""


@app.post("/api/conversations/{cid}/export")
def export_ergebnis(request: Request, cid: str, format: str = "xlsx"):
    """Erzeugt ein Artefakt aus dem gespeicherten Ergebnisdokument (oder erzeugt es nicht neu)."""
    conv = _conv_or_404(cid)
    data = _ergebnis_laden(cid, conv["tile_id"])
    if not data:
        raise HTTPException(404, "Kein Ergebnisdokument vorhanden – bitte zuerst „Ergebnis erzeugen“.")
    titel = data.get("titel") or conv["title"]
    if format == "xlsx":
        content, name, kind = export.build_xlsx(conv["tile_id"], data, titel), f"{titel[:50]}.xlsx", "xlsx"
    elif format == "csv":
        content, name, kind = export.build_csv(conv["tile_id"], data), f"{titel[:50]}.csv", "csv"
    elif format == "json":
        content, name, kind = export.build_json(conv["tile_id"], data), f"{titel[:50]}.json", "json"
    elif format in ("md", "markdown"):
        content, name, kind = export.build_markdown(conv["tile_id"], data), f"{titel[:50]}.md", "md"
    elif format in ("html", "pdf", "druck"):
        content, name, kind = (export.build_print_html(conv["tile_id"], data, titel, _kommune_name(conv["tile_id"])),
                               f"{titel[:50]}_druck.html", "html")
    else:
        raise HTTPException(400, f"Unbekanntes Format: {format}")
    artefakt = export.store_artifact(
        conversation_id=cid, tile_id=conv["tile_id"], kind=kind,
        filename=name.replace("/", "-").replace(" ", "_"), content=content, payload=data,
        artifacts_dir=ARTIFACT_DIR,
    )
    _audit(request, "export.erzeugt", "conversation", cid, f"{kind}: {name}")
    return artefakt


@app.get("/api/conversations/{cid}/artifacts")
def list_artifacts(cid: str):
    _conv_or_404(cid)
    return [
        {"id": r["id"], "kind": r["kind"], "filename": r["filename"], "size": r["size"], "created_at": r["created_at"]}
        for r in db.query(
            "SELECT id, kind, filename, size, created_at FROM artifacts WHERE conversation_id=? ORDER BY created_at DESC",
            (cid,))
    ]


@app.get("/api/artifacts/{aid}/download")
def download_artifact(aid: str):
    try:
        path, filename = export.artifact_bytes(aid)
    except KeyError:
        raise HTTPException(404, "Artefakt nicht gefunden") from None
    media = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
        ".svg": "image/svg+xml",
        ".html": "text/html; charset=utf-8",
    }.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=filename)


@app.get("/api/artifacts/{aid}/anzeige", response_class=HTMLResponse)
def anzeige_artifact(aid: str):
    """Zeigt ein Artefakt direkt an (z. B. Druckansicht/Diagramm im Browser)."""
    try:
        path, _ = export.artifact_bytes(aid)
    except KeyError:
        raise HTTPException(404, "Artefakt nicht gefunden") from None
    if path.suffix == ".html":
        return HTMLResponse(path.read_text(encoding="utf-8"))
    if path.suffix == ".svg":
        return HTMLResponse(f'<html><body style="margin:0;background:#fff">{path.read_text(encoding="utf-8")}</body></html>')
    return FileResponse(path)


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
    return {"protected": bool(ADMIN_PASSWORD), "mode": SUSMOB_MODE}


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
        d["chain"] = health.ordered_chain(d)
        h = {m: health.model_info(m) for m in chain_for(d)}
        d["health"] = [{"model": m, "ok": bool(info.get("ok")), "checked_at": info.get("checked_at", ""),
                        "uptime": info.get("uptime"), "note": info.get("note", "")}
                       for m, info in h.items()]
        d["hat_rechner"] = bool(d.get("rechner"))
        out.append(d)
    return out


@app.put("/api/admin/tiles/{tid}")
def admin_update_tile(request: Request, tid: str, body: TileIn):
    _check_admin(request)
    _tile_or_404(tid)
    sets, params = [], []
    if body.model is not None:
        sets.append("model=?"); params.append(body.model)
    if body.fallback_models is not None:
        sets.append("fallback_models=?"); params.append(body.fallback_models)
    if body.temperature is not None:
        sets.append("temperature=?"); params.append(body.temperature)
    if sets:
        db.exec(f"UPDATE tiles SET {', '.join(sets)} WHERE id=?", (*params, tid))
        _audit(request, "tile.konfiguration", "tile", tid,
               ", ".join(f"{s.split('=')[0]}={v}" for s, v in zip(sets, params))[:400])
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
        _audit(request, "prompt.geaendert", "tile", tid, f"{len(body.system_prompt)} Zeichen")
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
    _audit(request, "prompt.wiederhergestellt", "tile", tid, f"Version {vid}")
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
    chain = health.ordered_chain(tile)
    started = time.time()
    try:
        result = await chat_chain(chain, messages, api_key, tile["temperature"])
    except LLMError as e:
        telemetry.log_call(kind="admin_test", tile_id=tid, chain=chain, error=str(e), status_code=e.status_code)
        raise HTTPException(502, _llm_error_text(e)) from e
    telemetry.log_call(kind="admin_test", tile_id=tid, chain=chain, result=result,
                       chars_in=len(system) + len(body.message), chars_out=len(result.content),
                       used_fallback=result.used_fallback)
    bewertung = eval_mod.bewerte(tid, result.content, body.message + "\n" + body.file_content)
    return {
        "ok": True, "content": result.content, "model": result.model, "fallback": result.used_fallback,
        "kette": result.chain, "tokens": result.usage.total_tokens,
        "kosten_usd": round(result.usage.cost_usd, 8), "dauer_ms": int((time.time() - started) * 1000),
        "bewertung": bewertung,
    }


@app.get("/api/admin/metrics")
def admin_metrics(request: Request, days: int = 30):
    """Kosten-/Token-Auswertung: macht die Schätzungen aus dem Plan zu Messwerten."""
    _check_admin(request)
    return telemetry.metrics(days)


@app.get("/api/admin/health")
def admin_health(request: Request):
    _check_admin(request)
    tiles = [dict(r) for r in db.query("SELECT * FROM tiles ORDER BY sort")]
    rows = []
    for t in tiles:
        chain = health.ordered_chain(t)
        rows.append({
            "tile_id": t["id"], "name": f"{t['emoji']} {t['name']}",
            "model": t["model"], "fallback_models": t["fallback_models"],
            "chain": [{"model": m, **{k: health.model_info(m).get(k) for k in
                                      ("ok", "checked_at", "uptime", "active_endpoints", "note",
                                       "supports_structured", "supports_vision", "pricing_prompt")}}
                      for m in chain],
        })
    return {"summary": health.summary(), "tiles": rows}


@app.post("/api/admin/health/check")
async def admin_health_check(request: Request, tile_id: str | None = None):
    _check_admin(request)
    tiles = [dict(r) for r in db.query("SELECT * FROM tiles ORDER BY sort")]
    if tile_id:
        tiles = [t for t in tiles if t["id"] == tile_id]
    models = await health.fetch_models()
    report = await health.check_tiles(tiles)
    report["models"] = models
    _audit(request, "health.geprueft", "system", tile_id or "alle",
           f"online={report.get('online')}, {len(report.get('failures', []))} Probleme")
    return report


@app.get("/api/admin/audit")
def admin_audit(request: Request, limit: int = 100, action: str = ""):
    _check_admin(request)
    return telemetry.audit_list(limit=limit, action=action)


@app.get("/api/admin/eval")
def admin_eval(request: Request, tile_id: str | None = None, limit: int = 50):
    _check_admin(request)
    return eval_mod.uebersicht(tile_id=tile_id, limit=limit)


@app.post("/api/admin/eval/run")
async def admin_eval_run(request: Request, body: EvalIn):
    """Eval-Harness: Testfälle einer Kachel (oder aller) gegen das aktuelle Modell laufen lassen."""
    _check_admin(request)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Kein OPENROUTER_API_KEY hinterlegt – Eval-Lauf nicht möglich.")
    tiles = [dict(r) for r in db.query("SELECT * FROM tiles ORDER BY sort")]
    if body.tile_id:
        tiles = [t for t in tiles if t["id"] == body.tile_id]
        if not tiles:
            raise HTTPException(404, "Kachel nicht gefunden")
    ergebnisse = []
    for tile in tiles:
        limit = max(1, min(10, body.limit))
        cases = [dict(r) for r in db.query(
            "SELECT * FROM test_cases WHERE tile_id=? ORDER BY id LIMIT ?", (tile["id"], limit))]
        if not cases:
            ergebnisse.append({"tile_id": tile["id"], "hinweis": "keine Testfälle"})
            continue
        prompt_row = db.query1("SELECT system_prompt FROM prompts WHERE tile_id=?", (tile["id"],))
        prompt = prompt_row["system_prompt"] if prompt_row else ""
        chain = health.ordered_chain(tile)
        for case in cases:
            system = build_system(tile, prompt, test_file=case["file_content"])
            system += "\n\n## Testmodus\nBehandle den Input als Testdaten der Beispiel-Kommune."
            msgs = [{"role": "system", "content": system}, {"role": "user", "content": case["message"]}]
            started = time.time()
            try:
                result = await chat_chain(chain, msgs, api_key, tile["temperature"])
            except LLMError as e:
                telemetry.log_call(kind="eval", tile_id=tile["id"], chain=chain, error=str(e))
                ergebnisse.append({"tile_id": tile["id"], "testfall": case["name"], "ok": False, "error": str(e)})
                continue
            telemetry.log_call(kind="eval", tile_id=tile["id"], chain=chain, result=result,
                               chars_in=len(system) + len(case["message"]), chars_out=len(result.content),
                               used_fallback=result.used_fallback)
            werte = _rechner_werte(tile["id"])
            extra = list(rechner.compute(tile["id"], werte).get("eingaben", {}).values()) if (werte and rechner.has_rechner(tile["id"])) else []
            bewertung = eval_mod.bewerte(tile["id"], result.content, case["message"] + "\n" + case["file_content"],
                                        extra_zahlen=[v for v in extra if isinstance(v, (int, float))])
            eval_mod.speichere(tile["id"], result.model, case["id"], case["name"], bewertung,
                               duration_ms=int((time.time() - started) * 1000), chars_out=len(result.content))
            ergebnisse.append({
                "tile_id": tile["id"], "testfall": case["name"], "ok": True,
                "score": bewertung["score"], "findings": bewertung["findings"],
                "unbelegte_zahlen": bewertung["unbelegte_zahlen"], "model": result.model,
            })
    _audit(request, "eval.gelaufen", "system", body.tile_id or "alle", f"{len(ergebnisse)} Läufe")
    return {"results": ergebnisse, "uebersicht": eval_mod.uebersicht(tile_id=body.tile_id)}


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
    """Erzeugt Beispielantworten mit dem echten, je Kachel konfigurierten Modell neu."""
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
        chain = health.ordered_chain(tile)
        try:
            for role, content in ex["messages"]:
                if role == "user":
                    neu.append((role, content))
                    messages.append({"role": "user", "content": content})
                else:
                    result = await chat_chain(chain, messages, api_key, tile["temperature"])
                    telemetry.log_call(kind="example", tile_id=tid, conversation_id=cid, chain=chain,
                                       result=result, chars_out=len(result.content))
                    neu.append(("assistant", result.content))
                    messages.append({"role": "assistant", "content": result.content})
            replace_messages(cid, neu)
            results.append({
                "tile_id": tid, "ok": True, "model": tile["model"],
                "chars": sum(len(c) for _, c in neu),
            })
        except LLMError as e:  # noqa: BLE001 – Fehler je Kachel zurückmelden
            results.append({"tile_id": tid, "ok": False, "model": tile["model"], "error": str(e)})
    _audit(request, "beispiele.neu_erzeugt", "system", tile_id or "alle", f"{len(results)} Kacheln")
    return {"results": results}


# ---------------------------------------------------------------- static


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/healthz")
def healthz():
    """Betriebs-Check für Monitoring/Reverse Proxy."""
    last = db.query1("SELECT ts, ok, model FROM llm_calls ORDER BY id DESC LIMIT 1")
    return {
        "ok": True,
        "mode": SUSMOB_MODE,
        "api_key": bool(os.environ.get("OPENROUTER_API_KEY", "")),
        "tiles": db.query1("SELECT COUNT(*) AS n FROM tiles")["n"],
        "letzter_llm_call": dict(last) if last else None,
        "health": {"last_check": health.summary().get("last_check", ""),
                   "models_broken": health.summary().get("models_broken", [])},
    }
