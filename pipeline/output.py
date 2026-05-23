"""JSONL writers + the hierarchy index."""
from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Iterable

from .nodes import Node
from .chunks import Chunk


def write_nodes_jsonl(nodes: Iterable[Node], path: str) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for node in nodes:
            f.write(json.dumps(node.to_dict(), ensure_ascii=False))
            f.write("\n")
            n += 1
    return n


def write_chunks_jsonl(chunks: Iterable[Chunk], path: str) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False))
            f.write("\n")
            n += 1
    return n


def build_hierarchy_index(nodes: Iterable[Node]) -> dict:
    """Group nodes by law_id and bucket them by type.

    Output shape:
      {
        law_id: {
          "title": "...",
          "source": "...",
          "chapters":    [chapter_id, ...],
          "sections":    [section_id, ...],
          "subsections": [...],
          "items":       [...],
        }
      }
    """
    by_law: dict[str, dict] = {}
    for node in nodes:
        lid = node.law_id
        if not lid:
            continue
        bucket = by_law.setdefault(lid, {
            "title": None,
            "source": node.source,
            "source_subcorpus": node.source_subcorpus,
            "source_file": node.source_file,
            "chapters": [],
            "sections": [],
            "subsections": [],
            "items": [],
            "amendments": [],
            "definitions": [],
            "other": [],
        })
        if node.type in ("LAW", "GUIDE", "CASE", "TREATY"):
            bucket["title"] = node.title or node.label or node.id
            bucket["source"] = node.source
        elif node.type == "CHAPTER":
            bucket["chapters"].append(node.id)
        elif node.type == "SECTION":
            bucket["sections"].append(node.id)
        elif node.type == "SUBSECTION":
            bucket["subsections"].append(node.id)
        elif node.type == "ITEM":
            bucket["items"].append(node.id)
        elif node.type == "AMENDMENT_BLOCK":
            bucket["amendments"].append(node.id)
        elif node.type == "DEFINITION":
            bucket["definitions"].append(node.id)
        else:
            bucket["other"].append(node.id)
    return by_law


def write_hierarchy_json(nodes: Iterable[Node], path: str) -> int:
    idx = build_hierarchy_index(nodes)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    return len(idx)
