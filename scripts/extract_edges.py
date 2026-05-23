"""B2.8 — Edge extraction pipeline runner.

Drives the full Step 2 workflow:

    1. Load `output/nodes.jsonl` into a `NodeIndex`.
    2. Pass 1 — `parent_of` structural edges.
    3. Pass 2 — anchor-based edges from raw HTML under `data/`.
    4. Pass 3 — regex citation edges on each node's text.
    5. Pass 4 — `defines` edges from DEFINITION → consumer nodes.
    6. Refine edge types (`cites` → interprets/applies/amends/repeals/transposes).
    7. Resolve and split into `output/edges.jsonl` + `output/dangling_edges.log`.
    8. Write `output/edge_stats.json`.

Run from the repo root:

    .venv/bin/python -m scripts.extract_edges                # full corpus
    .venv/bin/python -m scripts.extract_edges --limit 200    # smoke run
    .venv/bin/python -m scripts.extract_edges --skip-regex   # structural+anchor only

Parallelism: anchor extraction is parallelized across HTML files via
``multiprocessing.Pool`` (fork on Linux/macOS so the NodeIndex is shared
read-only). Structural, regex, and definition passes run in the parent
process — they're already streaming and fast enough at corpus scale.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterator, Optional

from src.extraction.anchor_edges import extract_anchor_edges
from src.extraction.citations_regex import extract_citations
from src.extraction.definition_edges import extract_definition_edges
from src.extraction.node_index import NodeIndex, NodeRecord
from src.extraction.refine import refine_edge_type
from src.extraction.resolve import RawMatch, resolve_matches
from src.extraction.structural_edges import build_structural_edges
from src.models import Edge


# --- Shared state for the fork-based anchor workers -----------------------
_WORKER_INDEX: NodeIndex | None = None


def _init_worker(nodes_jsonl_path: str) -> None:
    """When fork isn't available (spawn on macOS), workers re-load the index.

    On fork this is a no-op since `_WORKER_INDEX` is already populated from
    the parent process.
    """
    global _WORKER_INDEX
    if _WORKER_INDEX is None:
        _WORKER_INDEX = NodeIndex().load(Path(nodes_jsonl_path))


def _anchor_worker(task: tuple[str, str]) -> list[dict]:
    """Worker payload: (abs_path, rel_path) → serialized RawMatch dicts.

    We return dicts (not RawMatch objects) so the result pickles trivially
    and the parent process can re-route them into the resolution path.
    """
    abs_path, rel_path = task
    assert _WORKER_INDEX is not None
    out: list[dict] = []
    for raw, _span in extract_anchor_edges(Path(abs_path), rel_path, _WORKER_INDEX):
        out.append(_rawmatch_to_dict(raw))
    return out


def _rawmatch_to_dict(rm: RawMatch) -> dict:
    return {
        "source_id": rm.source_id,
        "target_ref": rm.target_ref,
        "key": rm.key.__dict__ if rm.key is not None else None,
        "type": rm.type,
        "confidence": rm.confidence,
        "extracted_by": rm.extracted_by,
        "context_snippet": rm.context_snippet,
        "source_law_id": rm.source_law_id,
    }


def _dict_to_rawmatch(d: dict) -> RawMatch:
    from src.extraction.ids import CitationKey
    k = d.get("key")
    return RawMatch(
        source_id=d["source_id"],
        target_ref=d["target_ref"],
        key=CitationKey(**k) if k is not None else None,
        type=d["type"],
        confidence=d["confidence"],
        extracted_by=d["extracted_by"],
        context_snippet=d.get("context_snippet"),
        source_law_id=d.get("source_law_id"),
    )


# --- File discovery (mirrors pipeline.ingest.classify) ---------------------

def _classify(rel_path: str) -> bool:
    parts = rel_path.split(os.sep)
    if len(parts) < 2:
        return False
    head = parts[0]
    if head == "finlex":
        return True
    if head == "vero":
        return True
    return False


def _iter_html_files(data_root: Path, limit: int | None) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for p in data_root.rglob("*.html"):
        if p.name.startswith("."):
            continue
        rel = str(p.relative_to(data_root))
        if not _classify(rel):
            continue
        files.append((str(p), rel))
        if limit is not None and len(files) >= limit:
            break
    return files


# --- Pipeline passes -------------------------------------------------------

def _emit_structural(nodes_jsonl: Path, sink) -> int:
    count = 0
    for edge in build_structural_edges(nodes_jsonl):
        sink(edge)
        count += 1
    return count


def _emit_anchor(
    files: list[tuple[str, str]],
    node_index: NodeIndex,
    nodes_jsonl: Path,
    workers: int,
    on_match,
) -> int:
    """Streams RawMatches from anchor extraction to `on_match`. Returns count."""
    count = 0
    if workers <= 1:
        for abs_path, rel_path in files:
            for raw, _span in extract_anchor_edges(Path(abs_path), rel_path, node_index):
                on_match(raw)
                count += 1
        return count

    ctx = mp.get_context("fork") if sys.platform != "win32" else mp.get_context("spawn")
    # On fork, set the global so children inherit it.
    global _WORKER_INDEX
    _WORKER_INDEX = node_index
    chunksize = max(1, len(files) // (workers * 16))
    with ctx.Pool(processes=workers, initializer=_init_worker,
                  initargs=(str(nodes_jsonl),)) as pool:
        for result in pool.imap_unordered(_anchor_worker, files, chunksize=chunksize):
            for d in result:
                on_match(_dict_to_rawmatch(d))
                count += 1
    return count


def _emit_regex(
    nodes_jsonl: Path,
    node_index: NodeIndex,
    anchor_refs_by_source: dict[str, set[str]],
    on_match,
    limit_nodes: int | None,
) -> int:
    """Scan nodes.jsonl, run citation regexes on text-bearing nodes."""
    text_types = {"SECTION", "SUBSECTION", "ITEM", "DEFINITION", "AMENDMENT_BLOCK", "GUIDE", "CASE", "TREATY"}
    count = 0
    seen = 0
    with nodes_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("type") not in text_types:
                continue
            text = d.get("text") or ""
            if not text:
                continue
            seen += 1
            if limit_nodes is not None and seen > limit_nodes:
                break
            refs = anchor_refs_by_source.get(d["id"], frozenset())
            for raw in extract_citations(
                text,
                source_id=d["id"],
                source_law_id=d.get("law_id"),
                anchor_target_refs=refs,
            ):
                on_match(raw)
                count += 1
    return count


def _emit_definitions(
    nodes_jsonl: Path,
    node_index: NodeIndex,
    sink,
) -> int:
    count = 0
    for edge in extract_definition_edges(node_index, nodes_jsonl):
        sink(edge)
        count += 1
    return count


# --- Output writers --------------------------------------------------------

class _Writer:
    """Streams resolved edges to edges.jsonl, dangling to dangling_edges.log,
    and updates per-type / per-reason counters in one place."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.edges_f = (out_dir / "edges.jsonl").open("w", encoding="utf-8")
        self.dangling_f = (out_dir / "dangling_edges.log").open("w", encoding="utf-8")
        self.by_type: Counter[str] = Counter()
        self.by_method: Counter[str] = Counter()
        self.resolved = 0
        self.dangling = 0
        self.dangling_by_reason: Counter[str] = Counter()
        self.incoming: Counter[str] = Counter()

    def write(self, edge: Edge) -> None:
        line = edge.model_dump_json(exclude_none=True)
        if edge.target_id is None:
            self.dangling_f.write(line + "\n")
            self.dangling += 1
            if edge.dangling_reason:
                self.dangling_by_reason[edge.dangling_reason] += 1
        else:
            self.edges_f.write(line + "\n")
            self.resolved += 1
            self.incoming[edge.target_id] += 1
        self.by_type[edge.type] += 1
        self.by_method[edge.extracted_by] += 1

    def close(self) -> None:
        self.edges_f.close()
        self.dangling_f.close()


