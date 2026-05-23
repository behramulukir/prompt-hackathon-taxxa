"""Builds the cinematic HTML for a given AnswerResult.

The template at web/cinematic_template.html is data-driven: it expects a
PAYLOAD object containing the result, the source metadata, and a timeline of
animation events. This module assembles that payload from the canonical
choreography table in our-docs/hybrid_cinematic_concept.md, conditioned on
which AnswerResult variant we received.

Variant handling (the core job of this module):
- assumptions == []        → skip Clarifier row
- single source            → skip Planner row, shorten Retriever phase
- no graph-via paths       → skip Extractor row (no edge write-back to animate)
- conflicts == []          → skip Verifier row
- no cited chunks at all   → minimal "no sources found" timeline
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import AnswerResult
from web.data import source_meta

_TEMPLATE_PATH = Path(__file__).parent / "cinematic_template.html"


def _has_graph_hops(result: AnswerResult) -> bool:
    return any(p.hops >= 1 for p in result.retrieval_paths.values())


def _sources_for_result(result: AnswerResult) -> dict[str, dict[str, Any]]:
    """Map every chunk_id touched by the result to its SourceMeta entry."""
    ids = set(result.retrieved_chunks) | set(result.cited_source_ids)
    for c in result.conflicts:
        ids.update(c.get("sources") or [])
    out: dict[str, dict[str, Any]] = {}
    for cid in ids:
        out[cid] = dict(source_meta.lookup(cid))
    return out


def _build_timeline(result: AnswerResult) -> list[dict[str, Any]]:
    """Translate an AnswerResult into a sequence of animation events.

    Times are relative to t=0 (when the user submits). The schedule mirrors
    hybrid_cinematic_concept.md but elides phases the result can't support.
    """
    events: list[dict[str, Any]] = []
    has_assumptions = bool(result.assumptions)
    has_conflicts   = bool(result.conflicts)
    has_graph       = _has_graph_hops(result)
    cited           = result.cited_source_ids
    paths           = result.retrieval_paths
    seeds = [cid for cid, p in paths.items() if p.via == "vector"]
    grafts = [(cid, p) for cid, p in paths.items() if p.via == "graph"]

    if not paths:
        # Truly empty — show a one-shot strategy badge and nothing else.
        events.append({"t": 0.2, "action": "strategy_set", "cls": "empty", "text": "No retrieval"})
        return events

    # --- Strategy routing badge ---
    t_routing_done = 2.3
    events.append({
        "t": 0.2, "action": "strategy_set", "cls": "routing", "text": "Routing…",
    })
    final_badge_cls = "single" if (len(cited) <= 1 and not has_graph) else "multi-hop"
    final_badge_text = "Single-hop" if final_badge_cls == "single" else "Multi-hop"

    # --- Clarifier ---
    cursor = 0.5
    if has_assumptions:
        first_assumption = result.assumptions[0]
        # Trim to a punchy summary if it's long
        if len(first_assumption) > 80:
            first_assumption = first_assumption[:80].rsplit(" ", 1)[0] + "…"
        events.append({
            "t": cursor, "action": "agent_start", "id": "clarifier",
            "text": "Scanning question for missing dimensions…",
        })
        events.append({"t": cursor + 0.05, "action": "bump_llm_calls", "delta": 1})
        events.append({
            "t": cursor + 0.6, "action": "agent_complete", "id": "clarifier",
            "text": f"Assumed: {first_assumption}",
        })
        cursor += 0.8

    # --- Planner (only when multi-source / has graph hops) ---
    if has_graph or len(cited) > 1:
        events.append({
            "t": cursor, "action": "agent_start", "id": "planner",
            "text": "Decomposing into sub-questions…",
        })
        events.append({"t": cursor + 0.05, "action": "bump_llm_calls", "delta": 1})
        n_subq = min(3, max(2, len(cited)))
        events.append({
            "t": cursor + 0.8, "action": "agent_complete", "id": "planner",
            "text": f"Split into {n_subq} sub-questions.",
        })
        cursor += 1.0

    # --- Strategy badge flips to final value ---
    events.append({
        "t": min(cursor, t_routing_done),
        "action": "strategy_set", "cls": final_badge_cls, "text": final_badge_text,
    })

    # --- Retriever: nodes appear in sequence, then edges ---
    events.append({
        "t": cursor, "action": "agent_start", "id": "retriever",
        "text": "Vector search + graph walk in progress…",
    })

    # Seeds first (vector hits), pulsing
    seed_appear_t = cursor + 0.25
    for i, sid in enumerate(seeds):
        events.append({
            "t": seed_appear_t + i * 0.25, "action": "show_node",
            "chunk_id": sid, "pulse": True,
        })
    # Graph expansions next — interleave node + edge so the line draws to a visible target
    exp_appear_t = seed_appear_t + max(0.5, len(seeds) * 0.25)
    for i, (cid, p) in enumerate(grafts):
        t = exp_appear_t + i * 0.35
        events.append({"t": t, "action": "show_node", "chunk_id": cid})
        events.append({"t": t + 0.08, "action": "show_edge", "chunk_id": cid})

    retriever_end_t = exp_appear_t + max(0.7, len(grafts) * 0.35) + 0.3
    edge_summary = "no expansion"
    if has_graph:
        # Distinct edge-type list for the summary text
        ets = sorted({(p.edge_type or "—") for _, p in grafts if p.edge_type})
        edge_summary = "walked " + ", ".join(ets) if ets else "expanded"
    n_seeds = len(seeds)
    events.append({
        "t": retriever_end_t, "action": "agent_complete", "id": "retriever",
        "text": f"Vector hit on {n_seeds} seed(s); {edge_summary}.",
    })
    cursor = retriever_end_t + 0.1

    # --- Extractor: edge write-back (only when graph hops occurred) ---
    if has_graph:
        # Pick a representative edge to display in the write-back card
        rep = next(iter(grafts))
        rep_target_id, rep_path = rep
        rep_src = rep_path.from_node_id or (seeds[0] if seeds else "?")
        write_card = (
            '<div class="edge-write">'
            + _shorten(rep_src, 30)
            + ' <span style="color: var(--muted);">—'
            + (rep_path.edge_type or "cites")
            + '→</span> '
            + _shorten(rep_target_id, 30)
            + '</div>'
        )
        events.append({
            "t": cursor, "action": "agent_start", "id": "extractor",
            "text": "Extracting new citation edge from retrieved chunk…",
        })
        events.append({"t": cursor + 0.05, "action": "bump_llm_calls", "delta": 1})
        events.append({
            "t": cursor + 0.7, "action": "agent_complete", "id": "extractor",
            "text": "Wrote edge back to graph (1 new edge):",
            "append_html": write_card,
        })
        events.append({"t": cursor + 0.75, "action": "reveal_edge_write", "id": "extractor"})
        events.append({"t": cursor + 0.75, "action": "bump_edges_added"})
        cursor += 1.0

    # --- Verifier: only if a conflict was surfaced ---
    if has_conflicts:
        c = result.conflicts[0]
        # Build a short conflict description for the timeline row
        resolution = c.get("resolution") or "Higher authority rank prevails."
        if len(resolution) > 90:
            resolution = resolution[:88].rsplit(" ", 1)[0] + "…"
        topic = c.get("topic") or "Authority divergence"
        mini = (
            '<div class="conflict-mini">'
            '<strong>Conflict:</strong> ' + _esc(topic) + '<br>'
            + _esc(resolution)
            + '</div>'
        )
        events.append({
            "t": cursor, "action": "agent_start", "id": "verifier",
            "text": "Cross-checking sources at different authority ranks…",
        })
        events.append({"t": cursor + 0.05, "action": "bump_llm_calls", "delta": 1})
        events.append({"t": cursor + 0.3, "action": "show_conflict_edge"})
        events.append({
            "t": cursor + 0.9, "action": "agent_complete", "id": "verifier",
            "text": "Conflict surfaced.",
            "append_html": mini,
        })
        events.append({"t": cursor + 0.95, "action": "reveal_conflict_mini", "id": "verifier"})
        events.append({"t": cursor + 0.95, "action": "bump_conflicts"})
        cursor += 1.1

    events.append({"t": cursor + 0.2, "action": "bump_llm_calls", "delta": 1})  # final synth call

    # Always sort by time so the JS consumer doesn't have to.
    events.sort(key=lambda e: e["t"])
    return events


def _shorten(chunk_id: str, max_chars: int) -> str:
    m = source_meta.lookup(chunk_id)
    label = m.get("label") or chunk_id.split("/")[-1]
    if len(label) > max_chars:
        return label[: max_chars - 1] + "…"
    return label


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _final_time_ms(result: AnswerResult) -> int:
    """The 'wall-clock' time displayed on the budget cell at the end.

    Sum of timing_ms if present; otherwise 3400 (the demo placeholder).
    """
    if result.timing_ms:
        return sum(result.timing_ms.values())
    return 3400


def render_html(result: AnswerResult) -> str:
    """Return the full HTML string ready for st.components.v1.html."""
    payload = {
        "result": {
            "question": result.question,
            "answer": result.answer,
            "cited_source_ids": result.cited_source_ids,
            "retrieved_chunks": result.retrieved_chunks,
            "retrieval_paths": {
                cid: {
                    "via": p.via,
                    "score": p.score,
                    "from_node_id": p.from_node_id,
                    "edge_type": p.edge_type,
                    "hops": p.hops,
                }
                for cid, p in result.retrieval_paths.items()
            },
            "conflicts": result.conflicts,
            "assumptions": result.assumptions,
            "timing_ms": result.timing_ms,
        },
        "sources": _sources_for_result(result),
        "timeline": _build_timeline(result),
        "config": {"finalTimeMs": _final_time_ms(result)},
    }

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    # Sentinel is intentionally distinctive so str.replace can't accidentally
    # match a literal string anywhere else in the template (e.g. a guard
    # clause in the JS that compares against the placeholder).
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", r"<\/")
    return template.replace("__CINEMATIC_PAYLOAD_SENTINEL__", payload_json)
