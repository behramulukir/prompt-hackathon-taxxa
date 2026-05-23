# Step 7 — Retrieval v2 graph expansion primitives (Track F, done)

Built the graph expansion layer for v2 per `07_retrieval_v2_graph_traversal.md`
and the Track F brief in `parallel_execution_after_step4.md`. Track F's
deliverable was the *primitives* — `graph_expand`, `strategy`,
`cross_encoder_rerank`, and their tests — not the v2 pipeline integration
itself. The v1 → v2 pipeline swap belongs to the convergence step
between Track D and Track F and is not part of this changelog.

The V7.2 hand-walked pilot ran *first* and shaped almost every design
decision below. The pilot finding was not "build what the brief said";
it was "the brief's strategy will produce worse-than-v1 results unless
three additional design constraints are baked in." Those constraints
became the module's load-bearing logic.

## What was built

```
src/retrieval/
├── graph_expand.py             # B7.1 + B7.5 + B7.7 — strategy-aware BFS
├── strategy.py                 # B7.2 — keyword router → ExpansionStrategy
└── cross_encoder_rerank.py     # B7.4 — BAAI/bge-reranker-v2-m3 wrapper

tests/
└── test_graph_expand.py        # 19 tests, all green, in-memory SQLite fixture

findings/
├── 07_pilot_results.md         # V7.2 hand-walk writeup
└── 07_expansion_strategies.md  # per-category strategy configs

our-docs/
├── edge_count_discrepancies.md # brief vs reality on edge counts
└── to-do/
    ├── step1_consolidated_law_section_parsing.md
    ├── step2_pervl_interprets_extraction.md
    ├── step2_section_level_target_resolution.md
    └── step2_or_loader_edge_count_audit.md
```

## V7.2 pilot — what we found

Three hard-tier questions (Q32 PerVL §38, Q34 Finland-Ireland treaty,
Q35 AVL §117) hand-walked through `GraphStore.bfs()` with edge sets
`["parent_of", "cites", "interprets", "applies"]` (variant A) and
`+ "defines"` (variant B). Zero Voyage calls — seeds picked by direct
`output/graph.db` lookup, not vector retrieval, so the pilot tests the
*graph layer in isolation*.

The headline findings, in priority order:

### 1. Typed edges live on SUBSECTIONs, not SECTIONs.

Aggregate counts in `output/graph.db`:

| edge | dominant source.type | dominant target.type |
|---|---|---|
| applies | SUBSECTION (18,259) | CASE (9,445) / LAW (8,811); only 3 to SECTION |
| cites | SUBSECTION (5,609) + LAW/ITEM/DEF | GUIDE (3,648) / LAW (2,939) / SECTION (577) |
| interprets | SUBSECTION (15,597) | LAW (14,412); only 263 to SECTION |
| defines | DEFINITION (234,570) | SUBSECTION (197,349) / ITEM (37,221) |

Vector retrieval anchors chunks to SECTION nodes (per Step 1). A SECTION
seed therefore has **only** `parent_of` edges. The brief's recipe of
`max_hops=1` from a SECTION seed is effectively a structural walk only.
v2 needs to first descend `parent_of`-OUT to the SUBSECTIONs before any
typed expansion is possible.

### 2. `applies`-IN floods unless capped.

TVL and AVL each have thousands of inbound `applies` edges from KHO/KVL
case SUBSECTIONs. Running `max_hops=1` BFS from a TVL or AVL law seed
exhausts a 500-node cap with `applies` edges *before* reaching the
~6,900 inbound `interprets` edges that are the actual cross-source
signal. The original brief had `interprets_in=30`, `cites_out=15`,
`parent_of_in=50` caps — no cap on `applies`. The pilot added
`applies_in=25`.

### 3. `interprets` resolves to LAW root, not SECTION.

Spot-check from a Vero guidance SUBSECTION:

```
interprets  target_ref='TVL 34 a §'  → target_id=…/tuloverolaki   (LAW root)
interprets  target_ref='TVL 54 d §'  → target_id=…/tuloverolaki   (LAW root)
```

