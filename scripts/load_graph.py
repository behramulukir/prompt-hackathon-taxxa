"""Step 4b — Load nodes + edges into a SQLite graph store.

Schema is defined in 04_embedding_and_indexing.md §4b.1. Uses bulk
``executemany`` inside a single transaction; on a laptop the entire
1.97M-node + 2.18M-edge corpus loads in well under a minute.

After both tables are populated, a third pass computes per-node degree
(per edge type, per direction) and writes it back into
``nodes.metadata_json`` so retrieval can read it from the same row.

CLI:

    .venv/bin/python -m scripts.load_graph                 # full load
    .venv/bin/python -m scripts.load_graph --rebuild       # drop & rebuild
    .venv/bin/python -m scripts.load_graph --skip-degree   # skip degree backfill
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output"
NODES_IN = OUTPUT_DIR / "nodes_enriched.jsonl"
NODES_FALLBACK = OUTPUT_DIR / "nodes.jsonl"
EDGES_IN = OUTPUT_DIR / "edges.jsonl"
GRAPH_DB = OUTPUT_DIR / "graph.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    source          TEXT NOT NULL,
    parent_id       TEXT,
    text            TEXT NOT NULL,
    label           TEXT,
    metadata_json   TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_type   ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_source ON nodes(source);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);

CREATE TABLE IF NOT EXISTS edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL,
    target_id       TEXT,
    target_ref      TEXT NOT NULL,
    type            TEXT NOT NULL,
    confidence      REAL NOT NULL,
    extracted_by    TEXT NOT NULL,
    context_snippet TEXT,
    dangling_reason TEXT,
    properties_json TEXT,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id, type);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id, type)
    WHERE target_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_edges_type   ON edges(type);
"""

NODE_INSERT = (
    "INSERT OR REPLACE INTO nodes "
    "(id, type, source, parent_id, text, label, metadata_json) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)

EDGE_INSERT = (
    "INSERT INTO edges "
    "(source_id, target_id, target_ref, type, confidence, extracted_by, "
    "context_snippet, dangling_reason, properties_json) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _open_db(rebuild: bool) -> sqlite3.Connection:
    if rebuild and GRAPH_DB.exists():
        GRAPH_DB.unlink()
        print(f"[graph] Removed existing {GRAPH_DB}")
    conn = sqlite3.connect(GRAPH_DB)
    # Speed knobs — fine because the load is a one-shot, the DB is local-only,
    # and we'd just re-run on corruption rather than recover.
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")  # ~200MB cache
    conn.executescript(SCHEMA)
    return conn


def _load_nodes(conn: sqlite3.Connection, path: Path) -> int:
    print(f"[graph] Loading nodes from {path.name} ...")
    t0 = time.time()
    rows: list[tuple] = []
    n = 0
    BATCH = 20_000
    with path.open() as f, conn:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            meta = d.get("metadata") or {}
            rows.append(
                (
                    d["id"],
                    d["type"],
                    d["source"],
                    d.get("parent_id"),
                    d.get("text") or "",
                    d.get("label"),
                    json.dumps(meta, ensure_ascii=False, default=str),
                )
            )
            if len(rows) >= BATCH:
                conn.executemany(NODE_INSERT, rows)
                n += len(rows)
                rows.clear()
        if rows:
            conn.executemany(NODE_INSERT, rows)
            n += len(rows)
            rows.clear()
    print(f"[graph] Inserted {n:,} nodes in {time.time()-t0:.1f}s")
    return n


def _load_edges(conn: sqlite3.Connection, path: Path) -> int:
    print(f"[graph] Loading edges from {path.name} ...")
    t0 = time.time()
    rows: list[tuple] = []
    n = 0
    BATCH = 20_000
    with path.open() as f, conn:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            props = d.get("properties") or {}
            rows.append(
                (
                    d["source_id"],
                    d.get("target_id"),
                    d["target_ref"],
                    d["type"],
                    d.get("confidence", 1.0),
                    d["extracted_by"],
                    d.get("context_snippet"),
                    d.get("dangling_reason"),
                    json.dumps(props, ensure_ascii=False, default=str) if props else None,
                )
            )
            if len(rows) >= BATCH:
                conn.executemany(EDGE_INSERT, rows)
                n += len(rows)
                rows.clear()
        if rows:
            conn.executemany(EDGE_INSERT, rows)
            n += len(rows)
            rows.clear()
    print(f"[graph] Inserted {n:,} edges in {time.time()-t0:.1f}s")
    return n


def _backfill_degree(conn: sqlite3.Connection) -> None:
    """Compute degree[edge_type][direction] per node, merge into metadata_json.

    Single SQL aggregation per direction beats N queries; result fits easily
    in memory at ~2M nodes.
    """
    print("[graph] Computing degree per (node, edge_type, direction) ...")
    t0 = time.time()
    deg: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Outgoing
    cur = conn.execute("SELECT source_id, type, COUNT(*) FROM edges GROUP BY source_id, type")
    for nid, etype, cnt in cur:
        deg[nid][f"{etype}_out"] = cnt

    # Incoming (only resolved edges have target_id; dangling=NULL is correctly excluded)
    cur = conn.execute(
        "SELECT target_id, type, COUNT(*) FROM edges "
        "WHERE target_id IS NOT NULL GROUP BY target_id, type"
    )
    for nid, etype, cnt in cur:
        deg[nid][f"{etype}_in"] = cnt

    print(f"[graph]   aggregation in {time.time()-t0:.1f}s, "
          f"{len(deg):,} nodes have at least one edge")

    # Stream existing metadata, merge in degree, update.
    print("[graph] Backfilling metadata_json with degree ...")
    t1 = time.time()
    cur = conn.execute("SELECT id, metadata_json FROM nodes")
    updates: list[tuple[str, str]] = []
    BATCH = 20_000
    n = 0
    for nid, mj in cur:
        node_deg = deg.get(nid)
        if not node_deg:
            continue
        try:
            meta = json.loads(mj) if mj else {}
        except json.JSONDecodeError:
            meta = {}
        meta["degree"] = dict(node_deg)
        updates.append((json.dumps(meta, ensure_ascii=False, default=str), nid))
        if len(updates) >= BATCH:
            conn.executemany(
                "UPDATE nodes SET metadata_json = ? WHERE id = ?", updates
            )
            n += len(updates)
            updates.clear()
    if updates:
        conn.executemany(
            "UPDATE nodes SET metadata_json = ? WHERE id = ?", updates
        )
        n += len(updates)
    conn.commit()
    print(f"[graph]   updated {n:,} nodes in {time.time()-t1:.1f}s")


def _final_pragmas(conn: sqlite3.Connection) -> None:
    """Restore durable-ish settings and analyze for query planner."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("ANALYZE")
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument(
        "--skip-degree",
        action="store_true",
        help="Skip the degree backfill (useful for partial debugging)",
    )
    args = ap.parse_args()

    nodes_path = NODES_IN if NODES_IN.exists() else NODES_FALLBACK
    print(f"[graph] Using nodes from: {nodes_path.name}")

    conn = _open_db(rebuild=args.rebuild)
    try:
        n_nodes = _load_nodes(conn, nodes_path)
        n_edges = _load_edges(conn, EDGES_IN)
        if not args.skip_degree:
            _backfill_degree(conn)
        _final_pragmas(conn)
    finally:
        conn.close()

    print(f"[graph] DONE. nodes={n_nodes:,}, edges={n_edges:,} -> {GRAPH_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
