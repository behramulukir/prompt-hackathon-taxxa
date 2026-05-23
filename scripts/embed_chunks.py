"""Step 4a.4 — Full corpus embedding pass.

Streams output/chunks.jsonl, composes hierarchy-prefixed text, embeds via
Voyage in batches of 128, writes to output/lancedb/chunks.

Two safety guardrails enforced here:
- ``--dry-run`` counts tokens without calling the API. The doc requires this
  before any real pass. If dry-run > 180M, stop and investigate.
- Resumable: chunk_ids already present in LanceDB are skipped on re-run, so
  a crash or rate-limit pause is cheap to recover from.

CLI:

    .venv/bin/python -m scripts.embed_chunks --dry-run            # token estimate
    .venv/bin/python -m scripts.embed_chunks --max-chunks 5000    # bounded test
    .venv/bin/python -m scripts.embed_chunks                      # full pass
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import lancedb
import tiktoken

from src.indexing.node_index import build_node_index
from src.indexing.text_composition import compose_embedding_text
from src.indexing.vector_store import VECTOR_TABLE, arrow_schema
from src.indexing.voyage_client import embed_batch, get_client

OUTPUT_DIR = PROJECT_ROOT / "output"
CHUNKS_IN = OUTPUT_DIR / "chunks.jsonl"
NODES_IN = OUTPUT_DIR / "nodes_enriched.jsonl"
NODES_FALLBACK = OUTPUT_DIR / "nodes.jsonl"
LANCEDB_PATH = OUTPUT_DIR / "lancedb"

# Voyage doesn't ship a public tokenizer; cl100k_base is a reasonable proxy
# for byte-pair sizing — overestimates by ~5-10% on Finnish, which gives us a
# conservative budget number rather than an optimistic one.
_TOKENIZER = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_TOKENIZER.encode(text, disallowed_special=()))


def _already_embedded(table) -> set[str]:
    if table is None:
        return set()
    n = table.count_rows()
    if n == 0:
        return set()
    # to_arrow() returns the full table; we only access the chunk_id column.
    # For ~400k rows this is ~40 MB of strings, fine in memory.
    arrow = table.to_arrow()
    return set(arrow["chunk_id"].to_pylist())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose all texts and count tokens, but do not call the API",
    )
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument(
        "--max-batch-tokens",
        type=int,
        default=80_000,
        help=(
            "Per-batch token cap (Voyage limit is 120k; we leave a generous "
            "buffer for tokenizer drift between tiktoken and Voyage's own count "
            "and keep per-call latency bounded)"
        ),
    )
    ap.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help="Hard cap for testing; default is the entire corpus",
    )
    ap.add_argument(
        "--skip-oversized",
        action="store_true",
        default=True,
        help="Skip chunks flagged oversized=True (default on)",
    )
    ap.add_argument(
        "--progress-every",
        type=int,
        default=5000,
        help="Print a progress line every N chunks",
    )
    args = ap.parse_args()

    nodes_path = NODES_IN if NODES_IN.exists() else NODES_FALLBACK
    print(f"[embed] Loading node index from {nodes_path.name} ...")
    t0 = time.time()
    node_index = build_node_index(nodes_path)
    print(f"[embed] Loaded {len(node_index):,} nodes in {time.time()-t0:.1f}s")

    # --- DRY RUN ------------------------------------------------------------
    if args.dry_run:
        return _dry_run(args, node_index)

    # --- REAL PASS ----------------------------------------------------------
    LANCEDB_PATH.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(LANCEDB_PATH))
    if VECTOR_TABLE in db.table_names():
        table = db.open_table(VECTOR_TABLE)
        seen = _already_embedded(table)
        print(f"[embed] Resuming: {len(seen):,} chunk_ids already in LanceDB")
    else:
        table = db.create_table(VECTOR_TABLE, schema=arrow_schema(), mode="create")
        seen = set()
        print(f"[embed] Created fresh table at {LANCEDB_PATH}/{VECTOR_TABLE}")

    client = get_client()
    total_tokens = 0
    n_embedded = 0
    n_skipped_resume = 0
    n_skipped_oversized = 0
    n_seen = 0
    # Batch items now carry their pre-counted token estimate so we can cap by
    # token count, not just chunk count. Voyage rejects batches > 120k tokens.
    batch: list[tuple[dict, str, int]] = []
    batch_tokens = 0
    t_start = time.time()

    def _flush(batch: list[tuple[dict, str, int]]) -> int:
        if not batch:
            return 0
        texts = [t for _, t, _ in batch]
        est_tokens = sum(t for _, _, t in batch)
        t_call = time.time()
        embeddings, used = embed_batch(client, texts, input_type="document")
        dur = time.time() - t_call
        # Per-batch line — terse, lets us see throughput in real time.
        print(
            f"[batch] n={len(batch):3d}  est={est_tokens:>6d}  "
            f"used={used:>6d}  dur={dur:5.1f}s  "
            f"tok/s={used/dur if dur else 0:>6.0f}",
            flush=True,
        )
        rows = []
        for (chunk, txt, _), vec in zip(batch, embeddings):
            primary = node_index.get(chunk["section_id"])
            rows.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "vector": vec,
                    "section_id": chunk["section_id"],
                    "source": chunk["source"],
                    "source_subcorpus": chunk["source_subcorpus"],
                    "node_type": primary.node_type if primary else "",
                    "authority_rank": (primary.authority_rank if primary else None),
                    "in_force": primary.in_force if primary else None,
                    "usable": primary.usable if primary else None,
                    "publication_date": (
                        primary.publication_date if primary else None
                    ),
                    "language": primary.language if primary else None,
                    "embedded_text": txt,
                }
            )
        table.add(rows)
        return used

    with CHUNKS_IN.open() as f:
        for line in f:
            if not line.strip():
                continue
            chunk = json.loads(line)
            n_seen += 1
            if args.max_chunks is not None and n_embedded >= args.max_chunks:
                break
            if args.skip_oversized and chunk.get("oversized"):
                n_skipped_oversized += 1
                continue
            if chunk["chunk_id"] in seen:
                n_skipped_resume += 1
                continue
            txt = compose_embedding_text(
                chunk_text=chunk["text"],
                section_id=chunk["section_id"],
                node_index=node_index,
            )
            t_est = _count_tokens(txt)

            # If adding this chunk would exceed the per-batch token cap, flush
            # first. Always allow at least one chunk in a batch even if the
            # single chunk itself is bigger than the cap — Voyage may still
            # accept it, and we'd rather try than drop it.
            if batch and (batch_tokens + t_est > args.max_batch_tokens):
                used = _flush(batch)
                total_tokens += used
                n_embedded += len(batch)
                batch.clear()
                batch_tokens = 0

            batch.append((chunk, txt, t_est))
            batch_tokens += t_est

            if len(batch) >= args.batch_size:
                used = _flush(batch)
                total_tokens += used
                n_embedded += len(batch)
                batch.clear()
                batch_tokens = 0
                if n_embedded % args.progress_every < args.batch_size:
                    elapsed = time.time() - t_start
                    rate = n_embedded / elapsed if elapsed else 0.0
                    print(
                        f"[embed] {n_embedded:,} chunks | "
                        f"{total_tokens:,} tokens | "
                        f"{rate:.1f} chunks/s | "
                        f"{elapsed:.0f}s elapsed"
                    )

    if batch:
        used = _flush(batch)
        total_tokens += used
        n_embedded += len(batch)

    elapsed = time.time() - t_start
    print(
        f"[embed] DONE. Embedded {n_embedded:,} chunks in {elapsed:.0f}s "
        f"({total_tokens:,} tokens). "
        f"Resume-skipped: {n_skipped_resume:,}, oversized-skipped: "
        f"{n_skipped_oversized:,}, total seen: {n_seen:,}"
    )
    print(f"[embed] LanceDB row count: {table.count_rows():,}")
    return 0


def _dry_run(args, node_index) -> int:
    """Count tokens for the entire corpus without calling Voyage."""
    print("[dry-run] Counting tokens via tiktoken (cl100k_base proxy) ...")
    n_total = 0
    n_oversized = 0
    total_tokens = 0
    prefix_tokens = 0
    chunk_text_tokens = 0
    per_subcorpus: dict[str, dict[str, int]] = {}
    t0 = time.time()

    with CHUNKS_IN.open() as f:
        for line in f:
            if not line.strip():
                continue
            chunk = json.loads(line)
            n_total += 1
            if args.skip_oversized and chunk.get("oversized"):
                n_oversized += 1
                continue
            if args.max_chunks is not None and n_total > args.max_chunks:
                break
            txt = compose_embedding_text(
                chunk_text=chunk["text"],
                section_id=chunk["section_id"],
                node_index=node_index,
            )
            full = _count_tokens(txt)
            raw = _count_tokens(chunk["text"])
            total_tokens += full
            chunk_text_tokens += raw
            prefix_tokens += max(0, full - raw)

            sub = chunk["source_subcorpus"]
            s = per_subcorpus.setdefault(
                sub, {"n": 0, "tok_total": 0, "tok_prefix": 0}
            )
            s["n"] += 1
            s["tok_total"] += full
            s["tok_prefix"] += max(0, full - raw)

            if n_total % 25000 == 0:
                print(
                    f"[dry-run] {n_total:,} chunks scanned, "
                    f"{total_tokens:,} tokens so far, "
                    f"{time.time()-t0:.0f}s"
                )

    print(f"[dry-run] DONE in {time.time()-t0:.0f}s")
    print(f"[dry-run] Chunks seen: {n_total:,} (oversized-skipped: {n_oversized:,})")
    print(
        f"[dry-run] Total estimated tokens: {total_tokens:,} "
        f"({total_tokens/1_000_000:.1f}M)"
    )
    print(
        f"[dry-run]   - chunk text only: {chunk_text_tokens:,} "
        f"({chunk_text_tokens/1_000_000:.1f}M)"
    )
    print(
        f"[dry-run]   - prefix overhead: {prefix_tokens:,} "
        f"({prefix_tokens/1_000_000:.1f}M, {prefix_tokens/total_tokens*100:.1f}%)"
    )
    print("[dry-run] Per subcorpus:")
    for sub, s in sorted(
        per_subcorpus.items(), key=lambda kv: -kv[1]["tok_total"]
    ):
        avg = s["tok_total"] / s["n"]
        pfx = s["tok_prefix"] / s["n"]
        print(
            f"  {sub:<20s}  n={s['n']:>7,}  "
            f"total={s['tok_total']/1_000_000:6.1f}M  "
            f"avg={avg:6.1f} (prefix={pfx:5.1f})"
        )

    # Verdict against the doc's 180M warning threshold.
    if total_tokens > 180_000_000:
        print(
            f"[dry-run] ⚠ Token estimate exceeds the 180M caution threshold "
            f"({total_tokens/1_000_000:.1f}M)."
        )
        print(
            "[dry-run]   Check per-subcorpus average prefix tokens above for "
            "outliers before proceeding."
        )
    else:
        print(
            f"[dry-run] OK — {total_tokens/1_000_000:.1f}M is under the "
            "180M caution threshold."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
