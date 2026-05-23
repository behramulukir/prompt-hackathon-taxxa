"""B2.1 — Structural edges.

Emits one `parent_of` edge per non-root node, derived from the `parent_id`
already stored in `output/nodes.jsonl`. Single direction only — the graph
store (Step 4) supports bidirectional traversal, so storing `child_of`
would double row count without adding information.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from src.models import Edge


def build_structural_edges(nodes_jsonl: Path) -> Iterator[Edge]:
    """Stream parent_of edges from a nodes.jsonl file.

    Roots (parent_id is None) are skipped — they have no parent to point at.
    """
    with nodes_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            parent_id = d.get("parent_id")
            if not parent_id:
                continue
            yield Edge(
                source_id=parent_id,
                target_id=d["id"],
                target_ref=d["id"],
                type="parent_of",
                confidence=1.0,
                extracted_by="structural",
            )
