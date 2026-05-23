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

----------------------------------------------------------------------
Field name conventions inherited from Step 1
----------------------------------------------------------------------
The instruction brief and the on-disk Step 1 output diverged in a few
places. Per the brief's "real file wins" rule, this schema follows the
on-disk shape and notes the deltas here so downstream agents are not
surprised.

1. ``source`` vs ``source_subcorpus``
   Brief listed ``source`` as one of {"finlex_laki", "finlex_skk", "kho",
   "vero", "treaty"}. The on-disk shape splits this into two fields:
       source           ∈ {"finlex", "vero"}                # publisher
       source_subcorpus ∈ {"laki", "asetus", "laki_skk",    # subcorpus
                           "asetus_skk", "kho", "vero_ohje",
                           "vero_paatos", "vero_kannanotto",
                           "vero_kvl", "treaty", "vero_other"}
   Both fields are exposed on Node, Chunk, and VectorRecord so filters
   can pick whichever granularity they need.

2. ``Chunk.primary_node_id`` → ``Chunk.section_id``
   Step 1 anchors each chunk to its SECTION (or per-corpus equivalent —
   the GUIDE/CASE/TREATY root). The field is called ``section_id`` on
   disk and is preserved here. ``VectorRecord`` mirrors the rename.

3. ``Node.url``
   Not present on disk. Step 1 stores source URLs implicitly through the
   ``source_file`` path; if a future step starts emitting canonical URLs
   it can use ``model_config = extra='allow'`` or the ``metadata.extra``
   escape hatch.

4. ``Node.title`` and ``Node.law_id``
   Both are populated by Step 1 and load-bearing for retrieval (title
   for chunk-head rendering, law_id for fast root lookups). Added as
   real fields so they're not lost through ``extra='allow'``.

5. ``Chunk`` carries ``law_id``, ``source``, ``source_subcorpus``,
   ``source_file`` for filterability without a node-table join.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------
# Type aliases & literals
# --------------------------------------------------------------------------

NodeType = Literal[
    "LAW",
    "CHAPTER",
    "SECTION",
    "SUBSECTION",
    "ITEM",
    "DEFINITION",
    "TITLE",
    "AMENDMENT_BLOCK",
    "GUIDE",
    "CASE",
    "TREATY",
]

# Publisher. The brief's collapsed Source literal is intentionally split into
# (source, source_subcorpus) to match Step 1's on-disk shape — see the file
# header for details.
Source = Literal["finlex", "vero"]

SourceSubcorpus = Literal[
    "laki",
    "asetus",
    "laki_skk",
    "asetus_skk",
    "kho",
    "vero_ohje",
    "vero_paatos",
    "vero_kannanotto",
    "vero_kvl",
    "vero_other",
    "treaty",
]

EdgeType = Literal[
    "parent_of",
    "cites",
    "interprets",
    "amends",
    "repeals",
    "transposes",
    "applies",
    "defines",
]

ExtractionMethod = Literal["structural", "anchor", "regex", "llm"]

DanglingReason = Literal[
    "out_of_corpus",
    "not_yet_parsed",
    "normalization_failed",
]

Authority = Literal["Finlex", "Vero", "KHO", "Treaty"]

Language = Literal["fi", "sv", "en"]

Direction = Literal["out", "in", "both"]


# --------------------------------------------------------------------------
# NodeMetadata — populated by Step 3 + Step 4
# --------------------------------------------------------------------------


class NodeMetadata(BaseModel):
    """All fields optional — Step 1 emits empty metadata, Step 3 populates
    status/date/authority fields, Step 4 populates ``degree``.

    Step 1 sometimes writes small, source-specific extras into ``metadata``
    (e.g. ``{"kind": "example"}`` on Vero example sections). Those land on
    the model as unnamed attributes thanks to ``extra='allow'``. Step 3 may
    move them into the dedicated ``extra`` dict if it wants them
    typed-but-flexible.
    """

    publication_date: date | None = None
    effective_date: date | None = None
    repeal_date: date | None = None
    in_force: bool | None = None
    authority: Authority | None = None
    authority_rank: int | None = None
    superseded_by: str | None = None
    language: Language | None = None
    usable: bool | None = None

    # Populated by Step 4 (graph loader), not Step 3.
    # Keys are "{edge_type}_{direction}" e.g. "interprets_in" / "cites_out".
    degree: dict[str, int] = Field(default_factory=dict)

    # Escape hatch — source-specific or extractor-specific fields. Keep small.
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


# --------------------------------------------------------------------------
# Node — produced by Step 1, enriched by Step 3
# --------------------------------------------------------------------------


class Node(BaseModel):
    """One legal-structure node. Backward-compatible with Step 1's output."""

    id: str
    type: NodeType
    text: str
    parent_id: str | None = None  # None only for root nodes (LAW, GUIDE, CASE, TREATY)
    order: int  # position among siblings, used for stable ordering

    source: Source
    source_subcorpus: SourceSubcorpus
    source_file: str  # path to original HTML (relative to data/)
    source_html_id: str | None = None  # DOM anchor if the parser found one

    label: str | None = None  # e.g. "5 §", "1 momentti", "kohta a"
    title: str | None = None  # human-readable name; load-bearing for LAW/GUIDE/CASE roots

    # Root document id this node belongs to. For root nodes themselves
    # ``law_id == id``. Lets retrieval cluster/score by document without a
    # join through parent_id.
    law_id: str | None = None

    # Populated by Step 3 (and partially Step 4). Step 1 emits empty.
    metadata: NodeMetadata = Field(default_factory=NodeMetadata)

    # Allow extra fields so future Step 1 additions don't break validation.
    # If a field becomes important, promote it to a real field above.
    model_config = {"extra": "allow"}


