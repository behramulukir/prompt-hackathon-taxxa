"""LLM generation step — DeepSeek via Featherless (OpenAI-compatible API).

Owns three concerns:
1. Build the system + user prompt against the assembled context.
2. Call the LLM with retry on transient errors (mirrors voyage_client).
3. Parse ``[Source N]`` citations out of the answer text and resolve them
   back to chunk_ids via ``AssembledContext.chunk_id_for_label``.

Asymmetry with voyage_client: the OpenAI SDK already retries on transient
errors internally, so we keep the loop short — one extra outer retry on
network-level failures is plenty.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from src.retrieval.assemble import AssembledContext


# --------------------------------------------------------------------------
# Featherless / DeepSeek config
# --------------------------------------------------------------------------

FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
# Model slug. Featherless typically uses HF-style names — if the exact slug
# differs (e.g. ``deepseek-ai/DeepSeek-V4-Flash``), update here only.
MODEL = "deepseek-ai/DeepSeek-V4-Flash"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TEMPERATURE = 0.2  # low — we want faithful citation, not creativity
DEFAULT_MAX_TOKENS = 1200


# --------------------------------------------------------------------------
# Prompt
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Finnish tax-regulation research assistant.

You answer questions using ONLY the sources provided below. Every factual claim must be followed by an inline citation in the form [Source N], where N is the source number from the provided list. You may cite multiple sources on one claim, e.g. [Source 1][Source 3].

Rules:
- Answer in the language of the question (Finnish if the question is in Finnish, English if in English).
- Finlex statutes are binding law; Vero guidance is interpretive. If Vero guidance appears to conflict with a Finlex section on the same point, surface the conflict explicitly and explain that the Finlex section prevails.
- If the sources do not contain enough information to answer, say so plainly. Do not guess, do not draw on outside knowledge.
- Be specific. Quote thresholds, percentages, and section numbers verbatim from the sources.
- Keep the answer concise — 3 to 8 sentences for most questions.
- When sources are connected (you see "Cites:", "Interpreted by:", "Amended by:" etc. between them), use those relationships to structure your reasoning: e.g. "The general rule is [Source 1], but [Source 1] cites [Source 3] for the exception..."
"""


USER_PROMPT_TEMPLATE = """Question: {question}

Sources:
{context}

Answer:"""


# --------------------------------------------------------------------------
# API key loading — mirrors voyage_client._load_api_key.
# --------------------------------------------------------------------------


def _load_api_key() -> str:
    key = os.environ.get("FEATHERLESS_API_KEY")
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("FEATHERLESS_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    os.environ["FEATHERLESS_API_KEY"] = val
                    return val
    raise RuntimeError(
        "FEATHERLESS_API_KEY not set in environment or .env at project root"
    )


_client: OpenAI | None = None


def get_client() -> OpenAI:
    """Lazy, process-singleton client. Featherless is OpenAI-compatible."""
    global _client
    if _client is None:
        api_key = _load_api_key()
        _client = OpenAI(api_key=api_key, base_url=FEATHERLESS_BASE_URL)
    return _client


# --------------------------------------------------------------------------
# Citation parsing
# --------------------------------------------------------------------------


# ``[Source 1]``, ``[Source 12]``, ``[source 3]``, ``[SOURCE 4]``,
# ``[Source 2, kappale 58]``, ``[Source 5, 1 kappale]`` — the LLM commonly
# adds a paragraph qualifier inside the brackets, which still points at the
# same numbered source. We accept any trailing content up to the closing ].
# Does not match ``[Source A]`` or ``Source 1`` without brackets.
_CITE_RE = re.compile(r"\[\s*source\s+(\d+)\b[^\]]*\]", re.IGNORECASE)


def parse_citations(answer: str) -> list[int]:
    """Return the de-duplicated 1-based source indices the answer cites,
    in order of first appearance.
    """
    seen: set[int] = set()
    out: list[int] = []
    for m in _CITE_RE.finditer(answer):
        idx = int(m.group(1))
        if idx in seen:
            continue
        seen.add(idx)
        out.append(idx)
    return out


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Generation:
    answer: str
    cited_chunk_ids: list[str]  # resolved [Source N] → chunk_id
    cited_indices: list[int]  # raw 1-based indices, including unresolved
    raw_response_id: str | None  # provider response id for debugging


def generate(
    question: str,
    context: AssembledContext,
    *,
    model: str = MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = 2,
) -> Generation:
    """One LLM call. Returns the answer text + resolved citations.

    A citation that doesn't resolve (LLM cited [Source 99] which doesn't
    exist) is silently dropped from ``cited_chunk_ids`` but kept in
    ``cited_indices`` so callers can detect and report it.
    """
    if not context.sources:
        # Don't burn a token; the LLM has nothing to cite.
        return Generation(
            answer=(
                "I could not find any sources relevant to this question in "
                "the corpus."
            ),
            cited_chunk_ids=[],
            cited_indices=[],
            raw_response_id=None,
        )

    client = get_client()
    user_prompt = USER_PROMPT_TEMPLATE.format(
        question=question, context=context.text
    )

    delay = 2.0
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            break
        except Exception as e:  # network / 5xx / rate-limit
            last_err = e
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    else:  # pragma: no cover — defensive
        raise RuntimeError(f"LLM call failed: {last_err}")

    answer = (resp.choices[0].message.content or "").strip()

    cited_indices = parse_citations(answer)
    cited_chunk_ids: list[str] = []
    for idx in cited_indices:
        cid = context.chunk_id_for_label(f"[Source {idx}]")
        if cid is not None:
            cited_chunk_ids.append(cid)

    return Generation(
        answer=answer,
        cited_chunk_ids=cited_chunk_ids,
        cited_indices=cited_indices,
        raw_response_id=getattr(resp, "id", None),
    )
