"""End-to-end v1 retrieval pipeline.

Wires:

    filters.infer_filters → vector_retriever.retrieve (k=20)
                          → rerank.rerank
                          → assemble.assemble (n=8)
                          → generate.generate
                          → AnswerResult

Returns the schema-locked ``AnswerResult`` from src.models so v2 and the
agentic pipeline can be swapped in without UI/eval changes.

The pipeline is stateful at the boundaries — it holds a ``VectorRetriever``
and a ``GraphStore`` for the lifetime of the process so each ``answer()``
call doesn't reopen LanceDB and SQLite. Construct once per process; call
``answer()`` many times.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.indexing.graph_store import GraphStore
from src.models import AmendmentCaveat, AnswerResult, RetrievalPath
from src.retrieval.assemble import AssembledContext, assemble
from src.retrieval.caveats import build_amendment_caveats
from src.retrieval.filters import infer_filters
from src.retrieval.generate import Generation, generate
from src.retrieval.query_rewrite import ExpandedQuery, expand_query
from src.retrieval.rerank import RerankedHit, rerank
from src.retrieval.vector_retriever import VectorRetriever


# Defaults from the brief §B5.2 / §B5.4.
DEFAULT_RETRIEVE_K = 20
DEFAULT_CONTEXT_N = 8


class Pipeline:
    """v1 retrieval pipeline. Reusable; thread-unsafe (LanceDB / SQLite)."""

    def __init__(
        self,
        *,
        vector_db_path: str | Path,
        graph_db_path: str | Path = "output/graph.db",
        query_rewrite: bool = True,
    ) -> None:
        self.vector_db_path = str(vector_db_path)
        self.graph_db_path = str(graph_db_path)
        # ``query_rewrite`` toggles Plan A's LLM expansion. Default on;
        # the eval / A/B harness can disable it by passing False.
        self.query_rewrite = query_rewrite
        self.retriever = VectorRetriever(self.vector_db_path)
        self.graph = GraphStore(self.graph_db_path)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def answer(
        self,
        question: str,
        *,
        k: int = DEFAULT_RETRIEVE_K,
        n: int = DEFAULT_CONTEXT_N,
        extra_filters: dict[str, Any] | None = None,
    ) -> AnswerResult:
        """Run the v1 pipeline and return the schema-locked AnswerResult."""
        timings: dict[str, int] = {}
        t_total = time.perf_counter()

        # 1. Filters --------------------------------------------------------
        # Filter inference runs on the ORIGINAL question — the user's
        # actual intent shouldn't be diluted by the LLM rewrite.
        t = time.perf_counter()
        filters = infer_filters(question)
        if extra_filters:
            filters = {**filters, **extra_filters}
        timings["filter_infer"] = _ms_since(t)

        # 1b. Query rewrite -------------------------------------------------
        # Plan A — one short LLM call to add Finnish equivalents and
        # likely document-type signals before retrieval. Soft-fails to
        # the original question on any LLM error. See
        # ``src/retrieval/query_rewrite.py`` for the design notes.
        if self.query_rewrite:
            t = time.perf_counter()
            expanded: ExpandedQuery = expand_query(question)
            timings["query_rewrite"] = _ms_since(t)
            retrieval_query = expanded.expanded
        else:
            expanded = ExpandedQuery(
                original=question, expanded=question,
                finnish_keywords=(), year=None, cached=False,
            )
            retrieval_query = question

        # 2. Vector retrieve ------------------------------------------------
        t = time.perf_counter()
        hits = self.retriever.retrieve(retrieval_query, k=k, filters=filters or None)
        timings["vector_retrieve"] = _ms_since(t)

        # 3. Rerank ---------------------------------------------------------
        # Bulk-fetch temporal_status for the candidate section_ids so the
        # graded penalty can be applied (Move 3). One SQL roundtrip
        # regardless of k. Hits without a status entry fall back to the
        # legacy binary penalty inside rerank().
        t = time.perf_counter()
        unique_section_ids = list({h.section_id for h in hits})
        temporal_status_map = self.graph.get_temporal_status_map(unique_section_ids)
        reranked: list[RerankedHit] = rerank(
            question, hits, temporal_status_map=temporal_status_map
        )
        timings["rerank"] = _ms_since(t)

        # 4. Assemble -------------------------------------------------------
        t = time.perf_counter()
        context: AssembledContext = assemble(reranked, graph=self.graph, n=n)
        timings["assemble"] = _ms_since(t)

        # 5. Generate -------------------------------------------------------
        t = time.perf_counter()
        gen: Generation = generate(question, context)
        timings["generate"] = _ms_since(t)

        # 6. Caveats --------------------------------------------------------
        # Build amendment_caveats from the actually-cited chunks. One graph
        # roundtrip; skipped entirely when the LLM cited nothing.
        amendment_caveats = build_amendment_caveats(
            cited_chunk_ids=gen.cited_chunk_ids,
            context=context,
            graph=self.graph,
        )

        timings["total"] = _ms_since(t_total)

        return _build_answer_result(
            question=question,
            generation=gen,
            context=context,
            reranked=reranked,
            applied_filters=filters,
            timings=timings,
            amendment_caveats=amendment_caveats,
            expanded=expanded,
        )

    def close(self) -> None:
        self.graph.close()


# ----------------------------------------------------------------------
# Module-level singleton + thin function for scripts/ask.py callers.
# ----------------------------------------------------------------------


_pipeline: Pipeline | None = None


def get_pipeline(
    vector_db_path: str | Path,
    query_rewrite: bool = True,
) -> Pipeline:
    """Process-singleton pipeline. The path is honored only on first call;
    ``query_rewrite`` is honored on first call and on flag change (the
    singleton is rebuilt when the toggle flips so A/B comparisons get a
    clean retriever each time)."""
    global _pipeline
    if _pipeline is None or _pipeline.query_rewrite != query_rewrite:
        _pipeline = Pipeline(
            vector_db_path=vector_db_path, query_rewrite=query_rewrite
        )
    return _pipeline


def answer(
    question: str,
    *,
    vector_db_path: str | Path,
    k: int = DEFAULT_RETRIEVE_K,
    n: int = DEFAULT_CONTEXT_N,
    extra_filters: dict[str, Any] | None = None,
    query_rewrite: bool = True,
) -> AnswerResult:
    """Convenience: open a pipeline (cached) and run one question."""
    return get_pipeline(vector_db_path, query_rewrite).answer(
        question, k=k, n=n, extra_filters=extra_filters
    )


# ----------------------------------------------------------------------
# Internal — convert intermediate state into AnswerResult.
# ----------------------------------------------------------------------


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _build_answer_result(
    *,
    question: str,
    generation: Generation,
    context: AssembledContext,
    reranked: list[RerankedHit],
    applied_filters: dict[str, Any],
    timings: dict[str, int],
    amendment_caveats: list[AmendmentCaveat] | None = None,
    expanded: ExpandedQuery | None = None,
) -> AnswerResult:
    """Compose the AnswerResult contract.

    ``retrieved_chunks`` carries the ordered chunk_ids that landed in the
    assembled context (after dedup-by-section). ``retrieval_paths`` covers
    those same chunks keyed by chunk_id, all ``via="vector"`` at v1.
    """
    retrieved_chunks: list[str] = [s.chunk_id for s in context.sources]

    retrieval_paths: dict[str, RetrievalPath] = {}
    # Map chunk_id → cosine_sim from context.sources (already deduped/topN).
    for s in context.sources:
        retrieval_paths[s.chunk_id] = RetrievalPath(
            via="vector",
            score=s.rerank_score,
            from_node_id=None,
            edge_type=None,
            hops=0,
        )

    # Assumptions: surface the implicit filters we applied so the UI can
    # show "we assumed: current rules only" etc.
    assumptions: list[str] = []
    if applied_filters.get("usable") is True:
        assumptions.append("Restricted to currently usable (non-repealed) sources.")
    if applied_filters.get("in_force") is True:
        assumptions.append("Restricted to sources in force.")
    src = applied_filters.get("source")
    if src == "finlex":
        assumptions.append("Restricted to Finlex (statute) sources.")
    elif src == "vero":
        assumptions.append("Restricted to Vero (tax administration) sources.")
    lang = applied_filters.get("language")
    if lang:
        assumptions.append(f"Restricted to language={lang}.")
    if expanded is not None and expanded.finnish_keywords:
        kw = ", ".join(expanded.finnish_keywords[:4])
        assumptions.append(
            f"Query expanded with Finnish keywords: {kw}."
        )

    return AnswerResult(
        question=question,
        answer=generation.answer,
        cited_source_ids=generation.cited_chunk_ids,
        retrieved_chunks=retrieved_chunks,
        retrieval_paths=retrieval_paths,
        timing_ms=timings,
        assumptions=assumptions,
        conflicts=[],  # v1 leaves conflict surfacing to the LLM prose; Verifier in Step 8 fills this.
        amendment_caveats=amendment_caveats or [],
    )