# --------------------------------------------------------------------------
# Chunk — produced by Step 1, embedded by Step 4
# --------------------------------------------------------------------------


class Chunk(BaseModel):
    """A token-bounded chunk anchored to one SECTION (or per-corpus root)."""

    chunk_id: str

    # The nodes packed into this chunk, in document order. Always includes
    # ``section_id`` as the first element so a chunk is self-describing.
    node_ids: list[str]

    # The SECTION (or GUIDE/CASE/TREATY root) this chunk anchors to. Named
    # ``section_id`` to match Step 1's on-disk shape; the original brief
    # called this ``primary_node_id``.
    section_id: str

    # The root document this chunk belongs to. Lets retrieval filter or
    # cluster by document without joining through nodes.
    law_id: str

    text: str
    token_count: int

    source: Source
    source_subcorpus: SourceSubcorpus
    source_file: str

    # True only when a single unsplittable sentence > 2000 tokens forced an
    # over-budget chunk. Consumers may filter these out before embedding.
    oversized: bool = False

    model_config = {"extra": "allow"}


# --------------------------------------------------------------------------
# Edge — produced by Step 2
# --------------------------------------------------------------------------


class Edge(BaseModel):
    """A typed relationship between two nodes. May dangle (``target_id=None``).

    A dangling edge represents a citation we extracted but could not resolve
    to an in-corpus node. ``target_ref`` always carries the raw citation
    string so resolution can be retried later as the corpus grows or the
    normalizer improves.
    """

    source_id: str
    target_id: str | None = None  # None = dangling edge
    target_ref: str  # raw citation string, always populated even when resolved
    type: EdgeType
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_by: ExtractionMethod
    context_snippet: str | None = None  # ~50 chars around the citation, for type refinement
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


# --------------------------------------------------------------------------
# VectorRecord — produced by Step 4a
# --------------------------------------------------------------------------


class VectorRecord(BaseModel):
    """Payload schema for the LanceDB vector store.

    Used for validation before write; LanceDB itself stores this as columnar
    Arrow. The field names mirror ``Chunk`` (notably ``section_id``, not
    ``primary_node_id``) so the embedding agent can copy fields straight
    across.
    """

    chunk_id: str  # primary key
    vector: list[float]  # embedding, dim depends on model (1024 for voyage-3-large)

    # Anchor + filterable payload — populated from the chunk's section root.
    section_id: str
    source: Source
    source_subcorpus: SourceSubcorpus
    node_type: NodeType
    authority_rank: int | None = None
    in_force: bool | None = None
    usable: bool | None = None
    publication_date: date | None = None
    language: Language | None = None

    # For debugging — the exact text that was embedded (with hierarchy prefix
    # if any). Optional; can be omitted at write time to save space.
    embedded_text: str | None = None


# --------------------------------------------------------------------------
# Helpers — bidirectional traversal types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Neighbor:
    """Returned by ``graph_store.get_neighbors()`` — pairs the connected node
    with the edge that connected it.
    """

    node_id: str
    edge: Edge
    direction: Direction  # "out" if we followed an outgoing edge from the query node


@dataclass(frozen=True)
class RetrievalPath:
    """How a node ended up in a result set. Layer 8 path-aware citations."""

    via: Literal["vector", "graph"]
    score: float  # cosine for vector, rerank for graph
    from_node_id: str | None = None  # only for via="graph" — the seed we expanded from
    edge_type: EdgeType | None = None
    hops: int = 0  # 0 for vector seed, 1+ for graph expansion


# --------------------------------------------------------------------------
# AnswerResult — produced by every retrieval pipeline (v1, v2, agentic)
# --------------------------------------------------------------------------


class AnswerResult(BaseModel):
    """Contract between retrieval, eval, agents, and UI.

    Every retrieval pipeline (v1, v2, agentic) returns this shape so
    downstream consumers can treat them interchangeably.
    """

    question: str
    answer: str

    # IDs of nodes/chunks the answer cites — drives the citation UI.
    cited_source_ids: list[str]

    # Chunk IDs surfaced by retrieval (pre-citation). ``cited_source_ids``
    # is usually a subset of this.
    retrieved_chunks: list[str]

    # How each retrieved/cited id ended up in the result set. Keyed by the
    # node or chunk id; see ``RetrievalPath`` for shape.
    retrieval_paths: dict[str, RetrievalPath] = Field(default_factory=dict)

    # Per-stage latency in milliseconds, e.g. {"retrieve": 120, "rerank": 40}.
    timing_ms: dict[str, int] = Field(default_factory=dict)

    # Anything the answer relied on that wasn't in the question (e.g. assumed
    # tax year, assumed jurisdiction).
    assumptions: list[str] = Field(default_factory=list)

    # Conflicts surfaced during synthesis (e.g. KHO vs Vero guidance).
    conflicts: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}
