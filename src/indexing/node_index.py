"""Compact in-memory node index for embedding-time lookups.

Loads only the fields needed for text composition and VectorRecord payload
construction, keeping the working set small enough to fit alongside the
embedding pass on a laptop.

Built from ``nodes_enriched.jsonl`` when available, falling back to
``nodes.jsonl`` (in which case the metadata-derived fields stay None and the
text composition simply omits the optional clauses).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(slots=True)
class NodeIdxEntry:
    parent_id: str | None
    node_type: str
    source: str
    source_subcorpus: str
    label: str | None
    title: str | None
    in_force: bool | None
    authority_rank: int | None
    usable: bool | None
    language: str | None
    publication_date: str | None  # kept as ISO string to skip date-parsing overhead


def _stream(path: Path) -> Iterator[dict]:
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def build_node_index(nodes_path: Path) -> dict[str, NodeIdxEntry]:
    """Stream nodes.jsonl / nodes_enriched.jsonl into a compact id->entry dict.

    On a 1.97M-node corpus this peaks around 1.5-2 GB; cheaper than holding
    the raw 1.5 GB JSONL parsed.
    """
    out: dict[str, NodeIdxEntry] = {}
    for n in _stream(nodes_path):
        meta = n.get("metadata") or {}
        out[n["id"]] = NodeIdxEntry(
            parent_id=n.get("parent_id"),
            node_type=n["type"],
            source=n["source"],
            source_subcorpus=n["source_subcorpus"],
            label=n.get("label"),
            title=n.get("title"),
            in_force=meta.get("in_force"),
            authority_rank=meta.get("authority_rank"),
            usable=meta.get("usable"),
            language=meta.get("language"),
            publication_date=meta.get("publication_date"),
        )
    return out


def walk_to_root(node_id: str, index: dict[str, NodeIdxEntry]) -> list[NodeIdxEntry]:
    """Return entries from the node up to its root (root last). Stops if a
    parent_id is missing from the index (corrupt or partial) to avoid loops.
    """
    seen: set[str] = set()
    chain: list[NodeIdxEntry] = []
    cur = node_id
    while cur and cur not in seen:
        seen.add(cur)
        entry = index.get(cur)
        if entry is None:
            break
        chain.append(entry)
        cur = entry.parent_id or ""
    return chain
