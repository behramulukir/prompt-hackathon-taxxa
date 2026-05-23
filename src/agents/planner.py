"""Planner agent — decomposes compound questions into ≤4 sub-questions
tagged with retrieval-strategy categories.

Per Step 8 brief (B8.2):
    Cost guard: cap sub-questions at 4. More than that is usually a sign of
    wrong decomposition.
"""

from __future__ import annotations

from . import Plan, SubQuestion, SubQuestionCategory
from ._llm import LLMError, chat, parse_json_object
from ._prompts import load

MODEL = "deepseek-ai/DeepSeek-V3"
SYSTEM_PROMPT = load("planner")

MAX_SUB_QUESTIONS = 4

_VALID_CATEGORIES: frozenset[str] = frozenset(
    {"single", "multi_hop", "cross_source", "conflict", "definition", "cross_reference"}
)


def planner(question: str) -> Plan:
    response = chat(system=SYSTEM_PROMPT, user=question, model=MODEL)
    obj = parse_json_object(response.text)

    raw_subs = obj.get("sub_questions")
    if not isinstance(raw_subs, list) or not raw_subs:
        raise LLMError(f"Planner returned no sub_questions: {obj!r}")

    subs: list[SubQuestion] = []
    for s in raw_subs[:MAX_SUB_QUESTIONS]:
        if not isinstance(s, dict):
            continue
        text = s.get("text")
        category = s.get("category", "single")
        if not isinstance(text, str) or not text.strip():
            continue
        if category not in _VALID_CATEGORIES:
            category = "single"
        subs.append(SubQuestion(text=text.strip(), category=category))  # type: ignore[arg-type]

    if not subs:
        raise LLMError(f"Planner produced no usable sub-questions: {obj!r}")

    # is_compound is True iff there are >1 sub-questions OR the single sub
    # is non-"single" category. The prompt is told this; we enforce here too.
    is_compound = len(subs) > 1 or subs[0].category != "single"
    declared = bool(obj.get("is_compound", is_compound))
    is_compound = declared if len(subs) > 1 else (len(subs) > 1)

    return Plan(sub_questions=tuple(subs), is_compound=is_compound)


__all__ = ["planner", "Plan", "SubQuestion", "SubQuestionCategory", "MAX_SUB_QUESTIONS"]
