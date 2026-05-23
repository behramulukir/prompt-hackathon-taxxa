# Out-of-corpus reference surfacing — Design

> Show the dataset's edges as honestly as its center. When a retrieved source cites something that lives outside the hackathon corpus (EU directive, government bill, KHO case, statute not yet loaded), surface it instead of silently dropping it.
>
> This turns Step 2's `dangling_edges.log` from a diagnostic artifact into a user-visible *limitation panel* — directly addressed to the challenge providers.

## Motivation

`output/edge_stats.json` currently logs ~57k dangling edges, ~23k of them `out_of_corpus` (EU/HE/KHO/older statutes). They are extracted, typed, and normalized by Step 2, then excluded from `graph.db` by design (`our-docs/04_embedding_and_indexing.md:251`). The retrieval pipeline never sees them, so the user never sees them.

For a hackathon judged on agentic GraphRAG, surfacing what the system *knows it doesn't know* — per query, with classification — is high signal:

- proves the extraction pipeline is more thorough than the loaded graph suggests
- frames coverage gaps as bounded and named (EU, HE, KHO, older säädöskokoelma) instead of unknown
- gives the Verifier a hook for *"this rule transposes an EU directive whose text I don't have"*

## Scope

- **In:** per-query surfacing of dangling refs reachable from the retrieved (and graph-expanded) source set.
- **Out:** corpus-wide stats dashboard, live fetch from Finlex/EUR-Lex, resolving `not_yet_parsed` at query time (already handled offline by `scripts/relink_year_number.py`).

## What "out-of-corpus" means for the UI

Two of the three `DanglingReason` values are surfaceable; one is not.

| Reason | Surface? | UI class |
|--------|----------|----------|
| `out_of_corpus` | yes — primary case | EU directive · Government bill · KHO case · Other external |
| `not_yet_parsed` | yes — labeled separately as "in scope but not loaded" | Statute not in dataset |
| `normalization_failed` | **no** — internal bug, route to `findings/`, never to user | — |

The two surfaced reasons map to different demo narratives. `out_of_corpus` is *"outside the dataset by design"*. `not_yet_parsed` is *"we extracted it, scoped it as Finnish, just didn't ingest it"* — useful because it shows the pipeline already has a hook to absorb more data without code changes.

## Backend

### B-OC.1 — Side-loaded dangling table

`output/dangling_edges.log` is not loaded into `graph.db` today (intentional: keeps the partial index on `edges.target_id` clean, keeps `verify_graph.py` strict). Don't break that. Add a **separate table** in the same SQLite file:

```sql
CREATE TABLE dangling_edges (
    source_id   TEXT NOT NULL,
    target_ref  TEXT NOT NULL,
    type        TEXT NOT NULL,
    extracted_by TEXT NOT NULL,
    dangling_reason TEXT NOT NULL,
    context_snippet TEXT,
    ref_class   TEXT NOT NULL,        -- see classifier below
    FOREIGN KEY (source_id) REFERENCES nodes(id)
);
CREATE INDEX idx_dangling_source ON dangling_edges(source_id);
CREATE INDEX idx_dangling_class  ON dangling_edges(ref_class);
```

Loader: extend `scripts/load_graph.py` with a 6th step ("load dangling refs") that streams `dangling_edges.log`, computes `ref_class` per row, bulk-inserts. Reject the load if `verify_graph.py` finds a `source_id` that doesn't resolve (same invariant as resolved edges).

### B-OC.2 — Ref class classifier

`src/extraction/classify_dangling.py`. Deterministic regex on `target_ref` + `dangling_reason`. Run once at load time, stored on the row (no runtime cost):

| `ref_class` | Rule |
|-------------|------|
| `eu_directive` | `target_ref` matches `\d{4}/\d{1,4}/(EY\|EU\|ETY)` or starts with `https?://eur-lex` |
| `government_bill` | matches `^HE \d+/\d{4}` |
| `kho_case` | matches `^KHO \d{4}:\d+` or contains `/kho/` |
| `statute_not_loaded` | matches `^https://www\.finlex\.fi/akn/fi/act/statute/\d{4}/\d+` AND `dangling_reason='not_yet_parsed'` |
| `other_external` | everything else with `dangling_reason='out_of_corpus'` |
| `other_unloaded` | everything else with `dangling_reason='not_yet_parsed'` |

Verification: run the classifier over the full log, assert that no class is empty (sanity), no row falls into a default bucket > 5% of total (would indicate a missing rule).

### B-OC.3 — Model addition

Add to `src/models.py` (extends [[models-py-instruction]]):

```python
RefClass = Literal[
    "eu_directive", "government_bill", "kho_case",
    "statute_not_loaded", "other_external", "other_unloaded",
]

@dataclass(frozen=True)
class DanglingRef:
    """A reference extracted from a source node whose target is not in the
    loaded corpus. Surfaced to the user when the source is in the retrieved set."""

    source_id: str            # the retrieved node that mentions it
    target_ref: str           # the raw citation, normalized
    type: EdgeType            # cites / transposes / ...
    ref_class: RefClass
    dangling_reason: DanglingReason
    context_snippet: str | None
```