# --- Main ------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="output")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--limit", type=int, default=None,
                    help="cap HTML files for anchor pass + node count for regex pass")
    ap.add_argument("--skip-anchor", action="store_true")
    ap.add_argument("--skip-regex", action="store_true")
    ap.add_argument("--skip-definitions", action="store_true")
    args = ap.parse_args()

    data_root = Path(args.data).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes_jsonl = out_dir / "nodes.jsonl"

    print(f"loading NodeIndex from {nodes_jsonl}…")
    t0 = time.time()
    index = NodeIndex().load(nodes_jsonl)
    print(f"  loaded {len(index.nodes):,} nodes in {time.time()-t0:.1f}s")

    writer = _Writer(out_dir)

    def handle_resolved_or_dangling(edges: Iterator[Edge]) -> None:
        for edge in edges:
            src = index.nodes.get(edge.source_id)
            tgt = index.nodes.get(edge.target_id) if edge.target_id else None
            new_type = refine_edge_type(edge, src, tgt) if src else edge.type
            if new_type != edge.type:
                edge = edge.model_copy(update={"type": new_type})
            writer.write(edge)

    # Pass 1: structural ----------------------------------------------------
    print("[1/5] structural edges (parent_of)…")
    t0 = time.time()
    n = 0
    for edge in build_structural_edges(nodes_jsonl):
        writer.write(edge)
        n += 1
    print(f"  emitted {n:,} parent_of edges in {time.time()-t0:.1f}s")

    # Pass 2: anchor --------------------------------------------------------
    anchor_refs_by_source: dict[str, set[str]] = {}
    if not args.skip_anchor:
        print("[2/5] anchor edges…")
        files = _iter_html_files(data_root, args.limit)
        print(f"  scanning {len(files):,} HTML files (workers={args.workers})…")
        t0 = time.time()
        buffered: list[RawMatch] = []

        def on_anchor(rm: RawMatch) -> None:
            buffered.append(rm)
            anchor_refs_by_source.setdefault(rm.source_id, set()).add(rm.target_ref)

        actual = _emit_anchor(files, index, nodes_jsonl, args.workers, on_anchor)
        print(f"  extracted {actual:,} anchor RawMatches in {time.time()-t0:.1f}s")
        # Resolve + refine + write.
        handle_resolved_or_dangling(resolve_matches(buffered, index))
        del buffered

    # Pass 3: regex ---------------------------------------------------------
    if not args.skip_regex:
        print("[3/5] regex citation edges…")
        t0 = time.time()
        buffered_r: list[RawMatch] = []

        def on_regex(rm: RawMatch) -> None:
            buffered_r.append(rm)
            # Flush in batches to bound memory.
            if len(buffered_r) >= 200_000:
                handle_resolved_or_dangling(resolve_matches(buffered_r, index))
                buffered_r.clear()

        actual = _emit_regex(nodes_jsonl, index, anchor_refs_by_source, on_regex, args.limit)
        if buffered_r:
            handle_resolved_or_dangling(resolve_matches(buffered_r, index))
            buffered_r.clear()
        print(f"  extracted {actual:,} regex RawMatches in {time.time()-t0:.1f}s")

    # Pass 4: definitions ---------------------------------------------------
    if not args.skip_definitions:
        print("[4/5] definition edges…")
        t0 = time.time()
        n_def = 0
        for edge in extract_definition_edges(index, nodes_jsonl):
            writer.write(edge)
            n_def += 1
        print(f"  emitted {n_def:,} `defines` edges in {time.time()-t0:.1f}s")

    # Pass 5: stats ---------------------------------------------------------
    print("[5/5] writing edge_stats.json…")
    writer.close()

    top_cited = writer.incoming.most_common(50)
    stats = {
        "total": writer.resolved + writer.dangling,
        "by_type": dict(writer.by_type),
        "by_method": dict(writer.by_method),
        "resolved": writer.resolved,
        "dangling": writer.dangling,
        "resolved_fraction": round(writer.resolved / max(1, writer.resolved + writer.dangling), 3),
        "dangling_by_reason": dict(writer.dangling_by_reason),
        "top_cited": [
            {"node_id": nid, "incoming_count": cnt} for nid, cnt in top_cited
        ],
    }
    with (out_dir / "edge_stats.json").open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print()
    print(f"resolved:           {writer.resolved:,}")
    print(f"dangling:           {writer.dangling:,}")
    print(f"by_type:            {dict(writer.by_type)}")
    print(f"dangling_by_reason: {dict(writer.dangling_by_reason)}")
    print(f"outputs: {out_dir}/edges.jsonl, dangling_edges.log, edge_stats.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
