"""AgentEvent builders — keep the SSE wire format in lockstep with the frontend.

The TypeScript counterpart lives at ``lex-atlas-frontend/lib/types.ts``
(``AgentEvent`` union). Any field renamed or added here must be mirrored
there or the frontend's ``dispatch()`` in ``AnswerStream.tsx`` will silently
drop the event.

Two mappings live in this module:

* ``node_kind_for``  — the SECTION/LAW/GUIDE/CASE/... NodeType plus
  ``source_subcorpus`` collapse into the 11 frontend NodeKinds used to color
  nodes in the constellation/orbit.
* ``authority_rank_for_ui`` — the corpus's authority_rank is 0-100; the
  frontend's ``OrbitNode.authorityRank`` is a 1-8 lattice. We bucket so
  KHO/laki/vero-ohje land on visually distinct tiers without re-tuning.
"""
from __future__ import annotations

from typing import Any, Iterable

from src.indexing.graph_store import GraphStore
from src.models import Node
from src.retrieval.assemble import AssembledContext, Source

# Edge types we surface as orbit arcs.
#
# Goes wider than ``assemble.RENDERED_EDGE_TYPES`` because the orbit is a
# visual graph (so structural ``parent_of`` is signal) where the assembled
# LLM prompt deliberately omits it (would dilute citation accuracy).
#
# The full list of DB-native edge types lives on ``src.models.EdgeType``;
# every entry below has a matching ``RELATION_LABEL`` on the frontend so
# the chip never shows the raw SQL string.
ORBIT_EDGE_TYPES: tuple[str, ...] = (
    "parent_of",
    "cites",
    "interprets",
    "amends",
    "amends_section",
    "repeals",
    "applies",
    "defines",
)

# How many ``parent_of`` arcs we let through per source. The LAW root of
# 1551/1995 has ~100 SECTION children, and if every SECTION the assembler
# brought back also lists a parent_of, the orbit would degenerate into a
# starburst hub. We keep the top ones (sorted by graph_store insertion
# order, which is doc-order) and drop the rest — the inspector still has
# the full graph if the user wants to drill in.
_MAX_PARENT_OF_PER_SOURCE = 2


# ---------------------------------------------------------------------------
# kind / authority mapping
# ---------------------------------------------------------------------------


def node_kind_for(node_type: str | None, source_subcorpus: str | None) -> str:
    """Map (NodeType, SourceSubcorpus) → frontend NodeKind.

    Subcorpus wins when present — a SECTION inside a KHO ruling should
    paint as a "case" node, not a "ctv". Falls through to ``work`` when
    everything is unknown so the UI always has a renderable color.
    """
    sub = (source_subcorpus or "").lower()
    if sub == "kho":
        return "case"
    if sub.startswith("vero_"):
        return "guidance"
    if sub == "treaty":
        return "work"

    nt = (node_type or "").upper()
    if nt == "LAW":
        return "work"
    if nt in {"SECTION", "SUBSECTION", "ITEM", "DEFINITION"}:
        return "ctv"
    if nt == "CHAPTER":
        return "component"
    if nt == "AMENDMENT_BLOCK":
        return "action"
    if nt == "GUIDE":
        return "guidance"
    if nt == "CASE":
        return "case"
    if nt == "TREATY":
        return "work"
    return "work"


def authority_rank_for_ui(rank: int | None) -> int:
    """Bucket corpus authority_rank (0-100) into the UI lattice (1-8).

    The corpus ranks roughly: laki=80, asetus=60, KHO=70, vero_ohje=40,
    vero_kannanotto=30, vero_paatos=50. The 1-8 lattice is what the
    OrbitGraph reads for the priority halo.
    """
    if rank is None:
        return 4
    # Map 0..100 -> 1..8, clamp.
    bucket = int(round(rank / 12.5)) + 1
    return max(1, min(8, bucket))


# ---------------------------------------------------------------------------
# Source → OrbitNode / OrbitEdge
# ---------------------------------------------------------------------------


def _short_label(
    section_id: str,
    title: str | None,
    node_label: str | None,
    *,
    root_title: str | None = None,
) -> str:
    """Build a single-line label for the orbit chip.

    Composition (richest first, fall back as fields disappear):

        "<label> · <title>"             — both present (e.g. "§ 3 · ...")
        "<label> · <root_title>"        — section label inside a parent law (e.g.
                                          "1.3 · Avainhenkilölaki") — keeps the
                                          chip context-rich for deeply nested
                                          Vero/Finlex sections that otherwise
                                          render as bare numbers
        "<title>"                       — root or guidance with title only
        "<label>"                       — last resort before id sniffing
        "<id_tail>"                     — pulled from the section_id
    """
    title = (title or "").strip()
    node_label = (node_label or "").strip()
    root_title = (root_title or "").strip()

    if node_label and title:
        return f"{node_label} · {title}"
    if node_label and root_title:
        return f"{node_label} · {root_title}"
    if title:
        return title
    if root_title:
        return root_title
    if node_label:
        return node_label
    tail = section_id.split("/")[-1]
    return tail or section_id


