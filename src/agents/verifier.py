"""Verifier agent — surfaces conflicts between sources at different
authority tiers (Finlex > Vero) for a draft answer.

Per Step 8 brief (B8.4):
    Triggers when the assembled context contains sources from different
    authority tiers covering the same question.

The orchestrator (not this track) supplies ``authority_rank`` per source
from chunk metadata produced by Step 3. The Verifier MUST treat the rank
as an explicit input — it does not infer authority from text. This is
load-bearing for the L7 conflict-surfacing path described in
``00_overview.md``.

Step 10 / Move 5d also exposes ``check_temporal_mismatches`` — a
deterministic check that compares the LLM's quoted text against the
correct point-in-time version per cited SECTION. Surfaces structured
``TemporalMismatch`` records alongside the LLM-driven verification.
"""

from __future__ import annotations

import json
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from src.models import TemporalMismatch, VersionStep

from . import ClaimResolution, ClaimVerification, VerifyResult, VerifyStatus
from ._llm import LLMError, chat, parse_json_object
from ._prompts import load

MODEL = "deepseek-ai/DeepSeek-V4-Pro"
SYSTEM_PROMPT = load("verifier")

_VALID_RESOLUTIONS: frozenset[str] = frozenset({"ok", "conflict", "unsupported"})
_VALID_STATUSES: frozenset[str] = frozenset({"ok", "conflicts", "unsupported_claims"})

_REQUIRED_SOURCE_FIELDS = ("id", "text", "authority_rank")


def _validate_sources(sources: list[dict[str, Any]]) -> None:
    for i, s in enumerate(sources):
        if not isinstance(s, dict):
            raise ValueError(f"sources[{i}] must be a dict, got {type(s).__name__}")
        for field in _REQUIRED_SOURCE_FIELDS:
            if field not in s:
                raise ValueError(f"sources[{i}] missing required field {field!r}")
        if not isinstance(s["authority_rank"], int):
            raise ValueError(
                f"sources[{i}].authority_rank must be int, got {type(s['authority_rank']).__name__}"
            )


def verifier(answer: str, sources: list[dict[str, Any]]) -> VerifyResult:
    """Verify ``answer`` against ``sources``. ``authority_rank`` per source is mandatory."""

    _validate_sources(sources)

    user_payload = json.dumps(
        {"answer": answer, "sources": sources}, ensure_ascii=False
    )
    response = chat(system=SYSTEM_PROMPT, user=user_payload, model=MODEL)
    obj = parse_json_object(response.text)

    status_raw = obj.get("status", "ok")
    if status_raw not in _VALID_STATUSES:
        status_raw = "ok"
    status: VerifyStatus = status_raw  # type: ignore[assignment]

    raw_claims = obj.get("claims") or []
    if not isinstance(raw_claims, list):
        raise LLMError(f"Verifier returned non-list 'claims': {raw_claims!r}")

    claims: list[ClaimVerification] = []
    for c in raw_claims:
        if not isinstance(c, dict):
            continue
        resolution = c.get("resolution", "ok")
        if resolution not in _VALID_RESOLUTIONS:
            resolution = "ok"
        supporting = tuple(
            str(x) for x in (c.get("supporting_source_ids") or []) if isinstance(x, (str, int))
        )
        contradicting = tuple(
            str(x) for x in (c.get("contradicting_source_ids") or []) if isinstance(x, (str, int))
        )
        prevailing = c.get("prevailing_source_id")
        prevailing_str = str(prevailing) if isinstance(prevailing, (str, int)) else None
        claim_text = c.get("claim", "")
        claims.append(
            ClaimVerification(
                claim=str(claim_text),
                supporting_source_ids=supporting,
                contradicting_source_ids=contradicting,
                resolution=resolution,  # type: ignore[arg-type]
                prevailing_source_id=prevailing_str,
            )
        )

    # Recompute status from claims as a safety net — conflicts dominate unsupported.
    resolutions = {c.resolution for c in claims}
    if "conflict" in resolutions:
        status = "conflicts"
    elif "unsupported" in resolutions:
        status = "unsupported_claims"
    elif claims:
        status = "ok"

    report = obj.get("conflict_report")
    if report is not None and not isinstance(report, str):
        report = str(report)
    if status != "conflicts":
        report = None

    return VerifyResult(status=status, claims=tuple(claims), conflict_report=report)


