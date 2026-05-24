"""LanceDB-backed vector store adapter (Step 4a.6).

Thin wrapper that hides LanceDB specifics from callers and keeps the
input_type='query' vs 'document' distinction explicit — Voyage's
voyage-3-large is asymmetric and mixing the two degrades retrieval quality.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import lancedb
import pyarrow as pa

from src.indexing.voyage_client import OUTPUT_DIMENSION, embed_batch, get_client
from src.models import VectorRecord


VECTOR_TABLE = "chunks"


def arrow_schema() -> pa.Schema:
    """Arrow schema mirroring src.models.VectorRecord. Keep in sync."""
    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), OUTPUT_DIMENSION)),
            pa.field("section_id", pa.string()),
            pa.field("source", pa.string()),
            pa.field("source_subcorpus", pa.string()),
            pa.field("node_type", pa.string()),
            pa.field("authority_rank", pa.int32()),
            pa.field("in_force", pa.bool_()),
            pa.field("usable", pa.bool_()),
            pa.field("publication_date", pa.string()),
            pa.field("language", pa.string()),
            pa.field("embedded_text", pa.string()),
        ]
    )


def _record_to_row(r: VectorRecord) -> dict[str, Any]:
    return {
        "chunk_id": r.chunk_id,
        "vector": r.vector,
        "section_id": r.section_id,
        "source": r.source,
        "source_subcorpus": r.source_subcorpus,
        "node_type": r.node_type,
        "authority_rank": r.authority_rank,
        "in_force": r.in_force,
        "usable": r.usable,
        "publication_date": (
            r.publication_date.isoformat() if r.publication_date else None
        ),
        "language": r.language,
        "embedded_text": r.embedded_text,
    }


def _filter_to_where(filters: dict[str, Any] | None) -> str | None:
    """Translate a simple equality dict into LanceDB's SQL filter syntax.

    Supports str, bool, int, and None (rendered as IS NULL). Lists become
    SQL ``IN`` clauses. Returns None when filters is empty.
    """
    if not filters:
        return None
    parts: list[str] = []
    for k, v in filters.items():
        if v is None:
            parts.append(f"{k} IS NULL")
        elif isinstance(v, bool):
            parts.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            parts.append(f"{k} = {v}")
        elif isinstance(v, str):
            esc = v.replace("'", "''")
            parts.append(f"{k} = '{esc}'")
        elif isinstance(v, (list, tuple, set)):
            quoted = ", ".join(
                f"'{x.replace(chr(39), chr(39)*2)}'" if isinstance(x, str) else str(x)
                for x in v
            )
            parts.append(f"{k} IN ({quoted})")
        else:
            raise ValueError(f"Unsupported filter value for {k}: {v!r}")
    return " AND ".join(parts)


class VectorStore:
    """LanceDB-backed implementation of the Step 4 vector store interface."""

    def __init__(self, path: str | Path = "output/lancedb") -> None:
        self.path = str(path)
        self.db = lancedb.connect(self.path)
        if VECTOR_TABLE in self.db.table_names():
            self.table = self.db.open_table(VECTOR_TABLE)
        else:
            self.table = None  # call create_table() before writing

    # ----- write path -----------------------------------------------------

    def create_table(self, overwrite: bool = False) -> None:
        mode = "overwrite" if overwrite else "create"
        self.table = self.db.create_table(
            VECTOR_TABLE, schema=arrow_schema(), mode=mode
        )

    def upsert(self, record: VectorRecord) -> None:
        self.upsert_batch([record])

    def upsert_batch(self, records: Iterable[VectorRecord]) -> None:
        if self.table is None:
            self.create_table()
        rows = [_record_to_row(r) for r in records]
        if not rows:
            return
        # LanceDB's add() appends; for idempotent re-runs callers should
        # dedupe by chunk_id upstream (the resumable embed pass does).
        self.table.add(rows)

    # ----- read path ------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[dict, float]]:
        """Vector search with optional metadata filters.

        Returns (row_dict, score) pairs. Score is cosine distance for the
        default index — lower is closer. We expose the raw LanceDB row dict
        rather than VectorRecord so callers can read the embedded_text field
        without re-validating Pydantic on the hot path.
        """
        if self.table is None:
            raise RuntimeError("vector table not created yet")
        q = self.table.search(query_vector).limit(k)
        where = _filter_to_where(filters)
        if where:
            q = q.where(where, prefilter=True)
        results = q.to_list()
        out: list[tuple[dict, float]] = []
        for row in results:
            score = row.pop("_distance", float("inf"))
            out.append((row, score))
        return out

    def search_by_text(
        self,
        query_text: str,
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[dict, float]]:
        """Embed the query (input_type='query') then search.

        The query/document asymmetry matters: mixing them up measurably
        degrades retrieval quality on voyage-3-large.
        """
        client = get_client()
        vec, _ = embed_batch(client, [query_text], input_type="query")
        return self.search(vec[0], k=k, filters=filters)

    # ----- FTS / hybrid path ---------------------------------------------

    def search_fts(
        self,
        query_text: str,
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[dict, float]]:
        """Sparse BM25 search over ``embedded_text``.

        Requires the FTS index built by ``scripts.build_fts_index``.
        Returns the same shape as ``search()``: ``(row, score)`` pairs.
        Higher BM25 scores are better (opposite direction from vector
        distance), but the caller can use the ranking position rather
        than the score for fusion.
        """
        if self.table is None:
            raise RuntimeError("vector table not created yet")
        q = self.table.search(query_text, query_type="fts").limit(k)
        where = _filter_to_where(filters)
        if where:
            q = q.where(where, prefilter=True)
        results = q.to_list()
        out: list[tuple[dict, float]] = []
        for row in results:
            score = row.pop("_score", row.pop("_distance", 0.0))
            out.append((row, score))
        return out

    def search_hybrid(
        self,
        query_text: str,
        query_vector: list[float],
        k: int = 20,
        filters: dict[str, Any] | None = None,
        rrf_k: int = 60,
        oversample: int = 3,
    ) -> list[tuple[dict, float]]:
        """Hybrid vector + BM25 search with Reciprocal Rank Fusion (RRF).

        Each backend retrieves ``k * oversample`` candidates; ranks are
        fused with ``score(d) = sum(1 / (rrf_k + rank))`` over the
        rankings the candidate appears in. The top ``k`` after fusion
        are returned.

        ``rrf_k=60`` is the standard RRF constant from Cormack et al.
        (2009) and is robust to score-scale differences. Falls back to
        pure vector search when the FTS index is missing (e.g. local
        clone that hasn't run ``scripts.build_fts_index`` yet).
        """
        if self.table is None:
            raise RuntimeError("vector table not created yet")
        oversample_k = max(k, k * oversample)

        # Vector ranking — already returns sorted ascending by distance.
        vec_rows = self.search(query_vector, k=oversample_k, filters=filters)

        # BM25 ranking — may fail if no FTS index exists; degrade gracefully.
        try:
            fts_rows = self.search_fts(query_text, k=oversample_k, filters=filters)
        except Exception:
            return vec_rows[:k]

        # Reciprocal rank fusion. We key on chunk_id since that's the PK.
        scores: dict[str, float] = {}
        first_row: dict[str, dict] = {}
        for rank, (row, _d) in enumerate(vec_rows):
            cid = row["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
            first_row.setdefault(cid, row)
        for rank, (row, _s) in enumerate(fts_rows):
            cid = row["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)
            first_row.setdefault(cid, row)

        # Sort by fused score desc, take top-k. We re-emit ``_distance``-like
        # values (1 - fused_score) so downstream cosine-similarity math keeps
        # working: distance ∈ [0, ~2], smaller = better. The exact value
        # carries no calibrated meaning beyond ordering — the reranker is
        # the source of truth for the final score.
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        out: list[tuple[dict, float]] = []
        for cid, fused in ranked:
            # Translate fused score back to a distance-shaped value so
            # ``_distance_to_similarity`` in vector_retriever stays sane.
            distance = max(0.0, 1.0 - min(fused * (rrf_k + 1), 1.0))
            out.append((first_row[cid], distance))
        return out

    def search_by_text_hybrid(
        self,
        query_text: str,
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[dict, float]]:
        """Embed the query then run hybrid vector + BM25 search.

        Convenience wrapper that mirrors ``search_by_text`` but applies
        Reciprocal Rank Fusion across both rankings.
        """
        client = get_client()
        vec, _ = embed_batch(client, [query_text], input_type="query")
        return self.search_hybrid(query_text, vec[0], k=k, filters=filters)

    def count(self) -> int:
        return 0 if self.table is None else self.table.count_rows()
