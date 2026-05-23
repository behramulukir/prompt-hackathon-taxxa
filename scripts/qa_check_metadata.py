"""Quality check for the enrichment pass.

Reject the run if any of the following hold (per Step 3 §"Quality checks"):

- > 5% of nodes per source are missing ``publication_date``
- > 5% are missing ``authority`` (fixed mapping — should be ~0%)
- An ``amends``/``repeals`` edge exists but ``superseded_by`` was not
  propagated to the source root
- ``usable=true`` for a node with ``repeal_date < today``

Exit code 0 = pass, 1 = violations found. A summary report is always
written to ``findings/03_metadata_coverage.md`` regardless of pass/fail
(this is also the V3.1 deliverable).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NODES = PROJECT_ROOT / "output" / "nodes_enriched.jsonl"
EDGES = PROJECT_ROOT / "output" / "edges.jsonl"
FINDINGS = PROJECT_ROOT / "findings" / "03_metadata_coverage.md"

THRESHOLD = 0.05  # 5%


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    args = ap.parse_args()

    if not NODES.exists():
        print(f"ERROR: {NODES} not found — run scripts/enrich_metadata.py first.", file=sys.stderr)
        return 1

    today = date.fromisoformat(args.today) if args.today else date.today()

    per_source_total: dict[str, int] = defaultdict(int)
    per_source_pub: dict[str, int] = defaultdict(int)
    per_source_authority: dict[str, int] = defaultdict(int)
    superseded_roots: set[str] = set()
    bad_usable_repeal_in_past: int = 0
    nodes_with_repeal_in_past = 0

    print(f"reading {NODES}", flush=True)
    with NODES.open("r", encoding="utf-8") as f:
        for line in f:
            n = json.loads(line)
            src = n.get("source", "?")
            per_source_total[src] += 1
            md = n.get("metadata") or {}
            if md.get("publication_date"):
                per_source_pub[src] += 1
            if md.get("authority"):
                per_source_authority[src] += 1
            if md.get("superseded_by"):
                superseded_roots.add(n.get("law_id"))
            rd = _parse_date(md.get("repeal_date"))
            if rd is not None and rd <= today:
                nodes_with_repeal_in_past += 1
                if md.get("usable") is True:
                    bad_usable_repeal_in_past += 1

    violations: list[str] = []
    for src, total in per_source_total.items():
        if not total:
            continue
        missing_pub = total - per_source_pub[src]
        missing_auth = total - per_source_authority[src]
        if missing_pub / total > THRESHOLD:
            violations.append(
                f"{src}: {missing_pub}/{total} nodes missing publication_date "
                f"({missing_pub/total:.1%} > {THRESHOLD:.0%})"
            )
        if missing_auth / total > THRESHOLD:
            violations.append(
                f"{src}: {missing_auth}/{total} nodes missing authority "
                f"({missing_auth/total:.1%} > {THRESHOLD:.0%})"
            )

    if bad_usable_repeal_in_past:
        violations.append(
            f"{bad_usable_repeal_in_past} nodes have usable=true but repeal_date<=today"
        )

    # Edge → superseded_by propagation check. Mirror the runner's logic:
    # only edges that cross document roots produce supersession (a node
    # citing "muutettu lailla …" inside the *same* amendment file is a
    # self-reference and is intentionally skipped).
    unpropagated: list[str] = []
    if EDGES.exists():
        for e in _iter_jsonl(EDGES):
            if e.get("type") not in {"amends", "repeals"}:
                continue
            tgt = e.get("target_id")
            src = e.get("source_id")
            if not tgt or not src:
                continue
            tgt_root = "/".join(tgt.split("/")[:3])
            src_root = "/".join(src.split("/")[:3])
            if tgt_root == src_root:
                continue   # self-reference inside the same root, skipped by runner
            src_subcorpus = src_root.split("/")[1] if "/" in src_root else ""
            if not src_subcorpus.startswith(("laki", "asetus")):
                continue   # only statute subcorpora can amend; runner drops these
            if tgt_root not in superseded_roots:
                unpropagated.append(tgt_root)
                if len(unpropagated) >= 10:
                    break
        if unpropagated:
            violations.append(
                f"{len(unpropagated)}+ amends/repeals edges did not propagate to "
                f"superseded_by (sample: {unpropagated[:3]})"
            )

    _write_report(per_source_total, per_source_pub, per_source_authority,
                  nodes_with_repeal_in_past, bad_usable_repeal_in_past, violations, today)

    if violations:
        print("\nFAIL — violations:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1

    print("OK — all checks passed", flush=True)
    return 0


def _parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _write_report(total, pub, auth, repealed_in_past, usable_violations, violations, today):
    FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Metadata coverage (V3.1)",
        "",
        f"Run date: {today.isoformat()}.",
        "",
        "| source | nodes | publication_date | authority |",
        "|--------|-------|------------------|-----------|",
    ]
    for src in sorted(total):
        t = total[src]
        p = pub.get(src, 0)
        a = auth.get(src, 0)
        lines.append(f"| {src} | {t} | {p} ({p/t:.1%}) | {a} ({a/t:.1%}) |")

    lines += [
        "",
        f"Nodes with `repeal_date <= today`: {repealed_in_past}",
        f"Of those incorrectly marked `usable=true`: {usable_violations}",
        "",
    ]
    if violations:
        lines.append("## Violations")
        lines.append("")
        for v in violations:
            lines.append(f"- {v}")
    else:
        lines.append("All thresholds satisfied.")
    FINDINGS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report → {FINDINGS}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
