"""Quality checks per step-1-plan.md §9.

Reject (i.e. report) if:
  - any node id is non-deterministic (UUID-like)
  - any node has a parent_id that doesn't exist in nodes.jsonl
  - any chunk references a node id that doesn't exist
  - any chunk has token_count > HARD_MAX
  - any ITEM-only chunk was split across multiple chunks (partial ITEM)
  - source_file is missing from any node (text not traceable to DOM)
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .chunks import HARD_MAX


UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def main(out_dir: str = "output") -> int:
    out = Path(out_dir)
    nodes_path = out / "nodes.jsonl"
    chunks_path = out / "chunks.jsonl"

    # First pass: collect node ids, parent ids, types.
    print("scanning nodes...")
    node_ids: set[str] = set()
    parent_map: dict[str, str | None] = {}
    type_count = Counter()
    no_source_file = 0
    uuid_ids = 0
    sample_uuid: list[str] = []
    with open(nodes_path, encoding="utf-8") as f:
        for line in f:
            n = json.loads(line)
            nid = n["id"]
            node_ids.add(nid)
            parent_map[nid] = n.get("parent_id")
            type_count[n["type"]] += 1
            if not n.get("source_file"):
                no_source_file += 1
            if UUID_RE.search(nid):
                uuid_ids += 1
                if len(sample_uuid) < 3:
                    sample_uuid.append(nid)
    print(f"  nodes: {len(node_ids):,}")
    print(f"  by type: {dict(type_count.most_common())}")

    # Parent linkage check.
    missing_parents = []
    for nid, pid in parent_map.items():
        if pid is None:
            continue
        if pid not in node_ids:
            missing_parents.append((nid, pid))
    print(f"  nodes with missing parent: {len(missing_parents)}")

    # Second pass: chunks.
    print("scanning chunks...")
    chunk_count = 0
    over_hard = 0
    chunk_with_missing_node = 0
    item_split_violations = 0
    item_appears_in: dict[str, list[str]] = defaultdict(list)
    by_section_chunks: dict[str, int] = defaultdict(int)
    with open(chunks_path, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            chunk_count += 1
            if c["token_count"] > HARD_MAX:
                over_hard += 1
            for ref in c["node_ids"]:
                if ref not in node_ids:
                    chunk_with_missing_node += 1
                    break
            by_section_chunks[c["section_id"]] += 1
            # Track ITEM-node membership across chunks.
            for nid in c["node_ids"]:
                # We can't tell type without joining; defer to next pass.
                item_appears_in[nid].append(c["chunk_id"])

    # ITEM split detection: any ITEM node appearing in 2+ chunks is a violation.
    print("checking for split ITEM nodes...")
    item_ids = set()
    with open(nodes_path, encoding="utf-8") as f:
        for line in f:
            n = json.loads(line)
            if n["type"] == "ITEM":
                item_ids.add(n["id"])
    for iid in item_ids:
        if len(item_appears_in.get(iid, [])) > 1:
            item_split_violations += 1

    sections_with_many_chunks = sorted(by_section_chunks.items(), key=lambda x: -x[1])[:5]

    print("\n=== REPORT ===")
    print(f"chunks total:                  {chunk_count:,}")
    print(f"chunks > HARD_MAX ({HARD_MAX}):    {over_hard}  (oversized=true allowed; see field)")
    print(f"chunks with missing node ref:  {chunk_with_missing_node}")
    print(f"ITEM nodes split across chunks:{item_split_violations}")
    print(f"nodes with missing parent:     {len(missing_parents)}")
    print(f"nodes without source_file:     {no_source_file}")
    print(f"UUID-like node ids:            {uuid_ids}")
    print(f"sections with most chunks:")
    for sid, n in sections_with_many_chunks:
        print(f"  {n:4d}  {sid}")

    # Exit non-zero if anything looks broken.
    fatal = (
        chunk_with_missing_node
        + item_split_violations
        + len(missing_parents)
        + uuid_ids
    )
    return 0 if fatal == 0 else 1


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:] or ["output"])))
