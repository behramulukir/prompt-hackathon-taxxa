"""End-to-end ingestion: data/ HTML -> output/{nodes,chunks,hierarchy}.

Walks the data/ directory, dispatches each file to the right parser based on
its path, packs SectionBundles into Chunks, and streams everything to JSONL.

Run from the repo root:

    .venv/bin/python -m pipeline.ingest                       # full corpus
    .venv/bin/python -m pipeline.ingest --limit 100           # quick sanity
    .venv/bin/python -m pipeline.ingest --only finlex_skk     # one subcorpus
    .venv/bin/python -m pipeline.ingest --workers 8           # control pool
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Iterable, Iterator

from .chunks import HARD_MAX, TARGET_MAX, pack_sections
from .output import build_hierarchy_index
from .parsers import finlex_amendments, finlex_konsolidoitu, kho, treaty, vero


# --- Routing ----------------------------------------------------------------

# Map a top-level data/ subpath to a parser key.
SUBCORPUS_KEYS = {
    "finlex_skk":      "finlex säädöskokoelma (clean § structure)",
    "finlex_laki":     "finlex Laki/ + Asetus/ (amendment-heavy)",
    "vero":            "vero tax guidance + decisions",
    "kho":             "KHO case law precedents",
    "treaty":          "tax treaties (Tuloverosopimukset)",
}

PARSER_MODULES = {
    "finlex_skk": finlex_konsolidoitu,
    "finlex_laki": finlex_amendments,
    "vero": vero,
    "kho": kho,
    "treaty": treaty,
}


def classify(rel_path: str) -> str | None:
    """Decide which parser handles a file. Return None to skip."""
    parts = rel_path.split(os.sep)
    if len(parts) < 2:
        return None
    head = parts[0]
    if head == "finlex":
        # data/finlex/<bucket>/...
        bucket = parts[1]
        if "säädöskokoelma" in bucket.lower():
            return "finlex_skk"
        if bucket.startswith("Korkein hallinto-oikeus"):
            return "kho"
        if bucket == "Tuloverosopimukset":
            return "treaty"
        if bucket in {"Laki", "Asetus"}:
            return "finlex_laki"
        return None
    if head == "vero":
        return "vero"
    return None


# --- Worker -----------------------------------------------------------------

def _process_one(args: tuple[str, str, str]) -> tuple[str, list[dict], list[dict], str]:
    """Worker entry point. Returns (rel_path, node_dicts, chunk_dicts, error_or_empty)."""
    abs_path, rel_path, parser_key = args
    try:
        parser = PARSER_MODULES[parser_key]
        nodes, bundles = parser.parse(abs_path, rel_path)
        chunks = pack_sections(bundles)
        return (
            rel_path,
            [n.to_dict() for n in nodes],
            [c.to_dict() for c in chunks],
            "",
        )
    except Exception as e:  # noqa: BLE001
        return (rel_path, [], [], f"{type(e).__name__}: {e}\n{traceback.format_exc()}")


# --- File discovery ---------------------------------------------------------

def iter_files(data_root: Path, only: set[str] | None, limit_per: int | None) -> Iterator[tuple[str, str, str]]:
    """Yield (abs_path, rel_path, parser_key) for every HTML file under data/."""
    counts: dict[str, int] = {}
    for p in data_root.rglob("*.html"):
        # Skip macOS metadata + hidden
        if p.name.startswith("."):
            continue
        rel = str(p.relative_to(data_root))
        key = classify(rel)
        if key is None:
            continue
        if only and key not in only:
            continue
        if limit_per is not None and counts.get(key, 0) >= limit_per:
            continue
        counts[key] = counts.get(key, 0) + 1
        yield str(p), rel, key


# --- Main -------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data", help="data root (default: data/)")
    ap.add_argument("--out", default="output", help="output directory")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap on files per subcorpus (sanity-check runs)",
    )
    ap.add_argument(
        "--only",
        action="append",
        default=None,
        choices=list(SUBCORPUS_KEYS.keys()),
        help="restrict to one or more subcorpora (repeatable)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    data_root = Path(args.data).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    only_set = set(args.only) if args.only else None
    work = list(iter_files(data_root, only_set, args.limit))
    if not work:
        print("no files matched", file=sys.stderr)
        return 1

    by_key: dict[str, int] = {}
    for _, _, k in work:
        by_key[k] = by_key.get(k, 0) + 1
    print(f"queued {len(work)} files across {len(by_key)} subcorpora:")
    for k, n in sorted(by_key.items()):
        print(f"  {k:14s} {n:>7d}   ({SUBCORPUS_KEYS[k]})")

    nodes_path = out_dir / "nodes.jsonl"
    chunks_path = out_dir / "chunks.jsonl"
    hierarchy_path = out_dir / "hierarchy.json"
    errors_path = out_dir / "errors.log"
    stats_path = out_dir / "stats.json"

    # Streaming writers — keep memory bounded on the 60k-file corpus.
    nf = open(nodes_path, "w", encoding="utf-8")
    cf = open(chunks_path, "w", encoding="utf-8")
    ef = open(errors_path, "w", encoding="utf-8")

    # We need an in-memory list of (law_id, node-type, type) for the hierarchy
    # index — but only the small set of fields the index cares about.
    hier_slim: list[dict] = []

    total_nodes = 0
    total_chunks = 0
    total_files = 0
    error_files = 0
    oversized_chunks = 0
    chunk_token_sum = 0
    by_subcorpus = {k: {"files": 0, "nodes": 0, "chunks": 0} for k in SUBCORPUS_KEYS}

    start = time.time()
    last_print = start

    chunksize = max(1, len(work) // (args.workers * 32))
    ctx = mp.get_context("spawn") if sys.platform == "darwin" else mp.get_context()
    with ctx.Pool(processes=args.workers) as pool:
        for rel_path, node_dicts, chunk_dicts, err in pool.imap_unordered(
            _process_one, work, chunksize=chunksize
        ):
            total_files += 1
            key = classify(rel_path) or "?"
            by_subcorpus.setdefault(key, {"files": 0, "nodes": 0, "chunks": 0})
            by_subcorpus[key]["files"] += 1
            if err:
                error_files += 1
                ef.write(f"=== {rel_path} ===\n{err}\n")
                continue
            by_subcorpus[key]["nodes"] += len(node_dicts)
            by_subcorpus[key]["chunks"] += len(chunk_dicts)
            for nd in node_dicts:
                nf.write(json.dumps(nd, ensure_ascii=False))
                nf.write("\n")
                # Slim copy for the hierarchy index.
                hier_slim.append({
                    "id": nd["id"],
                    "type": nd["type"],
                    "title": nd.get("title"),
                    "law_id": nd.get("law_id"),
                    "source": nd.get("source"),
                    "source_subcorpus": nd.get("source_subcorpus"),
                    "source_file": nd.get("source_file"),
                })
            for cd in chunk_dicts:
                cf.write(json.dumps(cd, ensure_ascii=False))
                cf.write("\n")
                chunk_token_sum += cd.get("token_count", 0)
                if cd.get("oversized"):
                    oversized_chunks += 1
            total_nodes += len(node_dicts)
            total_chunks += len(chunk_dicts)
            now = time.time()
            if not args.quiet and now - last_print >= 2.0:
                rate = total_files / max(1e-6, now - start)
                eta = (len(work) - total_files) / max(1e-6, rate)
                print(
                    f"  {total_files}/{len(work)} files "
                    f"({rate:.0f}/s)  nodes={total_nodes:,}  chunks={total_chunks:,}  "
                    f"errors={error_files}  eta={int(eta)}s",
                    end="\r",
                    flush=True,
                )
                last_print = now

    nf.close()
    cf.close()
    ef.close()
    if not args.quiet:
        print()

    # Hierarchy index — rebuild from the slim records (avoids re-reading nodes.jsonl).
    print("building hierarchy index...")
    from .nodes import Node
    proxy_nodes: list[Node] = [
        Node(
            id=r["id"],
            type=r["type"],
            text="",
            title=r.get("title"),
            law_id=r.get("law_id"),
            source=r.get("source", "") or "",
            source_subcorpus=r.get("source_subcorpus", "") or "",
            source_file=r.get("source_file", "") or "",
        )
        for r in hier_slim
    ]
    idx = build_hierarchy_index(proxy_nodes)
    with open(hierarchy_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    print(f"  hierarchy: {len(idx)} root documents -> {hierarchy_path}")

    elapsed = time.time() - start
    stats = {
        "elapsed_seconds": round(elapsed, 1),
        "files_total": total_files,
        "files_with_error": error_files,
        "nodes_total": total_nodes,
        "chunks_total": total_chunks,
        "oversized_chunks": oversized_chunks,
        "avg_chunk_tokens": round(chunk_token_sum / max(1, total_chunks), 1),
        "by_subcorpus": by_subcorpus,
        "target_max_tokens": TARGET_MAX,
        "hard_max_tokens": HARD_MAX,
    }
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print("---")
    print(f"files: {total_files} ({error_files} errors)")
    print(f"nodes: {total_nodes:,}")
    print(f"chunks: {total_chunks:,}  (avg {stats['avg_chunk_tokens']} tok, {oversized_chunks} oversized)")
    print(f"elapsed: {elapsed:.1f}s")
    print(f"outputs: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
