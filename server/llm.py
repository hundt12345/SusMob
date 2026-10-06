"""OpenRouter-Client mit Messbarkeit, Fallback-Kette und Structured Output.

Phase 0 des Plans:
  * **Usage-Logging** – jeder Call schreibt Tokens, Kosten, Laufzeit und Status
    in ``llm_calls``; fehlt die ``usage`` im Response, wird geschätzt (±25 %).
  * **Fallback-Kette** – Modelle werden in Prioritätsreihenfolge probiert;
    fehlender Endpunkt, 404/429/5xx und leere Antworten lösen den nächsten
    Versuch aus. Der Nutzer sieht keinen Fehler, nur einen Hinweis-Hinweis.
  * **429-Backoff** – ``Retry-After`` wird respektiert, danach exponentiell.
  * **Health-Check** – Endpunktliste je Modell live prüfen, Ergebnis cachen.
  * **Structured Output** – ``json_schema`` wenn das Modell es unterstützt,
    sonst ``json_object``, sonst JSON-Extraktion aus dem Text.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable

import httpx

BASE = "https://openrouter.ai/api/v1"
HEADERS = {
    "HTTP-Referer": "https://susmob.local",
    "X-Title": "SusMob",
}

# Zeichen/Token für deutsche Fachtexte (Plan Abschnitt 3.1) – nur als Rückfall,
# wenn OpenRouter keine usage liefert.
CHARS_PER_TOKEN = 3.3
MAX_ATTEMPTS_PER_MODEL = 2          # 1 Versuch + 1 Retry bei 429/5xx/Netzfehler
BACKOFF_BASE = 1.6                  # Sekunden; wird exponentiell erhöht
MAX_BACKOFF = 20.0

PRICING: dict[str, dict[str, float]] = {}   # model-id → {prompt, completion} $/Token
CAPS: dict[str, dict[str, Any]] = {}        # model-id → Fähigkeiten (aus /models)


def _headers(api_key: str) -> dict:
    return {**HEADERS, "Authorization": f"Bearer {api_key}"}


def estimate_tokens(text: str) -> int:
    """Token-Schätzung über Zeichenmenge (3,3 Z/Tok, Plan Abschnitt 3.1)."""
    return max(1, int(len(text or "") / CHARS_PER_TOKEN))


def estimate_messages_tokens(messages: Iterable[dict]) -> int:
    return sum(estimate_tokens(m.get("content", "")) for m in messages) + 4 * len(list(messages))


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False
    cost_usd: float = 0.0

    @property
    def as_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tokens_estimated": 1 if self.estimated else 0,
            "cost_usd": self.cost_usd,
        }


@dataclass
class CallResult:
    content: str
    model: str                 # tatsächlich genutztes Modell
    model_requested: str       # primär angefragtes Modell
    usage: Usage = field(default_factory=Usage)
    duration_ms: int = 0
    attempts: list[dict] = field(default_factory=list)   # {model, attempt, status, error}
    degraded: bool = False     # True, wenn ein Fallback-Modell geantwortet hat


def cost_from_pricing(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0
    return prompt_tokens * float(p.get("prompt", 0)) + completion_tokens * float(p.get("completion", 0))


def usage_from_payload(payload: dict, model: str, messages: list[dict], content: str) -> Usage:
    """Usage aus dem Response lesen; fehlt sie, konservativ schätzen."""
    raw = payload.get("usage") or {}
    if raw.get("prompt_tokens") or raw.get("completion_tokens"):
        pt = int(raw.get("prompt_tokens", 0))
        ct = int(raw.get("completion_tokens", 0))
        tt = int(raw.get("total_tokens", pt + ct))
        cost = raw.get("cost")
        if cost is None:
            cost = cost_from_pricing(model, pt, ct)
        return Usage(pt, ct, tt, False, float(cost or 0.0))
    pt = estimate_messages_tokens(messages)
    ct = estimate_tokens(content)
    return Usage(pt, ct, pt + ct, True, cost_from_pricing(model, pt, ct))


def _retry_after(resp: httpx.Response) -> float | None:
    ra = resp.headers.get("Retry-After") or resp.headers.get("X-RateLimit-Reset")
    if not ra:
        return None
    try:
        return max(0.0, float(ra))
    except ValueError:
        return None


def _is_retryable(status: int) -> bool:
    # 404 = Modell/Endpunkt weg (Qwen-Fall), 408/409/425/429/5xx = temporär
    return status in (404, 408, 409, 425, 429) or status >= 500


def _short(text: str, n: int = 300) -> str:
    return (text or "").replace("\n", " ")[:n]


def resolve_chain(model: str, fallbacks: str | list[str] | None) -> list[str]:
    """Modell + Fallback-Kette als eindeutige Liste."""
    chain: list[str] = []
    if model:
        chain.append(model)
    if isinstance(fallbacks, str):
        try:
            fallbacks = json.loads(fallbacks) if fallbacks.strip() else []
        except json.JSONDecodeError:
            fallbacks = [f.strip() for f in fallbacks.split(",") if f.strip()]
    for m in fallbacks or []:
        if m and m not in chain:
            chain.append(m)
    return chain


async def models_catalog(refresh: bool = False, ttl: int = 900) -> list[dict]:
    """Liste aller OpenRouter-Modelle (öffentlich, ohne Key), mit Caching."""
    global _CATALOG
    now = time.time()
    if not refresh and _CATALOG["items"] and now - _CATALOG["ts"] < ttl:
        return _CATALOG["items"]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            r = await client.get(f"{BASE}/models")
            r.raise_for_status()
            items = r.json().get("data", []) or []
    except Exception:  # noqa: BLE001 – offline/Netzsperre
        return _CATALOG["items"]
    if items:
        _CATALOG = {"ts": now, "items": items}
        _index_catalog(items)
    return _CATALOG["items"]


_CATALOG: dict[str, Any] = {"ts": 0.0, "items": []}


def _index_catalog(items: list[dict]) -> None:
    for m in items:
        mid = m.get("id")
        if not mid:
            continue
        PRICING[mid] = m.get("pricing") or {}
        arch = m.get("architecture") or {}
        params = m.get("supported_parameters") or []
        inp = arch.get("input_modalities") or []
        CAPS[mid] = {
            "context_length": int(m.get("context_length") or 0),
            "max_completion_tokens": int((m.get("top_provider") or {}).get("max_completion_tokens") or 0),
            "structured_outputs": bool(m.get("structured_outputs")) or "structured_outputs" in params,
            "response_format": bool(m.get("response_format")) or "response_format" in params or "structured_outputs" in params,
            "tools": "tools" in params or bool(m.get("tools")),
            "vision": "image" in inp,
            "pricing": PRICING.get(mid, {}),
            "free": str((m.get("pricing") or {}).get("prompt", "1")) in ("0", "0.0", "0.00"),
        }


def capabilities(model: str) -> dict:
    return CAPS.get(model, {})


# ------------------------------------------------------------------ Health-Check


async def model_endpoints(model: str) -> dict:
    """Endpunktliste + Uptime eines Modells (der Qwen-Check aus dem Plan)."""
    admin_key = _admin_key()
    headers = {"Authorization": f"Bearer {admin_key}"} if admin_key else {}
    url = f"{BASE}/models/{model}/endpoints"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return {"reachable": True, "model_known": False, "endpoints": 0, "uptime": 0.0,
                        "note": f"HTTP {r.status_code}"}
            data = r.json().get("data", {}) or {}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "model_known": False, "endpoints": 0, "uptime": 0.0,
                "note": f"nicht erreichbar: {_short(str(e), 120)}"}
    eps = data.get("endpoints") or []
    live = [e for e in eps if (e.get("status") in (None, 0, "ok")) or e.get("uptime_last_30m") is not None]
    uptimes = [float(e.get("uptime_last_30m") or 0) for e in eps]
    return {
        "reachable": True,
        "model_known": True,
        "endpoints": len(live) or len(eps),
        "uptime": (sum(uptimes) / len(uptimes) / 100.0) if uptimes else 0.0,
        "note": "" if eps else "keine aktiven Endpunkte",
    }


def _admin_key() -> str:
    import os

    return os.environ.get("OPENROUTER_API_KEY", "")


def record_health(model: str, info: dict) -> None:
    from server import db

    caps = capabilities(model)
    db.exec(
        "INSERT INTO model_health (model, checked_at, ok, endpoints, uptime, context_length, structured, vision, note) "
        "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(model) DO UPDATE SET checked_at=excluded.checked_at, ok=excluded.ok, "
        "endpoints=excluded.endpoints, uptime=excluded.uptime, context_length=excluded.context_length, "
        "structured=excluded.structured, vision=excluded.vision, note=excluded.note",
        (
            model,
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            1 if (info.get("endpoints", 0) > 0 or info.get("model_known")) else 0,
            int(info.get("endpoints", 0)),
            float(info.get("uptime", 0.0)),
            int(caps.get("context_length", 0)),
            1 if caps.get("structured_outputs") else 0,
            1 if caps.get("vision") else 0,
            info.get("note", "") or "",
        ),
    )


async def check_health(models: list[str], persist: bool = True) -> list[dict]:
    """Prüft mehrere Modelle parallel und schreibt das Ergebnis nach ``model_health``."""
    await models_catalog()
    results = await asyncio.gather(*(model_endpoints(m) for m in models), return_exceptions=True)
    out = []
    for m, info in zip(models, results):
        if isinstance(info, Exception):
            info = {"reachable": False, "model_known": False, "endpoints": 0, "uptime": 0.0, "note": str(info)}
        row = {"model": m, **info, "caps": capabilities(m)}
        if persist:
            try:
                record_health(m, info)
            except Exception:  # noqa: BLE001 – Health darf nie werfen
                pass
        out.append(row)
    return out


# ------------------------------------------------------------------ LLM-Calls


def _log_call(
    *,
    conversation_id: str | None,
    tile_id: str | None,
    feature: str,
    model: str,
    model_requested: str,
    attempt: int,
    usage: Usage | None,
    duration_ms: int,
    status: str,
    error: str = "",
) -> None:
    from server import db

    u = usage or Usage()
    db.exec(
        "INSERT INTO llm_calls (conversation_id, tile_id, feature, model, model_requested, attempt, "
        "prompt_tokens, completion_tokens, total_tokens, tokens_estimated, cost_usd, duration_ms, status, error, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            conversation_id, tile_id, feature, model, model_requested, attempt,
            u.prompt_tokens, u.completion_tokens, u.total_tokens,
            1 if u.estimated else 0, float(u.cost_usd), duration_ms, status, _short(error, 500),
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def _payload(
    model: str,
    messages: list[dict],
    temperature: float,
    stream: bool,
    response_format: dict | None,
    max_tokens: int | None,
    extra: dict | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
        "usage": {"include": True},       # OpenRouter liefert damit usage im Stream
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if response_format:
        payload["response_format"] = response_format
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if extra:
        payload.update(extra)
    return payload


async def _error_text(resp: httpx.Response) -> str:
    try:
        body = (await resp.aread()).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        body = ""
    try:
        obj = json.loads(body)
        msg = (obj.get("error") or {}).get("message") or body
    except json.JSONDecodeError:
        msg = body
    return f"HTTP {resp.status_code}: {_short(msg, 400)}"


async def _post_with_retry(payload: dict, api_key: str) -> tuple[dict, int, str]:
    """Führt einen Non-Streaming-Request mit Backoff aus.

    Rückgabe: (payload, statuscode, fehlertext). ``statuscode == 200`` heißt ok.
    """
    delay = BACKOFF_BASE
    last = (0, "kein Versuch")
    for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                resp = await client.post(f"{BASE}/chat/completions", json=payload, headers=_headers(api_key))
                if resp.status_code == 200:
                    return resp.json(), 200, ""
                text = await _error_text(resp)
                last = (resp.status_code, text)
                if not _is_retryable(resp.status_code) or attempt == MAX_ATTEMPTS_PER_MODEL:
                    return {}, resp.status_code, text
                wait = _retry_after(resp) or delay
                await asyncio.sleep(min(wait, MAX_BACKOFF))
                delay *= 2
        except Exception as e:  # noqa: BLE001 – Netzfehler
            last = (0, f"{type(e).__name__}: {_short(str(e), 200)}")
            if attempt == MAX_ATTEMPTS_PER_MODEL:
                return {}, 0, last[1]
            await asyncio.sleep(delay)
            delay *= 2
    return {}, last[0], last[1]


async def chat_once(
    model: str,
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
    *,
    fallbacks: str | list[str] | None = None,
    response_format: dict | None = None,
    max_tokens: int | None = None,
    feature: str = "chat_once",
    tile_id: str | None = None,
    conversation_id: str | None = None,
) -> CallResult:
    """Einmal-Call mit Fallback-Kette, Backoff und Usage-Logging."""
    chain = resolve_chain(model, fallbacks)
    started = time.time()
    attempts: list[dict] = []
    for midx, m in enumerate(chain):
        payload = _payload(m, messages, temperature, False, response_format, max_tokens)
        t0 = time.time()
        data, status, err = await _post_with_retry(payload, api_key)
        if status == 200:
            try:
                content = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                content = ""
            if not content.strip():
                err, status = "leere Antwort", 0
            else:
                usage = usage_from_payload(data, m, messages, content)
                dur = int((time.time() - t0) * 1000)
                _log_call(conversation_id=conversation_id, tile_id=tile_id, feature=feature, model=m,
                          model_requested=model, attempt=midx + 1, usage=usage, duration_ms=dur, status="ok")
                attempts.append({"model": m, "attempt": midx + 1, "status": "ok"})
                return CallResult(content, m, model, usage, int((time.time() - started) * 1000), attempts, degraded=midx > 0)
        dur = int((time.time() - t0) * 1000)
        _log_call(conversation_id=conversation_id, tile_id=tile_id, feature=feature, model=m,
                  model_requested=model, attempt=midx + 1, usage=None, duration_ms=dur, status="error", error=err)
        attempts.append({"model": m, "attempt": midx + 1, "status": "error", "error": err})
    raise RuntimeError(
        "Alle Modelle der Kette sind ausgefallen: "
        + " | ".join(f"{a['model']}: {a.get('error', a['status'])}" for a in attempts)
    )


async def chat_json(
    model: str,
    messages: list[dict],
    api_key: str,
    schema: dict,
    *,
    temperature: float = 0.1,
    fallbacks: str | list[str] | None = None,
    feature: str = "extract",
    tile_id: str | None = None,
    conversation_id: str | None = None,
) -> tuple[dict, CallResult]:
    """Structured-Output-Call: liefert (geparstes JSON, CallResult).

    Reihenfolge je Modell: ``json_schema`` → ``json_object`` → Text mit
    JSON-Extraktion. Die Schemareparatur (Reparaturprompt) übernimmt der Aufrufer.
    """
    chain = resolve_chain(model, fallbacks)
    catalog = await models_catalog()
    last_err = "kein Versuch"
    for midx, m in enumerate(chain):
        caps = capabilities(m) if catalog else {}
        if caps.get("structured_outputs"):
            rf = {"type": "json_schema", "json_schema": {"name": "susmob_ergebnis", "strict": True, "schema": schema}}
        elif caps.get("response_format"):
            rf = {"type": "json_object"}
        else:
            rf = None
        msgs = messages
        if rf is None or rf.get("type") == "json_object":
            msgs = messages + [{
                "role": "system",
                "content": "Antworte ausschließlich mit einem JSON-Objekt, das exakt diesem JSON-Schema folgt "
                           "(keine Erklärungen, kein Markdown):\n" + json.dumps(schema, ensure_ascii=False),
            }]
        result = await chat_once(
            m, msgs, api_key, temperature, fallbacks=[], response_format=rf,
            feature=feature, tile_id=tile_id, conversation_id=conversation_id,
        )
        result.attempts = [{"model": m, "attempt": midx + 1, "status": "ok"}]
        parsed = parse_json_block(result.content)
        if parsed is not None:
            if midx > 0:
                result.degraded = True
            return parsed, result
        last_err = f"{m}: kein gültiges JSON in der Antwort"
        result.attempts = [{"model": m, "attempt": midx + 1, "status": "error", "error": last_err}]
    raise RuntimeError("Kein Modell lieferte gültiges JSON. " + last_err)


def parse_json_block(text: str) -> dict | None:
    """Robustes JSON aus einer Modellantwort ziehen (```json-Blöcke, Text davor/danach)."""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


async def stream_chat(
    model: str,
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
    *,
    fallbacks: str | list[str] | None = None,
    feature: str = "chat",
    tile_id: str | None = None,
    conversation_id: str | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """Streamt Token-Chunks mit Fallback-Kette.

    Yieldet ``("token", {"t": ...})`` je Chunk, ``("notice", {...})`` wenn auf ein
    Fallback-Modell gewechselt wurde und am Ende ``("usage", Usage.as_dict)``.
    """
    chain = resolve_chain(model, fallbacks)
    attempts: list[dict] = []
    last_err = "kein Versuch"
    for midx, m in enumerate(chain):
        payload = _payload(m, messages, temperature, True, None, None)
        t0 = time.time()
        collected: list[str] = []
        usage: Usage | None = None
        delay = BACKOFF_BASE
        for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
            collected = []
            usage = None
            status_code, err_text, retry_after = 0, "", None
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=30.0)) as client:
                    async with client.stream("POST", f"{BASE}/chat/completions", json=payload,
                                             headers=_headers(api_key)) as resp:
                        if resp.status_code != 200:
                            err_text = await _error_text(resp)
                            status_code = resp.status_code
                            retry_after = _retry_after(resp)
                        else:
                            async for line in resp.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                data = line[6:].strip()
                                if data == "[DONE]":
                                    break
                                try:
                                    obj = json.loads(data)
                                except json.JSONDecodeError:
                                    continue
                                if obj.get("usage"):
                                    usage = usage_from_payload(obj, m, messages, "".join(collected))
                                choices = obj.get("choices") or [{}]
                                delta = (choices[0] or {}).get("delta") or {}
                                tok = delta.get("content")
                                if tok:
                                    collected.append(tok)
                                    yield "token", {"t": tok}
                            if not collected:
                                err_text, status_code = "leere Antwort", 0
            except Exception as e:  # noqa: BLE001 – Netzfehler
                err_text, status_code = f"{type(e).__name__}: {_short(str(e), 200)}", 0

            if collected:
                content = "".join(collected)
                u = usage or usage_from_payload({}, m, messages, content)
                dur = int((time.time() - t0) * 1000)
                _log_call(conversation_id=conversation_id, tile_id=tile_id, feature=feature, model=m,
                          model_requested=model, attempt=midx + 1, usage=u, duration_ms=dur, status="ok")
                yield "usage", {**u.as_dict, "model": m, "model_requested": model,
                                "duration_ms": dur, "degraded": midx > 0 or attempt > 1,
                                "attempts": attempts + [{"model": m, "attempt": attempt, "status": "ok"}]}
                return
            dur = int((time.time() - t0) * 1000)
            _log_call(conversation_id=conversation_id, tile_id=tile_id, feature=feature, model=m,
                      model_requested=model, attempt=attempt, usage=None, duration_ms=dur,
                      status="error", error=err_text)
            attempts.append({"model": m, "attempt": attempt, "status": "error", "error": _short(err_text, 200)})
            last_err = f"{m}: {err_text}"
            retryable = status_code == 0 or _is_retryable(status_code)
            if not retryable or attempt == MAX_ATTEMPTS_PER_MODEL:
                break
            await asyncio.sleep(min(retry_after or delay, MAX_BACKOFF))
            delay *= 2
        if midx + 1 < len(chain):
            yield "notice", {"t": f"⚠️ Modell `{m}` nicht verfügbar – weiche auf `{chain[midx + 1]}` aus. "
                                  f"Grund: {_short(last_err, 160)}"}
    raise RuntimeError(
        "Alle Modelle der Fallback-Kette sind ausgefallen – "
        + " | ".join(f"{a['model']}: {a.get('error', '')}" for a in attempts)
    )