# --------------------------------------------------------------------------
# Step 10 / Move 5d — TemporalMismatch detector
#
# Deterministic, no LLM. Runs cheaply per cited SECTION whose version
# chain has more than just the original step. The pipeline collects
# results into ``AnswerResult.conflicts`` so the UI can render them
# next to authority conflicts.
#
# Strategy:
#   1. For each cited SECTION with a non-trivial version chain, score
#      the LLM's answer against each VersionStep.text using SequenceMatcher
#      ratio. We use the answer's *full text* rather than slicing into
#      quoted snippets — slicing requires reliable quote detection,
#      which the v1 prompt doesn't enforce.
#   2. Identify the "correct" step: the last applied step in the chain
#      (what ``text_at(as_of_used)`` returns).
#   3. Identify the "best matching" step: the highest-similarity step.
#   4. If best != correct AND the gap is large enough, emit a
#      TemporalMismatch. Threshold tuning is conservative — we'd rather
#      miss than spuriously flag.
#
# The check is deliberately advisory: it doesn't gate generation, doesn't
# trigger a regenerate, doesn't return a "fail". Its output lives in
# ``AnswerResult.conflicts`` for the UI/UX to surface.
# --------------------------------------------------------------------------


# Minimum similarity gain (best vs correct) to flag a mismatch. Below
# this the LLM's text isn't *meaningfully* closer to a historical
# version — it's just generic Finnish legalese matching weakly to
# everything. Tuned by hand against a handful of v2+chain demo runs.
_MISMATCH_GAIN_THRESHOLD = 0.08

# Minimum similarity to *any* step for the check to fire at all. Below
# this, the answer isn't quoting the section's text in any meaningful
# way — likely the LLM paraphrased without quoting, and any
# "best-match" verdict would be noise.
_MIN_BEST_SIMILARITY = 0.20


def _similarity(answer: str, text: str | None) -> float:
    """SequenceMatcher ratio normalised to [0, 1].

    Used pairwise (answer × one step). For long answers we slide a
    window the size of the step text across the answer and take the
    max — that's a cheap proxy for "the answer contains a passage
    similar to this step" without doing full alignment.
    """
    if not text:
        return 0.0
    a = answer.strip()
    b = text.strip()
    if not a or not b:
        return 0.0
    # Cheap shortcut: if the step text is short and appears verbatim
    # in the answer, score 1.0.
    if len(b) <= 200 and b in a:
        return 1.0
    # Otherwise run the matcher on the answer + step text directly. The
    # answer is usually small (~1-3 KB) so this is fine; we don't slice.
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _last_applied_step(chain: list[VersionStep]) -> VersionStep | None:
    """The step ``text_at(as_of_used)`` would return as ``current_text``.

    Walks from end backwards. A trailing ``kumotaan`` (text=None) is
    treated as "no correct version" — we have to handle that explicitly.
    """
    for step in reversed(chain):
        if step.provenance == "kumotaan":
            return None
        if step.text:
            return step
    return None


def check_temporal_mismatches(
    *,
    answer: str,
    cited_sections: list[tuple[str, list[VersionStep]]],
    as_of_used: date,
) -> list[TemporalMismatch]:
    """Return TemporalMismatch records for every cited SECTION whose
    chain suggests the LLM quoted a non-current version.

    ``cited_sections`` is built by the pipeline from
    ``AssembledContext.sources`` — one entry per cited chunk's
    section, paired with that section's already-played version chain.
    Sections with empty/trivial chains are skipped by the caller
    rather than us (keeps this function loop-pure).
    """
    if not answer.strip() or not cited_sections:
        return []

    out: list[TemporalMismatch] = []
    for section_id, chain in cited_sections:
        if not chain or len(chain) < 2:
            continue
        correct = _last_applied_step(chain)
        # Score every step that has text.
        scores: list[tuple[VersionStep, float]] = []
        for step in chain:
            if not step.text:
                continue
            scores.append((step, _similarity(answer, step.text)))
        if not scores:
            continue
        scores.sort(key=lambda t: t[1], reverse=True)
        best_step, best_sim = scores[0]
        if best_sim < _MIN_BEST_SIMILARITY:
            # Answer doesn't quote any version. Likely paraphrased,
            # don't second-guess.
            continue
        # Find correct's similarity.
        correct_sim = 0.0
        for step, sim in scores:
            if correct is not None and step.source_id == correct.source_id and step.provenance == correct.provenance:
                correct_sim = sim
                break
        if best_step is correct:
            continue  # all is well
        gain = best_sim - correct_sim
        if gain < _MISMATCH_GAIN_THRESHOLD:
            continue

        out.append(
            TemporalMismatch(
                cited_section_id=section_id,
                as_of_used=as_of_used,
                correct_version_effective_date=correct.effective_date if correct else None,
                llm_appears_to_quote_version_date=best_step.effective_date,
                similarity_to_correct=correct_sim,
                similarity_to_quoted=best_sim,
            )
        )
    return out


__all__ = [
    "verifier",
    "VerifyResult",
    "ClaimVerification",
    "ClaimResolution",
    "check_temporal_mismatches",
]
