# Parallel Execution Plan — Post Steps 2, 3, 4b

> **State of the world:** Steps 1, 2, 3, and 4b are complete. Step 4a (full embedding pass) is running in the background, ~1.6 hours to completion. The pilot vector store (`output/lancedb_pilot/`, 1000 chunks) is already usable for development.

## Artifacts you can rely on right now

| Artifact | Location | Size | Status |
|----------|----------|-----:|--------|
| Nodes (enriched) | `output/nodes_enriched.jsonl` | ~1.6 GB | done |
| Chunks | `output/chunks.jsonl` | 691 MB | done |
| Edges (resolved) | `output/edges.jsonl` | 883 MB | done |
| Hierarchy index | `output/hierarchy.json` | 159 MB | done |
| Graph store (SQLite) | `output/graph.db` | 3.2 GB | done, verified |
| Vector store (pilot) | `output/lancedb_pilot/chunks.lance/` | ~6 MB | done, 1000 chunks |
| Vector store (full) | `output/lancedb/chunks.lance/` | growing | **in progress, ~1.6 h ETA** |
| Schemas | `src/models.py` | — | done |
| Vector store adapter | `src/indexing/vector_store.py` | — | done |
| Graph store adapter | `src/indexing/graph_store.py` | — | done |
| Voyage client | `src/indexing/voyage_client.py` | — | done |
| Text composition | `src/indexing/text_composition.py` | — | done |

## What this means

Almost everything downstream of Step 4 can start **now**, in parallel. The only thing waiting on the full embed is the *evaluation at full corpus scale* — and even that can be benchmarked first against the pilot, then re-run against the full store with one config change.

The graph store is the bigger unlock than the vectors. Most of what makes GraphRAG interesting (graph traversal, hub caps, conflict surfacing) runs against `graph.db`, which is fully loaded.

## Five parallel tracks

Each track has explicit file ownership. **No two tracks write to the same file.** Where a track needs to extend a shared file (notably `src/models.py`), the change is scoped and listed.

### Track D — Retrieval v1 (Step 5)

Build the vector-only baseline against the pilot store. Swap to full store with a one-line config change when the embed finishes.

**Reads:** `src/models.py`, `src/indexing/vector_store.py`, `src/indexing/graph_store.py`, `output/lancedb_pilot/` (now) and `output/lancedb/` (later), `output/graph.db`, `output/nodes_enriched.jsonl`, `output/edges.jsonl`

**Writes:**
- `src/retrieval/__init__.py`
- `src/retrieval/filters.py` — keyword-based filter inference
- `src/retrieval/vector_retriever.py` — wraps `VectorStore.search_by_text`
- `src/retrieval/rerank.py` — metadata reranker using `authority_rank`, `usable`, `publication_date`
- `src/retrieval/assemble.py` — annotated context (Layer 5), renders inter-source edges from graph store
- `src/retrieval/generate.py` — LLM call + citation parsing
- `src/retrieval/pipeline.py` — the glue, produces `AnswerResult`
- `scripts/ask.py` — CLI
- `findings/05_baseline_failures.md` — 10-question diagnosis

**Special instructions:**
- Use `output/lancedb_pilot/` as the dev target until full embed completes. Make the path a config var so you can flip it.
- The assembler needs `GraphStore.get_neighbors()` to render edges between retrieved chunks — already available.
- Don't wait for the full embed to declare done. The pipeline works regardless of corpus size; the *eval numbers* will only be meaningful at full scale.

**Done when:** `python -m scripts.ask "Onko ALV vähennyskelpoinen, jos..."` returns a Finnish answer with `[Source N]` citations against the pilot store.

---

### Track E — Demo questions

Build a small set of high-quality demo questions. **No automated eval — hackathon scope.**

**Reads:** `output/nodes_enriched.jsonl`, `output/chunks.jsonl` (to find supporting node IDs for each question)

