"""Backfill ``amends`` edges from amendment-instrument LAWs to their target.

Step 2's regex extractor resolved only a few dozen ``amends`` edges
between standalone "Laki X muuttamisesta" acts and the consolidated
LAW they amend. The rest — hundreds of amendment instruments — sit in
the graph as orphaned roots, even though their title encodes the
target deterministically (X is in the Finnish genitive).

This script applies the same genitive→nominative trick that
``src/retrieval/caveats._amends_target_for`` already uses at query
time, but bakes the inferred relationship into the edge graph so
``compute_temporal_status`` picks it up next run. The result: the
consolidated ennakkoperintälaki, sairausvakuutuslaki, etc. report an
honest ``amendment_count_in_law`` and their child sections flip from
``effective_usable=ok`` to ``suspect`` when newer amendments exist.

Idempotent via ``extracted_by='backfill_muuttamisesta'``.

CLI:

  .venv/bin/python -m scripts.backfill_muuttamisesta_edges --dry-run
  .venv/bin/python -m scripts.backfill_muuttamisesta_edges
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction.dates import parse_numeric, parse_spelled

OUTPUT_DIR = PROJECT_ROOT / "output"
GRAPH_DB = OUTPUT_DIR / "graph.db"
EDGES_JSONL = OUTPUT_DIR / "edges_muuttamisesta.jsonl"

EXTRACTED_BY = "backfill_muuttamisesta"
CONFIDENCE = 0.85  # slug-inferred, less certain than Move 1's direct edges


# Same genitive-stem matcher as ``src.retrieval.caveats._GENITIVE_TOKEN_PAT``.
_GENITIVE_TOKEN_PAT = re.compile(
    r"-([a-zäöå]+(?:lain|uksen))(?:-|$)", re.IGNORECASE
)


def _genitive_to_nominative(slug: str) -> str | None:
    if slug.endswith("lain"):
        return slug[:-2] + "ki"
    if slug.endswith("uksen"):
        return slug[:-4] + "s"
    return None


def _build_law_root_index(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Pre-build ``{nominative_stem: [law_id, ...]}`` over every Finlex LAW.

    Doing the slug match in Python against a pre-loaded list of ~55k LAW
    ids is ~30,000× faster than running one ``LIKE`` query per candidate
    against a 1.97M-row table. We index by the stem token between the
    last ``-`` segment before ``-html-`` so the per-candidate lookup is
    O(1) instead of O(N).
    """
    cur = conn.execute(
        "SELECT id FROM nodes WHERE type='LAW' AND source='finlex'"
    )
    # Extract a "stem" — the last hyphen-delimited token before "-html-".
    # The previous LIKE pattern matched ``%-<nominative>-html-%`` so the
    # stem is the token immediately before ``-html-``.
    import re as _re
    stem_pat = _re.compile(r"-([a-zäöå0-9]+)-html-")
    by_stem: dict[str, list[str]] = {}
    for (law_id,) in cur:
        m = stem_pat.search(law_id)
        if not m:
            continue
        by_stem.setdefault(m.group(1).lower(), []).append(law_id)
    # Prefer ``finlex/laki/`` over ``finlex/laki_skk/`` — same convention
    # as the original SQL ORDER BY clause.
    def _sort_key(lid: str) -> int:
        return 0 if lid.startswith("finlex/laki/") else 1
    for v in by_stem.values():
        v.sort(key=_sort_key)
    return by_stem


def _infer_target_law(law_index: dict[str, list[str]], amendment_law_id: str) -> str | None:
    """Mirror ``caveats._amends_target_for`` but O(1) via ``law_index``."""
    m = _GENITIVE_TOKEN_PAT.search(amendment_law_id)
    if not m:
        return None
    nominative = _genitive_to_nominative(m.group(1).lower())
    if not nominative:
        return None
    bucket = law_index.get(nominative)
    return bucket[0] if bucket else None


