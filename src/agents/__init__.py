"""Track H — Agent layer.

Four standalone agents (Clarifier, Planner, Verifier, Extractor) plus their
result types. Agents are pure callables: synchronous, no shared state, no
retrieval-pipeline coupling. They are wired together later by the
orchestrator (Convergence step 2, not this track).

Result types live here because ``src/models.py`` is the locked schema
contract for Steps 1–4 and must not absorb agent-layer types. If a result
type ever needs to cross the agent boundary into ``AnswerResult``, the
orchestrator converts it to the loose ``conflicts: list[dict]`` /
``assumptions: list[str]`` shape that ``AnswerResult`` already defines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# --------------------------------------------------------------------------
# Clarifier
# --------------------------------------------------------------------------

MissingDimension = Literal["year", "entity_type", "jurisdiction"]


@dataclass(frozen=True)
class ClarifyResult:
    """Output of the Clarifier agent.

    ``clarified=True`` means the orchestrator can proceed: either nothing was
    missing, or sensible defaults were chosen (and recorded in ``assumptions``
    so the final answer can surface them).

    ``clarified=False`` means a dimension is missing and no safe default
    exists (interactive flow → ask back to the user).
    """

    clarified: bool
    missing: tuple[MissingDimension, ...]
    assumptions: dict[str, str]
    normalized_question: str


# --------------------------------------------------------------------------
# Planner
# --------------------------------------------------------------------------

SubQuestionCategory = Literal[
    "single",
    "multi_hop",
    "cross_source",
    "conflict",
    "definition",
    "cross_reference",
]


@dataclass(frozen=True)
class SubQuestion:
    text: str
    category: SubQuestionCategory


@dataclass(frozen=True)
class Plan:
    """Output of the Planner agent.

    ``is_compound=False`` and ``len(sub_questions)==1`` is the pass-through
    case — the question is atomic and v2 should answer it directly.
    Otherwise each sub-question is fed independently through ``answer_v2``
    and the orchestrator synthesises a combined answer.
    """

    sub_questions: tuple[SubQuestion, ...]
    is_compound: bool


# --------------------------------------------------------------------------
# Verifier
# --------------------------------------------------------------------------

VerifyStatus = Literal["ok", "conflicts", "unsupported_claims"]
ClaimResolution = Literal["ok", "conflict", "unsupported"]


@dataclass(frozen=True)
class ClaimVerification:
    claim: str
    supporting_source_ids: tuple[str, ...]
    contradicting_source_ids: tuple[str, ...]
    resolution: ClaimResolution
    prevailing_source_id: str | None  # set iff resolution == "conflict"


@dataclass(frozen=True)
class VerifyResult:
    """Output of the Verifier agent.

    The orchestrator feeds ``conflict_report`` back to the generator for one
    regenerate-with-acknowledgment pass (per Step 8 plan, max one revision).
    """

    status: VerifyStatus
    claims: tuple[ClaimVerification, ...]
    conflict_report: str | None = None


# --------------------------------------------------------------------------
# Extractor
# --------------------------------------------------------------------------
#
# The Extractor returns ``list[models.Edge]`` directly — no wrapper type.
# Every extracted edge is dangling (``target_id=None``,
# ``dangling_reason="not_yet_parsed"``) because the on-demand extractor runs
# on retrieved chunks at query time, with no node-resolution context. Step
# 2's resolver picks them up when they're written back to ``edges.jsonl``.


__all__ = [
    "ClarifyResult",
    "MissingDimension",
    "Plan",
    "SubQuestion",
    "SubQuestionCategory",
    "ClaimVerification",
    "VerifyResult",
    "VerifyStatus",
    "ClaimResolution",
]
