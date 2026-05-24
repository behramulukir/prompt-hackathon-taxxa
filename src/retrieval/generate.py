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
- Begin the answer directly with the substantive response. Do NOT open with a parenthetical aside, a header like "Vastaus:" / "Answer:" / "Note:", a preface ("Based on the sources, ..."), or any meta-commentary about how you derived the answer. The first character of your response must be the first character of the actual sentence.
- Answer in the language of the question (Finnish if the question is in Finnish, English if in English).
- Finlex statutes are binding law; Vero guidance is interpretive. If Vero guidance appears to conflict with a Finlex section on the same point, surface the conflict explicitly and explain that the Finlex section prevails.
- If the sources do not contain enough information to answer, say so plainly. Do not guess, do not draw on outside knowledge.
- Be specific. Quote thresholds, percentages, and section numbers verbatim from the sources.
- Keep the answer concise — 3 to 8 sentences for most questions.
- When sources are connected (you see "Cites:", "Interpreted by:", "Amended by:" etc. between them), use those relationships to structure your reasoning: e.g. "The general rule is [Source 1], but [Source 1] cites [Source 3] for the exception..."
- If a prior assistant turn appears in this conversation, treat it as context for the user's follow-up. The Source numbering in the CURRENT turn refers to the CURRENT source list only — never re-cite an old [Source N] number that no longer exists in the current list.

Temporal awareness:
- Each source header may carry `status=suspect | stale | repealed`, and the block may include `Amendments to parent LAW`, `Interpretations on file`, or `Note:` lines. Read these.
- If a cited source's status is `suspect`, `stale`, or `repealed`, add a short "Huomioitavaa:" / "Note:" block (one or two sentences) after the answer. Name the source and explain why it might be outdated: e.g. "[Source 3] kuuluu lakiin, johon on tehty 200+ muutosta, joista uusin on voimassa 2025 alkaen — varmista nykytila." Never silently rely on a suspect/stale source.
- For `repealed` sources, do not present them as current law — describe them as historical and prefer a non-repealed alternative if one is in the sources.
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


# Patterns the LLM has been observed to lead with even when the system
# prompt forbids preambles. Stripped at the start of the answer only
# (the ``^`` anchor matters — temporal "Huomioitavaa:" / "Note:" blocks
# the prompt explicitly asks for trail at the END and must survive).
#
# Tested against:
#   "<think>Let me check...</think>The answer is..."     → "The answer is..."
#   "(Note: based on Source 1) Yhtiöt..."                → "Yhtiöt..."
#   "**Vastaus:** Yhtiöt..."                             → "Yhtiöt..."
#   "Vastaus: Yhtiöt..."                                 → "Yhtiöt..."
#   "Based on the sources, Yhtiöt..."                    → "Yhtiöt..."
_PREAMBLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # DeepSeek-style reasoning block — strip the whole <think>…</think>
    re.compile(r"\A\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE),
    # Leading parenthetical aside ("(Note: …)"). Capped at 200 chars so we
    # don't accidentally eat a long opening sentence wrapped in parens.
    re.compile(r"\A\s*\([^)\n]{1,200}\)\s*"),
    # Leading bold header like **Vastaus:** or **Answer:** (with trailing
    # colon, dash, or em-dash — the header form, not a bold first phrase).
    re.compile(
        r"\A\s*\*\*\s*(?:vastaus|answer|note|huomio|huomioitavaa|yhteenveto|summary)"
        r"\s*[:\-—]\s*\*\*\s*",
        re.IGNORECASE,
    ),
    # Bare header word: "Vastaus: …", "Answer: …", "Note: …"
    re.compile(
        r"\A\s*(?:vastaus|answer|note|huomio|huomioitavaa|yhteenveto|summary)"
        r"\s*[:\-—]\s+",
        re.IGNORECASE,
    ),
    # Stock prefaces: "Based on the sources, …", "Lähteiden perusteella, …"
    re.compile(
        r"\A\s*(?:based on (?:the )?sources?|according to (?:the )?sources?|"
        r"lähteiden perusteella|annettujen lähteiden perusteella)\s*[,:]\s+",
        re.IGNORECASE,
    ),
)


def _strip_answer_preamble(answer: str) -> str:
    """Belt-and-suspenders for the system-prompt "begin directly" rule.

    Strips a leading parenthetical / header / reasoning block from the LLM
    output BEFORE rewrite_citations runs. The rule is in the system prompt
    already; this is a defensive cleanup for cases where the model still
    emits a preface (DeepSeek-V4-Flash has been observed to wrap answers in
    a parenthetical when it's not fully sure, despite instructions).

    Idempotent: re-applied until no pattern matches, so a model that emits
    BOTH a ``<think>`` block AND a ``Vastaus:`` header loses both. Bounded
    at 4 iterations so a malformed input can't loop.
    """
    cleaned = answer
    for _ in range(4):
        before = cleaned
        for pat in _PREAMBLE_PATTERNS:
            cleaned = pat.sub("", cleaned, count=1)
        if cleaned == before:
            break
    return cleaned.lstrip()


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
    history: list[dict[str, str]] | None = None,
    model: str = MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = 2,
) -> Generation:
    """One LLM call. Returns the answer text + resolved citations.

    A citation that doesn't resolve (LLM cited [Source 99] which doesn't
    exist) is silently dropped from ``cited_chunk_ids`` but kept in
    ``cited_indices`` so callers can detect and report it.

    ``history`` is prior conversation turns as OpenAI-format messages
    (``{"role": "user"|"assistant", "content": str}``). Source numbering in
    each turn is local — the system prompt warns the model not to reuse a
    [Source N] reference from a prior turn against the current source list.
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

    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    if history:
        for msg in history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_prompt})

    delay = 2.0
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=messages,
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
    # Defensive: the system prompt forbids preambles, but the model
    # occasionally ignores it (typically a leading parenthetical or a
    # ``Vastaus:`` header). Strip those so the rendered answer always
    # opens with the substantive sentence.
    answer = _strip_answer_preamble(answer)

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
