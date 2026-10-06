"""OpenRouter-Client: Streaming (SSE), Einmal-Requests, Fallback-Kette, Backoff.

Phase 0 des Plans:
* **Usage-Erfassung** – jeder Call liefert Tokens (Input/Output/Cache) und Kosten zurück.
* **Fallback-Kette** – scheitert ein Modell (kein Endpunkt, 429, 5xx, Netzfehler),
  wird automatisch das nächste Modell der Kette versucht.
* **429-Backoff** – ``Retry-After`` wird respektiert, sonst exponentiell (2 s, 4 s).
"""
from __future__ import annotations

import asyncio
import json as _json
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

import httpx

BASE = "https://openrouter.ai/api/v1"
HEADERS = {
    "HTTP-Referer": "https://susmob.local",
    "X-Title": "SusMob",
}
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}
MAX_TRIES_PER_MODEL = 2
BACKOFF_BASE = 2.0


class LLMError(RuntimeError):
    """Alle Modelle der Kette gescheitert – Klartext-Meldung für die UI."""

    def __init__(self, message: str, errors: list[str] | None = None, status_code: int = 0):
        super().__init__(message)
        self.errors = errors or []
        self.status_code = status_code


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cost_estimated: bool = True

    def as_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 8),
            "cost_estimated": self.cost_estimated,
        }


@dataclass
class LLMResult:
    content: str
    model: str
    requested_model: str = ""
    attempt: int = 1
    used_fallback: bool = False
    usage: Usage = field(default_factory=Usage)
    duration_ms: int = 0
    chain: list[str] = field(default_factory=list)
    repair_attempts: int = 0


def _headers(api_key: str) -> dict:
    return {**HEADERS, "Authorization": f"Bearer {api_key}"}


def chain_for(tile: dict | None, model: str | None = None) -> list[str]:
    """Modell-Kette einer Kachel: Hauptmodell + Fallbacks (ohne Dubletten)."""
    primary = (model or (tile.get("model") if tile else "") or "").strip()
    raw = (tile.get("fallback_models") if tile else "") or ""
    chain: list[str] = []
    for m in [primary, *[x.strip() for x in str(raw).replace(";", ",").split(",")]]:
        if m and m not in chain:
            chain.append(m)
    return chain


def _pricing(model: str) -> tuple[float, float] | None:
    """Preise (USD je Token) aus der Health-Tabelle, falls vorhanden."""
    try:
        from server import db

        row = db.query1("SELECT pricing_prompt, pricing_completion FROM model_health WHERE model=?", (model,))
        if row and row["pricing_prompt"] is not None and row["pricing_completion"] is not None:
            return float(row["pricing_prompt"]), float(row["pricing_completion"])
    except Exception:  # noqa: BLE001 – Preistabelle ist optional
        pass
    return None


