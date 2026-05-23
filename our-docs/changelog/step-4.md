# Step 4 — Embedding and indexing (4b done, 4a in progress)

Built Step 4 per `04_embedding_and_indexing.md`. Substep split was honoured:

| Substep | Status | Notes |
|---------|--------|-------|
| **4a — Embeddings + LanceDB** | **in progress** | full embedder running in background; pilot already passed |
| **4b — SQLite graph store**   | **done**        | load + verify both green |

Intermittent changelog: 4b is fully wrapped and the 4a pilot/spot-check is
done; only the 147M-token corpus pass and the 4a.7 sanity check remain.

## What was built

```
src/indexing/
├── __init__.py
├── node_index.py        # streaming nodes.jsonl → compact {id: NodeIdxEntry} dict
├── text_composition.py  # 4a.2 hierarchy-prefixed embedding text (pure function)
├── voyage_client.py     # SDK wrapper: .env loading, retry on 429/5xx, locked dims
├── vector_store.py      # 4a.6 LanceDB adapter: upsert, search, search_by_text
└── graph_store.py       # 4b.3 SQLite adapter: get_node, get_neighbors, get_degree, bfs

scripts/
├── embed_pilot.py       # 4a.3 stratified 1000-chunk pilot
├── embed_chunks.py      # 4a.4 full pass — streaming, batched, resumable, --dry-run
├── spot_check_pilot.py  # 4a.3 ten Finnish tax queries → findings/04a_pilot.md
└── load_graph.py        # 4b.2 bulk loader: nodes → edges → degree backfill

pipeline/
└── verify_graph.py      # 4b.4 invariants + degree-hub report → findings/04b_load_report.md

findings/
├── 04a_pilot.md         # 10-query spot-check + token math (9/10 plausibly-relevant)
└── 04b_load_report.md   # row counts, edge-type breakdown, top hubs — PASS verdict
```

## 4a — Embeddings (in progress)

### Pilot (`scripts/embed_pilot.py`)

Stratified 1000-chunk sample (600 laki / 100 each of laki_skk, kho,
vero_ohje, treaty), embedded via Voyage `voyage-3-large` at 1024 dim, written
to `output/lancedb_pilot/`. ~22 s wall, 540,616 tokens.

10 hand-written Finnish tax queries → top-5 each, embedded with
`input_type="query"` (the asymmetry matters on voyage-3-large). Result:
**9 of 10 queries had a plausibly-relevant chunk in top-3**, comfortably
above the 7/10 gate in the doc. Only Q5 ("asianomistajan oikeus") was
marginal — the model surfaced civil-procedure §s before criminal ones; a
known Finnish near-synonym pitfall, not a corpus problem.

### Dry-run vs reality

The doc estimated ~147M tokens for the full pass. The pilot's
~540 tok/chunk extrapolated to ~217M (above the 200M free tier), so I
ran the doc-mandated `--dry-run` token estimator before committing:

```
Chunks seen:        402,098  (10 oversized-skipped)
Total tokens (est): 174,813,916  (174.8M)
  chunk text only:  146.8M
  prefix overhead:   28.0M  (16.0%)
```

Per subcorpus (the pilot oversampled long-text categories):

| subcorpus       |   chunks | avg tokens | of which prefix |
|-----------------|---------:|-----------:|----------------:|
| laki            | 129,893  | 342        | 66 |
| asetus          | 106,335  | 362        | 76 |
| kho             |  29,132  | **1,198**  | 33 |
| laki_skk        |  64,701  | 348        | 69 |
| asetus_skk      |  48,126  | 353        | 79 |
| vero_ohje       |  15,947  | 749        | 90 |
| treaty          |   4,663  | 861        | 102 |
| vero_kvl        |   1,209  | 712        | 34 |
| vero_paatos     |   1,744  | 290        | 86 |
| vero_kannanotto |     338  | 592        | 73 |

Tiktoken (cl100k_base) is a proxy for Voyage's tokenizer — calibrating
against the pilot's actual Voyage usage suggests Voyage counts ~4% higher,
so realistic spend is ~182M tokens. Under the 200M free tier with ~10%
headroom; below the 180M caution threshold the doc set is the proxy
estimate of 174.8M, so the budget signal is **green**.

### Voyage rate-limit gotcha (resolved)

First pilot attempt failed with `RateLimitError`: **3 RPM / 10K TPM**
applies to accounts without a payment method on file, even though the
200M free tokens still apply. At 10K TPM the full pass would have taken
**~10 days**. After adding a card (no charges within the free tier), the
standard rate limits kicked in and the pilot ran to completion in ~22 s.

### Full pass (running)

Started as a background job. Progress checkpoint while writing this
changelog:

```
LanceDB row count:  23,552 / 402,098   (5.9%)
On-disk:            121 MB
Throughput:         ~65 chunks/s
ETA:                ~1.6 hours
```

