# Coding Agent Brief — `src/models.py`

> **Goal:** Define the Pydantic schemas that the next three steps of the GraphRAG pipeline write against. Three agents (Edges, Metadata, Embeddings) will run in parallel and all import from this file. **It must be written first and locked.**

## Scope of this task

Produce a single Python file: `src/models.py`.

Do **not** modify any other file. Do **not** load data. Do **not** write tests in this file — tests go in `tests/test_models.py` if produced.

This file is the schema contract between four pipeline stages:
- Step 1 (already complete) — produces nodes and chunks in JSONL
- Step 2 — produces edges (extraction agent)
- Step 3 — produces metadata annotations (metadata agent)
- Step 4a — embeds chunks (embeddings agent)

If a downstream agent needs a field not in this file, they are required to request a schema change rather than add it ad-hoc. This is enforced socially, not by code.

## Context you need

### What Step 1 already produced

The team has already run the ingestion pipeline. The following files exist on disk:

- `output/nodes.jsonl` — 1,967,776 nodes, one JSON object per line
- `output/chunks.jsonl` — 402,098 chunks, one JSON object per line
- `output/hierarchy.json` — `{law_id: {title, source, chapters[], sections[], ...}}`

The schemas below must be **backward-compatible** with what's already on disk. **Do not invent field names — use what the data already has.** Open a few lines of `output/nodes.jsonl` to confirm field names if uncertain.

Known field names from Step 1 documentation:
- Node: `id`, `type`, `text`, `parent_id`, `order`, `source_html_id`, `label` (optional), `source` (e.g. `"finlex_laki"`), `source_file`, `url` (optional)
- Chunk: `chunk_id`, `node_ids` (list), `text`, `token_count`, `primary_node_id`, `oversized` (optional bool)

Node `type` is one of: `LAW`, `CHAPTER`, `SECTION`, `SUBSECTION`, `ITEM`, `DEFINITION`, `TITLE`, `AMENDMENT_BLOCK`, `GUIDE`, `CASE`, `TREATY`.

Sources observed in the ingested corpus: `finlex_laki`, `finlex_skk` (säädöskokoelma), `kho`, `vero`, `treaty`. (Note: the original plan said Finlex + Vero only, but Step 1 also ingested KHO case law and tax treaties. Schemas must support all five.)

### What Step 2 will produce

Edges in `output/edges.jsonl`. Each edge:
- Has a `source_id` pointing to a node ID
- May have a `target_id` pointing to a node ID, **OR may dangle** (`target_id=None` with `target_ref` carrying the raw citation string)
- Has a typed `type` (one of: `parent_of`, `cites`, `interprets`, `amends`, `repeals`, `transposes`, `applies`, `defines`)
- Has a `confidence` in [0, 1] (1.0 for structural / anchor-based, lower for regex and LLM)
- Has an `extracted_by` provenance: one of `structural`, `anchor`, `regex`, `llm`
- May carry a `context_snippet` (50 chars around the citation) used for edge-type refinement
- May carry free-form `properties` dict for edge-type-specific fields (e.g. amendment date on `amends`)

Dangling edges also carry a `dangling_reason`: one of `out_of_corpus`, `not_yet_parsed`, `normalization_failed`.

### What Step 3 will produce

Per-node metadata annotations written to `output/nodes_enriched.jsonl`. The enriched file has the **same shape as `nodes.jsonl`** but with a populated `metadata` field on each node. Fields populated by Step 3:

