"""Minimal client for the OpenAI-compatible chat endpoint of the Meta Model API."""

from __future__ import annotations

import json
import re
import time

import httpx

from .config import Settings, get_settings


class LLMError(RuntimeError):
    pass


def chat(
    messages: list[dict],
    *,
    client: httpx.Client | None = None,
    settings: Settings | None = None,
    retries: int = 2,
    backoff_s: float = 1.0,
    extra: dict | None = None,
) -> str:
    settings = settings or get_settings()
    if not settings.api_key:
        raise LLMError("MODEL_API_KEY is not set (see .env.example)")
    body = {"model": settings.llm_model, "messages": messages, "temperature": 0}
    if extra:
        body.update(extra)
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    url = settings.api_base + "/chat/completions"
    own = client is None
    client = client or httpx.Client(timeout=120)
    try:
        for attempt in range(retries + 1):
            try:
                r = client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                if attempt == retries:
                    raise LLMError(f"Network error: {exc}") from exc
                time.sleep(backoff_s * (attempt + 1))
                continue
            if (r.status_code == 429 or r.status_code >= 500) and attempt < retries:
                time.sleep(backoff_s * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise LLMError(f"Chat request failed with HTTP {r.status_code}: {r.text[:1500]}")
            try:
                content = r.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"Unexpected response shape: {r.text[:500]}") from exc
            if isinstance(content, list):  # some APIs return a list of parts
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
            return str(content)
        raise LLMError("unreachable")
    finally:
        if own:
            client.close()


def parse_json_object(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences and chatter)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise LLMError("No JSON object in the model reply")
    depth = 0
    in_str = esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except ValueError as exc:
                    raise LLMError(f"Model returned invalid JSON: {exc}") from exc
    raise LLMError("Unterminated JSON object in the model reply")