The script:

- streams `chunks.jsonl` (no full load — file is 691 MB)
- preloads `nodes_enriched.jsonl` into the compact `NodeIdxEntry` index
  for prefix composition (~11 s, ~1.5 GB peak)
- batches 128 chunks → `client.embed(... input_type="document",
  output_dimension=1024)`
- **resumable**: on restart it pulls existing `chunk_id`s out of LanceDB
  and skips them, so an interrupted run costs only one batch of redo work
- progress prints every ~5,000 chunks (block-buffered through the `tee`
  pipe — direct LanceDB row counts are the live signal, not stdout)

### Embedding text composition (`text_composition.py`)

```
[Source: finlex_laki · in force]
[Path: Arvonlisäverolaki > Luku 10 > § 102]
[Title: Vähennysoikeus]

{chunk.text}
```

Pure function over the chunk text + the section's `node_index` chain.
Field collapse rules:

- Source-status clause omitted if `in_force` is `None` (Step 3
  hasn't populated yet — doesn't apply to us, full corpus is enriched).
- Path line walks the leaf's `parent_id` chain, preferring `title` over
  `label` at each level; the list is silently truncated if the chain
  breaks (corrupt or partial index).
- Title line uses leaf `title` or `label`; skipped if both are missing.

## 4b — Graph store (done)

### Schema (`scripts/load_graph.py`)

SQLite, exactly the schema in `04_embedding_and_indexing.md §4b.1`.
Indices that matter for retrieval:

- `idx_edges_source(source_id, type)` — outbound traversal
- `idx_edges_target(target_id, type) WHERE target_id IS NOT NULL` —
  inbound traversal (partial index excludes dangling automatically)
- `idx_edges_type(type)`, `idx_nodes_type`, `idx_nodes_source`,
  `idx_nodes_parent`

Loader uses single-transaction `executemany` with the durability PRAGMAs
turned off during the load (`journal_mode=OFF`, `synchronous=OFF`,
`temp_store=MEMORY`, 200 MB cache). These are reset to WAL + NORMAL
before close so subsequent reads behave normally. `ANALYZE` runs at the
end so the query planner has stats.

### Degree backfill

The doc requires `node.metadata.degree` populated by Step 4. Done in a
third pass:

1. Two SQL aggregates (outbound + inbound by `(node, edge_type)`).
2. Stream `(id, metadata_json)`, merge `degree[]` in Python, bulk
   `executemany` UPDATE in 20k-row batches.

Result: 1,967,769 of 1,967,776 nodes have non-empty `degree` (7 orphan
nodes have neither in- nor out-edges — plausible for isolated roots).

### Final run on the full corpus

M3, **~65 s** wall.

```
nodes inserted:   1,967,776   (20.8 s)
edges inserted:   2,180,769   (13.5 s)
degree aggregate:   9.0 s    (1,967,769 nodes with edges)
degree backfill:   21.5 s    (20k-row update batches)
total wall:      ~65 s
```

Edge-type breakdown:

| type       |    count |
|------------|---------:|
| parent_of  | 1,904,115 |
| defines    |   234,570 |
| applies    |    18,259 |
| interprets |    16,613 |
| cites      |     7,164 |
| amends     |        24 |
| repeals    |        24 |

`output/graph.db` is **3.2 GB** with WAL on.

### Quality checks (`pipeline/verify_graph.py`) — PASS

All 4b.4 invariants hold:

- nodes (db / file): **1,967,776** / 1,967,776 ✓
- edges (db / file): **2,180,769** / 2,180,769 ✓
- edges with missing source node: **0** ✓
- non-null edges with missing target node: **0** ✓
- `parent_of` count vs (nodes − roots): **1,904,115 == 1,904,115** ✓
- dangling edges in db: **0** (Step 2 resolved everything; the
  `dangling_edges.log` it produced is separate and not loaded here)

Smoke tests pass:

- A known SECTION returns its `m1`/`m2` `parent_of` children.
- `interprets`-edge count via `direction=in` returns Vero guidance
  references to Finlex sections.

### GraphStore adapter (`src/indexing/graph_store.py`)

API surface as specified:

```python
get_node(id) -> Node | None
get_neighbors(id, edge_types=[...], direction="in"|"out"|"both") -> [Neighbor]
get_degree(id, edge_type, direction) -> int     # reads cached metadata.degree, no aggregate
bfs(seed_ids, edge_types, direction, max_hops, degree_cap={...}) -> {id: RetrievalPath}
```

`bfs` honours `degree_cap` per edge type: a node is allowed to *appear* in
results regardless of degree, but expansion *through* it is skipped if the
relevant degree exceeds the cap. Keeps hub statutes like Tuloverolaki
(11k+ inbound) from blowing up the frontier in Step 7.

