"""Step 4a.3 — Pilot embedding pass (1000 chunks, stratified by source).

Mandatory before the full corpus pass. Catches text-composition bugs and
schema mismatches while spending ~0.3% of the token budget.

CLI:

    .venv/bin/python -m scripts.embed_pilot                # default 1000
    .venv/bin/python -m scripts.embed_pilot --n 200        # smaller smoke
    .venv/bin/python -m scripts.embed_pilot --no-embed     # compose only, no API
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import lancedb
import pyarrow as pa

from src.indexing.node_index import build_node_index
from src.indexing.text_composition import compose_embedding_text
from src.indexing.voyage_client import OUTPUT_DIMENSION, embed_batch, get_client

OUTPUT_DIR = PROJECT_ROOT / "output"
CHUNKS_IN = OUTPUT_DIR / "chunks.jsonl"
NODES_IN = OUTPUT_DIR / "nodes_enriched.jsonl"
NODES_FALLBACK = OUTPUT_DIR / "nodes.jsonl"
LANCEDB_PATH = OUTPUT_DIR / "lancedb_pilot"

# Stratification quota from the doc.
STRATA = {
    "laki": 600,
    "laki_skk": 100,
    "kho": 100,
    "vero_ohje": 100,
    "treaty": 100,
}


def _arrow_schema() -> pa.Schema:
    """Mirror src.models.VectorRecord — keep fields in sync if the model changes."""
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
            pa.field("publication_date", pa.string()),  # ISO string; LanceDB date support is uneven
            pa.field("language", pa.string()),
            pa.field("embedded_text", pa.string()),
        ]
    )


def _stratified_sample(n_total: int, seed: int = 42) -> list[dict]:
    """Stratified sample using reservoir per stratum so we don't load 800MB."""
    rng = random.Random(seed)
    # Scale quotas to n_total.
    total_quota = sum(STRATA.values())
    scaled = {k: max(1, round(v * n_total / total_quota)) for k, v in STRATA.items()}
    reservoirs: dict[str, list[dict]] = {k: [] for k in scaled}
    counts: dict[str, int] = {k: 0 for k in scaled}

    with CHUNKS_IN.open() as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            sub = c.get("source_subcorpus")
            if sub not in reservoirs:
                continue
            if c.get("oversized"):
                continue
            counts[sub] += 1
            k = scaled[sub]
            res = reservoirs[sub]
            if len(res) < k:
                res.append(c)
            else:
                j = rng.randrange(counts[sub])
                if j < k:
                    res[j] = c

    sample: list[dict] = []
    for sub, items in reservoirs.items():
        sample.extend(items)
    rng.shuffle(sample)
    return sample


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000, help="Total chunks to sample")
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument(
        "--no-embed",
        action="store_true",
        help="Compose text only; print samples, do not call Voyage",
    )
    args = ap.parse_args()

    nodes_path = NODES_IN if NODES_IN.exists() else NODES_FALLBACK
    print(f"[pilot] Loading node index from {nodes_path.name} ...")
    t0 = time.time()
    node_index = build_node_index(nodes_path)
    print(f"[pilot] Loaded {len(node_index):,} nodes in {time.time()-t0:.1f}s")

    print(f"[pilot] Sampling {args.n} chunks (stratified) ...")
    t0 = time.time()
    sample = _stratified_sample(args.n)
    print(f"[pilot] Sampled {len(sample)} chunks in {time.time()-t0:.1f}s")

    # Compose text up front so any composition bug is caught before the API
    # call. Keep both the composed text and the original chunk dict.
    composed: list[tuple[dict, str]] = []
    for c in sample:
        text = compose_embedding_text(
            chunk_text=c["text"],
            section_id=c["section_id"],
            node_index=node_index,
        )
        composed.append((c, text))

    # Show three composed examples regardless of mode for sanity.
    print("[pilot] Composed text examples:")
    for c, t in composed[:3]:
        print("---")
        print(t[:400])
    print("---")

    if args.no_embed:
        print("[pilot] --no-embed set, exiting before API calls")
        return 0

    # --- Embed ----------------------------------------------------------------
    LANCEDB_PATH.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(LANCEDB_PATH))
    schema = _arrow_schema()
    table = db.create_table("chunks", schema=schema, mode="overwrite")

    client = get_client()
    records: list[dict] = []
    total_tokens = 0
    t_embed = time.time()

    for start in range(0, len(composed), args.batch_size):
        batch = composed[start : start + args.batch_size]
        texts = [t for _, t in batch]
        embeddings, used = embed_batch(client, texts, input_type="document")
        total_tokens += used
        for (chunk, txt), vec in zip(batch, embeddings):
            primary = node_index.get(chunk["section_id"])
            records.append(
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
                    "publication_date": (primary.publication_date if primary else None),
                    "language": primary.language if primary else None,
                    "embedded_text": txt,
                }
            )
        if (start // args.batch_size) % 2 == 0:
            print(
                f"[pilot] batch {start//args.batch_size+1}: "
                f"{start+len(batch)}/{len(composed)} chunks, "
                f"{total_tokens} tokens, {time.time()-t_embed:.1f}s"
            )

    print(f"[pilot] Embedding done. Total tokens: {total_tokens}")

    # Bulk write
    table.add(records)
    print(f"[pilot] Wrote {len(records)} rows to {LANCEDB_PATH}/chunks")

    # Sanity counts
    n_rows = table.count_rows()
    print(f"[pilot] LanceDB row count: {n_rows}")
    if n_rows != len(composed):
        print("[pilot] WARNING: row count mismatch")

    # Quick null-vector check (pyarrow direct, no pandas required)
    arrow = table.to_arrow()
    vec_col = arrow["vector"].to_pylist()
    zero_vecs = sum(1 for v in vec_col if not any(v))
    in_force_col = arrow["in_force"].to_pylist()
    null_in_force = sum(1 for v in in_force_col if v is None)
    print(f"[pilot] Zero/empty vectors: {zero_vecs}")
    print(f"[pilot] Payload null check (in_force=None): {null_in_force}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
