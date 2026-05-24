"""Step 10 / Move 3 — Compute per-SECTION version chains.

Reads the ``amends_section`` edges written by Move 2 and, for every
SECTION that has at least one inbound edge, builds a chronological
list of ``VersionStep`` records:

    [
      {effective_date: <original pub>, source_id: <section_id>,
       provenance: "original", text: <section.text>, ...},
      {effective_date: <amendment 1>,  source_id: <instrument LAW>,
       provenance: "muutetaan", text: <new_text>, ...},
      ...
    ]

The chain is stored under ``Node.metadata.version_chain`` (in-place
update of ``metadata_json``). ``GraphStore.text_at(section_id, as_of)``
in Move 4 plays it back to a point in time.

Affected nodes only — clean SECTIONs (no inbound amends_section edges)
are not touched, so the script is cheap on incremental graphs. A full
graph rebuild that wipes ``metadata_json`` requires a re-run.

CLI::

    .venv/bin/python -m scripts.compute_version_chains             # full
    .venv/bin/python -m scripts.compute_version_chains --dry-run   # report only
    .venv/bin/python -m scripts.compute_version_chains --limit 100 # smoke test
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output"
GRAPH_DB = OUTPUT_DIR / "graph.db"
STATS_OUT = OUTPUT_DIR / "version_chain_stats.json"


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------


def _open_db_rw() -> sqlite3.Connection:
    if not GRAPH_DB.exists():
        raise SystemExit(f"ERROR: {GRAPH_DB} not found.")
    conn = sqlite3.connect(GRAPH_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _iter_inbound_edges(
    conn: sqlite3.Connection,
) -> Iterable[tuple[str, str, dict]]:
    """Yield (target_section_id, source_block_id, properties_dict) for
    every resolved ``amends_section`` edge.

    Dangling edges (target_id is NULL — those came from ``lisätään``
    ops on sections not yet in the consolidated law) are skipped: by
    construction they have no SECTION to attach a chain to. They will
    pick up a chain on the next re-ingestion that materialises the new §.
    """
    cur = conn.execute(
        "SELECT source_id, target_id, properties_json "
        "FROM edges WHERE type='amends_section' AND target_id IS NOT NULL"
    )
    for row in cur:
        try:
            props = json.loads(row["properties_json"]) if row["properties_json"] else {}
        except json.JSONDecodeError:
            props = {}
        yield row["target_id"], row["source_id"], props


def _fetch_sections(
    conn: sqlite3.Connection, section_ids: list[str]
) -> dict[str, tuple[str, str | None, str]]:
    """``{section_id: (text, label, metadata_json)}`` for the affected ids."""
    out: dict[str, tuple[str, str | None, str]] = {}
    if not section_ids:
        return out
    BATCH = 500
    for i in range(0, len(section_ids), BATCH):
        chunk = section_ids[i:i + BATCH]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT id, text, label, metadata_json FROM nodes WHERE id IN ({ph})",
            chunk,
        )
        for row in cur:
            out[row["id"]] = (row["text"] or "", row["label"], row["metadata_json"])
    return out


# --------------------------------------------------------------------------
# Chain construction
# --------------------------------------------------------------------------


def _parse_iso(s) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _publication_date_for(meta_json: str | None) -> date | None:
    if not meta_json:
        return None
    try:
        meta = json.loads(meta_json)
    except json.JSONDecodeError:
        return None
    return _parse_iso(meta.get("publication_date"))


def _build_chain(
    section_id: str,
    section_text: str,
    section_meta_json: str | None,
    inbound: list[tuple[str, dict]],
) -> list[dict]:
    """Return the version_chain list ready for JSON serialisation.

    Order: original first (provenance="original"), then amendments
    sorted by effective_date ascending. Steps with no effective_date go
    *after* dated steps in their declaration order — they're a small
    minority and erring towards "treated as recent" is safer than
    silently dropping them.
    """
    original = {
        "effective_date": (
            _publication_date_for(section_meta_json).isoformat()
            if _publication_date_for(section_meta_json) else None
        ),
        "source_id": section_id,
        "provenance": "original",
        "text": section_text or None,
        "amendment_block_id": section_id,
    }

    dated: list[tuple[date, dict]] = []
    undated: list[dict] = []
    for src_id, props in inbound:
        verb = props.get("verb") or "muutetaan"
        eff = _parse_iso(props.get("effective_date"))
        step = {
            "effective_date": eff.isoformat() if eff else None,
            "source_id": src_id,
            "provenance": verb,
            "text": props.get("new_text"),
            "amendment_block_id": src_id,
            # Optional carry — useful for the UI's drill-down.
            "target_subsection": props.get("target_subsection"),
            "chain_complex": props.get("chain_complex", False),
        }
        step = {k: v for k, v in step.items() if v is not None}
        if eff is not None:
            dated.append((eff, step))
        else:
            undated.append(step)
    dated.sort(key=lambda t: t[0])
    return [original] + [s for _, s in dated] + undated


# --------------------------------------------------------------------------
# Streaming runner
# --------------------------------------------------------------------------


def run(*, dry_run: bool = False, limit: int | None = None) -> dict:
    conn = _open_db_rw()
    try:
        t0 = time.time()
        print("[chains] aggregating amends_section edges ...", flush=True)
        inbound_by_target: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        n_edges = 0
        for tgt, src, props in _iter_inbound_edges(conn):
            inbound_by_target[tgt].append((src, props))
            n_edges += 1
        print(f"[chains]   {n_edges:,} edges covering "
              f"{len(inbound_by_target):,} sections "
              f"in {time.time()-t0:.1f}s")

        target_ids = list(inbound_by_target.keys())
        if limit:
            target_ids = target_ids[:limit]
            print(f"[chains] limited to {len(target_ids):,} (smoke run)")

        t1 = time.time()
        section_rows = _fetch_sections(conn, target_ids)
        print(f"[chains]   fetched section rows in {time.time()-t1:.1f}s")

        counts: Counter = Counter()
        updates: list[tuple[str, str]] = []
        for sid in target_ids:
            row = section_rows.get(sid)
            if row is None:
                counts["missing_section"] += 1
                continue
            text, label, meta_json = row
            chain = _build_chain(sid, text, meta_json, inbound_by_target[sid])
            counts["chains_built"] += 1
            counts["steps_total"] += len(chain) - 1  # exclude original
            if any(s["provenance"] == "kumotaan" for s in chain[1:]):
                counts["chains_with_repeal"] += 1
            if any(s.get("effective_date") is None for s in chain[1:]):
                counts["chains_with_undated_step"] += 1
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except json.JSONDecodeError:
                meta = {}
            meta["version_chain"] = chain
            updates.append((json.dumps(meta, ensure_ascii=False), sid))

        print(f"[chains] built {counts['chains_built']:,} chains "
              f"({counts['steps_total']:,} amendment steps; "
              f"{counts['chains_with_repeal']:,} with a kumotaan)")
        print(f"[chains]   undated steps in chain: {counts['chains_with_undated_step']:,}")
        if counts["missing_section"]:
            print(f"[chains]   WARN: {counts['missing_section']:,} target sections not in nodes")

        stats = {
            "edges_total": n_edges,
            "chains_built": counts["chains_built"],
            "steps_total": counts["steps_total"],
            "chains_with_repeal": counts["chains_with_repeal"],
            "chains_with_undated_step": counts["chains_with_undated_step"],
            "missing_section": counts["missing_section"],
            "dry_run": dry_run,
        }
        if dry_run:
            return stats

        t2 = time.time()
        BATCH = 2000
        for i in range(0, len(updates), BATCH):
            chunk = updates[i:i + BATCH]
            conn.executemany(
                "UPDATE nodes SET metadata_json = ? WHERE id = ?", chunk
            )
        conn.commit()
        print(f"[chains] wrote {len(updates):,} updates in {time.time()-t2:.1f}s")
        STATS_OUT.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print(f"[chains] stats → {STATS_OUT}")
        return stats
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Build chains in memory and report counts; no writes.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N sections (smoke run).")
    args = ap.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)
    print("[chains] DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