**Writes:**
- `demo/questions.yaml` — 10–15 hand-picked Finnish tax questions designed to make GraphRAG shine
- `demo/comparison_notes.md` — optional hand-graded v1-vs-v2 comparison once both pipelines exist

**Special instructions:**
- This is no longer an eval harness. It's a curated demo question pool. Quality over quantity.
- Each question must be designed to **exercise a specific GraphRAG strength**. Tag each:
  - `multi_hop` — requires rule + exception from different documents
  - `cross_source` — requires both Finlex statute and Vero guidance
  - `conflict` — sources at different `authority_rank` disagree (the Verifier's demo moment)
  - `definition` — answer depends on a defined term elsewhere in the corpus
  - `cross_reference` — answer requires following a `cites` edge
- For each question, also record the **expected reasoning path** ("vector hit on §114, walk parent_of to §114.2, walk cites to §117"). This becomes the script the demo narrator uses.
- 3 of these questions become the live demo. The remaining 10+ are backup for judge follow-ups ("show me another"). Order them so the live three are the most visually impressive.
- If you have a Finnish tax expert: have them verify each answer. Mark as `verified: true` in the YAML.
- If no expert: write the multi-hop and cross-reference questions by **deliberate construction** — pick a SECTION node, walk one edge in the graph, write a question that requires both endpoints. The graph itself guarantees the question is well-formed.

**Optional (do after Tracks D and F + integration are done):** run the 10–15 questions through both v1 and v2, hand-grade win/lose/tie per question. Write a one-paragraph summary to `demo/comparison_notes.md`. Not statistically valid; visually compelling in the pitch.

**Done when:** `demo/questions.yaml` has 10+ tagged questions with expected reasoning paths.

---

### Track F — Graph expansion primitives (Step 7, isolated parts)

Build the traversal logic that v2 will use. The graph store's `bfs` method already exists; this track builds the strategy router and the rerank step.

**Reads:** `src/models.py`, `src/indexing/graph_store.py`, `output/graph.db`

**Writes:**
- `src/retrieval/graph_expand.py` — wraps `GraphStore.bfs()` with strategy-specific configs
- `src/retrieval/strategy.py` — keyword classifier for expansion strategy
- `src/retrieval/cross_encoder_rerank.py` — `BAAI/bge-reranker-v2-m3` wrapper
- `tests/test_graph_expand.py` — synthetic-seed unit tests
- `findings/07_expansion_strategies.md` — per-category strategy configs
- `findings/07_pilot_results.md` — **V7.2 hand-walked pilot, do this FIRST**

**Special instructions:**
- **Run V7.2 (3-question hand-walk) before building the full module.** This is a critical sanity check on whether Step 2's edges produced a useful graph structure. If the multi-hop expansion doesn't surface the expected exception clauses, *stop and investigate* — the rest of the work is wasted if the edges are too sparse or wrong-typed.
- Use the pilot vector store + full graph store for the hand-walk: vector hit on a known SECTION, then `GraphStore.bfs()` with `edge_types=["parent_of", "cites", "interprets"]`, `max_hops=1`. Eyeball whether the right neighbors appear.
- Cross-encoder model download happens here. Cache it in `~/.cache/huggingface/`.
- Degree caps: start with `interprets_in=30`, `cites_out=15`, `parent_of_in=50` per the Step 7 plan. Tune from `metadata.degree` distributions.

**Done when:** V7.2 pilot passes (concretely: for a known multi-hop question, expansion brings in the exception clause that vector-only would miss). The modules are written but don't have to be integrated into pipeline_v2 yet (that's Track converge work).

---

### Track G — Demo UI

Build the real frontend that will be shown to judges. Replace the cinematic mockup's hardcoded data with calls to a real backend (or `MockPipeline` until Track D is done).

**Reads:** `src/models.py` (specifically the `AnswerResult` shape)

**Writes:**
- `web/` (or wherever the frontend lives) — full UI scaffolding
- Wire to either `MockPipeline` (now) or `pipeline.answer()` (when Track D delivers)

