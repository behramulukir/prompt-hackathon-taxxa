"""Parser for Finlex KHO (Korkein hallinto-oikeus) precedents.

These are short, flat documents:
    <h1>KHO:1988-B-516</h1>
    <p>... ratkaisukuvaus / abstract ...</p>
    <p>... lainkohta ...</p>
    <p>... kommentti ...</p>

Each <p> is captured as a SUBSECTION; the case is a CASE root with a single
SectionBundle covering everything (cases are small enough to fit in one
chunk almost always).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from bs4 import Tag

from ..chunks import SectionBundle
from ..html_utils import get_text, iter_block_children, parse_html
from ..nodes import (
    CASE,
    SUBSECTION,
    Node,
    child_id,
    doc_slug_from_path,
    law_id,
)


def _extract_dom_id(tag: Tag) -> str | None:
    raw = tag.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def parse(path: str, rel_path: str) -> Tuple[List[Node], List[SectionBundle]]:
    source = "finlex"
    subcorpus = "kho"
    with open(path, "rb") as f:
        raw = f.read()
    soup = parse_html(raw)
    body = soup.body or soup

    h1 = body.find("h1")
    title = get_text(h1) if h1 else Path(rel_path).stem
    root_id = law_id(source, subcorpus, doc_slug_from_path(rel_path))

    case_node = Node(
        id=root_id,
        type=CASE,
        text="",
        parent_id=None,
        order=0,
        label=None,
        title=title,
        source=source,
        source_subcorpus=subcorpus,
        source_file=rel_path,
        source_html_id=_extract_dom_id(h1) if h1 else None,
        law_id=root_id,
    )
    nodes: List[Node] = [case_node]
    members: List[Node] = []

    for i, ch in enumerate(iter_block_children(body)):
        if ch.name in {"h1", "h2", "h3", "h4"}:
            continue
        if ch.name == "p":
            txt = get_text(ch)
            if not txt:
                continue
            n_ = Node(
                id=child_id(root_id, "p", str(len(members) + 1)),
                type=SUBSECTION,
                text=txt,
                parent_id=root_id,
                order=len(members) + 1,
                label=f"kappale {len(members)+1}",
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=root_id,
            )
            members.append(n_)
            nodes.append(n_)

    bundle = SectionBundle(section=case_node, head_text=title, members=members)
    return nodes, [bundle]
