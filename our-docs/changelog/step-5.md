# Step 5 — Retrieval v1 (vector-only baseline) (done)

Built Step 5 per `05_retrieval_v1_vector_only.md` and the Track D brief in
`parallel_execution_after_step4.md`. The end-to-end loop now works:
a Finnish (or English) question goes in, an annotated `AnswerResult` with
`[Source N]` citations comes out. This is the baseline Step 7 has to beat.

## What was built

```
src/retrieval/
├── __init__.py                  # re-exports + VECTOR_DB_PATH config
├── filters.py                   # B5.1 — keyword filter inference
├── vector_retriever.py          # B5.2 — wraps VectorStore.search_by_text
├── rerank.py                    # B5.3 — metadata reranker
├── assemble.py                  # B5.4 — annotated context (Layer 5)
├── generate.py                  # B5.5 — DeepSeek via Featherless + citation parsing
└── pipeline.py                  # B5.6 — glue → AnswerResult

scripts/
└── ask.py                       # B5.7 — CLI front-end

findings/
└── 05_baseline_failures.md      # V5.1 — 10-question diagnosis
```

## Pipeline (single runner)

```
question
  → infer_filters          # keyword → {usable, in_force, source, language}
  → retrieve k=20          # VectorStore.search_by_text, input_type="query"
  → rerank                 # cosine + 0.10·auth + 0.05·rec + 0.05·term − 0.50·repealed
  → assemble n=8           # dedup by section_id, Layer-5 edges from GraphStore
  → generate               # DeepSeek-V4-Flash on Featherless, [Source N] citations
  → AnswerResult           # schema-locked; src/models.py untouched
```

All five sub-files are independently unit-testable; only `generate` and
`pipeline.answer` require the Featherless API key.

## What this baseline validates

This is *plumbing-complete*, not *quality-complete*. The 10-question
diagnosis in `findings/05_baseline_failures.md` confirms:

- Asymmetric query embedding (`input_type='query'`) runs cleanly through
  the existing `voyage_client`.
- Filter inference fires correctly on real queries: `usable+in_force`
  triggered by "current", `language=fi` triggered by "Finnish tax
  guidance", `source` triggered by Finlex/Vero mentions.
- Rerank correctly demotes treaty chunks of equal rank by recency and
  promotes higher-authority Finlex over equal-cosine Vero. Repealed
  chunks (`usable=False`) get the prescribed −0.50 penalty and sink.
- Layer-5 edge rendering runs end-to-end against `graph.db` —
  `Cites: → [Source N]`, `Amended by: ← [Source M]`, etc., between
  sections that landed together in the retrieved set. Confirmed against
  a real AVL § 114 amendment pair pulled from `graph.db`.
- Citation parser handles `[Source N]`, `[Source N, kappale M]`,
  mixed case, and adjacency (`[Source 1][Source 2]`).
- The pipeline returns a schema-locked `AnswerResult` with
  `retrieval_paths` (keyed by chunk_id), `timing_ms` per stage, and
  `assumptions` derived from the applied filters. UI-ready.

## V5.1 — 10-question baseline run

10 questions from `eval/questions.json` (5 basic + 3 medium + 2 hard) run
through the full pipeline against the **1000-chunk pilot store** and the
full `graph.db`:

| ID  | Tier   | Right answer? | Right chunk in top-3? | Primary failure mode |
|-----|--------|---|---|---|
| Q1  | basic  | yes | yes (#2 KHO) | — |
| Q3  | basic  | refusal | no  | pilot miss |
| Q4  | basic  | refusal | no  | pilot miss |
| Q6  | basic  | **hallucinated** | no | pilot miss + LLM prior |
| Q8  | basic  | refusal | no  | pilot miss |
| Q11 | medium | refusal | no  | pilot miss |
| Q15 | medium | refusal | no  | pilot miss |
| Q17 | medium | refusal | no  | pilot miss + LLM citation inflation |
| Q34 | hard   | partly  | yes (#6 Ireland, demoted) | rerank ties on authority_rank |
| Q35 | hard   | yes  | yes (#1) | — |

The dominant failure mode is **"the right chunk is not in the 1000-chunk
pilot at all"** (cos=0.000 on the top hits for 6/10 questions). This is
expected — the pilot is 0.02% of the corpus. Re-run against
`output/lancedb/` when the full embed finishes; the only code change
needed is flipping `VECTOR_DB_PATH` in `src/retrieval/__init__.py`.

## Bugs caught and fixed during the V5.1 run

**1. Citation regex rejected `[Source N, kappale M]`.** DeepSeek
commonly adds paragraph qualifiers inside the brackets ("Source 2,
kappale 58"). The original regex required `]` immediately after the
digit. Widened to accept any trailing content up to `]` while still
requiring a word boundary after the digit (so `[Source 12abc]` is still
rejected). See `src/retrieval/generate.py:_CITE_RE`.

**2. `.env` typo (`FEATHERLRESS_API_KEY`).** Found by a key-only probe
of `.env`. User corrected. The loader (mirrors
`voyage_client._load_api_key`) reads from process env first, then `.env`.

## Decisions and tradeoffs

### Vector store path is a config variable (`VECTOR_DB_PATH`)

Defaults to `output/lancedb_pilot/`. One-line flip in
`src/retrieval/__init__.py` switches to `output/lancedb/` once Step 4a
finishes. The pipeline, CLI, and `AnswerResult` shape are corpus-size
agnostic — only the *eval numbers* will change.

### Path and Title parsed out of `embedded_text`, not loaded from node index

The brief's example header carries `Path: Arvonlisäverolaki > Luku 10 > § 114`
and `Title: Vähennysoikeus`. Building those at assembly time from
`nodes_enriched.jsonl` would peak ~1.5–2 GB of RAM via `build_node_index`.
The LanceDB row already carries `embedded_text` (composed at Step 4a),
which contains both lines verbatim. Assembler regex-extracts them
instead. Trade: assembler is coupled to the `text_composition.py` prefix
format. If that format changes, two regexes in `assemble.py` need to
match.

### `effective_date` filter dropped for v1

The brief's example "as of 2024 → effective_date <= 2024 AND
(repeal_date is null OR repeal_date > 2024)" can't be filtered at the
LanceDB layer — `effective_date` lives only on `NodeMetadata`, not on
`VectorRecord`. v1 infers only filters present in `VectorRecord`:
`usable`, `in_force`, `source`, `language`. Year-as-of inference is
returned alongside (`infer_as_of_year`) but unused by the LanceDB
prefilter; the reranker could use it later. Year-aware filtering is
deferred to the Clarifier in Step 8 (the brief explicitly recommends
this).

### `chunk_id` everywhere in `AnswerResult`

`MockPipeline` used section-shaped strings (`finlex_laki/avl/s114`),
which conflated chunk IDs and node IDs. v1 uses **`chunk_id`
consistently** for `retrieved_chunks`, `cited_source_ids`, and
`retrieval_paths` keys (i.e. with `#0` suffix). At v2, graph-expanded
nodes will land in `retrieval_paths` keyed by `node_id` — mixed keying
is allowed by the schema docstring.

### Dedup by `section_id` at assembly, not in rerank

Two chunks of the same section can land in top-k. Keeping both creates
near-duplicate `[Source N]`s in the LLM context and measurably hurts
citation accuracy. Assembler keeps only the best-scoring chunk per
section before rendering. `N=8` in `assemble.assemble` is therefore "8
distinct sections", not "8 chunks".

### v1 renders edges only between retrieved sections

Per B5.4: "For v1, only edges where both endpoints are in the retrieved
set get rendered." No one-hop "referenced but not retrieved" hints — that
is a v2 affordance once graph expansion is on. The four edge types
rendered are `cites`, `interprets`, `amends`, `defines`. `parent_of` is
suppressed (structural noise; every node has one).

### Exact-term bonus computed against `embedded_text`

Same logic as the Path/Title parsing — the title prefix is already in
the row. The rerank term bonus tests for any non-stopword query token in
the prefix line (i.e. the `[Source ...]`, `[Path ...]`, `[Title ...]`
block), not in the body. Restricting to the prefix avoids rewarding
generic vocabulary that appears in many chunks.

### `recency_signal` is relative to the freshest hit in the set, not absolute

`publication_date` of the freshest retrieved chunk anchors `1.0`;
linear decay to `0.0` at `RECENCY_HALFLIFE_DAYS=3650` (10 years).
Older-but-not-ancient guidance still gets a small positive recency,
which is the right shape for tax law where decade-old Vero ohjeet are
sometimes still authoritative.

### OpenAI SDK against Featherless base URL

Featherless exposes an OpenAI-compatible API at
`https://api.featherless.ai/v1`. Using the `openai` SDK with a custom
`base_url` keeps `generate.py` thin and mirrors the
`voyage_client.get_client` pattern (singleton + lazy init). Model slug
is a module-level constant (`MODEL = "deepseek-ai/DeepSeek-V4-Flash"`)
so the exact name can be corrected without touching call sites.

### Verbose CLI path duplicates the pipeline stages

`scripts/ask.py --verbose` re-runs `infer_filters → retrieve → rerank →
assemble → generate` explicitly so it can print each stage's
intermediate state. The non-verbose path uses `Pipeline.answer()`. This
duplicates ~10 lines but keeps the verbose printer honest about what's
actually happening inside the pipeline.

## Observations to act on at v2

The V5.1 run surfaced three pipeline-level issues worth a v2 fix, beyond
the obvious "wait for the full embed":

- **Citation inflation when the LLM refuses.** Q17 ended with the LLM
  citing six retrieved sources as it explained which were *not*
  applicable. The parser correctly recorded all six in
  `cited_source_ids`, but downstream "what did the LLM actually rely
  on?" analysis treats discussion mentions and load-bearing cites
  identically. **Prompt rule for v2:** "Only cite `[Source N]` for
  claims you make. Do not cite sources you are dismissing as
  inapplicable."
- **Authority_rank ties on parallel chunks.** Q34 had the
  Finland-Ireland treaty at rank #6 because all retrieved treaties were
  rank 90 and rerank picked the highest-cosine one (Greece), not the
  one matching the question's proper noun. **v2:** raise the term-bonus
  weight when a proper noun in the query matches a path segment, or add
  a separate proper-noun term match into the rerank composite.
- **Stale answer keys in `eval/questions.json`.** Q35 expects the
  10,000 € vähäisen toiminnan raja; the LLM correctly reports the live
  20,000 € figure from the Vero ohje. The answer key needs a refresh
  from a Finnish tax expert.

## How to run

```bash
# Single question (uses lancedb_pilot until full embed lands)
.venv/bin/python -m scripts.ask "Mikä on pääomatulon verokanta yli 30 000 euron osalta?"

# Verbose — show filters, reranked top-10, assembled context, citations
.venv/bin/python -m scripts.ask --verbose "..."

# JSON output for the UI
.venv/bin/python -m scripts.ask --json "..."

# Swap to the full vector store (one-line config flip is the alternative)
.venv/bin/python -m scripts.ask --db output/lancedb "..."

# Re-run the V5.1 baseline diagnosis after the full embed completes
# (questions are hardcoded in the diagnosis script; see findings/05_baseline_failures.md)
```

## Output artifacts

| file                                  | size | contents |
|---------------------------------------|-----:|----------|
| `findings/05_baseline_failures.md`    |  ~9 K | 10-question diagnosis |

No new persistent corpus artifacts — v1 is read-only over Step 1–4's
outputs.

## Sequencing notes

- **Track G (Demo UI)** can consume `AnswerResult.model_dump_json()`
  directly. `scripts/ask.py --json` produces it; the
  `retrieval_paths`, `assumptions`, and `timing_ms` fields are
  populated.
- **Track F (Graph expansion, Step 7)** consumes `GraphStore.bfs` —
  unchanged. v2's `pipeline_v2.py` will mirror this file's shape,
  inserting an expansion step between rerank and assemble.
- **Track H (Agents, Step 8)** consumes `AnswerResult` and may extend
  `conflicts` and `assumptions`. The v1 pipeline leaves both populated
  conservatively (`conflicts: []`, `assumptions:` from filter inference
  only).
- **Eval** is hackathon-scoped to demo questions (per
  `parallel_execution_after_step4.md`'s Track E rewrite). The V5.1
  10-question diagnosis is the only quantified output v1 produces.

## Open items (will close once full embed lands)

- [ ] Flip `VECTOR_DB_PATH` from `output/lancedb_pilot` to
      `output/lancedb` in `src/retrieval/__init__.py`
- [ ] Re-run V5.1 against the full store; replace the "pilot miss"
      diagnoses in `findings/05_baseline_failures.md` with the
      full-corpus retrieval verdict
- [ ] Refresh stale answer keys in `eval/questions.json` against the
      live corpus (Q35 at minimum)
