# Per-Category Expansion Strategy Configs (v2)

> Pilot-derived. Codifies the strategy router output that `src/retrieval/strategy.py` returns and `src/retrieval/graph_expand.py` consumes. Tuned against the actual edge topology observed in `findings/07_pilot_results.md`, not the brief's idealised one.

## ExpansionStrategy shape

```python
@dataclass(frozen=True)
class ExpansionStrategy:
    name: str                              # e.g. "multi_hop", "definition", "default"
    seed_k: int                            # how many vector seeds to start from
    edge_types: tuple[EdgeType, ...]       # allowlist
    direction: Direction                   # "out" | "in" | "both"
    max_hops: int                          # 1 or 2; auto-bumped for SECTION seeds
    max_nodes: int                         # hard ceiling on result count
    degree_caps: dict[str, int]            # per "{edge_type}_{direction}" cap; skip expansion through hubs
    rerank_weights: tuple[float, float, float]  # (cross_encoder, cosine, metadata) — sums to 1.0
```

The `rerank_weights` field is consumed by Track D's reranker; included here so the strategy is self-describing.

## Categories

### `default` — no strong signal

Used when the keyword classifier doesn't fire. Vector-only, no graph expansion.

| field | value |
|---|---|
| seed_k | 10 |
| edge_types | `()` |
| direction | n/a |
| max_hops | 0 |
| max_nodes | 10 |
| degree_caps | `{}` |
| rerank_weights | (0.6, 0.3, 0.1) |

Reasoning: most questions in the eval set are answerable by vector alone — the corpus' sparse edge topology means graph adds noise more often than signal. Make the strategy router prove the question benefits from expansion before paying for one.

### `multi_hop` — rule + exception, condition chain

Triggered by: `poikkeus`, `exception`, `kuitenkin`, `mutta jos`, `however`, `unless`.

| field | value |
|---|---|
| seed_k | 10 |
| edge_types | `("parent_of", "cites")` |
| direction | `"out"` |
| max_hops | 2 (mandatory; rule + sibling/cited exception is 2 hops) |
| max_nodes | 40 |
| degree_caps | `{"cites_out": 15, "parent_of_in": 50}` |
| rerank_weights | (0.6, 0.3, 0.1) |

Reasoning: rules and their exceptions usually sit as sibling SUBSECTIONs under a shared SECTION, or as cited carve-outs. `parent_of`-OUT (drill into subsections) + `cites`-OUT (follow internal references). `interprets` excluded — multi-hop within statute should not pull in guidance, that's a different category.

### `cross_source` / `statute_vs_guidance` — Finlex statute ↔ Vero guidance

Triggered by: query contains both a Finlex citation pattern (`TVL`, `AVL`, `§`, `mom`) AND a guidance marker (`Vero`, `ohje`, `kannanotto`, `verohallinto`); or by intent classification.

| field | value |
|---|---|
| seed_k | 10 |
| edge_types | `("interprets", "parent_of")` |
| direction | `"both"` |
| max_hops | 2 |
| max_nodes | 40 |
| degree_caps | `{"interprets_in": 30}` |
| rerank_weights | (0.6, 0.3, 0.1) |

Reasoning: from a Finlex LAW seed, `interprets`-IN finds Vero guidance interpreting it. From a Vero GUIDE/SUBSECTION seed, `interprets`-OUT finds the statute it interprets. The brief's `interprets_in=30` cap holds. `parent_of` included so we can ladder up/down between LAW root and its children when needed. **`applies`-IN deliberately excluded** — that floods with KHO/KVL cases (pilot finding), which are a separate category.

### `case_law` / `applies` — precedent application

Triggered by: `KHO`, `tapaus`, `oikeustapaus`, `ratkaisu`, `ennakkoratkaisu`, `case`, `precedent`.

| field | value |
|---|---|
| seed_k | 10 |
| edge_types | `("applies", "interprets")` |
| direction | `"both"` |
| max_hops | 1 |
| max_nodes | 30 |
| degree_caps | `{"applies_in": 25}` ← NEW cap, not in original brief |
| rerank_weights | (0.6, 0.3, 0.1) |

