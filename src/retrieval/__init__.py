"""Track D — Retrieval v1 (vector-only baseline).

The path below is the one-line swap when the full embed (Step 4a) completes:
flip ``VECTOR_DB_PATH`` from the pilot to the full store and re-run.
"""
from __future__ import annotations

from src.models import AnswerResult, RetrievalPath
from src.retrieval.pipeline import Pipeline, answer, get_pipeline


# Default vector store — full corpus (402,088 vectors) now that Step 4a is done.
VECTOR_DB_PATH = "output/lancedb"

# Graph store is fully loaded at start of the parallel phase — no switch.
GRAPH_DB_PATH = "output/graph.db"


__all__ = [
    "AnswerResult",
    "RetrievalPath",
    "Pipeline",
    "answer",
    "get_pipeline",
    "VECTOR_DB_PATH",
    "GRAPH_DB_PATH",
]
