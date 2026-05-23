# Taxxa — Finnish legal RAG / GraphRAG

Query the Finnish tax-law corpus (Finlex statutes + KHO case law + Vero
guidance + treaties — 402,088 embedded chunks, 1.97M graph nodes) with one
of two retrieval pipelines:

- **v1** — vector-only baseline (cosine + metadata rerank)
- **v2** — GraphRAG: strategy router → vector seeds → graph expansion → rerank

Both share the same answer schema (`AnswerResult`) and the same Finnish
LLM generation step (DeepSeek-V4-Flash via Featherless).

## Quick start

```bash
# v1, full corpus, default flags
.venv/bin/python -m scripts.ask "Mikä on arvonlisäveron vähennysoikeus?"

# v2 / GraphRAG
.venv/bin/python -m scripts.ask --v2 "..."

# Standalone v1 runner (hard-coded to full store, ignores config flips)
.venv/bin/python -m scripts.ask_v1 "..."
```

The first run pulls the cross-encoder model from cache (~1.1 GB at
`~/.cache/huggingface/`). Set `HF_HUB_OFFLINE=1` to skip the hub
round-trip when the model is already local.

## The three entry points

| Command                                             | Pipeline           | Reranker                       | Default store          |
| --------------------------------------------------- | ------------------ | ------------------------------ | ---------------------- |
| `python -m scripts.ask "..."`                       | v1 (vector-only)   | metadata reranker (v1)         | full (`output/lancedb`)|
| `python -m scripts.ask --v2 "..."`                  | v2 (GraphRAG)      | cross-encoder + weighted combine | full                 |
| `python -m scripts.ask --v2 --rerank vector "..."`  | v2 (GraphRAG)      | v1 metadata reranker (post-expand) | full              |
| `python -m scripts.ask_v1 "..."`                    | v1 (vector-only)   | metadata reranker (v1)         | full (hard-coded)      |

The default store path lives in `src/retrieval/__init__.py:VECTOR_DB_PATH`.
`scripts.ask_v1` ignores that and pins the path itself, so a config
revert can't quietly silence it.

## One template per variation

```bash
# v1 (vector-only) — current default of scripts.ask
.venv/bin/python -m scripts.ask "Mikä on arvonlisäveron vähennysoikeus?"

# v2 / GraphRAG with cross-encoder rerank (the v2 default)
.venv/bin/python -m scripts.ask --v2 "Mikä on arvonlisäveron vähennysoikeus?"

# v2 / GraphRAG with vector-similarity rerank (skip the cross-encoder)
.venv/bin/python -m scripts.ask --v2 --rerank vector "Mikä on arvonlisäveron vähennysoikeus?"

# v1 standalone — same as scripts.ask but with the full store hard-coded
.venv/bin/python -m scripts.ask_v1 "Mikä on arvonlisäveron vähennysoikeus?"
```

Swap the question, add `--verbose` for diagnostics, or `--json` to feed
the UI/eval — every variation accepts the same flags.

## Side-by-side: `scripts.ask` vs `scripts.ask_v1`

Both run the same v1 pipeline. The difference is config behavior — `scripts.ask`
reads `VECTOR_DB_PATH` from `src/retrieval/__init__.py` (can be flipped
project-wide); `scripts.ask_v1` hard-codes the full store and is immune to
config drift. Use `scripts.ask_v1` when you want a known-good baseline.

### Plain question

```bash
.venv/bin/python -m scripts.ask    "Mikä on pääomatulon verokanta?"
.venv/bin/python -m scripts.ask_v1 "Mikä on pääomatulon verokanta?"
```

### Verbose — filters, top-10 reranked, full context, citations

```bash
.venv/bin/python -m scripts.ask    --verbose "Onko ALV vähennyskelpoinen edustuskuluista?"
.venv/bin/python -m scripts.ask_v1 --verbose "Onko ALV vähennyskelpoinen edustuskuluista?"
```

### JSON output (for the demo UI or eval pipelines)

```bash
.venv/bin/python -m scripts.ask    --json "Verovapaa lahja perintöverotuksessa" > /tmp/v1a.json
.venv/bin/python -m scripts.ask_v1 --json "Verovapaa lahja perintöverotuksessa" > /tmp/v1b.json

# They should match (same pipeline, same defaults now that the config is fixed)
jq -r '.cited_source_ids[]' /tmp/v1a.json
jq -r '.cited_source_ids[]' /tmp/v1b.json
```

### Tuning retrieval depth and context size