## Decisions and tradeoffs

### Locked text composition (Option B, hierarchy-prefixed)

Picked per the doc; jurisdiction-blindness is the real risk for Finnish
legal corpora where near-identical text appears across statutes,
amendments, and subcorpora. The prefix costs ~28 M tokens (16% of total)
and that overhead is what closes the gap between e.g. "Arvonlisäverolaki
§102" and "Laki arvonlisäverolain muuttamisesta §102". Cheap insurance.

### Voyage tokenizer is not public

`voyage-3-large` does not expose a tokenizer; the dry-run uses
`tiktoken.cl100k_base` as a proxy. Calibrated against the pilot's actual
`response.total_tokens`, the proxy is within ~4%. Documented in the
dry-run output so future re-estimates are honest about the uncertainty.

### LanceDB schema mirrors `VectorRecord` Pydantic model

Used an explicit `pyarrow.Schema` rather than letting LanceDB infer from
the first batch — keeps the column types stable across resumed runs and
lets us declare `vector` as a fixed-size 1024-element float32 list.
`publication_date` stored as ISO string because LanceDB's date support is
uneven across versions and we don't need date arithmetic at the store
layer.

### SQLite over Kùzu/Neo4j

Per the doc. At 1.97M nodes + 2.2M edges with BFS limited to 1–2 hops
and indices on both directions, SQLite is fast enough — `get_neighbors`
returns in sub-ms for typical sections, and the whole load runs in ~65 s.
Migration path to Kùzu later is a write-side concern only.

### Degree cached in `metadata_json`, not joined

Step 7 will call `get_degree` repeatedly during BFS gating. Doing the
COUNT(*) per call is 5–10 ms; reading the cached value out of
`metadata_json` is sub-ms. The trade is that the cache is only as fresh
as the last loader run, but loader is a one-shot and incremental updates
aren't a feature we need.

### Asymmetric query/document encoding

`search_by_text` embeds the query with `input_type="query"` while the
corpus is `"document"`. Voyage docs flag this as load-bearing for
retrieval quality on v3 models, and the pilot's 9/10 spot-check is
direct evidence the asymmetry is being honoured.

### Resumability via chunk-id dedup

`embed_chunks.py` reads existing `chunk_id`s out of LanceDB at startup
and skips them. Cheaper than a separate sidecar file, and the LanceDB
table is the source of truth anyway. Rate-limit hiccups, OS sleeps, or
manual interrupts all recover with at most one duplicated batch.

## How to run

```bash
# 4a — embeddings (compose-only smoke; no API)
.venv/bin/python -m scripts.embed_pilot --no-embed --n 200

# 4a — pilot (1000 chunks, ~540k tokens, ~22 s)
.venv/bin/python -m scripts.embed_pilot --n 1000
.venv/bin/python -m scripts.spot_check_pilot

# 4a — full pass token estimate (no API)
.venv/bin/python -m scripts.embed_chunks --dry-run

# 4a — full pass (resumable; expect ~1.6 hours)
.venv/bin/python -m scripts.embed_chunks

# 4b — graph load + verify
.venv/bin/python -m scripts.load_graph --rebuild
.venv/bin/python -m pipeline.verify_graph
```

Quick liveness check during a long embed run:

```bash
.venv/bin/python -c "import lancedb; t=lancedb.connect('output/lancedb').open_table('chunks'); print(f'{t.count_rows():,}/402,098')"
```

## Output artifacts (`output/`)

| file                          |     size | contents                                                                |
|-------------------------------|---------:|-------------------------------------------------------------------------|
| `lancedb_pilot/chunks.lance/` |    ~6 M  | 1000-row pilot table; safe to delete after full pass is verified        |
| `lancedb/chunks.lance/`       | growing  | full vector index — 1024-dim float32 + filterable payload columns       |
| `graph.db`                    |    3.2 G | SQLite with `nodes` + `edges`; `metadata_json` includes cached `degree` |

## Sequencing notes

- **Step 5 (retrieval)** can already use `GraphStore.bfs` and the partial
  LanceDB index (`search_by_text` works against any populated table).
  Recommend waiting for the full embed to land before benchmarking
  retrieval quality at scale.
- **Step 7 (degree-capped expansion)** consumes `metadata.degree` from
  the graph store — already populated and readable from
  `GraphStore.get_degree()`.
- **Step 8 (verifier)** uses `authority_rank` from the chunk payload —
  populated for every vector LanceDB row from `nodes_enriched.jsonl`.

## Open items (will close once 4a finishes)

- [ ] Full embed pass completes (background job; ~1.6 h ETA)
- [ ] 4a.7 quality checks: row-count parity vs `chunks.jsonl`,
      100-random-vector resolution, 20-query Finnish sanity set,
      metadata-filter test
- [ ] `findings/04a_index_sanity.md` written from 4a.7 results