- `publication_date`: ISO date string or None
- `effective_date`: ISO date string or None
- `repeal_date`: ISO date string or None
- `in_force`: bool
- `authority`: one of `Finlex`, `Vero`, `KHO`, `Treaty`
- `authority_rank`: int (Finlex=100, KHO=80, Treaty=90, Vero=60 — final values are Step 3's decision; the schema just stores an int)
- `superseded_by`: node ID string or None
- `language`: `fi`, `sv`, or `en`
- `usable`: bool (composite — see below)
- `degree`: dict mapping `{edge_type}_{direction}` → int, e.g. `{"interprets_in": 47, "cites_out": 3}`. Populated by Step 4 during graph loading, not Step 3.

`usable = in_force AND (repeal_date is None OR repeal_date > today) AND superseded_by is None`. The schema stores it as a bool; the computation happens in Step 3.

### What Step 4a will produce

Vector store records. Not file-based — the vector store is a LanceDB directory at `output/lancedb/`. Each vector record carries:

- `chunk_id` (primary key)
- `vector` (list[float], dim depends on the embedding model — likely 1024 for `voyage-3-large`)
- `primary_node_id`
- `source` (e.g. `finlex_laki`)
- `authority_rank` (int, from node metadata)
- `in_force` (bool)
- `usable` (bool)
- `publication_date` (ISO date string)
- `language` (str)
- `node_type` (str)

This is a **payload schema** for the vector store, not a Pydantic class the team imports. Still, define it as a Pydantic class so the embedding agent can validate before writing.

## What to produce

A single file `src/models.py` containing the classes below. Use Pydantic v2 (`pydantic >= 2.0`).

### Class list (write in this order)

#### 1. Type aliases and literals

Define `Literal` types at the top of the file:

```python
NodeType = Literal[
    "LAW", "CHAPTER", "SECTION", "SUBSECTION", "ITEM",
    "DEFINITION", "TITLE", "AMENDMENT_BLOCK",
    "GUIDE", "CASE", "TREATY",
]

Source = Literal["finlex_laki", "finlex_skk", "kho", "vero", "treaty"]

EdgeType = Literal[
    "parent_of", "cites", "interprets",
    "amends", "repeals", "transposes",
    "applies", "defines",
]

ExtractionMethod = Literal["structural", "anchor", "regex", "llm"]

DanglingReason = Literal["out_of_corpus", "not_yet_parsed", "normalization_failed"]

Authority = Literal["Finlex", "Vero", "KHO", "Treaty"]

Language = Literal["fi", "sv", "en"]

Direction = Literal["out", "in", "both"]
```

#### 2. `NodeMetadata` — populated by Step 3 + Step 4

```python
class NodeMetadata(BaseModel):
    """All fields optional — Step 1 emits empty metadata, Step 3 populates
    status/date/authority fields, Step 4 populates degree."""

    publication_date: date | None = None
    effective_date: date | None = None
    repeal_date: date | None = None
    in_force: bool | None = None
    authority: Authority | None = None
    authority_rank: int | None = None
    superseded_by: str | None = None
    language: Language | None = None
    usable: bool | None = None

    # Populated by Step 4 (graph loader), not Step 3
    degree: dict[str, int] = Field(default_factory=dict)

    # Escape hatch — source-specific or extractor-specific fields. Keep small.
    extra: dict[str, Any] = Field(default_factory=dict)
```

> **Compatibility note:** Step 3 writes this back into `output/nodes_enriched.jsonl` as a nested object under `node.metadata`. The field names above must match the JSON exactly.

#### 3. `Node` — produced by Step 1, enriched by Step 3

```python
class Node(BaseModel):
    """One legal-structure node. Backward-compatible with Step 1's output."""

    id: str
    type: NodeType
    text: str
    parent_id: str | None = None    # None only for root nodes (LAW, GUIDE, CASE, TREATY)
    order: int                       # position among siblings, used for stable ordering
    source: Source
    source_file: str                 # path to original HTML
    source_html_id: str | None = None  # DOM anchor if the parser found one
    label: str | None = None         # e.g. "§5", "1 momentti", "a)"
    url: str | None = None

    # Populated by Step 3 (and partially Step 4). Step 1 emits empty.
    metadata: NodeMetadata = Field(default_factory=NodeMetadata)

    model_config = {"extra": "allow"}
    # allow extra fields so Step 1 outputs with additional fields don't break
    # validation. If a field becomes important, promote it to a real field.
```

#### 4. `Chunk` — produced by Step 1, embedded by Step 4

```python
class Chunk(BaseModel):
    """A token-bounded chunk anchored to one or more nodes."""

    chunk_id: str
    node_ids: list[str]              # the nodes packed into this chunk, in order
    primary_node_id: str             # the SECTION (or equivalent) this chunk anchors to
    text: str
    token_count: int
    oversized: bool = False          # True only for single unsplittable sentences > 2000 tokens

    model_config = {"extra": "allow"}
```

#### 5. `Edge` — produced by Step 2

```python
class Edge(BaseModel):
    """A typed relationship between two nodes. May dangle (target_id=None)."""

    source_id: str
    target_id: str | None = None     # None = dangling edge
    target_ref: str                  # raw citation string, always populated even when resolved
    type: EdgeType
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_by: ExtractionMethod
    context_snippet: str | None = None   # ~50 chars around the citation, for type refinement
    dangling_reason: DanglingReason | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_dangling_consistency(self) -> "Edge":
        # If target_id is None, dangling_reason must be set.
        # If target_id is set, dangling_reason must be None.
        if self.target_id is None and self.dangling_reason is None:
            raise ValueError("Dangling edge requires dangling_reason")
        if self.target_id is not None and self.dangling_reason is not None:
            raise ValueError("Resolved edge cannot have dangling_reason")
        return self
```

#### 6. `VectorRecord` — produced by Step 4a

```python
class VectorRecord(BaseModel):
    """Payload schema for the LanceDB vector store. Used for validation
    before write; LanceDB itself stores this as columnar Arrow."""

    chunk_id: str                    # primary key
    vector: list[float]              # embedding, dim depends on model

    # Filterable payload — populated from the chunk's primary node
    primary_node_id: str
    source: Source
    node_type: NodeType
    authority_rank: int | None = None
    in_force: bool | None = None
    usable: bool | None = None
    publication_date: date | None = None
    language: Language | None = None

    # For debugging — the exact text that was embedded (with hierarchy prefix
    # if any). Optional; can be omitted at write time to save space.
    embedded_text: str | None = None
```

#### 7. Helpers — bidirectional traversal types

These aren't Pydantic models but small typed records used by the graph store adapter (Step 4) and retrieval (Steps 5, 7). Include them so all agents share the names.

```python
@dataclass(frozen=True)
class Neighbor:
    """Returned by graph_store.get_neighbors() — pairs the connected node
    with the edge that connected it."""

    node_id: str
    edge: Edge
    direction: Direction             # "out" if we followed an outgoing edge from the query node


@dataclass(frozen=True)
class RetrievalPath:
    """How a node ended up in a result set. Layer 8 path-aware citations."""

    via: Literal["vector", "graph"]
    score: float                     # cosine for vector, rerank for graph
    from_node_id: str | None = None  # only for via="graph" — the seed we expanded from
    edge_type: EdgeType | None = None
    hops: int = 0                    # 0 for vector seed, 1+ for graph expansion
```

## Imports

Top of file. Use exactly these:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
```

No other imports.

## File header (docstring)

Top of file, before imports:

```python
"""Pydantic schemas for the GraphRAG pipeline.

This module is the schema contract between Step 1 (ingestion, done), Step 2
(edge extraction), Step 3 (metadata enrichment), and Step 4 (embedding +
graph loading). Three agents work in parallel against this file; do not
modify it without coordination.

Conventions:
- All node/chunk IDs are strings, deterministic, ASCII-safe.
- Dangling edges (target_id=None) are kept; they are not errors.
- NodeMetadata fields are all Optional — Step 1 emits empty metadata, later
  steps populate it incrementally.
"""
```

## What NOT to do

- Do not add fields beyond those listed above. If a downstream step needs more, the convention is to use `metadata.extra` (free-form dict) or `edge.properties`, not to extend the schema.
- Do not add validators beyond the dangling-edge consistency check on `Edge`. Heavier validation belongs in `pipeline/verify_*.py`, not in the model definition.
- Do not import anything from `src/` — this file must have no internal dependencies. Every other module imports from here, not the other way around.
- Do not write JSON serialization helpers. Pydantic v2's `.model_dump_json()` and `.model_validate_json()` are sufficient.
- Do not write a `Database` or storage class. Storage adapters belong in `src/indexing/`.

## Definition of done

- `src/models.py` exists.
- `python -c "from src.models import Node, Chunk, Edge, VectorRecord, NodeMetadata, Neighbor, RetrievalPath"` succeeds.
- The following round-trips work:
  ```python
  # Load 100 existing nodes from output/nodes.jsonl, validate each
  # through the Node schema, dump back to JSON, compare for equality.
  ```
  If real data fails to validate, you have used the wrong field name — open `output/nodes.jsonl` and reconcile.
- Same round-trip on 100 chunks from `output/chunks.jsonl`.
- A hand-built `Edge` with `target_id=None` and `dangling_reason=None` raises a validation error.
- A hand-built `Edge` with `confidence=1.5` raises a validation error.

## How to verify before declaring done

Write a small verification script (not committed, just for self-check):

```python
import json
from src.models import Node, Chunk, Edge

# Round-trip 100 nodes from disk
with open("output/nodes.jsonl") as f:
    for i, line in enumerate(f):
        if i >= 100: break
        original = json.loads(line)
        parsed = Node.model_validate(original)
        roundtripped = json.loads(parsed.model_dump_json(exclude_none=True))
        # roundtripped should be a subset of original (extra=allow may keep extras)

# Same for chunks
with open("output/chunks.jsonl") as f:
    for i, line in enumerate(f):
        if i >= 100: break
        Chunk.model_validate(json.loads(line))

# Synthetic edge tests
ok = Edge(source_id="a", target_id="b", target_ref="§ 5", type="cites",
          confidence=1.0, extracted_by="anchor")
print("Resolved edge OK")

try:
    bad = Edge(source_id="a", target_ref="§ 5", type="cites",
               confidence=1.0, extracted_by="regex")  # target_id=None, no reason
    print("FAIL: should have raised")
except Exception as e:
    print(f"Dangling-without-reason correctly rejected: {e}")
```

If all checks pass, declare done. Otherwise, fix and re-verify.

## Open questions you may need to resolve

If during verification you find that the real `output/nodes.jsonl` uses field names different from what's listed above (e.g. `parent` instead of `parent_id`, or `source_path` instead of `source_file`), **the real file wins**. Update the schema field names to match the data, do not modify the data. Note any such discrepancies in a comment at the top of the file under "Field name conventions inherited from Step 1."