def usage_from_response(model: str, payload: dict, chars_in: int, chars_out: int) -> Usage:
    """Usage-Block der Antwort auswerten; Kosten notfalls aus der Preistabelle rechnen."""
    raw = payload.get("usage") or {}
    u = Usage(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        completion_tokens=int(raw.get("completion_tokens") or 0),
        cached_tokens=int((raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        total_tokens=int(raw.get("total_tokens") or 0),
    )
    cost = raw.get("cost")
    if cost is not None:
        u.cost_usd = float(cost)
        u.cost_estimated = False
    else:
        price = _pricing(model)
        if price:
            u.cost_usd = u.prompt_tokens * price[0] + u.completion_tokens * price[1]
            u.cost_estimated = False
        else:
            # Grobe Notfall-Schätzung: 3.3 Zeichen je Token, 0 USD (Free) bis 2/10 USD je Mio.
            if not u.prompt_tokens:
                u.prompt_tokens = max(1, int(chars_in / 3.3))
                u.completion_tokens = max(1, int(chars_out / 3.3))
            u.total_tokens = u.total_tokens or (u.prompt_tokens + u.completion_tokens)
            u.cost_usd = 0.0
            u.cost_estimated = True
    if not u.total_tokens:
        u.total_tokens = u.prompt_tokens + u.completion_tokens
    return u


def error_hint(status_code: int, body: str) -> str:
    """Kurze, verständliche Einordnung eines OpenRouter-Fehlers."""
    b = body.lower()
    if status_code == 429 or "rate limit" in b or "too many requests" in b:
        return "Rate-Limit erreicht (Free-Tier: ca. 50 Requests/Tag)."
    if status_code == 404 or "no endpoints" in b or "not found" in b:
        return "Modell hat aktuell keinen aktiven Anbieter (Endpunktliste leer)."
    if status_code in (401, 402, 403):
        return "API-Key ungültig, nicht berechtigt oder Guthaben/Kreditlimit erschöpft."
    if status_code >= 500:
        return "Anbieter-Fehler (5xx) – Server des Modell-Anbieters."
    return "Antwort des Anbieters nicht verwertbar."


def _status_of(err: Exception) -> int:
    return getattr(err, "status_code", 0) or 0


NETWORK_MARKERS = ("ssl", "eof", "connect", "timeout", "timed out", "getaddrinfo", "name or service")


def _is_network_error(text: str) -> bool:
    """Netz-/TLS-Fehler betreffen alle Modelle gleich → kein Modell-Retry, kein Backoff."""
    t = (text or "").lower()
    return any(k in t for k in NETWORK_MARKERS)


def _is_retryable(status: int, text: str) -> bool:
    if status in RETRY_STATUS:
        return True
    return _is_network_error(text)


def _backoff_seconds(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return min(30.0, max(0.5, float(retry_after)))
        except ValueError:
            pass
    return min(20.0, BACKOFF_BASE ** attempt)


def _sse_usage(obj: dict, acc: dict) -> None:
    """Usage kann im letzten SSE-Chunk oder in jedem Chunk stehen."""
    u = obj.get("usage")
    if isinstance(u, dict) and u:
        acc["usage"] = u
    if obj.get("model"):
        acc["model"] = obj["model"]


async def stream_chat_chain(
    chain: list[str],
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
    extra_payload: dict | None = None,
) -> AsyncIterator[dict]:
    """Streamt über die Modell-Kette.

    Yieldet Ereignisse für die UI::

        {"type": "token",  "t": "…"}
        {"type": "retry",  "model": "…", "reason": "…", "attempt": 1}
        {"type": "done",   "result": LLMResult}

    Ist die Kette erschöpft, wird :class:`LLMError` geworfen.
    """
    errors: list[str] = []
    started = time.time()
    chain = [m for m in chain if m]
    if not chain:
        raise LLMError("Kein Modell konfiguriert.")

    for idx, model in enumerate(chain):
        for try_no in range(MAX_TRIES_PER_MODEL):
            attempt = idx * MAX_TRIES_PER_MODEL + try_no + 1
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
                "usage": {"include": True},
                **(extra_payload or {}),
            }
            acc: dict = {"usage": {}, "model": model}
            full: list[str] = []
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                    async with client.stream(
                        "POST", f"{BASE}/chat/completions", json=payload, headers=_headers(api_key)
                    ) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "replace")[:600]
                            retry_after = resp.headers.get("retry-after")
                            err = LLMError(
                                f"OpenRouter {resp.status_code}: {error_hint(resp.status_code, body)}",
                                [body], resp.status_code,
                            )
                            if _is_retryable(resp.status_code, body) and try_no + 1 < MAX_TRIES_PER_MODEL:
                                yield {"type": "retry", "model": model, "attempt": attempt,
                                       "reason": str(err), "wait": _backoff_seconds(try_no, retry_after)}
                                await asyncio.sleep(_backoff_seconds(try_no, retry_after))
                                continue
                            raise err
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                obj = _json.loads(data)
                            except Exception:
                                continue
                            _sse_usage(obj, acc)
                            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                            token = delta.get("content")
                            if token:
                                full.append(token)
                                yield {"type": "token", "t": token}
            except Exception as e:  # noqa: BLE001 – Netz, Timeout, HTTP, Abbruch
                status = _status_of(e)
                errors.append(f"{model}: {e}")
                if _is_network_error(str(e)):
                    break  # alle Modelle laufen über dieselbe Verbindung → direkt nächstes Modell
                retryable = _is_retryable(status, str(e))
                if retryable and try_no + 1 < MAX_TRIES_PER_MODEL:
                    wait = _backoff_seconds(try_no)
                    yield {"type": "retry", "model": model, "attempt": attempt, "reason": str(e), "wait": wait}
                    await asyncio.sleep(wait)
                    continue
                break  # nächstes Modell der Kette
            content = "".join(full)
            usage = usage_from_response(model, {"usage": acc["usage"]}, _chars_in(messages), len(content))
            result = LLMResult(
                content=content,
                model=acc.get("model") or model,
                requested_model=chain[0],
                attempt=attempt,
                used_fallback=idx > 0,
                usage=usage,
                duration_ms=int((time.time() - started) * 1000),
                chain=chain,
            )
            yield {"type": "done", "result": result}
            return

    raise LLMError(
        "Alle Modelle der Kette sind gescheitert: " + " | ".join(errors[-4:]),
        errors,
        _status_of(Exception(errors[-1] if errors else "")),
    )


def _chars_in(messages: Iterable[dict]) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(part.get("text") or "")
                elif isinstance(part, dict):
                    total += 256  # Bild grob als Textäquivalent
    return total


async def chat_chain(
    chain: list[str],
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
    extra_payload: dict | None = None,
) -> LLMResult:
    """Nicht-gestreamter Call mit Fallback-Kette (Admin-Test, Beispiele, Eval, Extraktion)."""
    errors: list[str] = []
    started = time.time()
    chain = [m for m in chain if m]
    if not chain:
        raise LLMError("Kein Modell konfiguriert.")

    for idx, model in enumerate(chain):
        for try_no in range(MAX_TRIES_PER_MODEL):
            attempt = idx * MAX_TRIES_PER_MODEL + try_no + 1
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
                "usage": {"include": True},
                **(extra_payload or {}),
            }
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                    resp = await client.post(
                        f"{BASE}/chat/completions", json=payload, headers=_headers(api_key)
                    )
                if resp.status_code != 200:
                    body = resp.text[:600]
                    err = LLMError(
                        f"OpenRouter {resp.status_code}: {error_hint(resp.status_code, body)}",
                        [body], resp.status_code,
                    )
                    if _is_retryable(resp.status_code, body) and try_no + 1 < MAX_TRIES_PER_MODEL:
                        await asyncio.sleep(_backoff_seconds(try_no, resp.headers.get("retry-after")))
                        continue
                    raise err
                data = resp.json()
            except LLMError:
                errors.append(f"{model}: {err}")  # type: ignore[possibly-undefined]
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{model}: {e}")
                if _is_network_error(str(e)):
                    break  # Verbindungsproblem betrifft jedes Modell gleich
                if _is_retryable(_status_of(e), str(e)) and try_no + 1 < MAX_TRIES_PER_MODEL:
                    await asyncio.sleep(_backoff_seconds(try_no))
                    continue
                break
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            usage = usage_from_response(model, data, _chars_in(messages), len(content))
            return LLMResult(
                content=content,
                model=data.get("model") or model,
                requested_model=chain[0],
                attempt=attempt,
                used_fallback=idx > 0,
                usage=usage,
                duration_ms=int((time.time() - started) * 1000),
                chain=chain,
            )

    raise LLMError(
        "Alle Modelle der Kette sind gescheitert: " + " | ".join(errors[-4:]),
        errors,
    )


# ------------------------------------------------------------------ Kompatibilität
# Ältere Aufrufer (Admin-Testlauf, Beispiele) nutzen die schlanken Funktionen.
async def stream_chat(
    model: str,
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
) -> AsyncIterator[str]:
    """Yieldet Token-Chunks (ohne Metadaten) – dünner Wrapper um die Kette."""
    async for ev in stream_chat_chain([model], messages, api_key, temperature):
        if ev["type"] == "token":
            yield ev["t"]


async def chat_once(
    model: str,
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
) -> str:
    """Einmal-Call, gibt nur den Text zurück (Kompatibilitäts-Wrapper)."""
    result = await chat_chain([model], messages, api_key, temperature)
    return result.content
