"""Parser for Finlex Tuloverosopimukset (tax treaties).

Each country folder contains 1+ HTML files. They're long but have minimal
HTML structure (h1 + many <p>, sometimes a <h2> or <h3>). Strategy: collect
all <p> under each (h2|h3) heading as one SectionBundle; floating paragraphs
before the first heading belong to a synthetic 'preamble' bundle.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from bs4 import Tag

from ..chunks import SectionBundle
from ..html_utils import get_text, iter_block_children, parse_html
from ..nodes import (
    SECTION,
    SUBSECTION,
    TREATY,
    ITEM,
    Node,
    child_id,
    doc_slug_from_path,
    law_id,
    slug,
)


def _extract_dom_id(tag: Tag) -> str | None:
    raw = tag.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def parse(path: str, rel_path: str) -> Tuple[List[Node], List[SectionBundle]]:
    source = "finlex"
    subcorpus = "treaty"
    with open(path, "rb") as f:
        raw = f.read()
    soup = parse_html(raw)
    body = soup.body or soup

    h1 = body.find("h1")
    title = get_text(h1) if h1 else Path(rel_path).stem
    # Country folder gives us a stable id prefix; the hash suffix in
    # doc_slug_from_path protects against very long, near-identical names.
    parts = Path(rel_path).parts
    country = parts[-2] if len(parts) >= 2 else "unknown"
    root_id = law_id(source, subcorpus, doc_slug_from_path(rel_path))

    treaty_node = Node(
        id=root_id,
        type=TREATY,
        text="",
        parent_id=None,
        order=0,
        label=country,
        title=title,
        source=source,
        source_subcorpus=subcorpus,
        source_file=rel_path,
        source_html_id=_extract_dom_id(h1) if h1 else None,
        law_id=root_id,
    )
    nodes: List[Node] = [treaty_node]
    bundles: List[SectionBundle] = []

    children = list(iter_block_children(body))

    # We walk the tree, grouping content by the nearest preceding heading.
    current_section: Node | None = None
    current_members: List[Node] = []
    sec_order = 0

    def flush():
        nonlocal current_section, current_members
        if current_section is None:
            return
        head_parts = [title]
        if current_section.label:
            head_parts.append(current_section.label)
        if current_section.title and current_section.title != current_section.label:
            head_parts.append(current_section.title)
        bundles.append(SectionBundle(
            section=current_section,
            head_text=" — ".join(p for p in head_parts if p),
            members=list(current_members),
        ))
        current_section = None
        current_members = []

    # Synthetic preamble section for paragraphs that appear before any heading.
    def start_preamble():
        nonlocal current_section
        current_section = Node(
            id=child_id(root_id, "s", "preamble"),
            type=SECTION,
            text="",
            parent_id=root_id,
            order=0,
            label="Johdanto",
            title=None,
            source=source,
            source_subcorpus=subcorpus,
            source_file=rel_path,
            law_id=root_id,
        )
        nodes.append(current_section)

    saw_first_heading_after_title = False
    for ch in children:
        name = ch.name or ""
        if name in {"h1"}:
            # Document title — already handled.
            continue
        if name in {"h2", "h3", "h4"}:
            flush()
            sec_order += 1
            txt = get_text(ch)
            marker = slug(txt, max_len=40) or str(sec_order)
            sec = Node(
                id=child_id(root_id, "s", marker),
                type=SECTION,
                text="",
                parent_id=root_id,
                order=sec_order,
                label=txt[:80],
                title=txt,
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=root_id,
            )
            nodes.append(sec)
            current_section = sec
            current_members = []
            saw_first_heading_after_title = True
            continue

        if name == "p":
            txt = get_text(ch)
            if not txt:
                continue
            if current_section is None:
                start_preamble()
            n_ = Node(
                id=child_id(current_section.id, "m", str(len(current_members) + 1)),
                type=SUBSECTION,
                text=txt,
                parent_id=current_section.id,
                order=len(current_members) + 1,
                label=f"{len(current_members)+1} kappale",
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=root_id,
            )
            nodes.append(n_)
            current_members.append(n_)
            continue

        if name in {"ul", "ol"}:
            if current_section is None:
                start_preamble()
            for k, li in enumerate(ch.find_all("li", recursive=False), start=1):
                li_text = get_text(li)
                if not li_text:
                    continue
                n_ = Node(
                    id=child_id(current_section.id, "i", f"{len(current_members)+1}-{k}"),
                    type=ITEM,
                    text=li_text,
                    parent_id=current_section.id,
                    order=len(current_members) + 1,
                    label=str(k),
                    source=source,
                    source_subcorpus=subcorpus,
                    source_file=rel_path,
                    source_html_id=_extract_dom_id(li),
                    law_id=root_id,
                )
                nodes.append(n_)
                current_members.append(n_)
            continue

        if name in {"div", "table", "section"}:
            txt = get_text(ch)
            if txt:
                if current_section is None:
                    start_preamble()
                n_ = Node(
                    id=child_id(current_section.id, "p", f"misc-{len(current_members)+1}"),
                    type=SUBSECTION,
                    text=txt,
                    parent_id=current_section.id,
                    order=len(current_members) + 1,
                    label=None,
                    source=source,
                    source_subcorpus=subcorpus,
                    source_file=rel_path,
                    source_html_id=_extract_dom_id(ch),
                    law_id=root_id,
                    metadata={"kind": name},
                )
                nodes.append(n_)
                current_members.append(n_)
            continue

    flush()

    if not bundles:
        bundles.append(SectionBundle(section=treaty_node, head_text=title, members=[]))

    return nodes, bundles
