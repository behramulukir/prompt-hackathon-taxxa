"""CLI front-end for the retrieval pipelines (v1 vector-only and v2 GraphRAG).

    python -m scripts.ask "Mikä on pääomatulon verokanta?"
    python -m scripts.ask --verbose "Onko ALV vähennyskelpoinen, jos..."
    python -m scripts.ask --v2 "Tuloverolain 30 §:n poikkeus pienille yhtiöille"
    python -m scripts.ask --db output/lancedb "..."

Verbose mode prints filter inference, rerank score breakdown, and the
assembled context, which is what you want while developing.
"""
from __future__ import annotations

import argparse
import json
import sys

from src.retrieval import GRAPH_DB_PATH, VECTOR_DB_PATH, Pipeline


def _print_block(title: str, body: str) -> None:
    bar = "─" * max(20, min(80, len(title)))
    print(f"\n{bar}\n{title}\n{bar}\n{body}")


def main() -> int:
    p = argparse.ArgumentParser(description="Ask the retrieval pipeline a question.")
    p.add_argument("question", help="The question to answer (Finnish or English).")
    p.add_argument(
        "--v2",
        action="store_true",
        help="Use the v2 GraphRAG pipeline (strategy router + graph expansion + reranker).",
    )
    p.add_argument(
        "--rerank",
        choices=("cross_encoder", "vector"),
        default="cross_encoder",
        help=(
            "v2 reranker mode. 'cross_encoder' uses BAAI/bge-reranker-v2-m3 + "
            "weighted combine (default). 'vector' skips the cross-encoder and "
            "re-queries cosine for every candidate, then runs v1's full metadata "
            "rerank (cosine + authority + recency + term + repealed penalty). "
            "Use 'vector' to isolate graph-expansion benefit from cross-encoder noise."
        ),
    )
    p.add_argument(
        "--db",
        default=VECTOR_DB_PATH,
        help=f"LanceDB path. Default: {VECTOR_DB_PATH}. "
        "Switch to output/lancedb when full embed finishes.",
    )
    p.add_argument(
        "--graph-db",
        default=GRAPH_DB_PATH,
        help=f"SQLite graph path. Default: {GRAPH_DB_PATH}",
    )
    p.add_argument("-k", type=int, default=20, help="v1 vector retrieval depth (ignored in v2 — strategy.seed_k controls).")
    p.add_argument("-n", type=int, default=8, help="Sources in assembled context.")
    p.add_argument("--verbose", "-v", action="store_true", help="Show retrieved chunks, scores, and context.")
    p.add_argument("--json", action="store_true", help="Emit the AnswerResult as JSON.")
    args = p.parse_args()

    if args.v2:
        return _run_v2(args)

    pipe = Pipeline(vector_db_path=args.db, graph_db_path=args.graph_db)

    # Reach into the pipeline once to grab the intermediate state when verbose,
    # otherwise the public answer() path is fine.
    if args.verbose:
        from src.retrieval.assemble import assemble
        from src.retrieval.filters import infer_filters
        from src.retrieval.generate import generate
        from src.retrieval.rerank import rerank

        filters = infer_filters(args.question)
        hits = pipe.retriever.retrieve(args.question, k=args.k, filters=filters or None)
        reranked = rerank(args.question, hits)
        ctx = assemble(reranked, graph=pipe.graph, n=args.n)
        gen = generate(args.question, ctx)

        _print_block("INFERRED FILTERS", json.dumps(filters, indent=2))
        _print_block(
            "RERANKED HITS (top 10)",
            "\n".join(
                f"  {r.score:+.4f}  cos={r.hit.cosine_sim:.3f}  "
                f"rank={r.hit.authority_rank}  usable={r.hit.usable}  "
                f"sub={r.hit.source_subcorpus:14}  {r.hit.chunk_id}"
                for r in reranked[:10]
            ),
        )
        _print_block("ASSEMBLED CONTEXT", ctx.text or "(empty)")
        _print_block("ANSWER", gen.answer)
        _print_block(
            "CITATIONS",
            f"indices={gen.cited_indices}\nchunk_ids={gen.cited_chunk_ids}",
        )
        return 0

    result = pipe.answer(args.question, k=args.k, n=args.n)

    if args.json:
        print(result.model_dump_json(indent=2))
        return 0

    _print_block("ANSWER", result.answer)
    if result.cited_source_ids:
        _print_block(
            "CITATIONS",
            "\n".join(f"  [Source {i + 1}] {cid}" for i, cid in enumerate(result.cited_source_ids)),
        )
    if result.assumptions:
        _print_block("ASSUMPTIONS", "\n".join(f"  - {a}" for a in result.assumptions))
    _print_block(
        "TIMING (ms)",
        "\n".join(f"  {stage:18} {ms:>6}" for stage, ms in result.timing_ms.items()),
    )
    return 0


def _run_v2(args) -> int:
    """v2 pipeline runner with the same UX as the v1 path."""
    from src.retrieval.pipeline_v2 import PipelineV2

    pipe = PipelineV2(
        vector_db_path=args.db,
        graph_db_path=args.graph_db,
        rerank_mode=args.rerank,
    )

    if args.verbose:
        return _run_v2_verbose(args, pipe)

    result = pipe.answer(args.question, n=args.n)

    if args.json:
        print(result.model_dump_json(indent=2))
        return 0

    _print_block("ANSWER", result.answer)
    if result.cited_source_ids:
        _print_block(
            "CITATIONS",
            "\n".join(f"  [Source {i + 1}] {cid}" for i, cid in enumerate(result.cited_source_ids)),
        )
    if result.assumptions:
        _print_block("ASSUMPTIONS", "\n".join(f"  - {a}" for a in result.assumptions))
    _print_block(
        "TIMING (ms)",
        "\n".join(f"  {stage:18} {ms:>6}" for stage, ms in result.timing_ms.items()),
    )
    return 0