**Special instructions:**
- The cinematic mockup we built is the reference. Build a real version of it.
- Use `MockPipeline` to develop in isolation. When Track D ships, switch the import.
- Most of the wow factor for judges lives here. Spend time on:
  - The reasoning panel with the graph traversal animation
  - The agent timeline with the edge write-back moment
  - The Skip/Replay controls
  - Citation hover previews (new — show the chunk text on hover)
- Do **not** try to render the real `graph.db` directly in the UI. Use the precomputed `retrieval_paths` from `AnswerResult` — that's the contract.
- **MANDATORY: Show `authority_rank` in every source label.** Step 3's rank values are provisional and unsigned-off. The UI must surface them prominently (e.g. `[Source 1] Finlex · §114 AVL (rank 100, binding)`) so:
  - the Verifier's "higher rank prevails" logic is legible to demo viewers
  - a Finnish tax expert reviewing the demo can spot rank errors and flag them
  - The banner from `findings/03_authority_ranks.md` is reflected in the UI (e.g. a small "provisional" pill in the corner)

**Done when:** Typing a question into the UI produces the cinematic animation, the inline memo with annotated sources, and the agent timeline — all driven by real (or mock) `AnswerResult` objects.

---

### Track H — Agent prompts (Step 8, isolated parts)

Build and iterate on the four agent prompts (Clarifier, Planner, Verifier, Extractor) against synthetic inputs. Orchestrator waits until Track D delivers `pipeline.answer()`.

**Reads:** `src/models.py` only

**Writes:**
- `src/agents/__init__.py`
- `src/agents/clarifier.py` — prompt + JSON parsing, no retrieval calls
- `src/agents/planner.py` — sub-question decomposition, no retrieval calls
- `src/agents/verifier.py` — takes (claims, sources) → conflict report
- `src/agents/extractor.py` — citation extraction prompt (reuses Step 2's LLM extractor logic, here at query time)
- `tests/test_agent_prompts.py` — hand-built synthetic inputs per agent
- `findings/08_agent_prompts.md` — calibration notes

**Special instructions:**
- Each agent's prompt is testable against synthetic inputs:
  - Clarifier: 20 hand-crafted ambiguous Finnish tax questions → it should identify the missing dimension (year, entity type, jurisdiction)
  - Planner: 20 compound questions → it should produce 1–4 sub-questions each
  - Verifier: 10 hand-built (claim, supporting source, contradicting source) triples → it should flag the conflict
  - Extractor: 20 sentences with implicit Finnish legal references → it should produce typed edges
- **Verifier needs Step 3's authority_rank.** When two sources at different ranks address the same target, the Verifier surfaces the conflict and prefers the higher rank. This is the L7 conflict-surfacing path.
- Do not build the orchestrator yet. The orchestrator is converge work.

**Done when:** Each agent has a tested prompt with documented behavior on the synthetic set. No integration yet.

---

## What runs sequentially (not parallel)

These integration steps converge the parallel tracks. They happen **after** Track D delivers `pipeline.answer()`:

### Convergence step 1 — v2 pipeline assembly

Wire Track F's `graph_expand` and `cross_encoder_rerank` into a `pipeline_v2.py` that mirrors Track D's `pipeline.py` shape. Run a few questions from Track E's demo set through both v1 and v2, eyeball the differences.

### Convergence step 2 — orchestrator (Track H completion)

Wire Track H's four agents into `src/agents/orchestrator.py` that calls `answer_v2`. Run the same demo questions through the agentic pipeline. Compare to v2.

### Convergence step 3 — final UI integration

Swap Track G's `MockPipeline` for the real `answer_agentic` (or `answer_v2` if agents aren't ready). Adjust UI to render real `retrieval_paths`, real conflicts, real assumptions.

### Convergence step 4 — optional v1-vs-v2 comparison

