"""OpenRouter-Client: Streaming (SSE) und Einmal-Requests (Admin-Testlauf)."""
from __future__ import annotations

from typing import AsyncIterator

import httpx

BASE = "https://openrouter.ai/api/v1"
HEADERS = {
    "HTTP-Referer": "https://susmob.local",
    "X-Title": "SusMob",
}


def _headers(api_key: str) -> dict:
    return {**HEADERS, "Authorization": f"Bearer {api_key}"}


async def stream_chat(
    model: str,
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
) -> AsyncIterator[str]:
    """Yieldt Token-Chunks als sie eintreffen (OpenRouter SSE)."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
        async with client.stream(
            "POST", f"{BASE}/chat/completions", json=payload, headers=_headers(api_key)
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "replace")[:500]
                raise RuntimeError(f"OpenRouter {resp.status_code}: {body}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    import json as _json

                    obj = _json.loads(data)
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content")
                    if token:
                        yield token
                except Exception:
                    continue


async def chat_once(
    model: str,
    messages: list[dict],
    api_key: str,
    temperature: float = 0.2,
) -> str:
    """Nicht-gestreamter Einmal-Call (für den Admin-Testlauf)."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        resp = await client.post(
            f"{BASE}/chat/completions", json=payload, headers=_headers(api_key)
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
        return resp.json()["choices"][0]["message"]["content"]