def _run_v2_verbose(args, pipe) -> int:
    """v2 with full intermediate state — strategy, expansion stats, top-10 reranked."""
    from src.retrieval.assemble import assemble
    from src.retrieval.cross_encoder_rerank import combine_scores, get_reranker
    from src.retrieval.filters import infer_filters
    from src.retrieval.generate import generate
    from src.retrieval.graph_expand import expand
    from src.retrieval.pipeline_v2 import (
        _fetch_chunks_for_sections,
        _metadata_signal,
        _rerank_vector,
        _Candidate,
    )
    from src.retrieval.rerank import RerankedHit
    from src.models import RetrievalPath
    from src.retrieval.strategy import pick_strategy

    strategy = pick_strategy(args.question)
    filters = infer_filters(args.question)
    seeds = pipe.retriever.retrieve(args.question, k=strategy.seed_k, filters=filters or None)
    seed_section_ids: list[str] = []
    seen: set[str] = set()
    for h in seeds:
        if h.section_id not in seen:
            seen.add(h.section_id)
            seed_section_ids.append(h.section_id)
    paths = expand(seed_section_ids, strategy, pipe.graph)
    expanded_only = [nid for nid in paths if nid not in seen]
    expanded_hits = _fetch_chunks_for_sections(pipe.vector_store, expanded_only)

    seed_hits_by_cid = {h.chunk_id: h for h in seeds}
    candidates = list(seeds) + [h for h in expanded_hits if h.chunk_id not in seed_hits_by_cid]
    cand_by_id = {c.chunk_id: c for c in candidates}

    if args.rerank == "cross_encoder":
        rr = get_reranker()
        pairs = [(c.chunk_id, c.embedded_text or "") for c in candidates]
        scored = rr.score(args.question, pairs)
        for s in scored:
            c = cand_by_id[s.chunk_id]
            s.cosine = max(0.0, min(2.0, 2.0 * (1.0 - c.cosine_sim)))
            s.metadata_score = _metadata_signal(c)
        combined = combine_scores(scored, weights=strategy.rerank_weights)
        reranked = [
            RerankedHit(
                hit=cand_by_id[s.chunk_id],
                score=s.final_score or s.cross_score,
                components={
                    "cross_encoder": s.cross_score,
                    "cosine_sim": cand_by_id[s.chunk_id].cosine_sim,
                    "metadata": s.metadata_score or 0.0,
                    "final": s.final_score or 0.0,
                },
            )
            for s in combined
        ]
    else:  # "vector"
        # Build a candidate_pool that _rerank_vector can read for hops/paths.
        pool: dict[str, _Candidate] = {}
        for h in seeds:
            pool[h.chunk_id] = _Candidate(
                hit=h,
                cosine_sim=h.cosine_sim,
                from_seed=True,
                retrieval_path=RetrievalPath(via="vector", score=h.cosine_sim, hops=0),
            )
        for h in expanded_hits:
            if h.chunk_id in pool:
                continue
            path = paths.get(h.section_id) or RetrievalPath(via="graph", score=0.0, hops=1)
            pool[h.chunk_id] = _Candidate(
                hit=h, cosine_sim=h.cosine_sim, from_seed=False, retrieval_path=path
            )
        candidates_pool = list(pool.values())
        reranked = _rerank_vector(
            question=args.question,
            candidates=candidates_pool,
            candidate_pool=pool,
            retriever=pipe.retriever,
        )

    ctx = assemble(reranked, graph=pipe.graph, n=args.n)
    gen = generate(args.question, ctx)

    _print_block(
        "STRATEGY",
        f"{strategy.name}  edges={list(strategy.edge_types)}  "
        f"direction={strategy.direction}  hops={strategy.max_hops}  "
        f"seed_k={strategy.seed_k}  max_nodes={strategy.max_nodes}  "
        f"rerank_mode={args.rerank}",
    )
    _print_block("INFERRED FILTERS", json.dumps(filters, indent=2))
    _print_block(
        "GRAPH EXPANSION",
        f"seeds={len(seed_section_ids)}  expanded_nodes={len(paths)}  "
        f"new_after_seeds={len(expanded_only)}  "
        f"fetched_chunks={len(expanded_hits)}  "
        f"total_candidates={len(candidates)}",
    )
    if args.rerank == "cross_encoder":
        score_header = "ce= "
        score_fmt = lambda r: f"ce={r.components.get('cross_encoder', 0):+.3f}"
    else:
        score_header = "auth="
        score_fmt = lambda r: f"auth={r.components.get('authority', 0):+.3f} rec={r.components.get('recency', 0):+.3f}"
    _print_block(
        f"RERANKED HITS (top 10, mode={args.rerank})",
        "\n".join(
            f"  {r.score:+.4f}  {score_fmt(r)}  "
            f"cos={r.hit.cosine_sim:.3f}  "
            f"sub={r.hit.source_subcorpus:14}  {r.hit.chunk_id}"
            for r in reranked[:10]
        ),
    )
    _print_block("ASSEMBLED CONTEXT", ctx.text or "(empty)")
    _print_block("ANSWER", gen.answer)
    _print_block(
        "CITATIONS",
        f"indices={gen.cited_indices}\nchunk_ids={gen.cited_chunk_ids}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
