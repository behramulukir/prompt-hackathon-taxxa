"""Step 4b.4 — Quality checks for ``output/graph.db``.

Rejects the load if any of the following invariants fail:

1. nodes table row count == lines in nodes_enriched.jsonl (or nodes.jsonl)
2. edges table row count == lines in edges.jsonl
3. Every ``edges.source_id`` matches a node id
4. Every non-NULL ``edges.target_id`` matches a node id
5. Total ``parent_of`` edges == (total nodes − number of root nodes)

Then runs two smoke tests (children of a known section; vero-guidance edges
pointing into a known finlex section) and emits a markdown report at
``findings/04b_load_report.md`` with node/edge counts and degree distribution.

CLI:

    .venv/bin/python -m pipeline.verify_graph
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output"
GRAPH_DB = OUTPUT_DIR / "graph.db"
NODES_IN = OUTPUT_DIR / "nodes_enriched.jsonl"
NODES_FALLBACK = OUTPUT_DIR / "nodes.jsonl"
EDGES_IN = OUTPUT_DIR / "edges.jsonl"
REPORT = PROJECT_ROOT / "findings" / "04b_load_report.md"


def _count_jsonl(path: Path) -> int:
    n = 0
    with path.open() as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--no-fail",
        action="store_true",
        help="Print violations but exit 0 (for diagnostics)",
    )
    args = ap.parse_args()

    if not GRAPH_DB.exists():
        print(f"[verify] {GRAPH_DB} missing — run scripts/load_graph.py first")
        return 2

    nodes_path = NODES_IN if NODES_IN.exists() else NODES_FALLBACK
    print(f"[verify] Counting {nodes_path.name} ...")
    n_nodes_file = _count_jsonl(nodes_path)
    print(f"[verify] Counting edges.jsonl ...")
    n_edges_file = _count_jsonl(EDGES_IN)

    conn = sqlite3.connect(GRAPH_DB)
    conn.row_factory = sqlite3.Row
    violations: list[str] = []
    report: list[str] = []
    report.append("# 04b Graph load report\n")

    # 1. Row count parity
    n_nodes_db = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    n_edges_db = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    print(f"[verify] nodes: db={n_nodes_db:,}  file={n_nodes_file:,}")
    print(f"[verify] edges: db={n_edges_db:,}  file={n_edges_file:,}")
    if n_nodes_db != n_nodes_file:
        violations.append(f"nodes row count mismatch: db={n_nodes_db}, file={n_nodes_file}")
    if n_edges_db != n_edges_file:
        violations.append(f"edges row count mismatch: db={n_edges_db}, file={n_edges_file}")

    # 2. FK integrity: edges.source_id
    bad_source = conn.execute(
        "SELECT COUNT(*) FROM edges e "
        "WHERE NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id = e.source_id)"
    ).fetchone()[0]
    print(f"[verify] edges with missing source node: {bad_source:,}")
    if bad_source:
        violations.append(f"{bad_source} edges have source_id that doesn't match any node")

    # 3. FK integrity: edges.target_id (only non-NULL)
    bad_target = conn.execute(
        "SELECT COUNT(*) FROM edges e "
        "WHERE e.target_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id = e.target_id)"
    ).fetchone()[0]
    print(f"[verify] non-null edges with missing target node: {bad_target:,}")
    if bad_target:
        violations.append(f"{bad_target} edges have non-null target_id that doesn't match any node")

    # 4. parent_of count == (nodes − roots)
    n_roots = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE parent_id IS NULL"
    ).fetchone()[0]
    n_parent_of = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE type = 'parent_of'"
    ).fetchone()[0]
    expected = n_nodes_db - n_roots
    print(
        f"[verify] roots={n_roots:,}  parent_of={n_parent_of:,}  "
        f"expected={expected:,}"
    )
    if n_parent_of != expected:
        violations.append(
            f"parent_of edges ({n_parent_of}) != nodes-roots ({expected}); "
            f"diff = {n_parent_of - expected}"
        )

    # 5. Dangling stats (informational, not a violation)
    n_dangling = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_id IS NULL"
    ).fetchone()[0]
    print(f"[verify] dangling edges (target_id IS NULL): {n_dangling:,}")

    # 6. Edge-type breakdown
    type_rows = conn.execute(
        "SELECT type, COUNT(*) AS c FROM edges GROUP BY type ORDER BY c DESC"
    ).fetchall()
    print("[verify] edge type breakdown:")
    for r in type_rows:
        print(f"  {r['type']:<12s}  {r['c']:>10,}")

    # 7. Smoke test: get_neighbors should return children for a known section.
    section_row = conn.execute(
        "SELECT id FROM nodes WHERE type = 'SECTION' LIMIT 1"
    ).fetchone()
    smoke_msgs: list[str] = []
    if section_row is None:
        smoke_msgs.append("WARN: no SECTION nodes in graph")
    else:
        sid = section_row["id"]
        children = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE source_id = ? AND type = 'parent_of'",
            (sid,),
        ).fetchone()[0]
        smoke_msgs.append(
            f"Section {sid} has {children} parent_of children "
            f"(expect > 0 for a non-leaf section)"
        )

    # 8. Smoke test: interprets edges from vero into finlex
    n_interprets = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE type = 'interprets' AND target_id IS NOT NULL"
    ).fetchone()[0]
    smoke_msgs.append(
        f"Resolved interprets edges (vero → finlex etc.): {n_interprets:,}"
    )

    # 9. Degree backfill check: how many nodes have degree.* in metadata
    deg_count_row = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE metadata_json LIKE '%\"degree\":%' "
        "AND metadata_json NOT LIKE '%\"degree\":{}%'"
    ).fetchone()
    nodes_with_degree = deg_count_row[0]
    print(f"[verify] nodes with non-empty degree[]: {nodes_with_degree:,}")

    # --- Report -----------------------------------------------------------
    report.append("## Row counts\n")
    report.append(f"- nodes (db / file): **{n_nodes_db:,}** / {n_nodes_file:,}")
    report.append(f"- edges (db / file): **{n_edges_db:,}** / {n_edges_file:,}")
    report.append(f"- roots (parent_id IS NULL): {n_roots:,}")
    report.append(f"- dangling edges (target_id IS NULL): {n_dangling:,}")
    report.append(f"- nodes with non-empty degree: {nodes_with_degree:,}\n")

    report.append("## Edge types\n")
    for r in type_rows:
        report.append(f"- `{r['type']}`: {r['c']:,}")

    report.append("\n## Smoke tests\n")
    for m in smoke_msgs:
        report.append(f"- {m}")

    # Degree distribution (top-of-distribution, useful for hub detection)
    print("[verify] Sampling top-degree nodes per edge type ...")
    top_hubs: dict[str, list[tuple[str, int]]] = {}
    for etype_row in type_rows[:5]:
        etype = etype_row["type"]
        cur = conn.execute(
            "SELECT target_id, COUNT(*) AS c FROM edges "
            "WHERE type = ? AND target_id IS NOT NULL "
            "GROUP BY target_id ORDER BY c DESC LIMIT 5",
            (etype,),
        )
        top_hubs[etype] = [(r["target_id"], r["c"]) for r in cur]

    report.append("\n## Top inbound-degree hubs (per edge type)\n")
    for etype, hubs in top_hubs.items():
        report.append(f"\n### `{etype}` (inbound)\n")
        if not hubs:
            report.append("- (none)")
        for tid, c in hubs:
            report.append(f"- `{tid}` ← {c:,}")

    report.append("\n## Verdict\n")
    if violations:
        report.append("**FAIL** — violations:\n")
        for v in violations:
            report.append(f"- {v}")
    else:
        report.append("**PASS** — all invariants hold.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(f"[verify] wrote {REPORT}")

    if violations:
        print("[verify] FAIL:")
        for v in violations:
            print(f"  - {v}")
        return 0 if args.no_fail else 1

    print("[verify] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
