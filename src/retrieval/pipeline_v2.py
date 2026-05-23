"""End-to-end v2 retrieval pipeline — GraphRAG.

Wires:

    filters.infer_filters
      → strategy.pick_strategy
      → vector_retriever.retrieve (k=strategy.seed_k)
      → graph_expand.expand (BFS along strategy.edge_types)
      → fetch_chunks_for_sections (vector store)
      → cross_encoder_rerank.score + combine_scores
      → assemble.assemble (n)
      → generate.generate
      → AnswerResult

Same shape as v1's ``Pipeline`` with one expansion step inserted and the
metadata reranker replaced with the cross-encoder + weighted combine.

The cross-encoder is the load-bearing piece — per the Step 7 brief,
graph expansion *without* cross-encoder rerank typically makes results
worse on single-hop queries by adding plausible-but-irrelevant neighbors
that share embedding space with the query. With it, v2 should match or
beat v1 across the board.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.indexing.graph_store import GraphStore
from src.indexing.vector_store import VectorStore
from src.models import AnswerResult, RetrievalPath
from src.retrieval.assemble import AssembledContext, assemble
from src.retrieval.cross_encoder_rerank import (
    ScoredCandidate,
    combine_scores,
    get_reranker,
)
from src.retrieval.filters import infer_filters
from src.retrieval.generate import Generation, generate
from src.retrieval.graph_expand import ExpansionStrategy, expand
from src.retrieval.rerank import RerankedHit
from src.retrieval.strategy import pick_strategy
from src.retrieval.vector_retriever import RetrievedHit, VectorRetriever, _row_to_hit


# Maximum chunks pulled per graph-expanded section. One per section keeps the
# rerank candidate set bounded; the cross-encoder picks the most relevant.
MAX_CHUNKS_PER_SECTION = 1

# How many results to assemble into the final context. Matches v1's default.
DEFAULT_CONTEXT_N = 8


class PipelineV2:
    """v2 retrieval pipeline. Reusable; thread-unsafe (LanceDB / SQLite / torch model)."""

    def __init__(
        self,
        *,
        vector_db_path: str | Path,
        graph_db_path: str | Path = "output/graph.db",
        load_cross_encoder_eagerly: bool = False,
    ) -> None:
        self.vector_db_path = str(vector_db_path)
        self.graph_db_path = str(graph_db_path)
        self.retriever = VectorRetriever(self.vector_db_path)
        self.vector_store = self.retriever.store  # reuse same LanceDB connection
        self.graph = GraphStore(self.graph_db_path)
        # Cross-encoder model is heavy (~1.1 GB, ~5-10 s warmup). Lazy by
        # default so import-time and test fixtures stay fast.
        if load_cross_encoder_eagerly:
            get_reranker()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def answer(
        self,
        question: str,
        *,
        n: int = DEFAULT_CONTEXT_N,
        extra_filters: dict[str, Any] | None = None,
        strategy_override: ExpansionStrategy | None = None,
    ) -> AnswerResult:
        """Run the v2 pipeline and return a schema-locked AnswerResult.

        ``strategy_override`` lets callers (eval scripts, A/B tests) force a
        specific expansion strategy instead of trusting the keyword router.
        """
        timings: dict[str, int] = {}
        t_total = time.perf_counter()

        # 1. Strategy router -------------------------------------------------
        t = time.perf_counter()
        strategy = strategy_override or pick_strategy(question)
        timings["strategy_pick"] = _ms_since(t)

        # 2. Filters ---------------------------------------------------------
        t = time.perf_counter()
        filters = infer_filters(question)
        if extra_filters:
            filters = {**filters, **extra_filters}
        timings["filter_infer"] = _ms_since(t)

        # 3. Vector seeds ----------------------------------------------------
        t = time.perf_counter()
        seeds: list[RetrievedHit] = self.retriever.retrieve(
            question, k=strategy.seed_k, filters=filters or None
        )
        timings["vector_retrieve"] = _ms_since(t)

        # 4. Graph expand ----------------------------------------------------
        t = time.perf_counter()
        seed_section_ids = [h.section_id for h in seeds]
        # Dedupe while preserving order — multiple chunks can anchor on the
        # same section_id, and we want one BFS per section, not per chunk.
        seen_seeds: set[str] = set()
        unique_seeds: list[str] = []
        for sid in seed_section_ids:
            if sid not in seen_seeds:
                seen_seeds.add(sid)
                unique_seeds.append(sid)
        paths: dict[str, RetrievalPath] = expand(unique_seeds, strategy, self.graph)
        timings["graph_expand"] = _ms_since(t)

        # 5. Materialise expanded nodes as chunk candidates ------------------
        # Seed chunks come directly from the vector retrieve. Graph-expanded
        # nodes (paths.keys() minus seeds) need a chunk lookup from the vector
        # store — they don't have cosine scores, so cross-encoder discrimination
        # is the only signal until combine_scores runs.
        t = time.perf_counter()
        candidate_pool: dict[str, _Candidate] = {}
        for h in seeds:
            candidate_pool[h.chunk_id] = _Candidate(
                hit=h,
                cosine_sim=h.cosine_sim,
                from_seed=True,
                retrieval_path=RetrievalPath(via="vector", score=h.cosine_sim, hops=0),
            )
        # Expanded nodes — fetch one chunk per section_id from LanceDB.
        expanded_only = [nid for nid in paths if nid not in seen_seeds]
        if expanded_only:
            expanded_hits = _fetch_chunks_for_sections(self.vector_store, expanded_only)
            for h in expanded_hits:
                if h.chunk_id in candidate_pool:
                    continue
                path = paths.get(h.section_id) or RetrievalPath(
                    via="graph", score=0.0, hops=1
                )
                candidate_pool[h.chunk_id] = _Candidate(
                    hit=h,
                    cosine_sim=h.cosine_sim,  # cosine_sim==1.0 placeholder from fetch
                    from_seed=False,
                    retrieval_path=path,
                )
        timings["materialise"] = _ms_since(t)

        # 6. Cross-encoder rerank --------------------------------------------
        t = time.perf_counter()
        rr = get_reranker()
        candidates = list(candidate_pool.values())
        pairs = [(c.hit.chunk_id, c.hit.embedded_text or "") for c in candidates]
        scored: list[ScoredCandidate] = rr.score(question, pairs)
        # Annotate ScoredCandidate with cosine + metadata-score so the
        # weighted combine has all three components per the strategy.
        cand_by_id = {c.hit.chunk_id: c for c in candidates}
        for s in scored:
            c = cand_by_id[s.chunk_id]
            # Convert similarity in [0,1] back to a distance-shaped value the
            # combine helper expects (it does the inverse internally).
            s.cosine = max(0.0, min(2.0, 2.0 * (1.0 - c.cosine_sim)))
            s.metadata_score = _metadata_signal(c.hit)
        combined = combine_scores(scored, weights=strategy.rerank_weights)
        timings["cross_encoder"] = _ms_since(t)

        # 7. Build RerankedHits for assemble.assemble ------------------------
        t = time.perf_counter()
        reranked: list[RerankedHit] = []
        for s in combined:
            c = cand_by_id[s.chunk_id]
            reranked.append(
                RerankedHit(
                    hit=c.hit,
                    score=s.final_score or s.cross_score,
                    components={
                        "cross_encoder": s.cross_score,
                        "cosine_sim": c.cosine_sim,
                        "metadata": s.metadata_score or 0.0,
                        "final": s.final_score or 0.0,
                        "hops": float(c.retrieval_path.hops),
                    },
                )
            )
        timings["rerank_build"] = _ms_since(t)

        # 8. Assemble + generate (unchanged from v1) -------------------------
        t = time.perf_counter()
        context: AssembledContext = assemble(reranked, graph=self.graph, n=n)
        timings["assemble"] = _ms_since(t)

        t = time.perf_counter()
        gen: Generation = generate(question, context)
        timings["generate"] = _ms_since(t)

        timings["total"] = _ms_since(t_total)

        return _build_answer_result_v2(
            question=question,
            generation=gen,
            context=context,
            reranked=reranked,
            paths=paths,
            candidate_pool=candidate_pool,
            strategy=strategy,
            applied_filters=filters,
            timings=timings,
        )

    def close(self) -> None:
        self.graph.close()


# ----------------------------------------------------------------------
# Module-level singleton + thin function for scripts/ask.py callers.
# ----------------------------------------------------------------------


_pipeline_v2: PipelineV2 | None = None


def get_pipeline_v2(vector_db_path: str | Path) -> PipelineV2:
    """Process-singleton v2 pipeline. Path honored only on first call."""
    global _pipeline_v2
    if _pipeline_v2 is None:
        _pipeline_v2 = PipelineV2(vector_db_path=vector_db_path)
    return _pipeline_v2


def answer_v2(
    question: str,
    *,
    vector_db_path: str | Path,
    n: int = DEFAULT_CONTEXT_N,
    extra_filters: dict[str, Any] | None = None,
    strategy_override: ExpansionStrategy | None = None,
) -> AnswerResult:
    """Convenience: open a v2 pipeline (cached) and run one question."""
    return get_pipeline_v2(vector_db_path).answer(
        question,
        n=n,
        extra_filters=extra_filters,
        strategy_override=strategy_override,
    )


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


@dataclass
class _Candidate:
    """One candidate flowing through the v2 pipeline."""

    hit: RetrievedHit
    cosine_sim: float
    from_seed: bool
    retrieval_path: RetrievalPath


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _fetch_chunks_for_sections(
    store: VectorStore, section_ids: list[str], limit_per: int = MAX_CHUNKS_PER_SECTION
) -> list[RetrievedHit]:
    """Look up chunks whose ``section_id`` is in the supplied list.

    LanceDB's ``IN`` clause works fine for up to a few hundred ids. We keep
    one chunk per section (the first one, ordered by chunk_id) because the
    cross-encoder later picks the best — fetching all chunks per section
    would inflate the candidate pool 3-5x without quality benefit.
    """
    if store.table is None or not section_ids:
        return []
    # Single-quote each id, escape embedded quotes (rare but defensible).
    quoted = ",".join("'" + sid.replace("'", "''") + "'" for sid in section_ids)
    where = f"section_id IN ({quoted})"
    # search() requires a vector — we want a metadata-only scan. LanceDB's
    # to_arrow with a where filter on the table directly does this.
    # Slightly indirect: use a search with a dummy vector at low limit to
    # exploit the prefilter index. We then re-fetch via search() with a high
    # limit per section.
    arrow = store.table.search().where(where, prefilter=True).limit(
        limit_per * len(section_ids) + 50
    ).to_arrow()
    # Dedupe: keep ``limit_per`` chunks per section_id, ordered by chunk_id.
    seen_count: dict[str, int] = {}
    out: list[RetrievedHit] = []
    rows = arrow.to_pylist()
    # Sort so the per-section pick is deterministic.
    rows.sort(key=lambda r: r.get("chunk_id", ""))
    for row in rows:
        sid = row.get("section_id", "")
        if seen_count.get(sid, 0) >= limit_per:
            continue
        seen_count[sid] = seen_count.get(sid, 0) + 1
        # No real cosine for graph-expanded chunks (we didn't query by them);
        # we pass distance=1.0 → similarity 0.0 as a placeholder. The cross-
        # encoder is what discriminates these.
        out.append(_row_to_hit(row, distance=1.0))
    return out


def _metadata_signal(hit: RetrievedHit) -> float:
    """Light-weight metadata score in [0, 1] for the weighted combine.

    Picks up authority + usable + in_force so the cross-encoder's choice
    isn't blind to source rank. Not as elaborate as v1's metadata reranker
    because the cross-encoder is doing most of the discrimination work.
    """
    score = 0.0
    if hit.authority_rank is not None:
        score += hit.authority_rank / 100.0 * 0.6
    if hit.usable is True:
        score += 0.2
    elif hit.usable is False:
        score -= 0.4
    if hit.in_force is True:
        score += 0.2
    return max(0.0, min(1.0, score))


def _build_answer_result_v2(
    *,
    question: str,
    generation: Generation,
    context: AssembledContext,
    reranked: list[RerankedHit],
    paths: dict[str, RetrievalPath],
    candidate_pool: dict[str, _Candidate],
    strategy: ExpansionStrategy,
    applied_filters: dict[str, Any],
    timings: dict[str, int],
) -> AnswerResult:
    """Compose the AnswerResult for v2. ``retrieval_paths`` keys are chunk_ids
    for vector-anchored sources and node_ids for graph-expanded ones (allowed
    by the schema docstring)."""
    retrieved_chunks: list[str] = [s.chunk_id for s in context.sources]

    retrieval_paths: dict[str, RetrievalPath] = {}
    for s in context.sources:
        c = candidate_pool.get(s.chunk_id)
        if c is not None:
            retrieval_paths[s.chunk_id] = c.retrieval_path
        else:
            # Fallback — should not happen, but keep schema-correct.
            retrieval_paths[s.chunk_id] = RetrievalPath(via="vector", score=s.rerank_score)

    assumptions: list[str] = [
        f"Expansion strategy: {strategy.name} (seed_k={strategy.seed_k}, "
        f"edges={list(strategy.edge_types)}, hops={strategy.max_hops}).",
    ]
    if applied_filters.get("usable") is True:
        assumptions.append("Restricted to currently usable sources.")
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

    return AnswerResult(
        question=question,
        answer=generation.answer,
        cited_source_ids=generation.cited_chunk_ids,
        retrieved_chunks=retrieved_chunks,
        retrieval_paths=retrieval_paths,
        timing_ms=timings,
        assumptions=assumptions,
        conflicts=[],
    )