```bash
# Wider candidate pool, more sources in the LLM context
.venv/bin/python -m scripts.ask    -k 50 -n 12 "Yrityksen sukupolvenvaihdoksen veroseuraamukset"
.venv/bin/python -m scripts.ask_v1 -k 50 -n 12 "Yrityksen sukupolvenvaihdoksen veroseuraamukset"

# Smoke test with tiny context
.venv/bin/python -m scripts.ask    -k 5 -n 3 "..."
.venv/bin/python -m scripts.ask_v1 -k 5 -n 3 "..."
```

### Switching stores

```bash
# Both can be pointed at the pilot for a fast smoke run
.venv/bin/python -m scripts.ask    --db output/lancedb_pilot "..."
.venv/bin/python -m scripts.ask_v1 --db output/lancedb_pilot "..."

# Or at the full store explicitly
.venv/bin/python -m scripts.ask    --db output/lancedb "..."
.venv/bin/python -m scripts.ask_v1 --db output/lancedb "..."
```

### Different graph store path

```bash
.venv/bin/python -m scripts.ask    --graph-db /path/to/other.db "..."
.venv/bin/python -m scripts.ask_v1 --graph-db /path/to/other.db "..."
```

### Convenience: an English-tax-glossary mini sweep

```bash
for Q in \
  "What is the Finnish capital gains tax rate?" \
  "Mikä on perintöveron veroluokka?" \
  "Define permanent establishment in Finnish tax law" \
  "Yleishyödyllisen yhteisön verovapauden edellytykset"
do
  echo "=== $Q (scripts.ask) ==="
  .venv/bin/python -m scripts.ask --json "$Q" | jq -r '.answer'
  echo "=== $Q (scripts.ask_v1) ==="
  .venv/bin/python -m scripts.ask_v1 --json "$Q" | jq -r '.answer'
done
```

---

## v2 / GraphRAG examples (only `scripts.ask` supports `--v2`)

`scripts.ask_v1` is v1-only by design — to use the graph-expansion
pipeline, run `scripts.ask --v2`.

### 1. Basic Finnish tax question (v1, vector-only)

```bash
.venv/bin/python -m scripts.ask "Mikä on pääomatulon verokanta?"
```

Output: answer with `[Source N]` citations, the actual chunk_ids cited,
applied filters, per-stage timing.

### 2. Same question via v2 GraphRAG with cross-encoder

```bash
.venv/bin/python -m scripts.ask --v2 "Mikä on pääomatulon verokanta?"
```

v2 adds graph expansion (`pick_strategy → expand → cross-encoder rerank`)
on top of the v1 retrieval seeds. Default rerank is the multilingual
`BAAI/bge-reranker-v2-m3` cross-encoder.

### 3. v2 GraphRAG with vector-similarity rerank (no cross-encoder)

```bash
.venv/bin/python -m scripts.ask --v2 --rerank vector "..."
```

Same graph expansion, but skips the cross-encoder. Every candidate
(seeds + graph-expanded) is rescored with v1's full metadata reranker
(cosine + authority + recency + term bonus − repealed penalty). Useful
to isolate whether the cross-encoder is helping or hurting.

### 4. Verbose mode — see filters, reranked top-10, assembled context

```bash
.venv/bin/python -m scripts.ask --verbose "..."
.venv/bin/python -m scripts.ask --v2 --verbose "..."
.venv/bin/python -m scripts.ask --v2 --rerank vector --verbose "..."
```

For v2, verbose also shows the picked strategy and graph expansion stats
(seeds → BFS reach → fetched chunks → final candidate pool).

### 5. JSON output (for the demo UI or eval harness)

```bash
.venv/bin/python -m scripts.ask --json "..." > result.json
.venv/bin/python -m scripts.ask --v2 --json "..." > result_v2.json
```

Emits the full `AnswerResult` schema — `answer`, `cited_source_ids`,
`retrieved_chunks`, `retrieval_paths`, `assumptions`, `timing_ms`,
`conflicts`.

### 6. Side-by-side compare — v1 vs v2 modes on one question

```bash
Q="KHO ratkaisu arvonlisäveron vähennysoikeudesta"

echo "=== v1 ==="
.venv/bin/python -m scripts.ask                           "$Q"

echo "=== v2 cross-encoder ==="
.venv/bin/python -m scripts.ask --v2 --rerank cross_encoder "$Q"

echo "=== v2 vector-only rerank ==="
.venv/bin/python -m scripts.ask --v2 --rerank vector       "$Q"
```

Diff the `cited_source_ids` (with `--json | jq`) to spot regressions.

### 7. Each routing strategy in v2 (so you can see different graph behaviors)