`target_ref` preserves the precise citation, but `target_id` falls back
to the LAW root because no §34a SECTION exists in the corpus (Step 1
didn't ingest the consolidated TVL HTML). The graph collapses
section-level cross-reference structure into law-level structure.

### 4. PerVL has zero inbound `interprets` edges.

```sql
SELECT COUNT(*) FROM edges WHERE type='interprets' AND target_id LIKE '%perinto-ja-lahjaverolaki%';
-- 0
```

For comparison: TVL=6,934, AVL=3,284, EVL=2,364. Either Vero's PerVL
guidance is not in the corpus, or Step 2's extractor missed PerVL
citation patterns. Inheritance/gift-tax questions (Q14, Q26, Q32, Q42)
degrade to vector-only retrieval until this is fixed upstream.

### 5. The brief's edge counts are wrong by 10× on `cites`.

| Edge type | Brief | Actual | Δ |
|---|---:|---:|---|
| cites | 67,834 | 7,164 | ~10× fewer |
| transposes | 8,453 | 0 | missing entirely |
| amends | 75 | 24 | smaller |
| repeals | 102 | 24 | smaller |

Documented separately in `our-docs/edge_count_discrepancies.md`.

### 6. `defines` is identical to absent from LAW-root seeds.

Variant A and Variant B produced numerically identical results for every
seed in the pilot. `defines` fires from DEFINITION nodes, not LAW. Default
`defines` to OFF in the strategy router; turn it ON only for the
dedicated `definition` category.

## Verdict and decision

**AMBER, proceed to build with three mandatory design constraints.**

The pilot would have been a STOP if BFS was structurally broken or if no
typed edges existed at all. Neither is true. The graph has the right
edge *types* in the right places; the *distribution* is awkward and
some statutes are dead spots, but the cross-source structure exists for
TVL/AVL (the two highest-volume tax statutes) and that is enough to
justify v2. Upstream fixes to recover SECTION-level resolution for
TVL/AVL would lift v2 substantially but are out of Track F's scope and
out of the hackathon window.

## What was built (the modules)

### `graph_expand.py` — strategy-aware BFS

`expand(seed_ids, strategy, graph_store) -> dict[str, RetrievalPath]`.
The signature stays close to the brief; the body adds:

- **Seed-type auto-descend.** SECTION / CHAPTER / GUIDE / CASE / TREATY
  seeds, and LAW seeds when the strategy is OUT-only, get a free
  `parent_of`-OUT pre-walk before BFS proper. The pre-walk doesn't
  consume from `max_hops`. Encoded in `_needs_descend`.
- **Per-edge-type degree cap** keyed by `"{edge_type}_{direction}"` and
  enforced via `GraphStore.get_degree`. Seeds are never gated (they may
  be hubs that the user is explicitly asking about); only intermediates.
- **Per-edge-type frontier fairness**. No single edge type may consume
  more than `max_nodes // 2` of the result budget. Prevents the
  pilot-discovered `applies`-IN flood from monopolising the result set
  even if the cap is loose.
- **`RetrievalPath` per discovered node** with `from_node_id`,
  `edge_type`, `hops`. Layer-8 path-aware citations get this for free.

### `strategy.py` — keyword router

Six named strategies map 1:1 to the rows in `findings/07_expansion_strategies.md`:

| name | edges | direction | max_hops | caps |
|---|---|---|---:|---|
| `default` | () | n/a | 0 | — |
| `multi_hop` | parent_of, cites | out | 2 | cites_out=15, parent_of_in=50 |
| `cross_source` | interprets, parent_of | both | 2 | interprets_in=30 |
| `case_law` | applies, interprets | both | 1 | **applies_in=25** (new) |
| `definition` | defines, parent_of | both | 1 | defines_out=100 |
| `recency` | amends, repeals, parent_of | both | 1 | — |

`pick_strategy(query)` runs Finnish + English regexes in priority order
(case_law → recency → definition → cross_source → multi_hop → default).
Default is vector-only — when in doubt, v2 degrades to v1, no regression
risk. Conservative on purpose: the pilot showed graph expansion adds
noise more often than signal on this corpus, so the router only commits
to expansion when a strong marker fires.

### `cross_encoder_rerank.py` — BAAI/bge-reranker-v2-m3 wrapper

- `CrossEncoderReranker.score(query, candidates) -> list[ScoredCandidate]`
- `combine_scores(candidates, weights) -> list[ScoredCandidate]` —
  pure-Python weighted blend of `(cross_score, cosine, metadata_score)`
  with redistribution when components are missing.
- `get_reranker()` — module-level cache so the ~5-10s model load
  happens once per process.
- `finnish_smoke_check()` — one-question Finnish sanity probe; designed
  to be run after the first model download to catch silent multilingual
  regressions.

The cross-encoder shifted role between the brief and the pilot. The
brief framed it as "a quality lever." The pilot says it is **damage
control**: post-expansion candidate sets are 30-50 plausible-but-mixed
neighbors, cosine cannot discriminate them, and without rerank, v2 will
routinely underperform v1 on questions that don't benefit from graph.

Heavyweight deps (`torch`, `sentence-transformers`) are imported lazily
inside `__init__`. The module imports cleanly without them; calling
`score()` raises a clear `RuntimeError` with install instructions.
`combine_scores` is pure-Python and always available.

### `tests/test_graph_expand.py`

19 tests against a hand-built in-memory SQLite graph. Covers:

- vector-only strategy → seeds only
- subsection seed walks typed edges one hop
- SECTION seed auto-descends, then typed expansion fires
- edge-type allowlist filters non-listed edges
- `max_hops=0` returns seeds even with edges configured
- degree-cap path doesn't crash on a hub
- `applies`-IN flood capped by fairness limit (50 cases → max 10 reach result)
- `RetrievalPath` carries provenance (from_node_id, edge_type, hops, score)
- `max_nodes` hard ceiling
- strategy router picks the right strategy for 6 representative queries
- pilot-derived caps survive in the strategy presets (regression guard)
- `combine_scores` handles missing components and blends correctly

```
============================== 19 passed in 1.49s ==============================
```

## Real-graph smoke

Cross-source strategy with TVL law seed against `output/graph.db`:

```
total nodes: 40 (within max_nodes)
by edge type: seed=1, parent_of=19, interprets=20
```

`interprets`-IN respects the 30-cap. The pilot-flagged `applies`-IN
flood is absent because the strategy excludes `applies` from
cross-source. Exactly the intended shape.

## Decisions and tradeoffs

### Track F does not modify `src/retrieval/__init__.py`

Per the file-collision matrix in `parallel_execution_after_step4.md`,
`__init__.py` is Track D's territory. The new modules are importable
by full path (`from src.retrieval.graph_expand import expand`). Track D
will re-export at convergence time if needed.

### Seed-type auto-descend lives in `graph_expand`, not in the strategy

The strategy describes the *traversal* the question wants; the descend
is *plumbing* to make typed edges reachable from a vector-anchored
seed. Putting it in `graph_expand._needs_descend` keeps strategy configs
short and topology-agnostic, and means a future Step 1 fix (consolidated
TVL/AVL ingestion → SECTION nodes get typed edges directly) only
requires updating `_DESCEND_FROM`, not every strategy preset.

### Per-edge-type fairness over a single global cap

The brief had `max_nodes` and per-edge `degree_caps`. Both miss the
case where one edge type dominates *during* BFS even when no single
node exceeds its cap. The `applies`-IN flood is the canonical example:
50 different KHO case SUBSECTIONs each contribute one edge to LAW1, so
no individual node trips a degree cap, but together they consume the
budget. Fairness limit (`max_nodes // 2` per edge type) closes this.

### Cross-encoder model not auto-downloaded

`cross_encoder_rerank.py` doesn't try to download the 1.1 GB model on
import. The first `CrossEncoderReranker()` call triggers download,
which fails fast if `sentence-transformers` is missing. Decision: don't
bundle ML deps with the lazy-loaded module; let the consumer (Track D
pipeline_v2 or the convergence script) decide when to install.

### Conservative default strategy

The pilot showed five of six question categories have realistic
expansion paths. The sixth (`default`) is the vast majority of
real-world tax questions, which are single-fact lookups answerable by
vector alone. Graph expansion on those questions adds noise more often
than signal. The router's `default` branch is therefore zero-hop
vector-only — v2 reuses Track D's vector retrieval unchanged, and only
the questions whose markers fire strongly get graph expansion. This
preserves "v2 ≥ v1" as a baseline guarantee.

### Cap thresholds are pilot-grounded, not eval-tuned

Eval at scale is hackathon-scoped to demo questions (per Track E in
`parallel_execution_after_step4.md`). Without a quantified regression
harness, the caps are starting points: `interprets_in=30` from the
brief plus `applies_in=25`, `defines_out=100`, fairness=`max_nodes//2`
from the pilot's degree distributions. Tunable via the
`ExpansionStrategy` config without touching code; convergence work or
Track E (demo eval) can tighten them.

### `defines` is OFF by default

Variant A vs Variant B in the pilot produced identical results from
LAW-root seeds. From SUBSECTION/ITEM seeds with defined-term usages it
would fire, but the 234k-edge volume makes "always-on" untenable.
`defines` is on only in the `definition` category.

## Observations for the convergence step

Track D's `pipeline_v2.py` (not Track F's responsibility) will need:

- A vector-retriever call to produce `seed_k` chunks.
- A way to look up the chunk's `section_id` (Track D already does this
  for v1's assembly) — that section becomes the BFS seed.
- A call to `graph_expand.expand(section_ids, strategy, graph_store)`.
- A call to `cross_encoder_rerank.get_reranker().score(...)` followed by
  `combine_scores(...)`.
- Existing v1 `assemble` and `generate` consume the reranked set.

Track F's modules are self-contained; convergence is the wiring.

## Upstream fixes (logged for other owners)

| File | Owner | Priority |
|---|---|---|
| `our-docs/to-do/step1_consolidated_law_section_parsing.md` | Step 1 | High — unlocks SECTION-level retrieval for TVL/AVL |
| `our-docs/to-do/step2_pervl_interprets_extraction.md` | Step 2 | Medium — affects 5 eval questions |
| `our-docs/to-do/step2_section_level_target_resolution.md` | Step 2 | Medium — gated by Step 1 fix |
| `our-docs/to-do/step2_or_loader_edge_count_audit.md` | Step 2 + loader | Medium for `cites`, low for the rest |

None of these block Track F's deliverables. All would lift v2's ceiling
substantially if landed.

## How to use

```python
from src.indexing.graph_store import GraphStore
from src.retrieval.strategy import pick_strategy
from src.retrieval.graph_expand import expand
from src.retrieval.cross_encoder_rerank import get_reranker, combine_scores, ScoredCandidate

graph = GraphStore("output/graph.db")
strategy = pick_strategy(question)
seed_ids = [...]  # from vector retrieval, mapped to section_id
expanded = expand(seed_ids, strategy, graph)  # dict[node_id, RetrievalPath]

# Optional rerank
rr = get_reranker()  # requires sentence-transformers
candidates = [(nid, fetch_text(nid)) for nid in expanded]
scored = rr.score(question, candidates)
for s in scored:
    s.cosine = ...      # from Track D
    s.metadata_score = ...
ranked = combine_scores(scored, strategy.rerank_weights)
```