If time permits, Track E owner runs the 10–15 demo questions through v1 and v2, hand-grades win/lose/tie, writes a one-paragraph summary in `demo/comparison_notes.md`. Becomes a slide in the pitch.

## File-collision matrix

| File / dir | D | E | F | G | H |
|------------|:-:|:-:|:-:|:-:|:-:|
| `src/models.py` | R | – | R | R | R |
| `src/indexing/` | R | – | R | – | – |
| `output/lancedb*/` | R | – | – | – | – |
| `output/graph.db` | R | – | R | – | – |
| `output/nodes_enriched.jsonl` | R | R | – | – | – |
| `output/edges.jsonl` | R | – | R | – | – |
| `output/chunks.jsonl` | – | R | – | – | – |
| `src/retrieval/filters.py` | **W** | – | – | – | – |
| `src/retrieval/vector_retriever.py` | **W** | – | – | – | – |
| `src/retrieval/rerank.py` | **W** | – | – | – | – |
| `src/retrieval/assemble.py` | **W** | – | – | – | – |
| `src/retrieval/generate.py` | **W** | – | – | – | – |
| `src/retrieval/pipeline.py` | **W** | – | – | – | – |
| `src/retrieval/graph_expand.py` | – | – | **W** | – | – |
| `src/retrieval/strategy.py` | – | – | **W** | – | – |
| `src/retrieval/cross_encoder_rerank.py` | – | – | **W** | – | – |
| `src/agents/*` | – | – | – | – | **W** |
| `scripts/ask.py` | **W** | – | – | – | – |
| `web/` | – | – | – | **W** | – |
| `demo/questions.yaml` | – | **W** | – | – | – |
| `demo/comparison_notes.md` | – | **W** | – | – | – |
| `findings/05_*` | **W** | – | – | – | – |
| `findings/07_*` | – | – | **W** | – | – |
| `findings/08_*` | – | – | – | – | **W** |
| `tests/*` | – | – | **W** | – | **W** |

R = read-only; W = exclusive write.

## Schema status

`AnswerResult` and `RetrievalPath` are already in `src/models.py`. `MockPipeline` is in `src/retrieval/mock_pipeline.py`. **Pre-flight is complete — proceed straight to dispatch.**

## Recommended sequencing

| Order | Track | Owner | Why this order |
|-------|-------|-------|----------------|
| 1 | Track F V7.2 pilot only | Coding agent | Earliest possible signal on graph quality — fail fast |
| 1 (parallel) | Track E | Human or coding agent | Slow if done well, no code blockers |
| 1 (parallel) | Track D | Coding agent | Critical path for everything downstream |
| 1 (parallel) | Track G | Coding agent / designer | Highest demo impact |
| 2 (after F V7.2 passes) | Track F full module | Same agent | Only continue if pilot validated the graph |
| 2 (parallel) | Track H | Coding agent | Prompt engineering, mostly iteration |

## Critical-path gating

The hackathon ends when you converge. The order of arrival matters:

1. **Track D must finish before** v2 assembly. Without retrieval, nothing else has anything to consume.
2. **Track F's V7.2 pilot must pass before** Track F's full module is worth building. If it fails, you've discovered a problem in Step 2's edges that requires going back.
3. **Track E must finish before** the demo. Without curated demo questions, you have nothing reliable to show on stage.
4. **Track G can ship without** Track H (degrades to v2 pipeline output). It cannot ship without Track D (or MockPipeline).
5. **Track H is a nice-to-have.** v2 (graph + reranker) is the demo if agents aren't ready in time.

## What happens when 4a finishes

- Switch Track D's vector store path from `output/lancedb_pilot/` to `output/lancedb/`. One config change.
- Track E owner re-runs their 10–15 demo questions to confirm answers still look right at full scale.
- Track G's UI doesn't care — same `AnswerResult` shape.

This is the easiest convergence in the plan. No code changes required other than the path swap.
