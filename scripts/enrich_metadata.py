"""B3.4 — Metadata enrichment runner.

Streams Step 1's ``output/nodes.jsonl`` and emits an enriched copy with
``metadata.{publication_date, effective_date, repeal_date, in_force,
authority, authority_rank, superseded_by, language, usable}`` populated.

Algorithm:

    Pass 1  — scan root nodes (LAW/GUIDE/CASE/TREATY), collect one
              ``source_file`` per ``law_id``.
    Pass 1b — open each unique HTML file once, dispatch to a
              source-specific extractor, store a ``law_id → RootMetadata``
              map in memory (~63k entries, fits easily).
    Pass 1c — if ``output/edges.jsonl`` exists, walk ``amends``/``repeals``
              edges to set ``superseded_by`` per chain. Otherwise warn and
              continue — Step 2 may not be done yet.
    Pass 2  — stream every node again, attach root metadata + authority +
              composite ``usable``, write to
              ``output/nodes_enriched.jsonl``.

Runs in tens of seconds on a warm filesystem because each HTML is parsed
exactly once and node iteration is sequential JSONL.

CLI:

    .venv/bin/python -m scripts.enrich_metadata --limit-roots 200    # smoke
    .venv/bin/python -m scripts.enrich_metadata                      # full
    .venv/bin/python -m scripts.enrich_metadata --workers 8          # parallel HTML reads
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Iterator

# Make the project root importable when run as `python -m scripts.enrich_metadata`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction import metadata_finlex, metadata_kho, metadata_treaty, metadata_vero
from src.extraction.authority import tag as authority_tag
from src.extraction.composite import usable as compute_usable
from src.extraction.metadata_finlex import RootMetadata

# --- I/O paths --------------------------------------------------------------

DATA_ROOT = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
NODES_IN = OUTPUT_DIR / "nodes.jsonl"
NODES_OUT = OUTPUT_DIR / "nodes_enriched.jsonl"
EDGES_IN = OUTPUT_DIR / "edges.jsonl"
STATS_OUT = OUTPUT_DIR / "enrichment_stats.json"

ROOT_TYPES = {"LAW", "GUIDE", "CASE", "TREATY"}


# --- Pass 1: collect root file paths ---------------------------------------


def scan_roots(nodes_path: Path, limit: int | None) -> dict[str, dict[str, str]]:
    """Return ``{law_id: {"source_file": ..., "source_subcorpus": ..., "source": ..., "title": ...}}``.

    Stops after ``limit`` root nodes if set (smoke testing).
    """
    roots: dict[str, dict[str, str]] = {}
    with nodes_path.open("r", encoding="utf-8") as f:
        for line in f:
            n = json.loads(line)
            if n.get("type") not in ROOT_TYPES:
                continue
            law_id = n.get("id")  # for root nodes, id == law_id
            if not law_id or law_id in roots:
                continue
            roots[law_id] = {
                "source_file":     n.get("source_file", ""),
                "source_subcorpus":n.get("source_subcorpus", ""),
                "source":          n.get("source", ""),
                "title":           n.get("title") or "",
            }
            if limit is not None and len(roots) >= limit:
                break
    return roots


# --- Pass 1b: parse one HTML per root --------------------------------------


def _dispatch_extract(html: str, source: str, subcorpus: str, title: str, source_file: str) -> RootMetadata:
    if subcorpus.startswith("kho"):
        return metadata_kho.extract(html, title=title, source_file=source_file)
    if subcorpus.startswith("treaty"):
        return metadata_treaty.extract(html, title=title)
    if source == "vero":
        return metadata_vero.extract(html, title=title)
    return metadata_finlex.extract(html, title=title)


def _extract_one(arg: tuple[str, str, str, str, str]) -> tuple[str, RootMetadata | None, str]:
    """Worker. Returns (law_id, metadata_or_None, error_msg)."""
    law_id, abs_path, source, subcorpus, title = arg
    try:
        html = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        md = _dispatch_extract(html, source, subcorpus, title, abs_path)
        return law_id, md, ""
    except Exception as exc:  # noqa: BLE001
        return law_id, None, f"{type(exc).__name__}: {exc}"


def extract_all(roots: dict[str, dict[str, str]], workers: int) -> tuple[dict[str, RootMetadata], list[str]]:
    """Return ``(law_id → RootMetadata, errors)``."""
    work = []
    for law_id, info in roots.items():
        abs_path = str(DATA_ROOT / info["source_file"])
        work.append((law_id, abs_path, info["source"], info["source_subcorpus"], info["title"]))

    out: dict[str, RootMetadata] = {}
    errors: list[str] = []

    if workers <= 1:
        for arg in work:
            law_id, md, err = _extract_one(arg)
            if md is not None:
                out[law_id] = md
            elif err:
                errors.append(f"{arg[1]}\t{err}")
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for law_id, md, err in ex.map(_extract_one, work, chunksize=64):
                if md is not None:
                    out[law_id] = md
                elif err:
                    errors.append(f"{law_id}\t{err}")

    return out, errors


# --- Pass 1c: amendment / repeal chain walk --------------------------------


def walk_amendment_chains(edges_path: Path, root_metadata: dict[str, RootMetadata]) -> dict[str, str]:
    """Return ``{old_law_id: newest_amender_law_id}``.

    Walks ``amends`` and ``repeals`` edges to find the latest amending
    document per root. Edges are expected from Step 2; if the file is
    missing, return ``{}`` and let the caller log a warning.

    Defensive: per the Step 2 edge taxonomy, ``amends``/``repeals`` only
    flow ``finlex/* → finlex/*`` and only from a statute subcorpus
    (laki / asetus / *_skk). KHO precedents and Vero guidance can never
    legally amend a statute — if Step 2's regex labels one that way it's
    noise, and we drop it here rather than corrupt ``superseded_by``.
    """
    if not edges_path.exists():
        return {}

    # Subcorpora that can legally amend or repeal a statute.
    _STATUTE_SUBCORPORA = ("laki", "asetus")

    # Map: target_root → list of (source_root, edge_publication_date)
    amenders: dict[str, list[tuple[str, date | None]]] = defaultdict(list)

    with edges_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = e.get("type")
            if etype not in {"amends", "repeals"}:
                continue
            target = e.get("target_id")
            source = e.get("source_id")
            if not target or not source:
                continue
            # Trim node ids back to law_id (root). Step 1 ids are
            # hierarchical: "{source}/{subcorpus}/{doc_slug}[/...]". The
            # root is the first three segments.
            tgt_root = _root_of(target)
            src_root = _root_of(source)
            if tgt_root == src_root:
                continue
            # Only statute-subcorpus sources can amend. Both id segments
            # are "{publisher}/{subcorpus}/…"; segment 1 is the subcorpus.
            src_subcorpus = src_root.split("/")[1] if "/" in src_root else ""
            if not src_subcorpus.startswith(_STATUTE_SUBCORPORA):
                continue
            src_pub = root_metadata.get(src_root)
            amenders[tgt_root].append((src_root, src_pub.publication_date if src_pub else None))

    superseded_by: dict[str, str] = {}
    for tgt, candidates in amenders.items():
        # Pick the candidate with the latest publication date; ties go to
        # lexicographically later law_id for determinism.
        candidates.sort(key=lambda c: (c[1] or date.min, c[0]))
        superseded_by[tgt] = candidates[-1][0]
    return superseded_by


def _root_of(node_id: str) -> str:
    parts = node_id.split("/")
    return "/".join(parts[:3]) if len(parts) >= 3 else node_id


# --- Pass 2: rewrite nodes.jsonl with metadata -----------------------------


def rewrite_nodes(
    nodes_in: Path,
    nodes_out: Path,
    root_metadata: dict[str, RootMetadata],
    superseded_by: dict[str, str],
    today: date,
) -> dict[str, int]:
    """Stream and rewrite. Returns a small stats dict."""
    counts = {
        "nodes_total":           0,
        "with_publication_date": 0,
        "with_effective_date":   0,
        "with_repeal_date":      0,
        "with_authority":        0,
        "with_superseded_by":    0,
        "usable_true":           0,
        "in_force_false":        0,
        "no_root_metadata":      0,
    }
    nodes_out.parent.mkdir(parents=True, exist_ok=True)

    with nodes_in.open("r", encoding="utf-8") as fin, nodes_out.open("w", encoding="utf-8") as fout:
        for line in fin:
            n = json.loads(line)
            law_id = n.get("law_id") or n.get("id")
            md_root = root_metadata.get(law_id) if law_id else None

            md: dict[str, Any] = dict(n.get("metadata") or {})

            if md_root is not None:
                if md_root.publication_date:
                    md["publication_date"] = md_root.publication_date.isoformat()
                    counts["with_publication_date"] += 1
                if md_root.effective_date:
                    md["effective_date"] = md_root.effective_date.isoformat()
                    counts["with_effective_date"] += 1
                if md_root.repeal_date:
                    md["repeal_date"] = md_root.repeal_date.isoformat()
                    counts["with_repeal_date"] += 1
                if md_root.in_force is not None:
                    md["in_force"] = md_root.in_force
                if md_root.language:
                    md["language"] = md_root.language
            else:
                counts["no_root_metadata"] += 1

            # Authority is fixed-mapping — populated for every node.
            try:
                authority, rank = authority_tag(n.get("source", ""), n.get("source_subcorpus", ""))
                md["authority"] = authority
                md["authority_rank"] = rank
                counts["with_authority"] += 1
            except ValueError:
                pass

            if law_id in superseded_by:
                md["superseded_by"] = superseded_by[law_id]
                counts["with_superseded_by"] += 1

            md["usable"] = compute_usable(
                in_force=md.get("in_force"),
                repeal_date=_parse_iso_date(md.get("repeal_date")),
                superseded_by=md.get("superseded_by"),
                today=today,
            )
            if md["usable"]:
                counts["usable_true"] += 1
            if md.get("in_force") is False:
                counts["in_force_false"] += 1

            n["metadata"] = md
            fout.write(json.dumps(n, ensure_ascii=False))
            fout.write("\n")
            counts["nodes_total"] += 1

    return counts


def _parse_iso_date(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# --- Iterators -------------------------------------------------------------


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


# --- CLI -------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-roots", type=int, default=None,
                    help="Smoke-test: only process this many root documents.")
    ap.add_argument("--workers", type=int, default=1,
                    help="Parallel HTML readers (1 = single-threaded).")
    ap.add_argument("--today", default=None,
                    help="Override 'today' as ISO date for deterministic runs.")
    args = ap.parse_args()

    if not NODES_IN.exists():
        print(f"ERROR: {NODES_IN} not found — run Step 1 first.", file=sys.stderr)
        return 1

    today = date.fromisoformat(args.today) if args.today else date.today()
    print(f"[1/4] scanning roots from {NODES_IN}", flush=True)
    t0 = time.time()
    roots = scan_roots(NODES_IN, args.limit_roots)
    print(f"      → {len(roots)} roots in {time.time()-t0:.1f}s", flush=True)

    print(f"[2/4] extracting metadata from {len(roots)} HTML files (workers={args.workers})", flush=True)
    t0 = time.time()
    root_metadata, errors = extract_all(roots, workers=args.workers)
    print(f"      → {len(root_metadata)} extracted ({len(errors)} errors) in {time.time()-t0:.1f}s", flush=True)
    if errors:
        err_log = OUTPUT_DIR / "enrichment_errors.log"
        err_log.write_text("\n".join(errors[:1000]), encoding="utf-8")
        print(f"      first errors → {err_log}", flush=True)

    print("[3/4] walking amendment chains", flush=True)
    if EDGES_IN.exists():
        superseded_by = walk_amendment_chains(EDGES_IN, root_metadata)
        print(f"      → {len(superseded_by)} superseded laws", flush=True)
    else:
        superseded_by = {}
        print(f"      → SKIP: {EDGES_IN} not found (Step 2 not done yet)", flush=True)

    print(f"[4/4] rewriting nodes to {NODES_OUT}", flush=True)
    t0 = time.time()
    counts = rewrite_nodes(NODES_IN, NODES_OUT, root_metadata, superseded_by, today)
    print(f"      → {counts['nodes_total']} nodes in {time.time()-t0:.1f}s", flush=True)

    stats = {
        "today":            today.isoformat(),
        "roots_scanned":    len(roots),
        "roots_extracted":  len(root_metadata),
        "extract_errors":   len(errors),
        "superseded":       len(superseded_by),
        "edges_jsonl_present": EDGES_IN.exists(),
        **counts,
    }
    STATS_OUT.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"stats → {STATS_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