def _resolve_root_title(graph: GraphStore, node: Node | None) -> str | None:
    """Walk up the parent_id chain to find the root LAW/GUIDE/CASE title.

    Stops at the first ancestor with a title set, or when ``parent_id`` is
    None (root reached). Bounded at 8 hops so a malformed graph can't loop.
    """
    if node is None:
        return None
    if getattr(node, "title", None):
        return node.title
    parent_id = node.parent_id
    seen: set[str] = set()
    for _ in range(8):
        if not parent_id or parent_id in seen:
            return None
        seen.add(parent_id)
        parent = graph.get_node(parent_id)
        if parent is None:
            return None
        if getattr(parent, "title", None):
            return parent.title
        parent_id = parent.parent_id
    return None


def build_orbit(
    context: AssembledContext,
    *,
    graph: GraphStore,
    cited_chunk_ids: Iterable[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Source]]:
    """Render the assembled context as the orbit payload.

    Returns (orbit_nodes, orbit_edges, source_by_chunk_id). The third value is
    a small index callers reuse for citation rewriting.

    A source is marked ``isCenter=True`` when it tops the rerank list — that
    becomes the centerpiece of the OrbitGraph. Anything in ``cited_chunk_ids``
    is also marked active so the answer's cited sources sit at the front of
    the visual stack.
    """
    cited = set(cited_chunk_ids)
    nodes: list[dict[str, Any]] = []
    section_to_chunk: dict[str, str] = {}
    source_by_chunk: dict[str, Source] = {}

    for i, src in enumerate(context.sources):
        source_by_chunk[src.chunk_id] = src
        section_to_chunk[src.section_id] = src.chunk_id

        # Look up the section node for title/label/kind.
        node: Node | None = graph.get_node(src.section_id)
        title = getattr(node, "title", None) if node else None
        label_field = getattr(node, "label", None) if node else None
        node_type = node.type if node else None
        root_title = _resolve_root_title(graph, node) if node else None

        # Pull subcorpus + flags off the chunk header that the rerank step
        # already stashed onto the Source's rendered_block — but we have it
        # via the corpus metadata too. Cheapest read: hit the graph node.
        meta = node.metadata if node else None
        in_force = bool(getattr(meta, "in_force", None)) if meta else True
        authority_rank = getattr(meta, "authority_rank", None) if meta else None
        source_field = getattr(node, "source", None) if node else None
        # source_subcorpus isn't reliably round-tripped through the graph
        # store (it's "laki" by default there). Sniff the chunk id when
        # the graph node didn't carry one.
        subcorpus = _sniff_subcorpus(src.chunk_id, source_field)

        nodes.append(
            {
                "id": src.chunk_id,
                "kind": node_kind_for(node_type, subcorpus),
                "label": _short_label(
                    src.section_id, title, label_field, root_title=root_title
                ),
                "authorityRank": authority_rank_for_ui(authority_rank),
                "isActive": in_force is not False,
                "isCenter": i == 0,
                "tValid": (
                    meta.publication_date.isoformat()
                    if meta and getattr(meta, "publication_date", None)
                    else None
                ),
                "tInvalid": (
                    meta.repeal_date.isoformat()
                    if meta and getattr(meta, "repeal_date", None)
                    else None
                ),
                "isConflicted": False,
                # Internal: not consumed by the UI but kept so callers can
                # cross-reference back to the section without re-parsing.
                "_sectionId": src.section_id,
                "_isCited": src.chunk_id in cited,
            }
        )

    # Edges between assembled sources — wider type set than the LLM prompt
    # uses (see ORBIT_EDGE_TYPES comment).
    edges: list[dict[str, Any]] = []
    seen_edge: set[tuple[str, str, str]] = set()
    for src in context.sources:
        neighbors = graph.get_neighbors(
            src.section_id,
            edge_types=list(ORBIT_EDGE_TYPES),
            direction="both",
        )
        parent_of_left = _MAX_PARENT_OF_PER_SOURCE
        for nbr in neighbors:
            target_chunk = section_to_chunk.get(nbr.node_id)
            if target_chunk is None or target_chunk == src.chunk_id:
                continue
            etype = nbr.edge.type
            if etype == "parent_of":
                if parent_of_left <= 0:
                    continue
                parent_of_left -= 1
            outgoing = nbr.direction == "out"
            a, b = (src.chunk_id, target_chunk) if outgoing else (target_chunk, src.chunk_id)
            key = (a, b, etype)
            if key in seen_edge:
                continue
            seen_edge.add(key)
            edges.append({"source": a, "target": b, "relation": etype})

    return nodes, edges, source_by_chunk


