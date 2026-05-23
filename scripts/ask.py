"""CLI front-end for the v1 retrieval pipeline.

    python -m scripts.ask "Mikä on pääomatulon verokanta?"
    python -m scripts.ask --verbose "Onko ALV vähennyskelpoinen, jos..."
    python -m scripts.ask --db output/lancedb "..." # one-line swap to full store

Verbose mode prints the rerank score breakdown and the full assembled
context, which is what you actually want while developing v1.
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
    p = argparse.ArgumentParser(description="Ask the v1 retrieval pipeline a question.")
    p.add_argument("question", help="The question to answer (Finnish or English).")
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
    p.add_argument("-k", type=int, default=20, help="Vector retrieval depth.")
    p.add_argument("-n", type=int, default=8, help="Sources in assembled context.")
    p.add_argument("--verbose", "-v", action="store_true", help="Show retrieved chunks, scores, and context.")
    p.add_argument("--json", action="store_true", help="Emit the AnswerResult as JSON.")
    args = p.parse_args()

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


if __name__ == "__main__":
    sys.exit(main())