## How to test

```bash
.venv/bin/python -m pytest tests/test_graph_expand.py -v
```

No external services, no model downloads. Runs in ~1.5 s.

## Output artifacts

| file | size | contents |
|---|---:|---|
| `findings/07_pilot_results.md` | ~9 K | V7.2 hand-walked pilot writeup |
| `findings/07_expansion_strategies.md` | ~5 K | Per-category strategy configs |
| `our-docs/edge_count_discrepancies.md` | ~3 K | Brief vs reality on edge counts |
| `our-docs/to-do/step1_*.md` | ~3 K | Step 1 follow-up |
| `our-docs/to-do/step2_*.md` × 3 | ~9 K | Step 2 follow-ups |

No new persistent corpus artifacts. Track F is pure read-over Step 1–4
outputs plus three new Python modules + tests.

## Sequencing notes

- **Track D convergence (v2 pipeline)** consumes `graph_expand.expand`
  and the strategy presets. Drop-in: a single `expand` call between
  v1's vector-retrieve and v1's rerank stages.
- **Track G (Demo UI)** consumes `RetrievalPath.from_node_id` /
  `edge_type` / `hops` for the reasoning-panel graph-traversal
  animation. The Layer-8 contract is already populated.
- **Track H (Agents)** doesn't depend on Track F directly. The
  Verifier may use the graph for conflict detection independently of
  `expand` — strategy router output is the right hook if it wants to
  participate.

## Open items

- [ ] `sentence-transformers` install (~2 GB pulls torch + the 1.1 GB
      model) — deferred to convergence
- [ ] Run `finnish_smoke_check()` once the model is downloaded
- [ ] Convergence step: wire `expand` + `cross_encoder_rerank` into
      `src/retrieval/pipeline_v2.py` (Track D, not Track F)
- [ ] Tune cap thresholds if Track E's demo questions surface obvious
      misses; values today are pilot-grounded starting points
