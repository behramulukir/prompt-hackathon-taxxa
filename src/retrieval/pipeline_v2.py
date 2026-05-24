"""End-to-end v2 retrieval pipeline — GraphRAG.

Wires:

    filters.infer_filters
      → strategy.pick_strategy
      → vector_retriever.retrieve (k=strategy.seed_k)
      → graph_expand.expand (BFS along strategy.edge_types)
      → fetch_chunks_for_sections (vector store)
      → [rerank — see RerankMode below]
      → assemble.assemble (n)
      → generate.generate
      → AnswerResult

Same shape as v1's ``Pipeline`` with one expansion step inserted before
rerank. The reranker is pluggable so we can isolate whether the
cross-encoder helps or hurts on this corpus.

``RerankMode``:

- ``"cross_encoder"`` — BAAI/bge-reranker-v2-m3 + weighted combine with
  cosine and a light metadata signal. The Step-7 brief recommends this
  as load-bearing — graph expansion without it tends to add noise.
- ``"vector"`` — skip the cross-encoder; re-query LanceDB so every
  candidate (seeds + graph-expanded) carries a real cosine, then apply
  v1's full metadata reranker (cosine + authority + recency + term bonus
  + repealed penalty). Use this when v2 with cross-encoder regresses on
  basic factual queries — it isolates "did the graph add useful nodes?"
  from "is the cross-encoder picking badly on Finnish legal text?".
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from typing import Literal

from src.indexing.graph_store import GraphStore
from src.indexing.vector_store import VectorStore
from src.models import AmendmentCaveat, AnswerResult, RetrievalPath
from src.retrieval.assemble import AssembledContext, assemble
from src.retrieval.caveats import build_amendment_caveats
from src.retrieval.cross_encoder_rerank import (
    ScoredCandidate,
    combine_scores,
    get_reranker,
)
from src.retrieval.filters import infer_filters
from src.retrieval.generate import Generation, generate
from src.retrieval.graph_expand import ExpansionStrategy, expand
from src.retrieval.query_rewrite import ExpandedQuery, expand_query
from src.retrieval.rerank import RerankedHit, rerank as metadata_rerank
from src.retrieval.strategy import pick_strategy
from src.retrieval.vector_retriever import RetrievedHit, VectorRetriever, _row_to_hit


# Maximum chunks pulled per graph-expanded section. One per section keeps the
# rerank candidate set bounded; downstream rerank picks the most relevant.
MAX_CHUNKS_PER_SECTION = 1

# How many results to assemble into the final context. Matches v1's default.
DEFAULT_CONTEXT_N = 8

# Reranker selector. Flip this to switch the default mode across the whole
# codebase without touching call sites. The constructor arg
# ``rerank_mode`` and the CLI ``--rerank=...`` flag override it.
DEFAULT_RERANK_MODE: "RerankMode" = "cross_encoder"

RerankMode = Literal["cross_encoder", "vector"]


class PipelineV2:
    """v2 retrieval pipeline. Reusable; thread-unsafe (LanceDB / SQLite / torch model)."""

    def __init__(
        self,
        *,
        vector_db_path: str | Path,
        graph_db_path: str | Path = "output/graph.db",
        rerank_mode: RerankMode = DEFAULT_RERANK_MODE,
        load_cross_encoder_eagerly: bool = False,
        query_rewrite: bool = True,
    ) -> None:
        self.vector_db_path = str(vector_db_path)
        self.graph_db_path = str(graph_db_path)
        self.rerank_mode: RerankMode = rerank_mode
        # Plan A — LLM query expansion before retrieval. Default on; the
        # eval / A-B harness can disable via constructor or via the
        # ``--no-rewrite`` CLI flag (passed through scripts.ask).
        self.query_rewrite = query_rewrite
        self.retriever = VectorRetriever(self.vector_db_path)
        self.vector_store = self.retriever.store  # reuse same LanceDB connection
        self.graph = GraphStore(self.graph_db_path)
        # Cross-encoder model is heavy (~1.1 GB, ~5-10 s warmup). Lazy by
        # default; only relevant for ``rerank_mode='cross_encoder'``.
        if load_cross_encoder_eagerly and rerank_mode == "cross_encoder":
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
        # Router reads the ORIGINAL question — the LLM rewrite may
        # mention domain terms the user didn't and would noise up the
        # strategy decision.
        t = time.perf_counter()
        strategy = strategy_override or pick_strategy(question)
        timings["strategy_pick"] = _ms_since(t)

        # 2. Filters ---------------------------------------------------------
        # Same rationale — filters reflect user intent, not the rewrite.
        t = time.perf_counter()
        filters = infer_filters(question)
        if extra_filters:
            filters = {**filters, **extra_filters}
        timings["filter_infer"] = _ms_since(t)

        # 2b. Query rewrite --------------------------------------------------
        # Plan A — see ``src/retrieval/query_rewrite.py``. Adds Finnish
        # equivalents + likely document-type signals to the retrieval
        # query so the dense + sparse backends both see a richer match
        # surface. Soft-fails to the original question on any LLM error.
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

        # 3. Vector seeds ----------------------------------------------------
        t = time.perf_counter()
        seeds: list[RetrievedHit] = self.retriever.retrieve(
            retrieval_query, k=strategy.seed_k, filters=filters or None
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

        # 6. Rerank — branched by mode --------------------------------------
        t = time.perf_counter()
        candidates = list(candidate_pool.values())
        # Common to both rerank modes: bulk-fetch temporal_status for the
        # candidate sections so the graded penalty / metadata signal can be
        # ancestor-aware (Move 3).
        candidate_section_ids = list({c.hit.section_id for c in candidates})
        temporal_status_map = self.graph.get_temporal_status_map(
            candidate_section_ids
        )
        if self.rerank_mode == "cross_encoder":
            reranked = _rerank_cross_encoder(
                question=question,
                candidates=candidates,
                strategy=strategy,
                candidate_pool=candidate_pool,
                temporal_status_map=temporal_status_map,
            )
            timings["cross_encoder"] = _ms_since(t)
        else:  # "vector"
            reranked = _rerank_vector(
                question=question,
                candidates=candidates,
                candidate_pool=candidate_pool,
                retriever=self.retriever,
                graph=self.graph,
                temporal_status_map=temporal_status_map,
            )
            timings["vector_rerank"] = _ms_since(t)

        # 8. Assemble + generate (unchanged from v1) -------------------------
        t = time.perf_counter()
        context: AssembledContext = assemble(reranked, graph=self.graph, n=n)
        timings["assemble"] = _ms_since(t)

        t = time.perf_counter()
        gen: Generation = generate(question, context)
        timings["generate"] = _ms_since(t)

        # Amendment caveats from the actually-cited chunks (Move 5).
        amendment_caveats = build_amendment_caveats(
            cited_chunk_ids=gen.cited_chunk_ids,
            context=context,
            graph=self.graph,
        )

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
            amendment_caveats=amendment_caveats,
            expanded=expanded,
        )

    def close(self) -> None:
        self.graph.close()


# ----------------------------------------------------------------------
# Module-level singleton + thin function for scripts/ask.py callers.
# ----------------------------------------------------------------------


_pipeline_v2: PipelineV2 | None = None


def get_pipeline_v2(
    vector_db_path: str | Path,
    rerank_mode: RerankMode = DEFAULT_RERANK_MODE,
    query_rewrite: bool = True,
) -> PipelineV2:
    """Process-singleton v2 pipeline. Path + rerank_mode + query_rewrite
    honored only on first call — switching mid-process requires
    resetting ``_pipeline_v2``.
    """
    global _pipeline_v2
    needs_new = (
        _pipeline_v2 is None
        or _pipeline_v2.rerank_mode != rerank_mode
        or _pipeline_v2.query_rewrite != query_rewrite
    )
    if needs_new:
        _pipeline_v2 = PipelineV2(
            vector_db_path=vector_db_path,
            rerank_mode=rerank_mode,
            query_rewrite=query_rewrite,
        )
    return _pipeline_v2


def answer_v2(
    question: str,
    *,
    vector_db_path: str | Path,
    rerank_mode: RerankMode = DEFAULT_RERANK_MODE,
    n: int = DEFAULT_CONTEXT_N,
    extra_filters: dict[str, Any] | None = None,
    strategy_override: ExpansionStrategy | None = None,
    query_rewrite: bool = True,
) -> AnswerResult:
    """Convenience: open a v2 pipeline (cached) and run one question."""
    return get_pipeline_v2(vector_db_path, rerank_mode, query_rewrite).answer(
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


def _rerank_cross_encoder(
    *,
    question: str,
    candidates: list["_Candidate"],
    strategy: ExpansionStrategy,
    candidate_pool: dict[str, "_Candidate"],
    temporal_status_map: dict[str, dict | None],
) -> list[RerankedHit]:
    """Cross-encoder + weighted combine (cross, cosine, metadata).

    Reads each candidate's ``embedded_text`` against the query. Best on
    multi-hop / cross-source queries where the cosine alone can't tell which
    of several semantically-similar passages actually answers the question.

    ``temporal_status_map`` is consulted by ``_metadata_signal`` so the
    metadata score is ancestor-aware (Move 3) — a chunk whose LAW root has
    been amended after its publication_date is dampened relative to one
    whose ancestor chain is clean.
    """
    rr = get_reranker()
    pairs = [(c.hit.chunk_id, c.hit.embedded_text or "") for c in candidates]
    scored: list[ScoredCandidate] = rr.score(question, pairs)
    cand_by_id = {c.hit.chunk_id: c for c in candidates}
    for s in scored:
        c = cand_by_id[s.chunk_id]
        # combine_scores expects ``cosine`` as a distance-shaped value (it
        # converts back to similarity internally).
        s.cosine = max(0.0, min(2.0, 2.0 * (1.0 - c.cosine_sim)))
        s.metadata_score = _metadata_signal(
            c.hit, temporal_status_map.get(c.hit.section_id)
        )
    combined = combine_scores(scored, weights=strategy.rerank_weights)

    out: list[RerankedHit] = []
    for s in combined:
        c = cand_by_id[s.chunk_id]
        out.append(
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
    return out


def _rerank_vector(
    *,
    question: str,
    candidates: list["_Candidate"],
    candidate_pool: dict[str, "_Candidate"],
    retriever: VectorRetriever,
    graph: GraphStore,
    temporal_status_map: dict[str, dict | None],
) -> list[RerankedHit]:
    """Pure vector-similarity rerank.

    Re-queries LanceDB with ``chunk_id IN [all candidates]`` so every
    candidate — seeds and graph-expanded alike — gets a real cosine against
    the user's question. Then applies v1's full metadata reranker
    (cosine + authority + recency + term bonus − repealed penalty).

    Use this mode to isolate whether the cross-encoder is hurting on Finnish
    legal text. The graph expansion still happens; only the scoring changes.
    """
    if not candidates:
        return []
    candidate_ids = [c.hit.chunk_id for c in candidates]
    # Re-query gives every candidate (including formerly-cosine-0 graph
    # expansions) a real cosine. LanceDB's ``where`` supports IN clauses;
    # we set ``k`` to the full set size so nothing is dropped.
    rescored = retriever.retrieve(
        question,
        k=len(candidate_ids),
        filters={"chunk_id": candidate_ids},
    )
    # Edge case: LanceDB may return fewer rows than asked if some chunk_ids
    # weren't indexed (shouldn't happen post-sanity-check, but be defensive).
    rescored_by_id = {h.chunk_id: h for h in rescored}
    # Run v1's full metadata reranker. Its formula:
    #   score = cosine + 0.10*auth + 0.05*recency + 0.05*term − 0.50*repealed
    fresh_hits = [rescored_by_id[c.hit.chunk_id]
                  for c in candidates
                  if c.hit.chunk_id in rescored_by_id]
    # ``temporal_status_map`` is passed in by the caller (one fetch per
    # answer call). Forward it to the metadata reranker so the graded
    # penalty (Move 3) applies.
    reranked = metadata_rerank(
        question, fresh_hits, temporal_status_map=temporal_status_map
    )

    # Promote hops + retrieval_path provenance onto components so --verbose
    # still shows where each candidate came from.
    out: list[RerankedHit] = []
    for r in reranked:
        c = candidate_pool.get(r.hit.chunk_id)
        hops = float(c.retrieval_path.hops) if c is not None else 0.0
        out.append(
            RerankedHit(
                hit=r.hit,
                score=r.score,
                components={**r.components, "hops": hops},
            )
        )
    return out


def _metadata_signal(
    hit: RetrievedHit,
    temporal_status: dict | None = None,
) -> float:
    """Light-weight metadata score in [0, 1] for the weighted combine.

    Picks up authority + temporal_status + in_force so the cross-encoder's
    choice isn't blind to source rank or to ancestor-level amendment
    activity. Not as elaborate as v1's metadata reranker because the
    cross-encoder is doing most of the discrimination work.

    ``temporal_status`` (Move 2 output) supersedes the legacy
    ``hit.usable`` flag when supplied. Falls back to ``hit.usable`` for
    nodes whose status hasn't been computed.
    """
    score = 0.0
    if hit.authority_rank is not None:
        score += hit.authority_rank / 100.0 * 0.6

    # Prefer the ancestor-aware grade when available.
    grade = None
    if isinstance(temporal_status, dict):
        grade = temporal_status.get("effective_usable")
    if grade == "ok":
        score += 0.2
    elif grade == "suspect":
        # Small dampen — consolidated text usually reflects the amendment.
        score += 0.05
    elif grade == "stale":
        score -= 0.2
    elif grade == "repealed":
        score -= 0.4
    elif grade is None:
        # No graph status — fall back to the binary flag, same as before.
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
    amendment_caveats: list[AmendmentCaveat] | None = None,
    expanded: ExpandedQuery | None = None,
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
        conflicts=[],
        amendment_caveats=amendment_caveats or [],
    )