`AnswerResult` (defined in [[retrieval-pipeline]]) gets one new field:

```python
out_of_corpus_refs: list[DanglingRef] = []
```

### B-OC.4 — GraphStore adapter method

`src/indexing/graph_store.py`:

```python
def get_dangling(
    self,
    source_ids: list[str],
    reasons: list[DanglingReason] | None = None,
    classes: list[RefClass] | None = None,
) -> list[DanglingRef]:
    """Return dangling refs whose `source_id` is in the given set,
    optionally filtered by reason and ref_class. O(|source_ids|) with the
    idx_dangling_source index."""
```

Single SQL query with `WHERE source_id IN (...)`. No traversal — we never expand *through* dangling refs.

### B-OC.5 — Pipeline integration

`src/retrieval/pipeline.py` (v1) and `src/retrieval/pipeline_v2.py` (v2): after `assemble`, before `generate`, collect dangling refs from the assembled source set:

```python
retrieved_ids = [n.id for n in reranked[:N]]
result.out_of_corpus_refs = graph_store.get_dangling(
    retrieved_ids,
    reasons=["out_of_corpus", "not_yet_parsed"],
)
```

**Do not feed dangling refs into the LLM prompt body.** They are *metadata about the answer*, not content the LLM should reason over. Surfacing them in the prompt risks the model hallucinating their contents. The UI consumes them from `AnswerResult` directly.

