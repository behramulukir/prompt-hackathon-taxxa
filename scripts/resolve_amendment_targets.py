"""Step 10 / Move 2 — Resolve AmendmentOps to target SECTION ids.

Reads ``output/amendment_ops.jsonl`` (Move 1) and, for each op, locates
the SECTION node in the *target* consolidated LAW the op refers to.
Resolution combines two independent signals:

1. **Target LAW inference** — slug-based genitive→nominative on the
   amendment-instrument LAW id. Mirrors ``backfill_muuttamisesta_edges``
   and ``caveats._amends_target_for`` so the three callers stay in
   lockstep. The lookup is O(1) per op via a pre-built stem index over
   every Finlex LAW.

2. **Target SECTION matching** — normalize the directive's
   ``target_section_label`` (e.g. ``"11 a §"`` → ``"11a"``) and try, in
   order:
     a) ``{target_law}/s{N}{letter?}``        (no chapter)
     b) ``{target_law}/c%/s{N}{letter?}``     (chapter-wrapped)
   The first match wins; ambiguous matches across chapters keep the
   chapter wrap with the highest order index (deterministic).

Emits one ``amends_section`` edge per resolved op into ``graph.db``,
carrying ``verb``, ``new_text``, ``effective_date``, and
``target_subsection`` in ``properties_json``. Unresolved ops are logged
to ``output/amendment_ops_unresolved.jsonl`` with a reason.

Idempotent via ``extracted_by='amends_section_resolve'`` — re-runs
delete previous rows from this extractor before re-inserting.

CLI::

    .venv/bin/python -m scripts.resolve_amendment_targets             # full
    .venv/bin/python -m scripts.resolve_amendment_targets --dry-run   # report only
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output"
GRAPH_DB = OUTPUT_DIR / "graph.db"
OPS_JSONL = OUTPUT_DIR / "amendment_ops.jsonl"
UNRESOLVED_JSONL = OUTPUT_DIR / "amendment_ops_unresolved.jsonl"
EDGES_JSONL = OUTPUT_DIR / "edges_amends_section.jsonl"
STATS_OUT = OUTPUT_DIR / "amends_section_stats.json"

EXTRACTED_BY = "amends_section_resolve"


# --------------------------------------------------------------------------
# Slug inference — shared with caveats and backfill_muuttamisesta
# --------------------------------------------------------------------------


# Matches a Finnish-legal-name stem in the *genitive* embedded in an
# amendment-instrument law id slug. Anchors on ``-`` so the publisher
# prefix and section-number suffix don't get swept in.
_GENITIVE_TOKEN_PAT = re.compile(
    r"-([a-zäöå]+(?:lain|uksen))(?:-|$)", re.IGNORECASE
)


def _genitive_to_nominative(slug: str) -> str | None:
    """``rikoslain`` → ``rikoslaki``, ``asetuksen`` → ``asetus``."""
    s = slug.lower()
    if s.endswith("lain"):
        return s[:-2] + "ki"
    if s.endswith("uksen"):
        return s[:-4] + "s"
    return None


_STEM_RE = re.compile(r"-([a-zäöå0-9]+)-html-")


def _build_law_stem_index(
    conn: sqlite3.Connection,
) -> dict[str, list[str]]:
    """``{nominative_stem: [law_id, ...]}`` over every Finlex LAW.

    Same trick as ``backfill_muuttamisesta_edges``: a per-LAW LIKE
    against the full id space is too slow, so we extract the last
    hyphen-delimited token before ``-html-`` once and dictionary-index
    on it. Lookup is O(1) per op.
    """
    cur = conn.execute(
        "SELECT id FROM nodes WHERE type='LAW' AND source='finlex'"
    )
    by_stem: dict[str, list[str]] = defaultdict(list)
    for (law_id,) in cur:
        m = _STEM_RE.search(law_id)
        if m:
            by_stem[m.group(1)].append(law_id)
    return by_stem


def _infer_target_law(
    instrument_law_id: str, stem_index: dict[str, list[str]]
) -> str | None:
    """Map ``finlex/laki/.../laki-rikoslain-muuttamisesta-...`` → ``finlex/laki/.../rikoslaki-...``.

    Picks the consolidated Laki edition over Säädöskokoelma when both
    exist, mirroring the preference encoded in caveats and
    backfill_muuttamisesta. Returns None for instrument ids whose stem
    can't be inferred or whose target doesn't exist.
    """
    lower = instrument_law_id.lower()
    if "muuttamisesta" not in lower and "kumoamisesta" not in lower:
        return None
    m = _GENITIVE_TOKEN_PAT.search(instrument_law_id)
    if not m:
        return None
    nominative = _genitive_to_nominative(m.group(1))
    if not nominative:
        return None
    candidates = stem_index.get(nominative, [])
    if not candidates:
        return None
    # Prefer consolidated Laki edition; fall back to säädöskokoelma.
    candidates.sort(
        key=lambda x: (0 if x.startswith("finlex/laki/") else 1, x)
    )
    return candidates[0]


# --------------------------------------------------------------------------
# Section resolution
# --------------------------------------------------------------------------


def _normalize_section_norm(label: str) -> str | None:
    """Same normaliser the Move 1 directive parser used.

    Duplicated here intentionally — keeping the two scripts decoupled is
    worth the duplication. If the rule changes, update both.
    """
    if not label:
        return None
    s = label.lower().replace("§", "").strip()
    out = "".join(ch for ch in s if ch.isalnum())
    if not out or not out[0].isdigit():
        return None
    return out


def _build_section_index(
    conn: sqlite3.Connection, target_law: str
) -> dict[str, list[str]]:
    """``{section_norm: [section_id, ...]}`` for one target LAW.

    Section IDs follow ``{law}/s{N}`` or ``{law}/c{M}/s{N}``. We compute
    ``section_norm`` from the *label* so cosmetic differences (whitespace,
    letter case) cancel out. Cached per call; called once per resolved
    target LAW so repeated ops on the same LAW share the index.
    """
    cur = conn.execute(
        "SELECT id, label FROM nodes "
        "WHERE id LIKE ? AND type='SECTION'",
        (target_law + "/%",),
    )
    by_norm: dict[str, list[str]] = defaultdict(list)
    for sid, label in cur:
        norm = _normalize_section_norm(label) if label else None
        if not norm:
            # Some sections lack a label; fall back to parsing the id
            # tail. ``.../s11a`` → ``11a``.
            tail = sid.rsplit("/", 1)[-1]
            if tail.startswith("s") and tail[1:].isalnum():
                norm = tail[1:]
        if norm:
            by_norm[norm].append(sid)
    return by_norm


def _resolve_section(
    target_law: str,
    section_norm: str,
    section_index: dict[str, list[str]],
) -> str | None:
    """Pick the best concrete SECTION id for ``(target_law, section_norm)``.

    When multiple sections share a normalised label (rare — would only
    happen if a law has the same § number under two chapters, which is
    valid in Finnish hierarchy), prefer the *first* one in document
    order. We use the sorted id as a stable proxy because section ids
    embed an order suffix when they were disambiguated at parse time.
    """
    cands = section_index.get(section_norm) or []
    if not cands:
        return None
    # Prefer non-chapter-wrapped ids first; fall back to chapter-wrapped.
    cands.sort(key=lambda x: (x.count("/"), x))
    return cands[0]


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------


def _open_db_rw() -> sqlite3.Connection:
    if not GRAPH_DB.exists():
        raise SystemExit(f"ERROR: {GRAPH_DB} not found.")
    conn = sqlite3.connect(GRAPH_DB, timeout=30.0)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _delete_prior(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "DELETE FROM edges WHERE extracted_by = ?", (EXTRACTED_BY,)
    )
    return cur.rowcount


def _iter_ops() -> Iterator[dict]:
    if not OPS_JSONL.exists():
        raise SystemExit(
            f"ERROR: {OPS_JSONL} not found. Run scripts.extract_amendment_ops first."
        )
    with OPS_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _insert_edges(conn: sqlite3.Connection, rows: list[tuple]) -> int:
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


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def run(dry_run: bool = False) -> dict:
    conn = _open_db_rw()
    try:
        t0 = time.time()
        print("[resolve] building LAW stem index ...", flush=True)
        stem_index = _build_law_stem_index(conn)
        print(f"[resolve]   {sum(len(v) for v in stem_index.values()):,} laws "
              f"under {len(stem_index):,} stems in {time.time()-t0:.1f}s")

        # Cache per-target-LAW section indices — most ops cluster on a
        # small number of target LAWs (TVL, AVL, etc.).
        section_index_cache: dict[str, dict[str, list[str]]] = {}

        counts: Counter = Counter()
        sql_rows: list[tuple] = []
        jsonl_records: list[dict] = []
        unresolved: list[dict] = []
        t1 = time.time()
        ops_total = 0
        for op in _iter_ops():
            ops_total += 1
            if ops_total % 5000 == 0:
                rate = ops_total / max(time.time() - t1, 1e-6)
                print(f"[resolve]   {ops_total:>7,} ops ({rate:.0f}/s)",
                      flush=True)

            block_law = op["block_law_id"]
            target_law = _infer_target_law(block_law, stem_index)
            if target_law is None:
                counts["unresolved_target_law"] += 1
                unresolved.append({**op, "reason": "target_law_not_found"})
                continue

            section_norm = _normalize_section_norm(op["target_section_label"])
            if not section_norm:
                counts["unresolved_bad_label"] += 1
                unresolved.append({**op, "reason": "bad_section_label"})
                continue

            sidx = section_index_cache.get(target_law)
            if sidx is None:
                sidx = _build_section_index(conn, target_law)
                section_index_cache[target_law] = sidx

            target_id = _resolve_section(target_law, section_norm, sidx)
            if target_id is None:
                # ``lisätään`` ops often target a § that doesn't exist
                # yet (the whole point is to add it). For those we emit
                # a dangling edge so Step 9 can still pick up the
                # voimaantulo signal — the target SECTION will appear
                # once the consolidated law is re-ingested.
                if op["verb"] == "lisätään":
                    counts["dangling_lisätään"] += 1
                    target_id = None
                    target_ref_str = f"{target_law}/s{section_norm} (new)"
                    properties = {
                        "verb": op["verb"],
                        "target_law": target_law,
                        "target_section_norm": section_norm,
                        "target_subsection": op.get("target_subsection"),
                        "new_text": op.get("new_text"),
                        "effective_date": op.get("effective_date"),
                        "chain_complex": op.get("chain_complex", False),
                    }
                    properties = {k: v for k, v in properties.items() if v is not None}
                    sql_rows.append((
                        block_law,                  # source_id
                        None,                       # target_id (dangling)
                        target_ref_str,             # target_ref
                        "amends_section",           # type
                        max(0.5, float(op.get("confidence") or 0.0)),
                        EXTRACTED_BY,
                        (op.get("target_section_label") or "")[:80],
                        "not_yet_parsed",           # dangling_reason
                        json.dumps(properties, ensure_ascii=False),
                    ))
                    jsonl_records.append({
                        "source_id": block_law,
                        "target_id": None,
                        "target_ref": target_ref_str,
                        "type": "amends_section",
                        "dangling_reason": "not_yet_parsed",
                        "properties": properties,
                    })
                    counts["edges_total"] += 1
                    continue
                counts["unresolved_section_missing"] += 1
                unresolved.append({**op, "reason": "section_not_found",
                                   "target_law": target_law})
                continue

            # Resolved — build the typed edge row.
            properties = {
                "verb": op["verb"],
                "target_law": target_law,
                "target_section_norm": section_norm,
                "target_subsection": op.get("target_subsection"),
                "new_text": op.get("new_text"),
                "effective_date": op.get("effective_date"),
                "chain_complex": op.get("chain_complex", False),
            }
            properties = {k: v for k, v in properties.items() if v is not None}
            sql_rows.append((
                block_law,                          # source_id
                target_id,                          # target_id (resolved)
                op.get("target_section_label") or section_norm,  # target_ref
                "amends_section",                   # type
                float(op.get("confidence") or 1.0),
                EXTRACTED_BY,
                (op.get("target_section_label") or "")[:80],
                None,
                json.dumps(properties, ensure_ascii=False),
            ))
            jsonl_records.append({
                "source_id": block_law,
                "target_id": target_id,
                "target_ref": op.get("target_section_label") or section_norm,
                "type": "amends_section",
                "dangling_reason": None,
                "properties": properties,
            })
            counts["edges_total"] += 1
            counts[f"verb_{op['verb']}"] += 1

        dur = time.time() - t1
        print(f"[resolve] scanned {ops_total:,} ops in {dur:.1f}s")
        print(f"[resolve]   resolved edges: {counts['edges_total']:,}")
        print(f"[resolve]     muutetaan:    {counts.get('verb_muutetaan', 0):,}")
        print(f"[resolve]     kumotaan:     {counts.get('verb_kumotaan', 0):,}")
        print(f"[resolve]     lisätään:     {counts.get('verb_lisätään', 0):,}")
        print(f"[resolve]   unresolved target LAW:    {counts['unresolved_target_law']:,}")
        print(f"[resolve]   unresolved bad label:     {counts['unresolved_bad_label']:,}")
        print(f"[resolve]   unresolved section miss:  {counts['unresolved_section_missing']:,}")
        print(f"[resolve]   dangling lisätään:        {counts['dangling_lisätään']:,}")

        stats = {
            "ops_total": ops_total,
            "edges_total": counts["edges_total"],
            "verb_muutetaan": counts.get("verb_muutetaan", 0),
            "verb_kumotaan": counts.get("verb_kumotaan", 0),
            "verb_lisätään": counts.get("verb_lisätään", 0),
            "unresolved_target_law": counts["unresolved_target_law"],
            "unresolved_bad_label": counts["unresolved_bad_label"],
            "unresolved_section_missing": counts["unresolved_section_missing"],
            "dangling_lisätään": counts["dangling_lisätään"],
            "dry_run": dry_run,
        }
        if dry_run:
            return stats

        deleted = _delete_prior(conn)
        if deleted:
            print(f"[resolve] removed {deleted:,} prior {EXTRACTED_BY} edges")
        t2 = time.time()
        inserted = _insert_edges(conn, sql_rows)
        conn.commit()
        print(f"[resolve] inserted {inserted:,} edges in {time.time()-t2:.1f}s")
        EDGES_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with EDGES_JSONL.open("w", encoding="utf-8") as f:
            for rec in jsonl_records:
                f.write(json.dumps(rec, ensure_ascii=False, default=str))
                f.write("\n")
        print(f"[resolve] wrote {len(jsonl_records):,} records → {EDGES_JSONL}")
        if unresolved:
            with UNRESOLVED_JSONL.open("w", encoding="utf-8") as f:
                for rec in unresolved:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str))
                    f.write("\n")
            print(f"[resolve] wrote {len(unresolved):,} unresolved → {UNRESOLVED_JSONL}")
        STATS_OUT.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print(f"[resolve] stats → {STATS_OUT}")
        conn.execute("ANALYZE")
        conn.commit()
        return stats
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts without writing edges.")
    args = ap.parse_args()
    run(dry_run=args.dry_run)
    print("[resolve] DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
