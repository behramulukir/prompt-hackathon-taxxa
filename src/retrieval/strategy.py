"""Track F — Expansion-strategy router (Step 7, B7.2).

Maps a Finnish/English query to one of the strategies in
``findings/07_expansion_strategies.md``. Deterministic keyword/regex
routing — LLM-based planning is deferred to Step 8 (Planner agent) so
v2's improvements are attributable to the graph, not to the planner.

Routing is intentionally conservative. ``default`` (vector-only) is the
fallback whenever no category fires strongly — the pilot showed graph
expansion adds noise more often than signal on the current corpus, so
the burden of proof is on the classifier to commit to expansion.
"""
from __future__ import annotations

import re

from src.retrieval.graph_expand import ExpansionStrategy, vector_only_strategy


# ---------------------------------------------------------------------------
# Strategy presets — one per row in findings/07_expansion_strategies.md
# ---------------------------------------------------------------------------


MULTI_HOP = ExpansionStrategy(
    name="multi_hop",
    seed_k=10,
    edge_types=("parent_of", "cites"),
    direction="out",
    max_hops=2,
    max_nodes=40,
    degree_caps={"cites_out": 15, "parent_of_in": 50},
)

CROSS_SOURCE = ExpansionStrategy(
    name="cross_source",
    seed_k=10,
    edge_types=("interprets", "parent_of"),
    direction="both",
    max_hops=2,
    max_nodes=40,
    degree_caps={"interprets_in": 30},
)

CASE_LAW = ExpansionStrategy(
    name="case_law",
    seed_k=10,
    edge_types=("applies", "interprets"),
    direction="both",
    max_hops=1,
    max_nodes=30,
    # applies_in cap added per pilot finding (findings/07_pilot_results.md).
    # Without this, BFS exhausts on KHO/KVL case subsections before reaching
    # guidance.
    degree_caps={"applies_in": 25},
)

DEFINITION = ExpansionStrategy(
    name="definition",
    seed_k=10,
    edge_types=("defines", "parent_of"),
    direction="both",
    max_hops=1,
    max_nodes=20,
    degree_caps={"defines_out": 100},
)

RECENCY = ExpansionStrategy(
    name="recency",
    seed_k=10,
    edge_types=("amends", "repeals", "parent_of"),
    direction="both",
    max_hops=1,
    max_nodes=15,
    degree_caps={},
    # Bias toward metadata (effective_date / repeal_date) for recency.
    rerank_weights=(0.5, 0.2, 0.3),
)

DEFAULT = vector_only_strategy(seed_k=10)


# ---------------------------------------------------------------------------
# Keyword triggers (Finnish + English where natural)
# ---------------------------------------------------------------------------


_MULTI_HOP_PAT = re.compile(
    r"\b(poikkeus(?:el+isesti)?|exception|kuitenkin|mutta\s+jos|however|unless|"
    r"silloin\s+kun|sikäli\s+kuin)\b",
    re.IGNORECASE,
)

# A Finlex citation marker. Triggers cross_source only when paired with a
# guidance marker — see _is_cross_source.
_FINLEX_CITE_PAT = re.compile(
    r"\b(TVL|AVL|EVL|PerVL|MVL|EPL|OVML|VML|§|momentt|momentit|kohta\s*[a-z]|"
    r"tuloverolaki|arvonlisäverolaki|verotusmenettely)\b",
    re.IGNORECASE,
)

_GUIDANCE_PAT = re.compile(
    r"\b(vero(?:\s|hallinto|n\.fi)|kannanotto|kannanottoja|"
    r"syvent[äa]v[äa]\s+(?:vero-?)?ohje|ohje(?:ssa|en|et)?|"
    r"verohallinnon\s+p[äa][äa]t[öo]s|guidance|guide)\b",
    re.IGNORECASE,
)

_CASE_LAW_PAT = re.compile(
    r"\b(KHO|KVL|tapaus|oikeustapaus|ratkaisu|ennakkoratkaisu|ennakkop[äa][äa]t[öo]s|"
    r"case\s*law|precedent|prejudikaatti)\b",
    re.IGNORECASE,
)

_DEFINITION_PAT = re.compile(
    r"\b(m[äa][äa]ritelm[äa]|tarkoit(?:taa|etaan|tava)|"
    r"definition|defined\s+as|means\s+that|by\s+\"|k[äa]sit(?:e|teel)|"
    r"luokitellaan|katsotaan)\b",
    re.IGNORECASE,
)

_RECENCY_PAT = re.compile(
    r"\b(voimassa|kumott[uo]|nykyinen|current|repealed|superseded|"
    r"in\s+force|aiemm(?:in|alla)|ennen\s+\d{4}|vuosina?\s+\d{4})\b",
    re.IGNORECASE,
)


def _is_cross_source(query: str) -> bool:
    """Cross-source fires only when the query references *both* a Finlex
    citation form AND a guidance marker. Either alone is too broad."""
    return bool(_FINLEX_CITE_PAT.search(query)) and bool(_GUIDANCE_PAT.search(query))


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def pick_strategy(query: str) -> ExpansionStrategy:
    """Map a query to an ``ExpansionStrategy``.

    Routing priority (first match wins):

    1. ``case_law`` — explicit case-law markers (KHO / KVL / "tapaus").
    2. ``recency`` — explicit recency markers ("voimassa", "kumottu", "current").
    3. ``definition`` — explicit definition markers ("määritelmä", "tarkoittaa").
    4. ``cross_source`` — Finlex citation + guidance marker co-occur.
    5. ``multi_hop`` — exception / condition-chain markers.
    6. ``default`` — vector-only.

    The priority order favors precision (specific markers) over recall.
    When in doubt, the default strategy means v2 degrades to v1 — no
    regression risk.
    """
    if _CASE_LAW_PAT.search(query):
        return CASE_LAW
    if _RECENCY_PAT.search(query):
        return RECENCY
    if _DEFINITION_PAT.search(query):
        return DEFINITION
    if _is_cross_source(query):
        return CROSS_SOURCE
    if _MULTI_HOP_PAT.search(query):
        return MULTI_HOP
    return DEFAULT


# ---------------------------------------------------------------------------
# Introspection helpers (used by tests + by Track D pipeline_v2)
# ---------------------------------------------------------------------------


def all_strategies() -> dict[str, ExpansionStrategy]:
    """All named strategies. Useful for tests and for the UI's strategy
    badge in the reasoning panel."""
    return {
        s.name: s
        for s in (MULTI_HOP, CROSS_SOURCE, CASE_LAW, DEFINITION, RECENCY, DEFAULT)
    }
