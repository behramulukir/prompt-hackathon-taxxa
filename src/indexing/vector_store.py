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

    def count(self) -> int:
        return 0 if self.table is None else self.table.count_rows()
