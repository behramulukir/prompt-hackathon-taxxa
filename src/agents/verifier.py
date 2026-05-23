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
"""

from __future__ import annotations

import json
from typing import Any

from . import ClaimResolution, ClaimVerification, VerifyResult, VerifyStatus
from ._llm import LLMError, chat, parse_json_object
from ._prompts import load

MODEL = "deepseek-ai/DeepSeek-V3"
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


__all__ = ["verifier", "VerifyResult", "ClaimVerification", "ClaimResolution"]
