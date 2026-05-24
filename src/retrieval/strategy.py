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


# Step-11 Plan B: deeper candidate pools.
# Pre-Plan-B every strategy used ``seed_k=10`` — fast, but too tight to
# survive cross-lingual queries. The user's eval question
# ("maximum daily withholding tax percentage / ennakonpidätys") put the
# correct 2026 Verohallinto päätös chunk at *hybrid rank ~16* after
# Plan A's query expansion, which never reached the cross-encoder
# because seed_k=10 cut it off. Raising seed_k brings the cross-encoder
# the candidates it needs to discriminate properly.
#
# CROSS_SOURCE (the päätös / Vero-ohje route) gets the biggest bump
# because that's the strategy that most often spans the multilingual
# divide — administrative Finnish answering an English question.
# DEFAULT (the cross_source/case_law/etc. catch-all) gets a smaller
# bump so generic Finnish questions retain their speed budget.
# Other strategies are deliberately untouched — they have stronger
# graph priors (CASE_LAW expands inbound from KHO, RECENCY follows
# amendment edges, etc.) so 10 seeds already feed reasonable BFS.
#
# Cross-encoder cost scales linearly: 10 → 30 candidates is ~3x the
# scoring time (~150ms → ~450ms on local hardware). Dwarfed by the
# generation step (~10s) and Plan A's query_rewrite (~3-6s on cold).

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
    # 10 → 30: Plan B. Lets the cross-encoder see hybrid hits that
    # Plan A's query expansion now surfaces around rank 15-25, which
    # are typically the actual answer documents for cross-lingual
    # päätös / ohje questions.
    seed_k=30,
    edge_types=("interprets", "parent_of"),
    direction="both",
    max_hops=2,
    max_nodes=40,
    degree_caps={"interprets_in": 30},
    # Bump metadata weight 0.10 → 0.20 (taking from cross-encoder
    # 0.60 → 0.50). The cross-encoder under-rates current Verohallinto
    # päätökset against older statute amendments when both look
    # semantically similar; the metadata signal — now carrying an
    # absolute-freshness term keyed on publication_date — needs more
    # sway to break those ties in favour of currency.
    rerank_weights=(0.5, 0.3, 0.2),
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

# 10 → 20: Plan B applied at half strength for the catch-all. Generic
# Finnish questions usually hit the right chunk in the top 10 already,
# but English questions about Finnish concepts often sit at rank 11-20.
DEFAULT = vector_only_strategy(seed_k=20)


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

# Verohallinto / annual-decision marker. Fires on user questions about
# tax-administration päätökset — those are the cross-source pivot
# between Finlex framework (ennakkoperintälaki) and the concrete
# percentages (Verohallinto päätös for a given year). When this pattern
# alone fires (without an explicit Finlex citation), expand via
# ``interprets`` so the statutory neighborhood surfaces alongside the
# päätös chunks.
#
# Patterns are tuned to surface päätös documents — both Finnish
# administrative vocabulary and English "withholding tax" /
# "tax rate" framings users may ask in English even when the answer is
# Finnish.
_PAATOS_PAT = re.compile(
    r"\b("
    # Finnish päätös vocabulary
    r"p[äa][äa]t[öo]s|p[äa][äa]t[öo]ksen|p[äa][äa]t[öo]kset|"
    r"verohallinnon\s+p[äa][äa]t[öo]s|"
    r"verohallinto|"
    r"laskentaperuste(?:et|ist[äa])?|"
    # Withholding-percentage Finnish + English. Finnish consonant
    # doubling means the nominative ``ennakonpidätys`` becomes
    # ``ennakonpidätyks-`` in oblique cases (genitive
    # ``ennakonpidätyksen``, adessive ``ennakonpidätyksellä``). The
    # stem ``ennakonpidäty`` matches both forms. The päätös is the
    # controlling source for any question about rates/thresholds even
    # when the user does not say the word "päätös" explicitly.
    r"ennakonpid[äa]ty(?:s|ks)|"
    r"withholding\s+tax\s+(?:percent|rate|percentage|maximum)|"
    r"maximum\s+(?:daily\s+)?withholding|"
    r"tax\s+administration\s+decision"
    r")",
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
    """Cross-source fires when the query references *both* a Finlex
    citation form AND a guidance marker, OR when the query explicitly
    asks about a Verohallinto päätös (annual tax-administration
    decisions are inherently cross-source: they sit between the statute
    framework and the year-specific percentages).
    """
    if _FINLEX_CITE_PAT.search(query) and _GUIDANCE_PAT.search(query):
        return True
    # Päätös-only queries also benefit from CROSS_SOURCE expansion —
    # the päätös chunks alone don't cite back to the controlling
    # ennakkoperintälaki sections, but they're connected by inbound
    # interprets edges.
    return bool(_PAATOS_PAT.search(query))


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
