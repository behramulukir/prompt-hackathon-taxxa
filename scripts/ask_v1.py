"""Standalone v1 retrieval CLI — vector-only baseline, no GraphRAG.

This is the pre-Step-7 pipeline frozen behind its own entry point so it can
run in parallel with the v2 / GraphRAG CLI without sharing config:

    .venv/bin/python -m scripts.ask_v1 "Mikä on arvonlisäveron vähennysoikeus?"
    .venv/bin/python -m scripts.ask_v1 --verbose "..."

Why this exists separately:

- ``scripts/ask.py``'s default vector store has bounced between
  ``output/lancedb_pilot`` (1000 chunks) and ``output/lancedb`` (402,088
  chunks) across reverts. v1 *looks* broken whenever the default points
  at the pilot because 0.25 % of the corpus can't answer most questions.
- This script hard-codes the **full** store as the default and ignores
  anything v2 imports — strategy router, graph expansion, cross-encoder.
  Pure RAG, pre-GraphRAG.

If you want to test the full v2/GraphRAG pipeline use ``scripts/ask.py
--v2`` instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Hard-coded defaults — deliberately not read from src.retrieval so a config
# revert there can't change v1 behavior here.
FULL_VECTOR_DB_PATH = "output/lancedb"
GRAPH_DB_PATH = "output/graph.db"


def _print_block(title: str, body: str) -> None:
    bar = "─" * max(20, min(80, len(title)))
    print(f"\n{bar}\n{title}\n{bar}\n{body}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Ask the v1 vector-only retrieval pipeline a question.",
    )
    p.add_argument("question", help="The question to answer (Finnish or English).")
    p.add_argument(
        "--db",
        default=FULL_VECTOR_DB_PATH,
        help=(
            f"LanceDB path. Default: {FULL_VECTOR_DB_PATH} (full corpus, 402k chunks). "
            "Override with output/lancedb_pilot for a quick smoke test."
        ),
    )
    p.add_argument(
        "--graph-db",
        default=GRAPH_DB_PATH,
        help=f"SQLite graph path. Default: {GRAPH_DB_PATH}",
    )
    p.add_argument("-k", type=int, default=20, help="Vector retrieval depth.")
    p.add_argument("-n", type=int, default=8, help="Sources in assembled context.")
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show retrieved chunks, scores, and context.",
    )
    p.add_argument(
        "--json", action="store_true", help="Emit the AnswerResult as JSON.",
    )
    args = p.parse_args()

    # Defer the import so --help is snappy.
    from src.retrieval.pipeline import Pipeline

    db_path = Path(args.db)
    if not db_path.exists():
        print(
            f"[ask_v1] WARNING: LanceDB path '{db_path}' does not exist. "
            "Did the embed pass run?",
            file=sys.stderr,
        )
    pipe = Pipeline(vector_db_path=args.db, graph_db_path=args.graph_db)

    if args.verbose:
        # Re-run stages so we can print intermediate state. Mirrors v1's
        # internal pipeline; kept here so this script is self-contained.
        from src.retrieval.assemble import assemble
        from src.retrieval.filters import infer_filters
        from src.retrieval.generate import generate
        from src.retrieval.rerank import rerank

        filters = infer_filters(args.question)
        hits = pipe.retriever.retrieve(args.question, k=args.k, filters=filters or None)
        reranked = rerank(args.question, hits)
        ctx = assemble(reranked, graph=pipe.graph, n=args.n)
        gen = generate(args.question, ctx)

        _print_block(
            "PIPELINE",
            f"v1 vector-only  db={args.db}  k={args.k}  n={args.n}",
        )
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
            "\n".join(
                f"  [Source {i + 1}] {cid}"
                for i, cid in enumerate(result.cited_source_ids)
            ),
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