```bash
# case_law — triggers on KHO / KVL / "tapaus" / "ennakkoratkaisu"
.venv/bin/python -m scripts.ask --v2 --verbose "KHO ratkaisu osakeyhtiön sukupolvenvaihdoksesta"

# definition — triggers on "määritelmä" / "tarkoittaa"
.venv/bin/python -m scripts.ask --v2 --verbose "Mitä tarkoittaa kiinteä toimipaikka verotuksessa?"

# multi_hop — triggers on "poikkeus" / "kuitenkin" / "however"
.venv/bin/python -m scripts.ask --v2 --verbose "Arvonlisäveron vähennysoikeuden poikkeukset"

# recency — triggers on "voimassa" / "kumottu" / "current"
.venv/bin/python -m scripts.ask --v2 --verbose "Onko tämä laki yhä voimassa?"

# cross_source — triggers on Finlex citation + guidance marker co-occurrence
.venv/bin/python -m scripts.ask --v2 --verbose "Vero-ohje tuloverolain 28 § soveltamisesta"

# default (no trigger) — v2 still runs cross-encoder over vector seeds, no graph walk
.venv/bin/python -m scripts.ask --v2 --verbose "Pääomatulon verokanta yli 30000 euron tuloista"
```

### 8. Override the vector store (e.g. quick smoke test against the pilot)

```bash
# Pilot (1000 chunks, ~0.25 % of corpus — quick but limited)
.venv/bin/python -m scripts.ask --db output/lancedb_pilot "..."

# Explicit full store
.venv/bin/python -m scripts.ask --db output/lancedb "..."

# scripts.ask_v1 ignores --db default flips; pass --db to override its hard-coded default
.venv/bin/python -m scripts.ask_v1 --db output/lancedb_pilot "..."
```

### 9. Tuning the v1 pipeline

```bash
# Wider candidate pool, more sources in the LLM context
.venv/bin/python -m scripts.ask -k 50 -n 12 "..."
```

`-k` is the vector retrieval depth (default 20). `-n` is how many
deduped-by-section sources end up in the LLM context (default 8).

In v2 `-k` is ignored — the strategy's `seed_k` controls vector depth
instead (10 by default per strategy in `src/retrieval/strategy.py`).

### 10. Force a specific v2 strategy from Python (ablation)

```bash
.venv/bin/python - <<'PY'
from src.retrieval.pipeline_v2 import answer_v2
from src.retrieval.strategy import MULTI_HOP, CASE_LAW, DEFINITION, CROSS_SOURCE, RECENCY

r = answer_v2(
    "your question",
    vector_db_path="output/lancedb",
    rerank_mode="vector",                  # or "cross_encoder"
    strategy_override=CASE_LAW,            # bypass the keyword router
)
print(r.answer)
print("strategy:", r.assumptions[0])
print("timing:", r.timing_ms)
PY
```

## Flag reference

### `scripts.ask` (both v1 and v2)

| Flag | Default | Description |
|------|---------|-------------|
| `question` (positional) | — | The question (Finnish or English) |
| `--v2` | off | Use the v2 GraphRAG pipeline |
| `--rerank {cross_encoder,vector}` | `cross_encoder` | v2 reranker mode (ignored for v1) |
| `--db PATH` | from `src/retrieval/__init__.py` | LanceDB directory |
| `--graph-db PATH` | `output/graph.db` | SQLite graph store |
| `-k N` | 20 | v1 vector retrieval depth (v2 uses strategy.seed_k) |
| `-n N` | 8 | Sources assembled into LLM context |
| `--verbose`, `-v` | off | Show filters, reranked hits, full context, citations |
| `--json` | off | Emit the `AnswerResult` as JSON |

### `scripts.ask_v1` (v1 only, standalone)

| Flag | Default | Description |
|------|---------|-------------|
| `question` (positional) | — | The question (Finnish or English) |
| `--db PATH` | `output/lancedb` (hard-coded) | LanceDB directory |
| `--graph-db PATH` | `output/graph.db` | SQLite graph store |
| `-k N` | 20 | Vector retrieval depth |
| `-n N` | 8 | Sources assembled into LLM context |
| `--verbose`, `-v` | off | Show filters, reranked hits, full context, citations |
| `--json` | off | Emit the `AnswerResult` as JSON |

## Environment

```bash
# Required keys live in .env at the project root (already gitignored)
VOYAGE_API_KEY=...        # embeddings + query encoding
FEATHERLESS_API_KEY=...   # DeepSeek-V4-Flash for generation

# Optional: skip HuggingFace hub round-trips when the cross-encoder model is cached
export HF_HUB_OFFLINE=1
```

## Where to go deeper

- `our-docs/changelog/` — per-step build journals
- `our-docs/05_retrieval_v1_vector_only.md` — v1 spec
- `our-docs/07_retrieval_v2_graph_traversal.md` — v2 / GraphRAG spec
- `src/retrieval/` — pipeline implementation
- `findings/` — pilot results, baseline failures, sanity reports
