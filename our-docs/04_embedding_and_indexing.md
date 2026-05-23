# Step 4 — Embedding and Vector/Graph Indexing

> Step 1 produced chunks. This step makes them vector-searchable and loads the graph store. **Split into two substeps that run on different schedules.**

## Substep split

| Substep | Depends on | Can start when |
|---------|-----------|----------------|
| **4a — Embeddings + vector store** | Step 1 only | **Now** (parallel with Steps 2 and 3) |
| **4b — Graph store load** | Steps 1, 2, 3 | After Steps 2 and 3 complete |

Step 4a is one agent's full deliverable. Step 4b is glue that runs after the parallel fan-out converges.

## Inputs

For 4a:
- `output/nodes.jsonl` (read-only — for `hierarchy_path` and `source` during text composition)
- `output/chunks.jsonl` (read-only — the chunks to embed)
- `src/models.py` (already locked)

For 4b:
- All of 4a
- `output/edges.jsonl` from Step 2
- `output/nodes_enriched.jsonl` from Step 3

---

## Step 4a — Embeddings and Vector Store

### Locked decisions

These have been decided. Do not re-evaluate; do not benchmark alternatives.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Embedding service | **Voyage AI**, model `voyage-3-large` | Best legal-domain multilingual retrieval; free tier covers our corpus |
| Vector store | **LanceDB** (embedded, file-based) | Zero infrastructure, single-directory storage, fast enough at our scale |
| Embedding dimensions | **1024** (Matryoshka-reduced from 2048) | Halves storage, marginal quality impact |
| Text composition | **Hierarchy-prefixed** (Option B below) | Mitigates jurisdiction-blindness from slide 3 of the brief |

### 4a.1 — Voyage account and API key

Before writing any code:

