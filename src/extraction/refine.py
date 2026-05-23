"""B2.5 — Edge type refinement.

All extractors default to `cites`. This module promotes the generic edge
type to the most specific one supported by `EdgeType` based on:

    - source node's `source` / `source_subcorpus`
    - target node's `source` (None if dangling)
    - keyword markers in the surrounding `context_snippet`

Run *before* resolution so the type travels with the edge through dangling
recording (we want "this Vero guidance *interprets* this Finlex section"
even if Finlex hasn't loaded yet).
"""
from __future__ import annotations

from src.extraction.node_index import NodeRecord
from src.models import Edge, EdgeType


_AMEND_MARKERS = ("muutettu lailla", "muutetaan lailla", "muutetaan")
_REPEAL_MARKERS = ("kumottu lailla", "kumotaan lailla", "kumotaan")


def refine_edge_type(
    edge: Edge,
    source_node: NodeRecord,
    target_node: NodeRecord | None,
) -> EdgeType:
    snippet = (edge.context_snippet or "").lower()

    # Structural and definition edges keep their original type.
    if edge.type in ("parent_of", "defines"):
        return edge.type

    src = source_node.source
    src_sub = source_node.source_subcorpus

    # Statute chronology — keyword-driven, source/target need both be Finlex.
    if any(m in snippet for m in _AMEND_MARKERS) and (
        src == "finlex" and (target_node is None or target_node.source == "finlex")
    ):
        return "amends"
    if any(m in snippet for m in _REPEAL_MARKERS) and (
        src == "finlex" and (target_node is None or target_node.source == "finlex")
    ):
        return "repeals"

    # Cross-source relationships.
    if target_node is not None:
        if src == "vero" and target_node.source == "finlex":
            return "interprets"
        if src_sub == "kho" and target_node.source == "finlex":
            return "applies"

    # EU directive — kept as "transposes" even though the target dangles.
    # The dangling target_ref pattern is `NNNN/NNN/EY` or `/EU`.
    target_ref = edge.target_ref or ""
    if target_ref.upper().endswith(("/EY", "/EU", "/ETY")):
        return "transposes"

    return "cites"
