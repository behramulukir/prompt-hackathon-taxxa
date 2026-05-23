# Step 7 — Retrieval v2 (Graph Traversal Layer)

> Add the graph walk that turns the system from RAG into GraphRAG. Vector search finds entry points; graph traversal expands them along typed edges; reranking culls back to a context-window-fitting set.
>
> This is the payoff step. The whole reason for the Step 1 node taxonomy, Step 2 edges, and Step 3 metadata was to make this possible.

## Inputs

- v1 baseline metrics from Step 6 — the numbers to beat
- `findings/05_baseline_failures.md` — concrete failure cases v2 must address
- Graph store fully populated with edges (Step 2) and metadata (Step 3)
- Vector store from Step 4

## Verification tasks

### V7.1 — Per-category expansion strategy

For each question category in `eval/questions.yaml`, decide which edges to traverse and how far. Starting proposal:

| Category | Traversal strategy |
|----------|--------------------|
| Single-hop factual | No expansion. Vector top-5. |
| Multi-hop (rule + exception) | 1 hop on `parent_of` / `child_of` (sibling SUBSECTIONs / ITEMs), 1 hop on `cites` |
| Definition lookup | 1 hop on `defines` from any DEFINITION node hit; also 1 hop up to the containing SECTION |
| Statute-vs-guidance | From any Finlex node hit, 1 hop incoming on `interprets` (pulls in Vero guidance); from any Vero node hit, 1 hop outgoing on `interprets` / `cites` |
| Recency / repeal | 1 hop on `amends` / `repeals` / `superseded_by` to find current version |
| Cross-reference | 1 hop outgoing on `cites` |

Each strategy is a small config (edge types + direction + max hops + caps), not custom code per category. **Output:** `findings/07_expansion_strategies.md`.

### V7.2 — Pilot one strategy

Before building all of v2, pick the multi-hop case (highest expected payoff) and hand-run the expansion on 3 questions:

1. Vector retrieve top-10 entry points
2. For each, traverse the prescribed edges
3. Combine + dedupe
4. Eyeball: did the expansion bring in the exception clause v1 missed?

If yes → build the full v2. If no → diagnose. Usually the cause is a missing edge from Step 2 (regex missed a citation form) or wrong edge type chosen for this category.

**Output:** `findings/07_pilot_results.md`.

## Build tasks

### B7.1 — Graph expansion module

`src/retrieval/graph_expand.py`:

```python
def expand(
    seed_nodes: list[Node],
    edge_types: list[str],
    direction: Literal["out", "in", "both"],
    max_hops: int = 1,
    max_results: int = 30,
) -> list[Node]:
    """BFS expansion over the graph store. Returns expanded set including seeds."""
```

Boring BFS with a visited set, hard limits on hops and result count, and a **degree cap** to skip hub nodes (a widely cited statute article may have hundreds of incoming edges — without a cap, it dominates results).

### B7.2 — Strategy router

`src/retrieval/strategy.py` picks an expansion config from a lightweight classifier:

```python
def pick_strategy(query: str) -> ExpansionStrategy:
    """Keyword / regex / simple classifier → one of the strategies from V7.1."""
```

Keyword-based classification is fine for v2:
- "exception" / "poikkeus" → multi-hop
- "current" / "voimassa" → recency
- query contains both a Finlex citation and "Vero" → statute-vs-guidance
- otherwise → default vector top-N

Defer LLM-based planning to Step 8 (Planner agent). v2 uses deterministic routing so improvements are attributable to the graph, not to the planner.

### B7.3 — v2 pipeline

`src/retrieval/pipeline_v2.py`:

```python
def answer_v2(question: str) -> AnswerResult:
    strategy = pick_strategy(question)
    seeds = retrieve_vector(question, k=strategy.seed_k, filters=...)
    expanded, paths = expand_with_paths(
        seeds, strategy.edge_types, strategy.direction, strategy.max_hops
    )
    reranked = rerank(question, expanded, weights=strategy.rerank_weights)
    context = assemble(reranked[:N], graph_store=...)  # renders inter-source edges
    result = generate(question, context)
    result.retrieval_paths = paths  # Layer 8
    return result
```

