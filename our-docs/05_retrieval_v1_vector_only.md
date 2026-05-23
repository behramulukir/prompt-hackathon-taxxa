# Step 5 — Retrieval v1 (Vector-Only Baseline)

> End-to-end RAG that answers Finnish tax questions with citations. No graph traversal yet — this is the baseline Step 7 has to beat.

## Inputs

- Populated vector store and graph store from Step 4
- LLM API access (Claude or equivalent)

## Verification tasks

### V5.1 — Failure-mode inspection

Before writing the retriever, take **10 candidate questions** spanning the failure modes from slide 3 of the brief:

- Chunking — does the right SECTION come back even when the rule and its exception are in different chunks?
- Ranking — does a current Finlex section beat older Vero guidance on the same topic?
- Structure — does pure vector search bring in cross-referenced clauses, or only lexically similar ones?
- Composition — multi-hop questions: does top-k return three near-duplicates instead of three complementary sources?

For each, run plain vector search via the Step 4 adapter, dump top-10, write a one-line diagnosis:
- Did the right chunk land in top-3? top-10? not at all?
- If not, why? (jurisdiction-blind, granularity wrong, term mismatch?)

**Output:** `findings/05_baseline_failures.md`. This is the bar Step 7 must clear.

## Build tasks

### B5.1 — Query-time filter inference

Some queries carry implicit filters:

- "...as of 2024" → `effective_date <= 2024 AND (repeal_date is null OR repeal_date > 2024)`
- "in Finland" → `language=fi`
- "current rule on X" → `usable=true`

For v1, write keyword-based filter inference in `src/retrieval/filters.py`. Regex on a handful of keywords is fine — defer LLM-based filter inference to the Clarifier agent in Step 8.

### B5.2 — Vector retriever

`src/retrieval/vector_retriever.py`:

```python
def retrieve_vector(query: str, k: int = 20, filters: dict | None = None) -> list[Chunk]:
    """Embed query, search vector store, return top-k chunks (with primary_node_id)."""
```

Over-retrieve at k=20, then rerank down in B5.3.

### B5.3 — Metadata reranker

`src/retrieval/rerank.py`:

```python
final_score = (
    cosine_sim
    + 0.10 * (authority_rank / 100)        # Finlex > Vero
    + 0.05 * recency_signal                # newer publication_date helps
    - 0.50 * (1 if not usable else 0)      # heavily penalize repealed
    + 0.05 * exact_term_bonus              # query terms in node title
)
```

Weights are starting points. Tune against the evaluation set in Step 6.

This single step typically moves quality more than anything else in v1 — without it, current Finlex law sits at equal rank with old Vero guidance.

### B5.4 — Context assembly with relationship annotations

`src/retrieval/assemble.py` takes the reranked top-N (start at N=8) and builds the LLM prompt context.

**Annotated context (Layer 5) is mandatory, not optional.** A flat list of chunks lets the LLM treat sources as independent. Inline cross-references between sources are what make the LLM reason about the *graph*, not just the *nodes*.

Even at v1 (vector-only retrieval), if two retrieved nodes are connected by an edge in the graph store, that edge is rendered in the context. At v2 this becomes far richer because expansion follows edges explicitly.

```
[Source 1] Finlex · AVL § 114 (in force, authority_rank=100)
  Path: Arvonlisäverolaki > Luku 10 > § 114
  Cites: §117 AVL  → [Source 3]
  Interpreted by: Vero 2019 → [Source 2]

  Edustusmenoja koskeva vähennysrajoitus...

[Source 2] Vero guidance — Mainoslahjat ja edustuslahjat (2019-04-12, authority_rank=60)
  Path: Arvonlisäverotus > Edustusmenot
  Interprets: §114 AVL → [Source 1]

  Tavanomaisena mainoslahjana pidetään...

[Source 3] Finlex · AVL § 117 (in force, authority_rank=100)
  Path: Arvonlisäverolaki > Luku 10 > § 117
  Cited by: §114 AVL ← [Source 1]

  Jos verovelvollinen käyttää...
```

Three things to notice:

- **Edges between sources are rendered with their type and direction** (`Cites: → [Source 3]`, `Interprets: [Source 1]`, `Cited by: ← [Source 1]`)
- **Authority rank is in the source header**, not buried in metadata — the LLM and the Verifier both need it
- **The `[Source N]` label is the LLM's stable handle** for citations in the answer

For v1, only edges where *both* endpoints are in the retrieved set get rendered. For v2 (when graph expansion is on), edges to nodes one hop outside the set may also be rendered as "referenced but not retrieved" hints (low value at v1, very useful at v2).

### B5.4b — Path tracking (Layer 8)

Every retrieved node carries provenance: how it ended up in the result set. At v1 every node was a direct vector hit, so the path is trivial. At v2 the path becomes the BFS chain.

The `AnswerResult` returned by the pipeline carries a `retrieval_paths` dict:

```python
{
    "source_1": {"via": "vector", "score": 0.81},
    "source_2": {"via": "vector", "score": 0.72},
    "source_3": {"via": "vector", "score": 0.65},
    # at v2 some entries become e.g.
    # "source_4": {"via": "graph", "from": "source_1", "edge": "cites", "hops": 1},
}
```

This is consumed by the UI to show "how was this source reached?" — and by the eval harness in Step 6 to score retrieval quality.

### B5.5 — Generation prompt

`src/retrieval/generate.py` constructs the LLM call.

System prompt (sketch):
> You are a Finnish tax-regulation research assistant. Answer using only the provided sources. Cite each claim with `[Source N]`. Finlex statutes are binding; Vero guidance is interpretive — if Vero guidance appears to conflict with a Finlex section, surface the conflict explicitly. If the sources are insufficient, say so — do not guess.

User prompt:
```
Question: {question}

Sources:
{assembled_context}

Answer:
```

Returns: answer text, list of cited source IDs.

### B5.6 — Glue

`src/retrieval/pipeline.py`:

```python
def answer(question: str) -> AnswerResult:
    """Full v1 pipeline: filter inference → vector retrieve → rerank → assemble → generate."""
```

`AnswerResult` carries the answer, cited source IDs, the full retrieved set (for evaluation), and per-stage timing.

### B5.7 — CLI

`scripts/ask.py "your question here"` — prints the answer, citations, and (with `--verbose`) the retrieved chunks. Use this constantly while developing.

## Done when

- CLI returns a Finnish answer with `[Source N]` inline citations
- Citations resolve to real chunks (and via `primary_node_id`, real nodes)
- Repealed-law filter works: query for "current VAT deduction rules" returns no `usable=false` chunks
- All 10 V5.1 baseline questions have been run through v1 and failure modes documented
