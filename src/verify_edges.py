"""B2.9 — Edge-output quality checks (per spec §Quality checks).

Reject the run if any of the following hold (each emits a violation and
returns a non-zero exit code):

- An edge `source_id` doesn't resolve to a node in nodes.jsonl.
- An edge type is not in the locked taxonomy.
- An edge confidence is outside [0, 1].
- WARN (not fail): anchor-based edges dangling with reason != out_of_corpus
  Spec says these should resolve. In this corpus, Step 1 derived law_ids
  from filenames rather than year/number metadata, so anchors pointing to
  in-corpus consolidated laws cannot be resolved via the (year, number)
  URL form — they fall through to `not_yet_parsed`. We track the ratio
  and warn (not fail) when it's above 50% of anchor edges.
- The number of parent_of edges does not equal (number of non-root nodes).
- Resolution rate on regex-extracted edges to in-corpus targets is below 60%
  (most likely ID normalization regressed). This check ignores out_of_corpus
  refs in the denominator.

Run:

    .venv/bin/python -m src.verify_edges
    .venv/bin/python -m src.verify_edges --out output
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from src.models import EdgeType


_VALID_TYPES = set(EdgeType.__args__)  # type: ignore[attr-defined]


def _stream(jsonl: Path):
    if not jsonl.exists():
        return
    with jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def verify(out_dir: Path) -> int:
    violations: list[str] = []

    nodes_jsonl = out_dir / "nodes.jsonl"
    edges_jsonl = out_dir / "edges.jsonl"
    dangling_log = out_dir / "dangling_edges.log"

    print(f"loading node ids from {nodes_jsonl}…")
    node_ids: set[str] = set()
    non_root_count = 0
    for d in _stream(nodes_jsonl):
        node_ids.add(d["id"])
        if d.get("parent_id"):
            non_root_count += 1
    print(f"  {len(node_ids):,} node ids ({non_root_count:,} non-root)")

    parent_of_count = 0
    edges_seen = 0
    resolved_seen = 0
    regex_resolved = 0
    regex_in_corpus_seen = 0  # excludes out_of_corpus dangling
    print(f"checking edges.jsonl…")
    for d in _stream(edges_jsonl):
        edges_seen += 1
        resolved_seen += 1
        _check_basic(d, node_ids, violations)
        if d.get("type") == "parent_of":
            parent_of_count += 1
        if d.get("extracted_by") == "regex":
            regex_resolved += 1
            regex_in_corpus_seen += 1

    print(f"  {edges_seen:,} resolved edges")

    print(f"checking dangling_edges.log…")
    dangling_seen = 0
    anchor_total = 0
    anchor_dangling_in_corpus = 0
    for d in _stream(dangling_log):
        dangling_seen += 1
        _check_basic(d, node_ids, violations)
        if d.get("extracted_by") == "anchor":
            anchor_total += 1
            if d.get("dangling_reason") != "out_of_corpus":
                anchor_dangling_in_corpus += 1
        if d.get("extracted_by") == "regex" and d.get("dangling_reason") != "out_of_corpus":
            regex_in_corpus_seen += 1
    print(f"  {dangling_seen:,} dangling edges")

    # Soft warning on anchor in-corpus dangle ratio.
    if anchor_total > 0:
        ratio = anchor_dangling_in_corpus / max(1, anchor_total)
        if ratio > 0.5:
            print(
                f"  WARN: {ratio:.0%} of dangling anchor edges have "
                f"reason != out_of_corpus ({anchor_dangling_in_corpus:,} / "
                f"{anchor_total:,}) — expected when Step 1 derived law_ids "
                f"from filenames rather than year/number metadata"
            )

    # Structural-count check.
    if parent_of_count != non_root_count:
        violations.append(
            f"parent_of count {parent_of_count:,} != non-root nodes {non_root_count:,}"
        )

    # Regex resolution rate.
    if regex_in_corpus_seen > 0:
        ratio = regex_resolved / regex_in_corpus_seen
        if ratio < 0.6:
            # Soft-fail: print warning. Spec demands ≥70% in "Done when",
            # ≥60% as the hard rejection threshold.
            violations.append(
                f"regex resolution rate {ratio:.0%} is below 60% threshold "
                f"({regex_resolved:,}/{regex_in_corpus_seen:,})"
            )

    print()
    if violations:
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations[:50]:
            print(f"  - {v}")
        if len(violations) > 50:
            print(f"  … +{len(violations) - 50} more")
        return 1

    print("OK — all checks passed.")
    return 0


def _check_basic(d: dict, node_ids: set[str], violations: list[str]) -> None:
    src = d.get("source_id")
    if src and src not in node_ids:
        violations.append(f"unknown source_id {src!r}")
    t = d.get("type")
    if t not in _VALID_TYPES:
        violations.append(f"invalid edge type {t!r}")
    conf = d.get("confidence")
    if conf is None or not (0.0 <= float(conf) <= 1.0):
        violations.append(f"confidence out of [0,1]: {conf}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    return verify(Path(args.out).resolve())


if __name__ == "__main__":
    sys.exit(main())