1. Sign up at [voyageai.com](https://www.voyageai.com/) — new accounts get **200M tokens free** for `voyage-3-large`. Our corpus is ~147M tokens, so the entire embedding pass fits in the free tier with headroom for the inevitable re-run.
2. Generate an API key from the Voyage dashboard.
3. Store in `.env` as `VOYAGE_API_KEY=...`. Add `.env` to `.gitignore` (likely already there).
4. Install the SDK: `pip install voyageai`.

Verification: `python -c "import voyageai; print(voyageai.Client().embed(['test'], model='voyage-3-large').embeddings[0][:5])"` should print a list of 5 floats.

### 4a.2 — Embedding text composition (Option B, locked)

Each chunk's text is composed before embedding:

```
[Source: finlex_laki · in force]
[Path: Arvonlisäverolaki > Luku 10 > § 102]
[Title: Vähennysoikeus]

{chunk.text}
```

The prefix is built from the chunk's `primary_node_id` and the corresponding `Node` in `nodes.jsonl`:
- **Source line:** `node.source` (e.g. `finlex_laki`, `vero`) and `node.metadata.in_force` if available; otherwise omit the second clause
- **Path line:** walk `parent_id` chain from the primary node up to the root, collect titles, join with ` > `. Use `hierarchy.json` for fast lookup
- **Title line:** `node.label` or the first heading-type child's text — whichever is meaningful. Skip if no useful title

If `metadata.in_force` is not yet populated (Step 3 hasn't run), the source line still works without the status clause — the field is simply omitted, not faked. **Do not block on Step 3.** Re-embedding with full metadata can be done later as a delta if needed (it usually isn't — the path prefix carries most of the signal).

`src/indexing/text_composition.py`:

```python
def compose_embedding_text(chunk: Chunk, node_index: dict[str, Node],
                            hierarchy: dict) -> str:
    """Build the hierarchy-prefixed text that gets embedded.
    Pure function, no I/O. Used both during embedding and for spot-checking."""
```

### 4a.3 — Pilot run (mandatory before full embedding)

**Do not embed all 402k chunks until the pilot passes.** A 1000-chunk pilot is fast and catches the most common failure modes (wrong text composition, wrong dimensions, payload errors) before they cost you the full corpus pass.

`scripts/embed_pilot.py`:

1. Sample 1000 chunks stratified by source: 600 from `finlex_laki`, 100 each from `finlex_skk`, `kho`, `vero`, `treaty`
2. Compose text per 4a.2
3. Embed in batches of 128 via Voyage SDK (the SDK handles batching internally but you control the chunk loop)
4. Write to a temporary LanceDB at `output/lancedb_pilot/`
5. Run 10 hand-written Finnish tax queries through it, eyeball top-5 results

Spot-check criteria:
- For at least 7 of 10 queries, top-3 results contain at least one plausibly-relevant chunk
- No empty / zero vectors
- All payload fields populate (chunk_id, primary_node_id, source, node_type at minimum; metadata fields if Step 3 has run)

Write findings to `findings/04a_pilot.md` with the 10 queries, their top-5 results, and your assessment. **If the pilot fails the spot-check, debug before scaling up.**

### 4a.4 — Full embedding pass

After the pilot passes:

`scripts/embed_chunks.py`:

```
1. Read output/chunks.jsonl (streaming, not full load — 691MB)
2. For each chunk:
   - Look up primary_node_id in nodes.jsonl (preloaded as a dict, ~2GB peak)
   - Compose text per 4a.2
   - Add to a batch buffer
3. Every 128 chunks, send batch to Voyage:
   client.embed(texts, model="voyage-3-large", input_type="document",
                output_dimension=1024)
4. Write embeddings + payload to LanceDB
5. Track progress (every 10k chunks): tokens used, chunks/sec, ETA
6. Resumable: if interrupted, skip chunks already present in LanceDB by chunk_id
```

Use the **Voyage Batch API** if available for embedding-3-large — it processes asynchronously with significantly higher throughput than the real-time endpoint. As of writing, Voyage's batch API takes a JSONL of inputs and returns results within hours. Check Voyage docs (`docs.voyageai.com`) for the current endpoint shape — the SDK exposes it as `client.batch_embed()`.

If batch isn't available or is slower for our volume, the standard endpoint is fine. 147M tokens at the rate-limited throughput of `voyage-3-large` (check Voyage docs for current TPM limits) completes in 2–4 hours.

**Cost guardrails:**
- Voyage free tier: 200M tokens. Our usage: ~147M tokens. Headroom: ~36%.
- Add a `--dry-run` flag that counts tokens without calling the API. Run it once before the real pass to confirm the token estimate.
- If the dry-run shows > 180M tokens, investigate before proceeding (likely a text composition bug producing very long prefixes).

### 4a.5 — LanceDB schema

`output/lancedb/chunks/` is a LanceDB table with the schema below. Use the `VectorRecord` Pydantic model from `src/models.py` as the source of truth — generate the Arrow schema from it:

```python
import lancedb
from src.models import VectorRecord

db = lancedb.connect("output/lancedb")
# LanceDB infers schema from the first batch of records OR from an explicit
# pyarrow.Schema. Use the explicit schema to avoid surprises.
table = db.create_table("chunks", schema=_arrow_schema_from(VectorRecord), mode="overwrite")
```

Index the filterable columns server-side:

```python
table.create_scalar_index("source")
table.create_scalar_index("authority_rank")
table.create_scalar_index("in_force")
table.create_scalar_index("usable")
table.create_scalar_index("language")
table.create_scalar_index("node_type")
```

Vector index uses LanceDB's default (IVF_PQ). At 402k vectors this is plenty fast; tuning is unnecessary at this scale.

### 4a.6 — Vector store adapter

`src/indexing/vector_store.py`:

```python
class VectorStore:
    def __init__(self, path: str = "output/lancedb"): ...

    def upsert(self, record: VectorRecord) -> None: ...
    def upsert_batch(self, records: list[VectorRecord]) -> None: ...

    def search(
        self,
        query_vector: list[float],
        k: int = 20,
        filters: dict | None = None,   # e.g. {"source": "finlex_laki", "usable": True}
    ) -> list[tuple[VectorRecord, float]]:
        """Returns (record, similarity_score) pairs."""

    def search_by_text(
        self,
        query_text: str,
        k: int = 20,
        filters: dict | None = None,
    ) -> list[tuple[VectorRecord, float]]:
        """Embeds the query via Voyage (input_type='query') then searches.
        Note: Voyage uses different input_type for queries vs documents —
        this is important for retrieval quality. Do not skip it."""
```

**The `input_type` distinction matters.** Voyage's `voyage-3-large` is asymmetric — queries are embedded with `input_type="query"`, documents with `input_type="document"`. Mixing them up degrades retrieval quality noticeably. The chunk embedding pass in 4a.4 uses `"document"`; the query embedding in `search_by_text` uses `"query"`.

### 4a.7 — Quality checks

After the full embedding pass:

- Row count in LanceDB equals chunk count in `chunks.jsonl` (within rounding for any deliberately skipped chunks like `oversized=True` — decide upfront and document)
- For 100 random vectors: `chunk_id` resolves to a chunk in `chunks.jsonl`, `primary_node_id` resolves to a node in `nodes.jsonl`
- Pick 20 Finnish tax queries (the V4.1 set from before, plus 10 new ones). Run vector search. For each, top-5 contains at least one relevant chunk in the team's judgment
- Metadata filter test: `filters={"source": "finlex_laki"}` returns only Finlex chunks; `filters={"node_type": "SECTION"}` returns only SECTION-anchored chunks

Write findings to `findings/04a_index_sanity.md` with the 20 queries and team judgment per query.

---

## Step 4b — Graph Store Load (after Steps 2 and 3)

### Locked decisions

| Decision | Choice |
|----------|--------|
| Graph store | **SQLite** with `nodes` and `edges` tables |

Rationale: SQLite is fastest to stand up, has no daemon, and at 1.97M nodes + ~4M edges performs fine for our query patterns (BFS expansion limited to 1–2 hops). Migrating to Kùzu or Neo4j later is straightforward if needed.

### 4b.1 — Schema

`output/graph.db`:

```sql
CREATE TABLE nodes (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    source          TEXT NOT NULL,
    parent_id       TEXT,
    text            TEXT NOT NULL,
    label           TEXT,
    metadata_json   TEXT NOT NULL,   -- full NodeMetadata as JSON
    FOREIGN KEY (parent_id) REFERENCES nodes(id)
);

CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_source ON nodes(source);
CREATE INDEX idx_nodes_parent ON nodes(parent_id);

CREATE TABLE edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL,
    target_id       TEXT,            -- NULL for dangling edges
    target_ref      TEXT NOT NULL,
    type            TEXT NOT NULL,
    confidence      REAL NOT NULL,
    extracted_by    TEXT NOT NULL,
    context_snippet TEXT,
    dangling_reason TEXT,
    properties_json TEXT,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

-- Critical: index BOTH source_id and target_id for bidirectional traversal (Layer 2)
CREATE INDEX idx_edges_source ON edges(source_id, type);
CREATE INDEX idx_edges_target ON edges(target_id, type) WHERE target_id IS NOT NULL;
CREATE INDEX idx_edges_type ON edges(type);
```

The `WHERE target_id IS NOT NULL` partial index on `target_id` keeps the index small (dangling edges are excluded from inbound traversal — they can't be a target of one).

### 4b.2 — Loader

`scripts/load_graph.py`:

1. Open `output/nodes_enriched.jsonl` (Step 3's output) — falls back to `output/nodes.jsonl` if Step 3 hasn't run
2. Bulk insert all nodes
3. Open `output/edges.jsonl` — bulk insert all edges
4. Compute degree per node (per edge type, per direction), write back to `node.metadata.degree`
5. Run quality checks (4b.4)

Use SQLite's `executemany` with explicit transactions — single-row inserts are 100x slower. Expect total load time < 60s for 1.97M nodes + ~4M edges on a laptop.

### 4b.3 — Graph store adapter

`src/indexing/graph_store.py`:

```python
class GraphStore:
    def __init__(self, path: str = "output/graph.db"): ...

    def get_node(self, node_id: str) -> Node | None: ...

    def get_neighbors(
        self,
        node_id: str,
        edge_types: list[str] | None = None,
        direction: Literal["out", "in", "both"] = "both",
    ) -> list[Neighbor]:
        """Returns neighbors with the edge that connected them.
        Bidirectional traversal: 'in' returns nodes that point TO node_id,
        'out' returns nodes node_id points to."""

    def get_degree(
        self,
        node_id: str,
        edge_type: str,
        direction: Direction,
    ) -> int: ...

    def bfs(
        self,
        seed_ids: list[str],
        edge_types: list[str],
        direction: Direction,
        max_hops: int,
        degree_cap: dict[str, int] | None = None,
    ) -> dict[str, RetrievalPath]:
        """BFS expansion. Returns {node_id: RetrievalPath}. Used by Step 7
        retrieval. Honors degree caps (skips expansion through hub nodes)."""
```

The `bfs` method is what Step 7 calls. Implementing it here (rather than in `src/retrieval/`) keeps graph-walk logic close to the graph store and lets Step 5's retriever stay simple.

### 4b.4 — Quality checks (`pipeline/verify_graph.py`)

Reject the load if:
- `nodes` table row count ≠ `nodes.jsonl` (or `nodes_enriched.jsonl`) line count
- `edges` table row count ≠ `edges.jsonl` line count
- Any `edges.source_id` doesn't have a matching node
- Any non-NULL `edges.target_id` doesn't have a matching node (dangling = target_id is NULL; mismatched non-NULL targets are bugs)
- The total count of `parent_of` edges doesn't equal (total nodes − number of root nodes)

Smoke test:
- `get_neighbors(some_known_section_id, edge_types=["parent_of"], direction="out")` returns the section's children
- `get_neighbors(some_known_finlex_section, edge_types=["interprets"], direction="in")` returns Vero guidance pointing to it

---

## Done when

### 4a — done when
- `output/lancedb/chunks/` contains one vector per chunk in `chunks.jsonl`
- 20-query spot-check passes per 4a.7
- `findings/04a_pilot.md` and `findings/04a_index_sanity.md` exist
- Voyage token budget: actual usage ≤ 180M tokens (with headroom from free tier)

### 4b — done when
- `output/graph.db` exists with both tables populated
- `pipeline/verify_graph.py` passes with zero violations
- `get_neighbors` smoke tests pass in both directions
- `findings/04b_load_report.md` exists with node/edge counts and degree distribution