One exception: in the assembled context block (Layer 5, [[retrieval-v1#B5.4]]), append a single line per retrieved source listing its dangling refs by `target_ref` only:

```
[Source 1] Finlex · AVL § 102 (in force, authority_rank=100)
  Path: Arvonlisäverolaki > Luku 10 > § 102
  Interpreted by: Vero 2019 → [Source 2]
  External references (full text not in corpus): 2006/112/EY · HE 88/1993
  ...
```

This lets the generator say *"§ 102 transposes EU directive 2006/112/EY (not available in the dataset)"* instead of inventing the directive's contents.

### B-OC.6 — Agent wiring

- **Verifier** ([[agentic-workflow#B8.4]]) treats an `out_of_corpus` ref of type `transposes` to an EU directive as a documented epistemic gap, not a conflict. It can flag the answer with *"depends on EU source not in dataset"* — a third callout class alongside conflicts and unsupported claims.
- **Extractor** ([[agentic-workflow#B8.3]]) skips dangling refs from the write-back path (they're already in the log; re-extracting them adds noise).
- **Clarifier** is unaffected.

## Frontend

### F-OC.1 — Strip placement

Add an `OutOfCorpusStrip` component to the memo column, between the inline memo footer and the composer. Always rendered — hidden visually when the count is zero, but the contract is *"this answer was checked against the limitation set."*

Closed state — one line:

```
External references touched but not in corpus  ·  2 EU directives  ·  1 government bill  ·  1 older statute     [expand ▾]
```

Open state — grouped list, one section per `ref_class` that has hits, each item showing `target_ref` and a link to the citing `[Source N]`:

```
EU directives (2)
  · 2006/112/EY      cited by [Source 1] AVL § 102          (transposes)
  · 2008/118/EY      cited by [Source 1] AVL § 102          (cites)

Government bills (1)
  · HE 88/1993       cited by [Source 3] AVL § 117          (cites)

Statutes not in dataset (1)
  · 1559/2001        cited by [Source 1] AVL § 102          (cites)
```

The right-hand chip on each row is the edge type — `transposes` reads very differently from `cites`, and that distinction is the whole point of typed edges. Reuse the citation-pill component already in [[hybrid-cinematic-concept]].

### F-OC.2 — Reasoning panel updates

Two small additions, both deliberately minor — the strip below the memo is the load-bearing surface; the reasoning panel only echoes the count.

1. **Run budget footer** gains a fifth cell: `External: N` next to `Conflicts: N`.
2. **Graph block**: ghost nodes (already in the design as faded gray peripheral dots, [[hybrid-cinematic-concept#graph-block]]) gain a class distinction — `out_of_corpus` neighbors render with a small `↗` glyph to signal "exists but lives outside the dataset boundary." `not_yet_parsed` neighbors render with `…` to signal "in scope, not loaded." `not-traversed` in-corpus neighbors stay as plain dots.

The legend at the bottom of the graph block expands to four entries: Finlex · Vero · Not traversed · External (`↗`/`…`).

### F-OC.3 — Color and copy

- Strip background: neutral surface (the same as the memo footer). **Not** amber. Amber is reserved for authority conflicts ([[hybrid-cinematic-concept#color-and-source-semantics]]); reusing it here dilutes the conflict-callout signal.
- Strip header tooltip: *"These references appear in retrieved sources but their full text is outside the provided hackathon dataset (Finlex + Vero). They were extracted and classified at ingestion time — they just aren't ingested."*
- Per-row tooltip on `ref_class`:
  - `eu_directive` — *"EU legal source. Out of scope by design."*
  - `government_bill` — *"Finnish government bill (HE). Out of scope by design."*
  - `kho_case` — *"Finnish Supreme Administrative Court decision. Out of scope by design."*
  - `statute_not_loaded` — *"Finnish statute. In scope; not in the current dataset slice. Would resolve automatically if loaded."*

The wording matters for the audience: phrases like *"out of scope by design"* vs *"would resolve if loaded"* tell the challenge providers which gaps are intentional vs which are coverage they could close.

### F-OC.4 — Cinematic timeline integration

Add one beat to the choreography ([[hybrid-cinematic-concept#animation-choreography]]), after Verifier (t≈6.9–7.1s), before memo stream (t≈7.1s):

| Time (s) | Phase | Visible action |
|----------|-------|----------------|
| 7.0–7.1 | External-refs | Strip slides up under the (empty) memo area with the closed-state count populated. Run-budget `External` cell ticks 0 → N. |

Total cinematic length unchanged — this beat fits inside the existing gap between Verifier completion and memo streaming. No new agent row in the timeline; this is a derived view of the retrieval set, not an agent.

## Demo narrative

One sentence to add to the suggested demo arc ([[hybrid-cinematic-concept#suggested-demo-arc]]), step 4 (Skip → final state):

> "Notice the strip below the memo: this answer leans on AVL § 102, which transposes EU directive 2006/112/EY. We didn't have the directive's text in the dataset, so we name it explicitly instead of pretending it doesn't exist."

This is the moment that earns the *"agentic + honest"* framing in front of judges. Don't cut it for time.

## Caps and noise control

A query that lands on widely-cited statutes can drag in dozens of dangling refs.

- **Per-class cap in the open state: top-5 by frequency**, with a "+N more" expander. Sort within class by mention count across the retrieved set, then by `target_ref` lexically.
- **Hard cap on the strip header counts**: if total > 50, show `"50+"` and gate behind the expander.
- **Suppress if every retrieved source has the same single ref** (common for narrow EU-transposition queries) — collapse to one line: *"All retrieved sources reference EU directive 2006/112/EY (not in dataset)."*

The cap rules are conservative on purpose: if the strip is louder than the memo, judges read it as the system being broken, not transparent.

## Eval

Add to [[evaluation-harness]] a per-question column: `out_of_corpus_refs_count`. Inspect manually after the v2 eval run:

- Categories where the count is consistently >0: EU-transposing statutes (AVL chapters touching VAT directives), older säädöskokoelma references. Expected.
- Categories where the count is consistently 0: pure Vero-guidance queries, modern non-EU-touching statutes. Expected.
- Outliers either way deserve a one-line note in `findings/out_of_corpus_eval.md`.

No quantitative target — this is a transparency feature, not a metric to optimize.

## Done when

- `dangling_edges` table exists in `graph.db`, classified, indexed.
- `GraphStore.get_dangling` works end-to-end; smoke test on a known EU-transposing statute (`AVL § 102` or similar) returns its EU directive refs.
- `AnswerResult.out_of_corpus_refs` populated by both v1 and v2 pipelines.
- `OutOfCorpusStrip` renders on the memo column, closed and open states both styled.
- For the cinematic demo question, the strip shows ≥1 EU directive and ≥1 statute-not-loaded ref, with type chips correct.
- Run-budget `External` counter ticks during the cinematic.
- `findings/out_of_corpus_eval.md` written with manual category-level observations.

## Open questions

- Should the strip be visible by default in non-cinematic, follow-up answers, or hidden behind a toggle to keep the chat compact? Default: visible (closed state is one line, low cost).
- Should `kho_case` refs be promoted out of `other_external` even though KHO is technically ingested? The corpus has KHO nodes (`Source = "kho"`), so most KHO refs should resolve — those that *don't* are noise (citation form not matched). Decision: keep them in `kho_case` class but watch the count during eval; if >10% of total it's a normalization bug, not a coverage gap.

## File scope

This document defines intent and contract. Implementation lives in:

- `src/extraction/classify_dangling.py` (new)
- `src/indexing/graph_store.py` (extend with `get_dangling`)
- `src/models.py` (add `RefClass`, `DanglingRef`, extend `AnswerResult`)
- `scripts/load_graph.py` (load `dangling_edges` table)
- `src/retrieval/pipeline.py` and `pipeline_v2.py` (populate `out_of_corpus_refs`)
- `src/retrieval/assemble.py` (one-line external-refs annotation per source)
- `web/` — new `OutOfCorpusStrip` component, run-budget cell, graph-block legend update