Reasoning: `applies`-IN floods from a statute seed (TVL/AVL hit the 500 cap in 1 hop, almost entirely `applies` from KHO/KVL subsections). The `applies_in=25` cap is mandatory; without it BFS exhausts on case-law before exploring guidance. From a CASE seed, `applies`-OUT finds the statute applied. From a statute seed (rare in this category), `applies`-IN with the cap finds a small set of leading cases.

### `definition` — defined-term lookup

Triggered by: `määritelmä`, `tarkoittaa`, `tarkoitetaan`, `definition`, `defined as`, `means`.

| field | value |
|---|---|
| seed_k | 10 |
| edge_types | `("defines", "parent_of")` |
| direction | `"both"` |
| max_hops | 1 |
| max_nodes | 20 |
| degree_caps | `{"defines_out": 100}` |
| rerank_weights | (0.6, 0.3, 0.1) |

Reasoning: this is the ONE category where `defines` is on. From a DEFINITION node seed, `defines`-OUT finds usages; `parent_of`-IN finds the containing section so the LLM sees the definition in context. From a SUBSECTION seed that uses a defined term, `defines`-IN walks back to the DEFINITION node. The `defines_out=100` cap is generous because a definition's whole point is to have wide reach, but caps the absolute worst case.

### `recency` / `repeal` — current version, what superseded what

Triggered by: `voimassa`, `kumottu`, `nykyinen`, `current`, `repealed`, `superseded`, `in force`, date references.

| field | value |
|---|---|
| seed_k | 10 |
| edge_types | `("amends", "repeals", "parent_of")` |
| direction | `"both"` |
| max_hops | 1 |
| max_nodes | 15 |
| degree_caps | `{}` |
| rerank_weights | (0.5, 0.2, 0.3) ← metadata weight ↑ (effective_date / repeal_date matter here) |

Reasoning: `amends`/`repeals` are sparse (24 + 24 edges total in graph.db, per `our-docs/edge_count_discrepancies.md`). One hop is plenty. Metadata reranker weight bumped because Step 3's `effective_date` / `repeal_date` fields are the actual answer for recency questions; the cross-encoder is secondary.

## Seed-type auto-rules (applied by `graph_expand` regardless of strategy)

These fire after the strategy is picked but before BFS starts. They prevent the SECTION-seed-no-edges trap discovered in the pilot.

1. **Seed type = SECTION**: prepend a `parent_of`-OUT hop to reach SUBSECTIONs. This consumes one hop from `max_hops`, so the effective downstream `max_hops` is `strategy.max_hops + 1` for SECTION seeds (still bounded at `2` total descend + typed expansion).
2. **Seed type = CHAPTER**: same as SECTION but two `parent_of`-OUT hops to reach SUBSECTIONs.
3. **Seed type = LAW**: no descend needed — `interprets`-IN and `applies`-IN edges land here directly.
4. **Seed type = SUBSECTION / ITEM / DEFINITION**: no descend — typed edges fire from here.
5. **Seed type = GUIDE / CASE root**: prepend a `parent_of`-OUT hop to reach the SUBSECTIONs that carry the outgoing edges.

The auto-rule logic is encoded in `graph_expand._maybe_descend(seed, strategy)`.

## Why these caps and not the brief's

| Edge type/dir | Brief | This doc | Reason |
|---|---:|---:|---|
| `interprets_in` | 30 | 30 | Confirmed sane by pilot — top interprets-IN hubs (TVL=6,934; AVL=3,284) need a hard cap. |
| `cites_out` | 15 | 15 | Confirmed sane; not stressed by pilot but no reason to change. |
| `parent_of_in` | 50 | 50 | Confirmed sane. |
| `applies_in` | (none) | **25** | NEW. Pilot showed `applies`-IN flooding TVL/AVL BFS at hops=1; cap is mandatory. |
| `defines_out` | (none) | 100 | NEW. Bounds the worst case for definition category; generous because definitions are meant to have wide reach. |

## Open questions (deferred to runtime)

- **Cap thresholds may need tuning** once the eval harness (Step 6 / Track E) provides per-question regression data. Current values are pilot-grounded starting points.
- **Rerank weights** are taken from the Step 7 brief (`final = 0.6·cross + 0.3·cosine + 0.1·metadata`) except for `recency` which biases toward metadata. These are config-tunable in `cross_encoder_rerank.py`.
- **`default` strategy with seed_k=10 + max_hops=0** assumes Track D's vector retriever already pulls 10 — verify when Track D ships.
