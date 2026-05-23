"""Extractor agent — query-time citation extraction.

Per Step 8 brief (B8.3):
    Triggers when a retrieved chunk contains citation-like phrasing that
    Step 2's extraction missed. The newly extracted edges are walked
    immediately and written back to data/edges.jsonl for future queries.

Every emitted edge is dangling (``target_id=None``,
``dangling_reason="not_yet_parsed"``). The Step 2 resolver picks them up.
"""

from __future__ import annotations

import json
from typing import Any

from src.models import Edge

from ._llm import LLMError, chat, parse_json_object
from ._prompts import load

MODEL = "deepseek-ai/DeepSeek-V3"
SYSTEM_PROMPT = load("extractor")

_VALID_EDGE_TYPES: frozenset[str] = frozenset(
    {"cites", "interprets", "amends", "repeals", "defines", "transposes", "applies"}
)


def extractor(text: str, source_node_meta: dict[str, Any]) -> list[Edge]:
    """Extract typed edges from ``text``.

    ``source_node_meta`` must contain at least ``node_id`` (used as
    ``Edge.source_id``). Convention for the orchestrator:

        {
            "node_id": str,             # required
            "source": "finlex"|"vero",  # hints type selection (e.g. interprets)
            "source_subcorpus": str,    # optional
        }
    """

    source_id = source_node_meta.get("node_id")
    if not source_id or not isinstance(source_id, str):
        raise ValueError("source_node_meta['node_id'] is required and must be a string")

    user_payload = json.dumps(
        {"text": text, "source_node_meta": source_node_meta}, ensure_ascii=False
    )
    response = chat(system=SYSTEM_PROMPT, user=user_payload, model=MODEL)
    obj = parse_json_object(response.text)

    raw_edges = obj.get("edges") or []
    if not isinstance(raw_edges, list):
        raise LLMError(f"Extractor returned non-list 'edges': {raw_edges!r}")

    edges: list[Edge] = []
    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        edge_type = raw.get("type")
        if edge_type not in _VALID_EDGE_TYPES:
            continue
        target_ref = raw.get("target_ref")
        if not isinstance(target_ref, str) or not target_ref.strip():
            continue
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        context_snippet = raw.get("context_snippet")
        if context_snippet is not None and not isinstance(context_snippet, str):
            context_snippet = None

        try:
            edge = Edge(
                source_id=source_id,
                target_id=None,
                target_ref=target_ref.strip(),
                type=edge_type,  # type: ignore[arg-type]
                confidence=confidence,
                extracted_by="llm",
                context_snippet=context_snippet,
                dangling_reason="not_yet_parsed",
                properties={},
            )
        except Exception:
            # Pydantic validation failure (e.g. confidence out of range after
            # coercion, or invalid literal). Drop this edge — don't poison
            # the batch.
            continue
        edges.append(edge)

    return edges


__all__ = ["extractor"]
