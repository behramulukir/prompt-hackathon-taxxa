"""LLM-graded confidence estimate for a generated answer.

The frontend renders High / Medium / Low next to the answer card; when
the verdict is Low, an "Ask specialist" CTA opens an email composer the
user can copy. This module wraps a small DeepSeek call that returns one
of those three tokens and nothing else.

Design notes:

- Reuses ``src.retrieval.generate.get_client`` so we share the singleton
  OpenAI client and the FEATHERLESS_API_KEY discovery logic.
- Caps at ``max_tokens=4`` so the cost overhead per query is negligible
  (well under 1% of the main generation cost).
- Soft-fails to ``"medium"`` on any LLM error — the worst outcome of a
  failed eval is showing the neutral pill, not blocking the answer.
- Confidence is graded against the *question*, the *answer*, and a
  truncated *context preview*. Including the answer itself is
  load-bearing: the LLM grades how well-supported and unequivocal the
  answer reads.
"""
from __future__ import annotations

import logging
import time
from typing import Literal

from src.retrieval.assemble import AssembledContext
from src.retrieval.generate import MODEL, get_client

logger = logging.getLogger("lex_atlas.confidence")

Confidence = Literal["high", "medium", "low"]

# Default we return on any failure path. Medium is the right neutral
# default — high implies the LLM signed off, low triggers the
# "ask specialist" path which is wrong if eval just timed out.
_FALLBACK: Confidence = "medium"


_SYSTEM_PROMPT = """You are a precision evaluator for Finnish tax-law answers.

Given a USER QUESTION, the DRAFT ANSWER another model produced, and the
SOURCE EXCERPTS the answer was grounded on, return EXACTLY ONE WORD from
{high, medium, low} describing how confidently a Finnish tax practitioner
should rely on this answer.

Grading rubric:

- high   — Every factual claim is plainly supported by the sources, the
           answer is unambiguous, and no critical caveat is missing.
- medium — Mostly supported, but with hedging language, partial coverage
           of the question, or a missing edge case.
- low    — The answer leans on inference past what the sources say, the
           sources contradict each other, the topic isn't in scope, or
           the LLM declined to answer.

Output a single lowercase word: high, medium, or low. No punctuation,
no explanation.
"""


_USER_TEMPLATE = """QUESTION:
{question}

DRAFT ANSWER:
{answer}

SOURCE EXCERPTS (first {n} of {total}):
{context}
"""


# Cap on the context bytes we feed the grader. The full assembled context
# can be 10-15k chars; we don't need it all to judge — a couple of
# headers + the first few hundred chars of each block is plenty.
_CONTEXT_PREVIEW_CHARS = 2400


def _truncate_context(context: AssembledContext) -> tuple[str, int, int]:
    """Return (preview_text, sources_shown, sources_total).

    Picks the top-ranked sources (already sorted) up to the char cap,
    keeps full source headers, and replaces overflow body with ``…``.
    """
    total = len(context.sources)
    if total == 0 or not context.text:
        return "(no sources)", 0, 0

    buf: list[str] = []
    shown = 0
    used = 0
    for src in context.sources:
        block = src.rendered_block
        # Each block is "header\n  Path: ...\n\n<body>". Trim long bodies.
        if len(block) > 600:
            block = block[:600].rstrip() + " […]"
        if used + len(block) + 2 > _CONTEXT_PREVIEW_CHARS:
            break
        buf.append(block)
        used += len(block) + 2
        shown += 1

    return "\n\n".join(buf), shown, total


def evaluate_confidence(
    *,
    question: str,
    answer: str,
    context: AssembledContext,
    model: str = MODEL,
) -> Confidence:
    """Grade the draft answer's reliability. Returns 'high', 'medium', or 'low'.

    Single short LLM call: ~50 input tokens of rubric + a few hundred
    tokens of context preview + the answer. Output capped at 4 tokens.
    Soft-fails to 'medium' on any error.
    """
    if not answer.strip():
        return "low"

    preview, shown, total = _truncate_context(context)
    user = _USER_TEMPLATE.format(
        question=question.strip(),
        answer=answer.strip(),
        context=preview,
        n=shown,
        total=total,
    )

    try:
        client = get_client()
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=4,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
    except Exception as e:
        logger.warning("confidence eval failed: %s — defaulting to %s", e, _FALLBACK)
        return _FALLBACK

    raw = (resp.choices[0].message.content or "").strip().lower()
    # Pick the FIRST recognized token. The grader might respond with
    # "low.", "Low", "low confidence", etc. — tolerate light noise.
    for token in ("high", "medium", "low"):
        if token in raw.split():
            logger.info("confidence=%s · raw=%r · %d ms", token, raw, elapsed_ms)
            return token  # type: ignore[return-value]
    # Strict-equals fallback for single-token responses without whitespace.
    if raw in {"high", "medium", "low"}:
        logger.info("confidence=%s · %d ms", raw, elapsed_ms)
        return raw  # type: ignore[return-value]
    logger.warning("confidence: unrecognized response %r — defaulting to %s", raw, _FALLBACK)
    return _FALLBACK
