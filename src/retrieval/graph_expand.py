"""Track F — Graph expansion primitives (Step 7, B7.1 + B7.5 + B7.7).

Wraps ``GraphStore`` with strategy-aware BFS:

- Per-strategy edge-type allowlist (no broad "follow everything" mode).
- Per-edge-type degree caps to skip hub nodes during expansion.
- Per-edge-type frontier fairness so a single dominant edge type (notably
  ``applies``-IN on TVL/AVL — see ``findings/07_pilot_results.md``) cannot
  exhaust the node budget before other edge types are explored.
- Auto ``parent_of``-OUT descend when the seed type carries no typed edges
  (SECTION, CHAPTER, GUIDE root, CASE root).
- Returns a ``RetrievalPath`` per discovered node so Layer-8 path-aware
  citations can render *how* a source was reached.

This module does not touch the vector store. Track D supplies seed ids;
this module expands them.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Literal

from src.indexing.graph_store import GraphStore
from src.models import Direction, EdgeType, Node, RetrievalPath


# ---------------------------------------------------------------------------
# ExpansionStrategy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpansionStrategy:
    """One row of ``findings/07_expansion_strategies.md``.

    The strategy router (``src/retrieval/strategy.py``) returns one of these
    per query; ``expand`` consumes it.
    """

    name: str
    seed_k: int
    edge_types: tuple[EdgeType, ...]
    direction: Direction
    max_hops: int
    max_nodes: int
    # Keys are ``"{edge_type}_{direction}"`` matching ``Node.metadata.degree``,
    # e.g. ``"interprets_in"``, ``"applies_in"``, ``"cites_out"``.
    degree_caps: dict[str, int] = field(default_factory=dict)
    # ``(cross_encoder, cosine, metadata)`` — consumed by Track D's reranker.
    rerank_weights: tuple[float, float, float] = (0.6, 0.3, 0.1)


# The seed types that have no outgoing typed edges and therefore need a
# ``parent_of``-OUT descend before BFS starts. Pilot finding: vector seeds
# anchor at SECTION level; typed edges live one structural hop down.
_DESCEND_FROM = {"SECTION", "CHAPTER", "GUIDE", "CASE", "TREATY", "LAW"}
# Note LAW is *not* always descended-from: LAW roots for TVL/AVL receive
# inbound ``interprets`` directly. The descend rule applies only when the
# strategy's edge allowlist excludes inbound edges from the seed type.


def _needs_descend(seed_type: str, strategy: ExpansionStrategy) -> bool:
    """SECTION/CHAPTER/GUIDE/CASE seeds carry only ``parent_of``. If the
    strategy wants any typed edges, descend one ``parent_of``-OUT hop first.
    LAW seeds only descend when the strategy is OUT-only (no inbound walk).
    """
    if seed_type in {"SECTION", "CHAPTER", "GUIDE", "CASE", "TREATY"}:
        return any(e != "parent_of" for e in strategy.edge_types)
    if seed_type == "LAW":
        # LAW receives inbound interprets/applies/cites. Only descend if the
        # strategy is OUT-only — then the seed's outbound edges (which are
        # all parent_of) won't expose typed neighbours, so drill down.
        return strategy.direction == "out" and any(
            e != "parent_of" for e in strategy.edge_types
        )
    return False


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------


def expand(
    seed_ids: Iterable[str],
    strategy: ExpansionStrategy,
    graph_store: GraphStore,
) -> dict[str, RetrievalPath]:
    """Strategy-aware BFS over ``graph_store``.

    Returns ``{node_id: RetrievalPath}`` for every node reached, including the
    seeds themselves (recorded with ``hops=0``). Seeds are scored 1.0; expanded
    nodes are scored by edge ``confidence``.

    The returned set respects ``strategy.max_nodes`` as a hard ceiling.
    Per-edge-type frontier fairness ensures the cap is not consumed by a
    single dominant edge type before other allowed edges are explored.
    """
    seeds = list(seed_ids)
    if not seeds:
        return {}
    if strategy.max_hops <= 0 or not strategy.edge_types:
        return {sid: RetrievalPath(via="graph", score=1.0, hops=0) for sid in seeds}

    results: dict[str, RetrievalPath] = {
        sid: RetrievalPath(via="graph", score=1.0, hops=0) for sid in seeds
    }
    # frontier carries (node_id, hops_already_walked, descended_flag)
    frontier: deque[tuple[str, int, bool]] = deque()
    for sid in seeds:
        node = graph_store.get_node(sid)
        if node is None:
            continue
        if _needs_descend(node.type, strategy):
            # Pre-walk one parent_of-OUT hop. The descend consumes no hop
            # budget — it's structural plumbing to reach the edge-bearing
            # tier (SUBSECTION/ITEM). Children are entered into frontier
            # with hops=0 and descended=True so they don't get re-descended.
            _add_descended_children(sid, graph_store, results, frontier)
        else:
            frontier.append((sid, 0, False))

    # Per-edge-type fairness: no single edge type may consume more than this
    # fraction of the budget. Prevents the pilot's ``applies``-IN flood.
    fairness_cap = max(1, strategy.max_nodes // 2)
    edge_type_counts: dict[str, int] = {}

    while frontier and len(results) < strategy.max_nodes:
        nid, hops, _descended = frontier.popleft()
        if hops >= strategy.max_hops:
            continue

        # Degree-cap gate: skip expansion through hub nodes (per-edge-type).
        # Seeds are always allowed (hops==0 means we are at a seed or a
        # descended child) — only intermediates are gated.
        if hops > 0 and _exceeds_degree_cap(nid, strategy, graph_store):
            continue

        for nbr in graph_store.get_neighbors(
            nid,
            edge_types=list(strategy.edge_types),
            direction=strategy.direction,
        ):
            if nbr.node_id in results:
                continue
            et = nbr.edge.type
            if edge_type_counts.get(et, 0) >= fairness_cap:
                continue
            results[nbr.node_id] = RetrievalPath(
                via="graph",
                score=float(nbr.edge.confidence),
                from_node_id=nid,
                edge_type=et,
                hops=hops + 1,
            )
            edge_type_counts[et] = edge_type_counts.get(et, 0) + 1
            frontier.append((nbr.node_id, hops + 1, False))
            if len(results) >= strategy.max_nodes:
                break

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_descended_children(
    seed_id: str,
    graph_store: GraphStore,
    results: dict[str, RetrievalPath],
    frontier: deque[tuple[str, int, bool]],
) -> None:
    """Pre-walk parent_of-OUT from a seed. Children enter the frontier with
    hops=0 (the descend doesn't count) so they get the full hop budget for
    typed expansion."""
    for nbr in graph_store.get_neighbors(
        seed_id, edge_types=["parent_of"], direction="out"
    ):
        if nbr.node_id in results:
            continue
        # Descended children are still reported but with hops=0 and
        # edge_type=parent_of so the UI can show they were structural.
        results[nbr.node_id] = RetrievalPath(
            via="graph",
            score=1.0,
            from_node_id=seed_id,
            edge_type="parent_of",
            hops=0,
        )
        frontier.append((nbr.node_id, 0, True))


def _exceeds_degree_cap(
    node_id: str, strategy: ExpansionStrategy, graph_store: GraphStore
) -> bool:
    """Return True if any (edge_type, direction) the strategy follows has
    degree above its cap at this node. Skip expansion through hubs."""
    if not strategy.degree_caps:
        return False
    # Map strategy direction onto direction-specific cap keys.
    directions: tuple[Direction, ...]
    if strategy.direction == "both":
        directions = ("in", "out")
    else:
        directions = (strategy.direction,)
    for et in strategy.edge_types:
        for d in directions:
            key = f"{et}_{d}"
            cap = strategy.degree_caps.get(key)
            if cap is None:
                continue
            if graph_store.get_degree(node_id, et, d) > cap:
                return True
    return False


# ---------------------------------------------------------------------------
# Convenience constructor for the default vector-only strategy
# ---------------------------------------------------------------------------


def vector_only_strategy(seed_k: int = 10) -> ExpansionStrategy:
    """The do-nothing strategy: pass seeds through, no graph walk.

    Used by the ``default`` category in ``strategy.py`` and by Track D when
    it wants v2's interface without v2's traversal.
    """
    return ExpansionStrategy(
        name="default",
        seed_k=seed_k,
        edge_types=(),
        direction="both",
        max_hops=0,
        max_nodes=seed_k,
        degree_caps={},
        rerank_weights=(0.6, 0.3, 0.1),
    )
