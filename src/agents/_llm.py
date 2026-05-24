"""Minimal OpenAI-compatible LLM client.

Designed for Featherless (https://featherless.ai) hosting DeepSeek, but works
against any provider that implements the OpenAI ``/chat/completions`` shape.
No SDK dependency — pure stdlib HTTP — so this stays a leaf module.

Configuration is read from environment variables (all overridable per-call):

    FEATHERLESS_API_KEY   — required at call time, not at import time
    FEATHERLESS_BASE_URL  — default "https://api.featherless.ai/v1"
    AGENT_MODEL           — default "deepseek-ai/DeepSeek-V4-Pro"

Each agent module re-imports ``MODEL_DEFAULT`` and may override it via its
own module-level constant — keep model selection visible per-file.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

BASE_URL_DEFAULT = os.environ.get(
    "FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"
)
MODEL_DEFAULT = os.environ.get("AGENT_MODEL", "deepseek-ai/DeepSeek-V4-Pro")
TIMEOUT_S = float(os.environ.get("AGENT_TIMEOUT_S", "60"))


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw: dict[str, Any]


def chat(
    system: str,
    user: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1500,
    response_format_json: bool = True,
) -> LLMResponse:
    """One synchronous chat completion call.

    Returns the assistant message text plus the raw decoded JSON. JSON-mode
    is requested by default because every agent in this module parses a
    structured response. If the provider ignores ``response_format``, the
    agents' own parsers fall back to bracket-matching.
    """

    key = api_key or os.environ.get("FEATHERLESS_API_KEY")
    if not key:
        raise LLMError(
            "FEATHERLESS_API_KEY is not set. Export it before calling any agent."
        )

    url = (base_url or BASE_URL_DEFAULT).rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {
        "model": model or MODEL_DEFAULT,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format_json:
        body["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # noqa: PERF203 — explicit narrow
        detail = e.read().decode("utf-8", errors="replace")
        raise LLMError(f"HTTP {e.code} from LLM provider: {detail}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"Network error calling LLM provider: {e.reason}") from e

    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected response shape: {payload!r}") from e

    return LLMResponse(text=text, raw=payload)


def parse_json_object(text: str) -> dict[str, Any]:
    """Forgiving JSON-object extractor.

    DeepSeek (and similar) sometimes wrap JSON in ```json fences or include
    a sentence of preamble before the object. Strategy:
      1. Try direct ``json.loads``.
      2. Strip ```json fences.
      3. Take the first ``{ ... }`` balanced span.
    """

    candidates = [text.strip()]
    fenced = text.strip()
    if fenced.startswith("```"):
        fenced = fenced.strip("`")
        # drop optional "json\n" header
        if fenced.lower().startswith("json"):
            fenced = fenced[4:].lstrip()
        candidates.append(fenced.strip())

    # balanced-brace fallback
    s = text
    start = s.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(s[start : i + 1])
                    break

    last_err: Exception | None = None
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError as e:
            last_err = e
            continue
    raise LLMError(f"Could not parse JSON object from LLM output: {last_err!r}; raw: {text!r}")