def _sniff_subcorpus(chunk_id: str, source_field: str | None) -> str | None:
    """Infer the source_subcorpus from a chunk_id when the graph node lacks it.

    Our chunk_ids look like ``finlex/kho/...`` or ``vero/vero_ohje/...`` —
    the second path segment is the subcorpus.
    """
    parts = chunk_id.split("/")
    if len(parts) >= 2:
        return parts[1]
    return source_field


# ---------------------------------------------------------------------------
# Citation rewriting — [Source N] → [cite:node:<chunk_id>]Source N[/cite]
# ---------------------------------------------------------------------------


import re

_LLM_CITE_RE = re.compile(r"\[\s*source\s+(\d+)\b[^\]]*\]", re.IGNORECASE)


def rewrite_citations(answer: str, context: AssembledContext) -> str:
    """Replace ``[Source N]`` tokens with the frontend's cite markup.

    The AnswerStream renderer in ``components/AnswerStream.tsx`` looks for
    ``[cite:node:<id>]<label>[/cite]`` and turns the label into a hoverable
    underline. Anything we can't resolve we leave alone (the UI tolerates
    bare ``[Source N]`` as literal text).
    """
    def _sub(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        cid = context.chunk_id_for_label(f"[Source {idx}]")
        if cid is None:
            return m.group(0)
        return f"[cite:node:{cid}]Source {idx}[/cite]"

    return _LLM_CITE_RE.sub(_sub, answer)


# ---------------------------------------------------------------------------
# Cost estimate — DeepSeek V4 Pro
# ---------------------------------------------------------------------------

# Published DeepSeek V4 Pro pricing (USD per 1 million tokens).
# Cache-hit pricing is wildly cheaper but we don't yet pass the cache
# flag back from generate(), so the meter assumes cache-miss to stay
# conservative for the live cost display.
_DEEPSEEK_V4_PRO_INPUT_USD_PER_MTOK_MISS = 0.435
_DEEPSEEK_V4_PRO_INPUT_USD_PER_MTOK_HIT = 0.003625
_DEEPSEEK_V4_PRO_OUTPUT_USD_PER_MTOK = 0.87

# Chars-per-token heuristic. English averages ~4, Finnish closer to ~3
# because of agglutinative morphology; we land in the middle so the
# estimate doesn't lie either way. Coarse — fine for a meter, not for
# billing reconciliation.
_CHARS_PER_TOKEN = 3.8

# A typical empty-prompt overhead (system prompt + USER_PROMPT_TEMPLATE
# scaffolding + role tokens). We snapshot the system prompt length once
# at import time so the cost meter doesn't dip into the LLM module on
# every call. ``src.retrieval.generate.SYSTEM_PROMPT`` is currently ~1.9k
# chars — well under the few-token noise floor of the estimate anyway.
try:
    from src.retrieval.generate import SYSTEM_PROMPT as _SYSTEM_PROMPT
    _SYSTEM_PROMPT_CHARS = len(_SYSTEM_PROMPT)
except Exception:  # pragma: no cover — generate.py shouldn't fail to import
    _SYSTEM_PROMPT_CHARS = 1900

_USER_TEMPLATE_OVERHEAD_CHARS = 32  # "Question: ...\n\nSources:\n...\n\nAnswer:"


def estimate_cost_cents(
    answer: str,
    context: AssembledContext,
    *,
    question: str = "",
    cache_hit: bool = False,
) -> float:
    """Return the rough USD-cents cost of one DeepSeek V4 Pro generation.

    Counts the characters the model actually saw (system prompt + user
    template + question + assembled context) plus the characters of the
    streamed answer, divides by ``_CHARS_PER_TOKEN`` to get a token
    estimate, then applies the DeepSeek V4 Pro pricing the user supplied:

        $0.003625 / 1M input tokens (cache hit)
        $0.435    / 1M input tokens (cache miss)   ← default
        $0.870    / 1M output tokens

    Result is shown on the UI cost meter; not billing-grade.
    """
    in_chars = (
        _SYSTEM_PROMPT_CHARS
        + _USER_TEMPLATE_OVERHEAD_CHARS
        + len(question or "")
        + len(context.text)
    )
    out_chars = len(answer)
    in_tokens = in_chars / _CHARS_PER_TOKEN
    out_tokens = out_chars / _CHARS_PER_TOKEN
    in_price = (
        _DEEPSEEK_V4_PRO_INPUT_USD_PER_MTOK_HIT
        if cache_hit
        else _DEEPSEEK_V4_PRO_INPUT_USD_PER_MTOK_MISS
    )
    usd = (
        in_tokens * in_price / 1_000_000
        + out_tokens * _DEEPSEEK_V4_PRO_OUTPUT_USD_PER_MTOK / 1_000_000
    )
    return round(usd * 100, 4)
