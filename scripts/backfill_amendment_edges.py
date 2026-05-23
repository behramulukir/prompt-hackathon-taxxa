"""Backfill typed ``amends``/``repeals`` edges from AMENDMENT_BLOCK nodes.

The Step-1 parser emits ~14k AMENDMENT_BLOCK nodes (one per "14.5.2010/409"
heading inside a consolidated law's "Muutossäädösten voimaantulo ja
soveltaminen" chapter), but the Step-2 edge extractor only resolves ~48
amends/repeals edges (those that come from standalone "Laki X muuttamisesta"
or "kumoamisesta" files via regex). The amendment-block-driven side of the
graph is therefore effectively typeless and the ``RECENCY`` strategy in
``src/retrieval/strategy.py`` has nothing to walk.

This script closes the gap. Each AMENDMENT_BLOCK becomes one typed edge
back to its consolidated LAW root, carrying enactment/effective dates in
``properties_json``. The output is idempotent — re-running it deletes any
prior rows it inserted before writing fresh ones, identified by
``extracted_by='backfill_amendment'``.

Outputs:
- New rows in ``output/graph.db`` ``edges`` table (in-place).
- JSONL companion ``output/edges_amendments.jsonl`` for re-runnability /
  inspection / inclusion in a future ``load_graph --rebuild``.

CLI:

    .venv/bin/python -m scripts.backfill_amendment_edges            # full
    .venv/bin/python -m scripts.backfill_amendment_edges --dry-run  # report only
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction.dates import parse_any, parse_numeric, parse_spelled

OUTPUT_DIR = PROJECT_ROOT / "output"
GRAPH_DB = OUTPUT_DIR / "graph.db"
EDGES_JSONL = OUTPUT_DIR / "edges_amendments.jsonl"

EXTRACTED_BY = "backfill_amendment"

# Confidence: the AMENDMENT_BLOCK → LAW link is structurally derived (the
# block lives inside the consolidated law's own DOM), so 0.95 is honest.
# Slightly below 1.0 to leave room for future-edge-extractors that have
# section-level resolution.
CONFIDENCE = 0.95

# Heading like "14.5.2010/409" or "16.1.2026/15".
_AMEND_LABEL_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\s*/\s*(\d+)\b")

# "tulee voimaan ... <date>" scope. Mirrors ``metadata_finlex._VOIMAAN_RE``
# — the date we want is the *first* date inside this window, not just the
# first spelled date in the entire body. Without scoping, blocks that
# contain "Tämä laki, jolla kumotaan ... <old date>, tulee voimaan ..."
# pick up the old asetus date instead of the voimaantulo date.
_VOIMAAN_WINDOW_RE = re.compile(
    r"tulee\s+voimaan[^.<]{0,120}", re.IGNORECASE
)

# Pure-repeal marker. Finnish amendment blocks that ONLY repeal a section
# use "kumotaan" early in the text, often as the lead verb. We're
# conservative: require the verb to appear without an "ja muutetaan" /
# "ja lisätään" companion, otherwise treat as a mixed amendment.
_REPEAL_VERB_RE = re.compile(r"\bkumota(?:an|isin|ksi|essa|ttu)\b", re.IGNORECASE)
_AMEND_VERB_RE = re.compile(r"\bmuutet(?:aan|tu)\b", re.IGNORECASE)
_ADD_VERB_RE = re.compile(r"\blis[äa]t[äa](?:[äa]n)?\b", re.IGNORECASE)


@dataclass(frozen=True)
class _Block:
    node_id: str
    label: str | None
    text: str
    parent_id: str | None


def _law_root_of(node_id: str) -> str:
    """First three path segments — the LAW root id by construction.

    See ``scripts/enrich_metadata._root_of`` for the same convention.
    """
    parts = node_id.split("/")
    return "/".join(parts[:3]) if len(parts) >= 3 else node_id


def _classify_change(text: str) -> str:
    """Return one of ``repeal | amendment | addition``.

    Priority:
      * pure repeal (only kumotaan, no muutetaan / lisätään) → repeal
      * any muutetaan → amendment (most common)
      * only lisätään → addition
      * otherwise → amendment (default for blocks that only carry voimaantulo)
    """
    has_repeal = bool(_REPEAL_VERB_RE.search(text))
    has_amend = bool(_AMEND_VERB_RE.search(text))
    has_add = bool(_ADD_VERB_RE.search(text))
    if has_repeal and not has_amend and not has_add:
        return "repeal"
    if has_amend:
        return "amendment"
    if has_add and not has_amend:
        return "addition"
    return "amendment"


def _parse_label(label: str | None) -> tuple[str | None, str | None]:
    """Return ``(enactment_date_iso, act_number)`` parsed from ``label``.

    The label is what the parser captured as the h4 heading text — for
    consolidated Finlex it is shaped like ``14.5.2010/409``. We accept it
    even when followed by ``:`` or whitespace.
    """
    if not label:
        return None, None
    m = _AMEND_LABEL_RE.search(label)
    if not m:
        # Fall back to whatever numeric date the label carries.
        d = parse_numeric(label)
        return (d.isoformat() if d else None, None)
    day, month, year, act = m.groups()
    try:
        from datetime import date as _date
        return _date(int(year), int(month), int(day)).isoformat(), act
    except ValueError:
        return None, act


def _parse_effective(text: str) -> str | None:
    """Best-effort effective_date from the block body.

    Most blocks lead with ``Tämä laki tulee voimaan 1 päivänä joulukuuta
    2010.`` — a spelled date scoped right after "tulee voimaan". A few
    use the numeric form. We deliberately scope to the voimaantulo window
    because blocks that mention an older asetus the new law repeals
    ("kumotaan ... 24 päivänä helmikuuta 1873") would otherwise grab the
    1873 date as the new law's effective date.
    """
    if not text:
        return None
    for m in _VOIMAAN_WINDOW_RE.finditer(text):
        d = parse_any(m.group(0))
        if d is not None:
            return d.isoformat()
    # No voimaantulo clause — fall back to the first date in the whole
    # block. This is the case for a small number of blocks whose
    # boilerplate phrasing differs; better than null.
    d = parse_spelled(text) or parse_numeric(text)
    return d.isoformat() if d else None


def _iter_amendment_blocks(conn: sqlite3.Connection) -> Iterator[_Block]:
    cur = conn.execute(
        "SELECT id, label, text, parent_id FROM nodes WHERE type='AMENDMENT_BLOCK'"
    )
    for row in cur:
        yield _Block(node_id=row[0], label=row[1], text=row[2] or "", parent_id=row[3])


def _open_db() -> sqlite3.Connection:
    if not GRAPH_DB.exists():
        raise SystemExit(f"ERROR: {GRAPH_DB} not found — run scripts.load_graph first.")
    # ``timeout`` makes us wait politely for a writer rather than fail
    # instantly. The demo UI may hold a read connection in WAL mode.
    conn = sqlite3.connect(GRAPH_DB, timeout=30.0)
    # Stay in WAL — the live UI is a reader and switching journal modes
    # needs an exclusive lock we cannot get. WAL already gives us
    # concurrent-reader / single-writer semantics which is what we need.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _delete_prior_backfill(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM edges WHERE extracted_by = ?", (EXTRACTED_BY,))
    return cur.rowcount


def _law_root_exists(conn: sqlite3.Connection, law_root: str) -> bool:
    cur = conn.execute("SELECT 1 FROM nodes WHERE id = ?", (law_root,))
    return cur.fetchone() is not None


def _insert_edges(
    conn: sqlite3.Connection, rows: list[tuple]
) -> int:
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO edges "
        "(source_id, target_id, target_ref, type, confidence, extracted_by, "
        "context_snippet, dangling_reason, properties_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def _write_jsonl(records: list[dict]) -> None:
    EDGES_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with EDGES_JSONL.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False))
            f.write("\n")


def _build_edge_row(
    block: _Block,
    law_root: str,
) -> tuple[tuple, dict]:
    """Return (sql_row_tuple, jsonl_record_dict)."""
    change_type = _classify_change(block.text)
    edge_type = "repeals" if change_type == "repeal" else "amends"
    enactment_iso, act_number = _parse_label(block.label)
    effective_iso = _parse_effective(block.text)

    # target_ref: a human-readable handle — keep the act number when we
    # have it, otherwise the LAW id tail. The schema requires this field
    # be populated.
    if act_number:
        target_ref = f"act {act_number}"
    else:
        target_ref = block.label or law_root.rsplit("/", 1)[-1]

    # ~60 chars of context — the opening of the amendment body. Helps
    # downstream review; mirrors what regex-extracted edges carry.
    snippet = (block.text or "")[:80].replace("\n", " ").strip() or None

    properties = {
        "change_type": change_type,
        "act_number": act_number,
        "enactment_date": enactment_iso,
        "effective_date": effective_iso,
        "amendment_block_id": block.node_id,
    }
    # Drop None-valued props so the JSON is compact.
    properties = {k: v for k, v in properties.items() if v is not None}

    sql_row = (
        block.node_id,                # source_id
        law_root,                     # target_id (resolved — not dangling)
        target_ref,                   # target_ref
        edge_type,                    # type
        CONFIDENCE,                   # confidence
        EXTRACTED_BY,                 # extracted_by
        snippet,                      # context_snippet
        None,                         # dangling_reason
        json.dumps(properties, ensure_ascii=False) if properties else None,
    )
    jsonl_record = {
        "source_id": block.node_id,
        "target_id": law_root,
        "target_ref": target_ref,
        "type": edge_type,
        "confidence": CONFIDENCE,
        "extracted_by": EXTRACTED_BY,
        "context_snippet": snippet,
        "dangling_reason": None,
        "properties": properties,
    }
    return sql_row, jsonl_record


def _refresh_degree_for(
    conn: sqlite3.Connection, node_ids: set[str]
) -> int:
    """Recompute degree per node id and merge into ``metadata_json``.

    Only the supplied node ids are recomputed — the rest of the graph is
    untouched. We aggregate one SQL pass for outgoing, one for incoming,
    then write back updated metadata. Mirrors ``load_graph._backfill_degree``
    but restricted in scope.
    """
    if not node_ids:
        return 0
    # SQLite has a 999-param limit historically; chunk to be safe.
    deg_out: dict[str, dict[str, int]] = {}
    deg_in: dict[str, dict[str, int]] = {}
    ids = list(node_ids)
    BATCH = 500
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT source_id, type, COUNT(*) FROM edges "
            f"WHERE source_id IN ({ph}) GROUP BY source_id, type",
            chunk,
        )
        for nid, etype, cnt in cur:
            deg_out.setdefault(nid, {})[f"{etype}_out"] = cnt
        cur = conn.execute(
            f"SELECT target_id, type, COUNT(*) FROM edges "
            f"WHERE target_id IN ({ph}) GROUP BY target_id, type",
            chunk,
        )
        for nid, etype, cnt in cur:
            deg_in.setdefault(nid, {})[f"{etype}_in"] = cnt

    # Stream the affected nodes' metadata and merge.
    updates: list[tuple[str, str]] = []
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT id, metadata_json FROM nodes WHERE id IN ({ph})", chunk
        )
        for nid, mj in cur:
            try:
                meta = json.loads(mj) if mj else {}
            except json.JSONDecodeError:
                meta = {}
            merged: dict[str, int] = {}
            merged.update(deg_out.get(nid, {}))
            merged.update(deg_in.get(nid, {}))
            # Preserve any directions that didn't change (e.g. parent_of).
            existing = meta.get("degree") or {}
            # The recompute is authoritative for any (et, dir) we touched,
            # but other (et, dir) entries should remain — they weren't
            # affected by inserting amends/repeals edges. We only overwrite
            # the keys we just computed.
            for k, v in merged.items():
                existing[k] = v
            meta["degree"] = existing
            updates.append((json.dumps(meta, ensure_ascii=False), nid))
    if updates:
        conn.executemany(
            "UPDATE nodes SET metadata_json = ? WHERE id = ?", updates
        )
    return len(updates)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse blocks and report counts; do not write.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Smoke test: only process this many AMENDMENT_BLOCKs.")
    args = ap.parse_args()

    conn = _open_db()
    try:
        t0 = time.time()
        blocks = list(_iter_amendment_blocks(conn))
        if args.limit:
            blocks = blocks[: args.limit]
        print(f"[backfill] scanned {len(blocks):,} AMENDMENT_BLOCK nodes "
              f"in {time.time()-t0:.1f}s")

        # Stats counters.
        stats = {
            "blocks_seen":           len(blocks),
            "edges_amends":          0,
            "edges_repeals":         0,
            "missing_law_root":      0,
            "missing_effective":     0,
            "missing_enactment":     0,
        }

        sql_rows: list[tuple] = []
        jsonl_records: list[dict] = []
        affected_ids: set[str] = set()

        for b in blocks:
            law_root = _law_root_of(b.node_id)
            if law_root == b.node_id:
                # Block id is shorter than 3 segments — should not happen
                # given parser conventions. Skip defensively.
                stats["missing_law_root"] += 1
                continue
            if not _law_root_exists(conn, law_root):
                # Orphan AMENDMENT_BLOCK whose LAW root somehow isn't in the
                # graph. Skip — emitting a dangling edge would mask the
                # underlying load problem.
                stats["missing_law_root"] += 1
                continue

            sql_row, rec = _build_edge_row(b, law_root)
            sql_rows.append(sql_row)
            jsonl_records.append(rec)
            affected_ids.add(b.node_id)
            affected_ids.add(law_root)

            if rec["type"] == "repeals":
                stats["edges_repeals"] += 1
            else:
                stats["edges_amends"] += 1
            if rec["properties"].get("effective_date") is None:
                stats["missing_effective"] += 1
            if rec["properties"].get("enactment_date") is None:
                stats["missing_enactment"] += 1

        print(f"[backfill] amends={stats['edges_amends']:,}, "
              f"repeals={stats['edges_repeals']:,}, "
              f"orphan_blocks={stats['missing_law_root']:,}")
        print(f"[backfill]   missing effective_date={stats['missing_effective']:,}, "
              f"missing enactment_date={stats['missing_enactment']:,}")

        if args.dry_run:
            print("[backfill] DRY RUN — no writes.")
            return 0

        # Delete any prior backfill, insert fresh.
        deleted = _delete_prior_backfill(conn)
        if deleted:
            print(f"[backfill] removed {deleted:,} prior backfill edges")

        t1 = time.time()
        inserted = _insert_edges(conn, sql_rows)
        conn.commit()
        print(f"[backfill] inserted {inserted:,} edges in {time.time()-t1:.1f}s")

        t2 = time.time()
        n_updated = _refresh_degree_for(conn, affected_ids)
        conn.commit()
        print(f"[backfill] refreshed degree for {n_updated:,} nodes in "
              f"{time.time()-t2:.1f}s")

        _write_jsonl(jsonl_records)
        print(f"[backfill] wrote {len(jsonl_records):,} records to {EDGES_JSONL}")

        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()

    print("[backfill] DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