Same shape as v1 with one expansion step inserted. The same reranker handles the larger candidate set. `expand_with_paths` returns both the node set and the BFS provenance for each non-seed node (used by Layer 8 path-aware citations).

### B7.4 — Cross-encoder rerank (mandatory at v2)

After graph expansion the candidate set grows to 50–100 nodes. **Vector score alone is no longer enough discrimination** — without reranking, graph expansion typically makes results *worse* by adding plausible-but-irrelevant neighbors that share embedding space with the query. This is the single most important quality lever in Step 7.

- Use `BAAI/bge-reranker-v2-m3` (multilingual, handles Finnish) or `BAAI/bge-reranker-v2-gemma`
- Apply only to the expanded set, not the initial vector search
- Combine its score with the metadata reranker from Step 5:
  ```python
  final = 0.6 * cross_encoder_score + 0.3 * cosine + 0.1 * metadata_signals
  ```
- Tune weights against the eval set

Without this step, expect v2 to *underperform* v1 on single-hop questions and only marginally improve multi-hop. With it, v2 should beat v1 across the board.

### B7.5 — Degree caps and hub avoidance (Layer 4)

A widely cited Finlex statute may have hundreds of incoming `interprets` edges from Vero guidance and dozens of outgoing `cites` edges. Naive 2-hop expansion through such a hub returns thousands of nodes.

Three guards, all implemented in `graph_expand.py`:

1. **Skip expansion through hubs.** When BFS visits a node with `degree[edge_type, direction] > HUB_THRESHOLD`, do not expand through it (but keep it in the result if it was a direct seed). Threshold per edge type — different edges have different natural fan-outs. Start with: `interprets_in > 30`, `cites_out > 15`, `parent_of_in > 50`. Tune from the data.
2. **Limit hops aggressively.** 2 hops is usually too many. Default `max_hops=1`. Only escalate to 2 for explicit multi-hop strategies, and even then only on specific edge types (e.g. `parent_of` chains are safer than `cites` chains).
3. **Truncate by rerank score.** Even after caps, the expanded set may exceed the context budget. Cull to top-N by reranker score with a hard token-budget ceiling (default 25k tokens of context).

Hub nodes are also fingerprinted at load time (Step 4 B4.2 computes `degree` per node) — at retrieval time, the lookup is O(1).

### B7.6 — Edge-aware context assembly

The context assembler from Step 5 already renders edges between retrieved nodes (Layer 5). At v2 it does two additional things:

1. **Renders one-hop-outside-set neighbors as "referenced but not included"** — short labels that tell the LLM what exists beyond the retrieved set. E.g. *"§ 114.2 AVL (referenced but not retrieved)"*. Helps the LLM say "the question requires X which I don't have full text for" instead of guessing.
2. **Groups sources by traversal path origin.** If three sources were reached by expanding from a single seed, they're presented as a cluster. Helps the LLM (and the Verifier) see which sources are mutually reinforcing vs independent.

### B7.7 — Context bloat guards

- **Token budget.** Hard limit of 25k tokens of context. Truncate by rerank score.
- **Per-query degree cap.** Beyond the global hub cap, a per-query expansion cap of ~30 nodes prevents single questions from exploding.

### B7.6 — Run the evaluation

Run `eval/runner.py` against v2. Compare to v1:

- Per-category metric deltas
- Per-question diffs: which improved, which regressed
- Did multi-hop recall@10 jump? Did statute-vs-guidance handling improve?
- Single-hop must not regress significantly — if it does, expansion is adding noise for cases that didn't need it (lower max_hops, tighter edge type filtering)

**Output:** `findings/07_v2_eval.md` — v1 vs v2 per-category breakdown, honest about regressions.

## Done when

- v2 beats v1 on multi-hop, statute-vs-guidance, and cross-reference categories
- Single-hop performance has not regressed by more than a small margin
- Context size stays within budget on all eval questions
- A clear written explanation of any category that didn't improve, with hypotheses
