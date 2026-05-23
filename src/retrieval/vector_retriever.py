"""Vector retriever — thin wrapper over ``VectorStore.search_by_text``.

Owns three concerns the underlying adapter intentionally doesn't:

1. Holds onto a single ``VectorStore`` instance per process (the adapter's
   constructor opens a LanceDB connection — we don't want to reopen it on
   every call).
2. Returns a plain list of ``RetrievedHit`` records with cosine *similarity*
   (1 - distance), so downstream rerank can sum it with bonuses without
   thinking about distance vs similarity direction.
3. Defaults to v1's over-retrieval depth (k=20) so the reranker has enough
   candidates to do useful work; callers can override.

Voyage's voyage-3-large is asymmetric — ``search_by_text`` calls
``embed_batch(input_type="query")`` already; we never need to embed at this
layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.indexing.vector_store import VectorStore


# Default k for v1 — over-retrieve, then cull in rerank.
DEFAULT_K = 20


@dataclass(frozen=True)
class RetrievedHit:
    """One row from the vector store + cosine similarity in [0, 1]."""

    chunk_id: str
    section_id: str
    source: str
    source_subcorpus: str
    node_type: str
    authority_rank: int | None
    in_force: bool | None
    usable: bool | None
    publication_date: str | None  # ISO date string, may be None
    language: str | None
    embedded_text: str | None
    cosine_sim: float


def _distance_to_similarity(d: float) -> float:
    """LanceDB returns cosine *distance* (0 = identical, 2 = opposite). Map
    back to cosine *similarity* in roughly [0, 1] for use in rerank.

    LanceDB's cosine distance is ``1 - cos_sim`` for the default normalization,
    so similarity is ``1 - distance``. Clamp to [0, 1] to guard against
    numerical drift on near-duplicate vectors.
    """
    return max(0.0, min(1.0, 1.0 - d))


def _row_to_hit(row: dict[str, Any], distance: float) -> RetrievedHit:
    return RetrievedHit(
        chunk_id=row["chunk_id"],
        section_id=row["section_id"],
        source=row["source"],
        source_subcorpus=row["source_subcorpus"],
        node_type=row["node_type"],
        authority_rank=row.get("authority_rank"),
        in_force=row.get("in_force"),
        usable=row.get("usable"),
        publication_date=row.get("publication_date"),
        language=row.get("language"),
        embedded_text=row.get("embedded_text"),
        cosine_sim=_distance_to_similarity(distance),
    )


class VectorRetriever:
    """Reusable retriever bound to a single LanceDB instance.

    Construct once per process. ``retrieve()`` is the hot path.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self.store = VectorStore(db_path)

    def retrieve(
        self,
        query: str,
        *,
        k: int = DEFAULT_K,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedHit]:
        """Embed the query (input_type='query') and search.

        Filters are pushed down into LanceDB's ``where`` clause via the
        adapter; only keys present on ``VectorRecord`` are supported (see
        ``filters.infer_filters``).
        """
        rows = self.store.search_by_text(query, k=k, filters=filters)
        return [_row_to_hit(r, d) for r, d in rows]


def retrieve_vector(
    query: str,
    *,
    db_path: str | Path,
    k: int = DEFAULT_K,
    filters: dict[str, Any] | None = None,
) -> list[RetrievedHit]:
    """One-shot convenience for scripts/tests. Opens a fresh ``VectorStore``.

    Prefer ``VectorRetriever`` in long-running processes.
    """
    return VectorRetriever(db_path).retrieve(query, k=k, filters=filters)
