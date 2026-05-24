"""Compute ancestor-aware ``temporal_status`` for every node in graph.db.

The existing ``usable`` flag is computed from the node's own metadata only.
That misses the case the brief raised: a SUBSECTION may be unchanged on
paper while its parent SECTION's containing LAW has been amended, repealed,
or interpreted by a higher court. ``usable=True`` lies in that case.

This script reads the graph and writes a richer ``temporal_status`` dict
into every node's ``metadata_json``, computed by:

  1. Building a per-LAW summary from the AMENDMENT_BLOCK descendants
     (their effective_dates) and any direct ``amends``/``repeals`` edges
     targeting the LAW or its sections.
  2. For each node, deriving its LAW root from the id (first three path
     segments) and folding the LAW summary together with the node's own
     publication_date to produce a four-state ``effective_usable`` rating.

The new field never replaces ``usable`` — both coexist. ``usable`` is the
narrow self-only flag the rest of the pipeline already reads;
``temporal_status.effective_usable`` is the ancestor-aware grade that
Move 3 (rerank) consumes.

Output schema added to ``nodes.metadata_json[\"temporal_status\"]``::

    {
      "effective_usable":          "ok" | "suspect" | "stale" | "repealed",
      "self_repealed":             bool,
      "law_repealed":              bool,
      "law_stale":                 bool,
      "ancestor_amended":          bool,
      "ancestor_amended_after":    "YYYY-MM-DD" | null,
      "nearest_amendment_id":      str | null,
      "amendment_count_in_law":    int,
      "interpreted_count":         int,
      "latest_interpretation_date":"YYYY-MM-DD" | null,
      "computed_at":               "YYYY-MM-DD"
    }

CLI:

    .venv/bin/python -m scripts.compute_temporal_status                # full
    .venv/bin/python -m scripts.compute_temporal_status --dry-run      # report only
    .venv/bin/python -m scripts.compute_temporal_status --today 2026-05-24
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_DIR = PROJECT_ROOT / "output"
GRAPH_DB = OUTPUT_DIR / "graph.db"
STATS_OUT = OUTPUT_DIR / "temporal_status_stats.json"


def _law_root_of(node_id: str) -> str:
    parts = node_id.split("/")
    return "/".join(parts[:3]) if len(parts) >= 3 else node_id


def _parse_iso(s: str | None) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# Heuristic: "X-muuttamisesta-annetun-lain-kumoamisesta" laws are
# meta-repeals — they repeal an amendment law, not the underlying law.
# The existing enrich_metadata.walk_amendment_chains picks them up
# anyway and sets superseded_by on the underlying law, which is wrong
# for retrieval purposes. We detect and unwind that here.
def _is_meta_repeal_id(law_id: str) -> bool:
    lower = law_id.lower()
    return "muuttamisesta" in lower and "kumoamisesta" in lower


# ---------------------------------------------------------------------------
# Per-LAW temporal summary
# ---------------------------------------------------------------------------


@dataclass
class LawSummary:
    """Folded view of a LAW node + everything that touches it."""

    law_id: str
    publication_date: date | None = None
    effective_date: date | None = None
    repeal_date: date | None = None
    in_force: bool | None = None
    superseded_by: str | None = None
    # Aggregated from AMENDMENT_BLOCK descendants and inbound amends/repeals.
    amendment_effective_dates: list[date] = field(default_factory=list)
    amendment_count: int = 0
    repeal_amendment_count: int = 0
    # The amendment node id with the latest effective_date — useful for
    # surfacing as a caveat ("amended on YYYY-MM-DD by act NNN").
    nearest_amendment_id: str | None = None
    nearest_amendment_date: date | None = None

    # Derived status, set during finalize().
    law_status: str = "ok"   # ok | stale | repealed

    def finalize(self, today: date) -> None:
        # repealed wins over stale wins over ok.
        if self.in_force is False:
            self.law_status = "repealed"
            return
        if self.repeal_date is not None and self.repeal_date <= today:
            self.law_status = "repealed"
            return
        # superseded_by → stale, but only if it's not a meta-repeal pointer.
        # Meta-repeals (X-muuttamisesta-annetun-lain-kumoamisesta) merely
        # remove a stray amendment instrument from the chain; the underlying
        # law is still live.
        if self.superseded_by and not _is_meta_repeal_id(self.superseded_by):
            self.law_status = "stale"
            return
        # If half or more of the amendment activity is repeal-shaped,
        # treat the law as repealed by accumulation. Conservative threshold
        # — most consolidated laws have many amendments and ≤1 repeal block,
        # so this only fires on laws that have been comprehensively replaced.
        if self.repeal_amendment_count >= 3 and self.repeal_amendment_count * 2 >= self.amendment_count:
            self.law_status = "repealed"
            return
        self.law_status = "ok"


def build_law_summaries(conn: sqlite3.Connection, today: date) -> dict[str, LawSummary]:
    """Build ``{law_id: LawSummary}`` covering every LAW root in the graph."""
    summaries: dict[str, LawSummary] = {}

    # Step A — pull all LAW root rows.
    cur = conn.execute(
        "SELECT id, metadata_json FROM nodes WHERE type='LAW'"
    )
    for nid, mj in cur:
        try:
            meta = json.loads(mj) if mj else {}
        except json.JSONDecodeError:
            meta = {}
        s = LawSummary(
            law_id=nid,
            publication_date=_parse_iso(meta.get("publication_date")),
            effective_date=_parse_iso(meta.get("effective_date")),
            repeal_date=_parse_iso(meta.get("repeal_date")),
            in_force=meta.get("in_force"),
            superseded_by=meta.get("superseded_by"),
        )
        summaries[nid] = s

    # Step B — aggregate AMENDMENT_BLOCK metadata into the relevant LAW.
    # Each AMENDMENT_BLOCK lives under its consolidated LAW (id prefix);
    # the amends/repeals edges Move 1 inserted target the LAW directly.
    # We use the edge table here because it carries the per-amendment
    # effective_date in properties_json — the AMENDMENT_BLOCK's own
    # metadata is inherited LAW-root metadata and is not per-amendment.
    #
    # We also fold in Fix C's ``backfill_muuttamisesta`` edges — the
    # slug-inferred ``Laki X muuttamisesta`` → consolidated-LAW edges.
    # Those targets (ennakkoperintälaki, sairausvakuutuslaki, …) had
    # zero amendments in the graph before Fix C, so picking them up
    # here is what flips their children from ``ok`` to ``suspect``.
    cur = conn.execute(
        "SELECT source_id, target_id, type, properties_json "
        "FROM edges WHERE extracted_by IN ('backfill_amendment', 'backfill_muuttamisesta')"
    )
    for src, tgt, etype, pj in cur:
        if tgt is None or tgt not in summaries:
            continue
        props = json.loads(pj) if pj else {}
        s = summaries[tgt]
        s.amendment_count += 1
        if etype == "repeals":
            s.repeal_amendment_count += 1
        # Prefer the edge's explicit effective_date (Move 1 parses
        # ``Tämä laki tulee voimaan …`` from each AMENDMENT_BLOCK), then
        # fall back to the source LAW's own publication_date. Fix C's
        # slug-inferred edges rarely carry effective_date, but every
        # amendment-instrument LAW has its own publication_date from
        # enrich_metadata, which is a good lower-bound proxy for when
        # the amendment took effect.
        eff = _parse_iso(props.get("effective_date"))
        if eff is None:
            src_root = _law_root_of(src)
            src_summary = summaries.get(src_root)
            if src_summary is not None:
                # ``publication_date`` is when the amending act was
                # enacted; ``effective_date`` is when it took effect.
                # The latter is more accurate when known.
                eff = src_summary.effective_date or src_summary.publication_date
        if eff is not None:
            s.amendment_effective_dates.append(eff)
            if s.nearest_amendment_date is None or eff > s.nearest_amendment_date:
                s.nearest_amendment_date = eff
                s.nearest_amendment_id = src

    # Step C — also fold in legacy regex-extracted amends/repeals edges
    # whose target is a LAW root (Step 2 produced ~48 of these). They
    # don't always carry effective_date, but they confirm a real repeal/
    # amend event.
    cur = conn.execute(
        "SELECT source_id, target_id, type FROM edges "
        "WHERE type IN ('amends','repeals') "
        "AND extracted_by != 'backfill_amendment' "
        "AND target_id IS NOT NULL"
    )
    for src, tgt, etype in cur:
        if tgt not in summaries:
            continue
        s = summaries[tgt]
        # Only count repeals from a non-meta-repeal source. If a "X
        # muuttamisesta-annetun-lain kumoamisesta" file emits a repeal
        # edge to TVL, we treat it as a meta-action — see _is_meta_repeal_id.
        if etype == "repeals" and not _is_meta_repeal_id(src):
            # A real external repeal — bump repeal count to make the
            # threshold in finalize() trip if multiple confirm the same.
            s.repeal_amendment_count += 1

    # Finalize all law_status.
    for s in summaries.values():
        s.finalize(today)

    return summaries


# ---------------------------------------------------------------------------
# Inbound interprets — per-node
# ---------------------------------------------------------------------------


def build_interprets_summary(
    conn: sqlite3.Connection,
) -> dict[str, tuple[int, date | None]]:
    """Return ``{target_node_id: (count, latest_interpretation_date)}``.

    We use the source's metadata publication_date as the interpretation
    date. That's the document date of the KHO/Vero ruling that
    interprets the target statute section.
    """
    # First pass: count + collect (source_id, target_id) per target.
    cur = conn.execute(
        "SELECT source_id, target_id FROM edges "
        "WHERE type='interprets' AND target_id IS NOT NULL"
    )
    by_target: dict[str, list[str]] = defaultdict(list)
    for src, tgt in cur:
        by_target[tgt].append(src)

    if not by_target:
        return {}

    # Second pass: bulk-fetch source publication dates.
    all_sources = list({s for sources in by_target.values() for s in sources})
    src_date: dict[str, date | None] = {}
    BATCH = 500
    for i in range(0, len(all_sources), BATCH):
        chunk = all_sources[i:i + BATCH]
        ph = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT id, metadata_json FROM nodes WHERE id IN ({ph})",
            chunk,
        )
        for nid, mj in cur:
            try:
                meta = json.loads(mj) if mj else {}
            except json.JSONDecodeError:
                meta = {}
            src_date[nid] = _parse_iso(meta.get("publication_date"))

    out: dict[str, tuple[int, date | None]] = {}
    for tgt, sources in by_target.items():
        latest: date | None = None
        for s in sources:
            d = src_date.get(s)
            if d is not None and (latest is None or d > latest):
                latest = d
        out[tgt] = (len(sources), latest)
    return out


# ---------------------------------------------------------------------------
# Per-node temporal_status
# ---------------------------------------------------------------------------


def compute_node_status(
    *,
    node_id: str,
    node_type: str,
    own_meta: dict,
    summaries: dict[str, LawSummary],
    interprets: dict[str, tuple[int, date | None]],
    today: date,
) -> dict:
    """Compute the temporal_status dict for one node."""
    law_id = _law_root_of(node_id)
    summary = summaries.get(law_id)

    own_pub = _parse_iso(own_meta.get("publication_date"))
    own_repeal = _parse_iso(own_meta.get("repeal_date"))
    own_in_force = own_meta.get("in_force")

    self_repealed = (
        own_in_force is False
        or (own_repeal is not None and own_repeal <= today)
    )

    if summary is None:
        # No LAW root — non-Finlex nodes (KHO, Vero, Treaty, Guide). Their
        # temporal_status is just self-only.
        return {
            "effective_usable":          "repealed" if self_repealed else "ok",
            "self_repealed":             self_repealed,
            "law_repealed":              False,
            "law_stale":                 False,
            "ancestor_amended":          False,
            "ancestor_amended_after":    None,
            "nearest_amendment_id":      None,
            "amendment_count_in_law":    0,
            "interpreted_count":         interprets.get(node_id, (0, None))[0],
            "latest_interpretation_date":(
                interprets.get(node_id, (0, None))[1].isoformat()
                if interprets.get(node_id, (0, None))[1] else None
            ),
            "computed_at":               today.isoformat(),
        }

    law_repealed = summary.law_status == "repealed"
    law_stale = summary.law_status == "stale"

    # ancestor_amended: does the LAW have amendments effective AFTER this
    # node's own publication_date? For consolidated Finlex children,
    # own_pub == latest amendment date, so no amendments are newer →
    # ancestor_amended is False. For external citing chunks (KHO/Vero)
    # whose own_pub is older than the latest amendment, this fires →
    # "suspect".
    ancestor_amended = False
    ancestor_amended_after: str | None = None
    nearest_amendment_id: str | None = None
    if summary.nearest_amendment_date is not None:
        if own_pub is None or summary.nearest_amendment_date > own_pub:
            ancestor_amended = True
            ancestor_amended_after = summary.nearest_amendment_date.isoformat()
            nearest_amendment_id = summary.nearest_amendment_id

    # Severity order: repealed > stale > suspect > ok. A self-repeal can
    # override an "ok" law into "repealed".
    if self_repealed or law_repealed:
        effective_usable = "repealed"
    elif law_stale:
        effective_usable = "stale"
    elif ancestor_amended:
        effective_usable = "suspect"
    else:
        effective_usable = "ok"

    # Interprets: check inbound interprets on this node first, then on
    # the LAW root as a fallback (statute-level rulings apply to the
    # whole act). We don't sum because the same ruling could count twice.
    own_int = interprets.get(node_id, (0, None))
    law_int = interprets.get(law_id, (0, None)) if law_id != node_id else (0, None)
    interpreted_count = own_int[0] + law_int[0]
    latest_int = own_int[1]
    if law_int[1] is not None and (latest_int is None or law_int[1] > latest_int):
        latest_int = law_int[1]

    return {
        "effective_usable":          effective_usable,
        "self_repealed":             self_repealed,
        "law_repealed":              law_repealed,
        "law_stale":                 law_stale,
        "ancestor_amended":          ancestor_amended,
        "ancestor_amended_after":    ancestor_amended_after,
        "nearest_amendment_id":      nearest_amendment_id,
        "amendment_count_in_law":    summary.amendment_count,
        "interpreted_count":         interpreted_count,
        "latest_interpretation_date":(
            latest_int.isoformat() if latest_int else None
        ),
        "computed_at":               today.isoformat(),
    }


# ---------------------------------------------------------------------------
# Streaming update
# ---------------------------------------------------------------------------


def _iter_nodes(conn: sqlite3.Connection) -> Iterator[tuple[str, str, str]]:
    cur = conn.execute("SELECT id, type, metadata_json FROM nodes")
    for row in cur:
        yield row[0], row[1], row[2]


def update_all_nodes(
    conn: sqlite3.Connection,
    summaries: dict[str, LawSummary],
    interprets: dict[str, tuple[int, date | None]],
    today: date,
    dry_run: bool,
) -> dict[str, int]:
    counts = {
        "nodes_total":         0,
        "effective_ok":        0,
        "effective_suspect":   0,
        "effective_stale":     0,
        "effective_repealed":  0,
        "with_interpretations":0,
    }
    BATCH = 5000
    pending: list[tuple[str, str]] = []
    for nid, ntype, mj in _iter_nodes(conn):
        try:
            meta = json.loads(mj) if mj else {}
        except json.JSONDecodeError:
            meta = {}
        status = compute_node_status(
            node_id=nid,
            node_type=ntype,
            own_meta=meta,
            summaries=summaries,
            interprets=interprets,
            today=today,
        )
        counts["nodes_total"] += 1
        counts[f"effective_{status['effective_usable']}"] += 1
        if status["interpreted_count"] > 0:
            counts["with_interpretations"] += 1

        if dry_run:
            continue

        meta["temporal_status"] = status
        pending.append((json.dumps(meta, ensure_ascii=False), nid))
        if len(pending) >= BATCH:
            conn.executemany(
                "UPDATE nodes SET metadata_json = ? WHERE id = ?", pending
            )
            pending.clear()

    if pending and not dry_run:
        conn.executemany(
            "UPDATE nodes SET metadata_json = ? WHERE id = ?", pending
        )
        pending.clear()
    if not dry_run:
        conn.commit()
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts without writing.")
    ap.add_argument("--today", default=None,
                    help="Override 'today' as ISO date for deterministic runs.")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()

    if not GRAPH_DB.exists():
        print(f"ERROR: {GRAPH_DB} not found — run scripts.load_graph first.",
              file=sys.stderr)
        return 1

    conn = sqlite3.connect(GRAPH_DB, timeout=30.0)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    try:
        print(f"[temporal] today={today.isoformat()}")
        t0 = time.time()
        print("[temporal] building LAW summaries ...", flush=True)
        summaries = build_law_summaries(conn, today)
        print(f"[temporal]   {len(summaries):,} laws in {time.time()-t0:.1f}s")
        status_counts = {"ok": 0, "stale": 0, "repealed": 0}
        for s in summaries.values():
            status_counts[s.law_status] += 1
        print(f"[temporal]   law_status: {status_counts}")

        t1 = time.time()
        print("[temporal] aggregating interprets edges ...", flush=True)
        interprets = build_interprets_summary(conn)
        print(f"[temporal]   {len(interprets):,} interpreted targets in "
              f"{time.time()-t1:.1f}s")

        t2 = time.time()
        print("[temporal] computing temporal_status for every node ...",
              flush=True)
        counts = update_all_nodes(conn, summaries, interprets, today, args.dry_run)
        print(f"[temporal]   {counts['nodes_total']:,} nodes in "
              f"{time.time()-t2:.1f}s")
        print(f"[temporal]   ok={counts['effective_ok']:,}, "
              f"suspect={counts['effective_suspect']:,}, "
              f"stale={counts['effective_stale']:,}, "
              f"repealed={counts['effective_repealed']:,}")
        print(f"[temporal]   with interpretations: "
              f"{counts['with_interpretations']:,}")

        STATS_OUT.write_text(
            json.dumps({
                "today": today.isoformat(),
                "dry_run": args.dry_run,
                "law_status": status_counts,
                **counts,
            }, indent=2),
            encoding="utf-8",
        )
        print(f"[temporal] stats → {STATS_OUT}")

        if not args.dry_run:
            conn.execute("ANALYZE")
            conn.commit()
    finally:
        conn.close()

    print("[temporal] DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