def _parse_dates(law_id: str, text: str) -> tuple[str | None, str | None, str | None]:
    """Best-effort enactment + effective + act-number from the muuttamisesta
    LAW's metadata-derived hints. We use the LAW's id (which encodes the
    document publication year for some files) and the LAW's first SUBSECTION
    text (which often starts with ``Tämä laki tulee voimaan …``).
    """
    # Act number — sometimes present in slug as ``-NN-html-`` where NN is
    # the act number. Not always.
    act_match = re.search(r"-(\d{1,4})-html-", law_id)
    act_number = act_match.group(1) if act_match else None

    eff = parse_spelled(text) or parse_numeric(text)
    effective_iso = eff.isoformat() if eff else None
    return None, effective_iso, act_number


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not GRAPH_DB.exists():
        print(f"ERROR: {GRAPH_DB} missing", file=sys.stderr)
        return 1

    conn = sqlite3.connect(GRAPH_DB, timeout=30.0)
    conn.execute("PRAGMA synchronous=NORMAL")

    t0 = time.time()
    print("[muuttamisesta] building LAW-root index for O(1) target lookup…",
          flush=True)
    law_index = _build_law_root_index(conn)
    print(f"[muuttamisesta]   indexed {sum(len(v) for v in law_index.values()):,} "
          f"LAW roots under {len(law_index):,} stems "
          f"in {time.time()-t0:.1f}s")

    t1 = time.time()
    cur = conn.execute(
        "SELECT id, label FROM nodes WHERE type='LAW' "
        "AND source='finlex' AND id LIKE '%-muuttamisesta-%'"
    )
    candidates = cur.fetchall()
    if args.limit:
        candidates = candidates[: args.limit]
    print(f"[muuttamisesta] {len(candidates):,} amendment-instrument LAWs in "
          f"{time.time()-t1:.1f}s")

    stats = {"resolved": 0, "no_target": 0, "self_target": 0,
             "already_has_edge": 0, "inserted": 0}
    sql_rows: list[tuple] = []
    jsonl_records: list[dict] = []
    affected_ids: set[str] = set()

    # Skip any law that already has an outbound amends edge (Step 2 or
    # earlier backfill resolved it).
    cur = conn.execute(
        "SELECT DISTINCT source_id FROM edges WHERE type='amends'"
    )
    already_emitting: set[str] = {row[0] for row in cur}
    # Project to LAW root.
    already_emitting_roots = {
        "/".join(sid.split("/")[:3]) for sid in already_emitting
    }

    # Lead-text snippets: for each LAW root, grab its first non-empty
    # SUBSECTION text to fish out a ``tulee voimaan`` date.
    lead_text_cache: dict[str, str] = {}
    for law_id, _label in candidates:
        if law_id in already_emitting_roots:
            stats["already_has_edge"] += 1
            continue
        target = _infer_target_law(law_index, law_id)
        if target is None:
            stats["no_target"] += 1
            continue
        if target == law_id:
            stats["self_target"] += 1
            continue

        # Look up a representative text snippet for effective_date.
        if law_id not in lead_text_cache:
            cur = conn.execute(
                "SELECT text FROM nodes WHERE parent_id = ? AND "
                "text != '' ORDER BY id LIMIT 1",
                (law_id,),
            )
            row = cur.fetchone()
            lead_text_cache[law_id] = row[0] if row else ""
        snippet = lead_text_cache[law_id]
        _enact, effective_iso, act_number = _parse_dates(law_id, snippet)

        properties = {
            "change_type":      "amendment",
            "act_number":       act_number,
            "effective_date":   effective_iso,
            "inferred_from":    "title_slug",
        }
        properties = {k: v for k, v in properties.items() if v is not None}
        target_ref = f"act {act_number}" if act_number else target.rsplit("/", 1)[-1]
        snippet_short = (snippet or "")[:80].replace("\n", " ").strip() or None

        sql_rows.append((
            law_id,
            target,
            target_ref,
            "amends",
            CONFIDENCE,
            EXTRACTED_BY,
            snippet_short,
            None,
            json.dumps(properties, ensure_ascii=False) if properties else None,
        ))
        jsonl_records.append({
            "source_id": law_id,
            "target_id": target,
            "target_ref": target_ref,
            "type": "amends",
            "confidence": CONFIDENCE,
            "extracted_by": EXTRACTED_BY,
            "context_snippet": snippet_short,
            "properties": properties,
        })
        affected_ids.add(law_id)
        affected_ids.add(target)
        stats["resolved"] += 1

    print(f"[muuttamisesta] resolved={stats['resolved']:,}, "
          f"no_target={stats['no_target']:,}, "
          f"already_has_edge={stats['already_has_edge']:,}")

    if args.dry_run:
        print("[muuttamisesta] DRY RUN — no writes.")
        return 0

    # Wipe prior backfill, then insert fresh.
    cur = conn.execute("DELETE FROM edges WHERE extracted_by = ?", (EXTRACTED_BY,))
    print(f"[muuttamisesta] removed {cur.rowcount:,} prior backfill edges")

    conn.executemany(
        "INSERT INTO edges "
        "(source_id, target_id, target_ref, type, confidence, extracted_by, "
        "context_snippet, dangling_reason, properties_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        sql_rows,
    )
    conn.commit()
    stats["inserted"] = len(sql_rows)
    print(f"[muuttamisesta] inserted {stats['inserted']:,} edges")

    EDGES_JSONL.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in jsonl_records) + "\n",
        encoding="utf-8",
    )
    print(f"[muuttamisesta] wrote {EDGES_JSONL}")

    # Refresh degree for affected target laws (their amends_in jumps).
    print("[muuttamisesta] refreshing degree on affected nodes…")
    _refresh_degree(conn, list(affected_ids))
    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    print("[muuttamisesta] DONE. NEXT: re-run scripts.compute_temporal_status")
    return 0


def _refresh_degree(conn: sqlite3.Connection, node_ids: list[str]) -> None:
    """Same shape as backfill_amendment_edges._refresh_degree_for — copy of
    the logic kept here to keep this script standalone.
    """
    BATCH = 500
    deg: dict[str, dict[str, int]] = {}
    for i in range(0, len(node_ids), BATCH):
        chunk = node_ids[i:i + BATCH]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT source_id, type, COUNT(*) FROM edges "
            f"WHERE source_id IN ({ph}) GROUP BY source_id, type",
            chunk,
        )
        for nid, etype, cnt in cur:
            deg.setdefault(nid, {})[f"{etype}_out"] = cnt
        cur = conn.execute(
            f"SELECT target_id, type, COUNT(*) FROM edges "
            f"WHERE target_id IN ({ph}) GROUP BY target_id, type",
            chunk,
        )
        for nid, etype, cnt in cur:
            deg.setdefault(nid, {})[f"{etype}_in"] = cnt
    updates = []
    for i in range(0, len(node_ids), BATCH):
        chunk = node_ids[i:i + BATCH]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT id, metadata_json FROM nodes WHERE id IN ({ph})", chunk
        )
        for nid, mj in cur:
            try:
                meta = json.loads(mj) if mj else {}
            except json.JSONDecodeError:
                meta = {}
            existing = meta.get("degree") or {}
            for k, v in deg.get(nid, {}).items():
                existing[k] = v
            meta["degree"] = existing
            updates.append((json.dumps(meta, ensure_ascii=False), nid))
    if updates:
        conn.executemany(
            "UPDATE nodes SET metadata_json = ? WHERE id = ?", updates
        )


if __name__ == "__main__":
    raise SystemExit(main())
