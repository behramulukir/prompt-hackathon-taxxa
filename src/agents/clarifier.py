"""Clarifier agent — detects under-specified Finnish tax questions and
fills in safe defaults (year, entity_type, jurisdiction) for batch mode.

Per Step 8 brief (B8.1):
    For interactive use, ask back. For batch evaluation, run with explicit
    defaults (current year, Finnish tax-resident company) and have the final
    answer state the assumption.
"""

from __future__ import annotations

from . import ClarifyResult, MissingDimension
from ._llm import LLMError, chat, parse_json_object
from ._prompts import load

MODEL = "deepseek-ai/DeepSeek-V3"
SYSTEM_PROMPT = load("clarifier")

_VALID_MISSING: frozenset[str] = frozenset({"year", "entity_type", "jurisdiction"})


def clarifier(question: str) -> ClarifyResult:
    """Decide what's missing in ``question`` and produce a normalised form.

    No retrieval calls. Pure LLM. The orchestrator decides whether to act on
    ``clarified=False`` (ask user) or just surface ``assumptions`` in the
    final answer.
    """

    response = chat(system=SYSTEM_PROMPT, user=question, model=MODEL)
    obj = parse_json_object(response.text)

    clarified = bool(obj.get("clarified", False))
    raw_missing = obj.get("missing") or []
    if not isinstance(raw_missing, list):
        raise LLMError(f"Clarifier returned non-list 'missing': {raw_missing!r}")
    missing: tuple[MissingDimension, ...] = tuple(
        m for m in raw_missing if isinstance(m, str) and m in _VALID_MISSING
    )  # type: ignore[assignment]

    assumptions = obj.get("assumptions") or {}
    if not isinstance(assumptions, dict):
        raise LLMError(f"Clarifier returned non-dict 'assumptions': {assumptions!r}")
    assumptions = {str(k): str(v) for k, v in assumptions.items()}

    normalized = obj.get("normalized_question") or question
    if not isinstance(normalized, str):
        normalized = str(normalized)

    return ClarifyResult(
        clarified=clarified,
        missing=missing,
        assumptions=assumptions,
        normalized_question=normalized,
    )
