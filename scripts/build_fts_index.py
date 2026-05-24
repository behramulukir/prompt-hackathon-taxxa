"""Build a LanceDB full-text-search index on ``embedded_text``.

Required for Fix B.2 (hybrid retrieval). With this index in place,
``VectorStore.search_hybrid`` can do a sparse BM25 search alongside the
dense vector search and merge the results with Reciprocal Rank Fusion.

The index is persistent — once built it lives in
``output/lancedb/chunks.lance/_indices/``. Re-run after a full
re-embedding or after adding many new chunks.

CLI:

    .venv/bin/python -m scripts.build_fts_index            # build (idempotent)
    .venv/bin/python -m scripts.build_fts_index --rebuild  # drop + rebuild
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import lancedb

VECTOR_DB_PATH = PROJECT_ROOT / "output" / "lancedb"
TABLE = "chunks"
COLUMN = "embedded_text"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="Drop the existing FTS index before rebuilding.")
    args = ap.parse_args()

    if not VECTOR_DB_PATH.exists():
        print(f"ERROR: {VECTOR_DB_PATH} not found.", file=sys.stderr)
        return 1
    db = lancedb.connect(str(VECTOR_DB_PATH))
    if TABLE not in db.table_names():
        print(f"ERROR: table '{TABLE}' not found in {VECTOR_DB_PATH}",
              file=sys.stderr)
        return 1
    tbl = db.open_table(TABLE)

    existing = [i for i in tbl.list_indices() if COLUMN in (i.columns or [])]
    if existing and not args.rebuild:
        print(f"[fts] index on '{COLUMN}' already exists — skipping. "
              f"Pass --rebuild to drop and rebuild.")
        for idx in existing:
            print(f"  {idx}")
        return 0
    if existing and args.rebuild:
        for idx in existing:
            print(f"[fts] dropping existing index '{idx.name}'")
            tbl.drop_index(idx.name)

    print(f"[fts] building FTS index on '{COLUMN}' over {tbl.count_rows():,} rows…",
          flush=True)
    t0 = time.time()
    # ``with_position=True`` enables phrase queries; cheap on this corpus.
    # Use the multilingual tokenizer so Finnish ä/ö behave correctly.
    tbl.create_fts_index(
        COLUMN,
        replace=True,
        with_position=True,
        # Default tokenizer is ``simple`` (Unicode aware) — fine for Finnish
        # since LanceDB doesn't ship a Finnish-specific stemmer. Calling
        # this out so future maintainers know it's intentional.
    )
    print(f"[fts] done in {time.time()-t0:.1f}s")
    for idx in tbl.list_indices():
        if COLUMN in (idx.columns or []):
            print(f"  {idx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
