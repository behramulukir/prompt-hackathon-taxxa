"""Parser for the /Laki/ and /Asetus/ Finlex directories.

These differ from säädöskokoelma in two ways:

  1. Big consolidated laws (Tuloverolaki.html, Rikoslaki.html, etc.) contain
     only the *amendment history* — h1=law title, h2="Muutossäädösten
     voimaantulo ja soveltaminen", then a long sequence of:
        <h4>30.4.1993/391:</h4>
        <p>Tämä laki tulee voimaan ...</p>
     Each h4 is one AMENDMENT_BLOCK whose body is the following <p>s.

  2. Small "Laki X muuttamisesta" files describe one amendment in isolation:
        <h1>Laki ... muuttamisesta</h1>
        <p>Eduskunnan päätöksen mukaisesti ...</p>
        <h3>10 §.</h3>    <- the amended section
        <p>...</p> ...

The strategy:
  - First h1 -> LAW node.
  - First h2 is treated as a CHAPTER (typically the amendment-history header).
  - All h4 inside the amendment-history chapter become AMENDMENT_BLOCK nodes
    with their body text.
  - h3 headings become § SECTIONs (the small-file shape).
  - Each amendment block + each § section is its own SectionBundle.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

from bs4 import Tag

from ..chunks import SectionBundle
from ..html_utils import (
    get_text,
    iter_block_children,
    parse_chapter_heading,
    parse_html,
    parse_section_heading,
)
from ..nodes import (
    AMENDMENT_BLOCK,
    CHAPTER,
    DEFINITION,
    ITEM,
    LAW,
    SECTION,
    SUBSECTION,
    TITLE,
    Node,
    child_id,
    doc_slug_from_path,
    law_id,
    looks_like_definition,
    slug,
)


SUBCORPUS_BY_DIR = {
    "Laki": "laki",
    "Asetus": "asetus",
}


def detect_subcorpus(rel_path: str) -> str | None:
    parts = rel_path.split(os.sep)
    # Reject säädöskokoelma — handled by the other parser.
    for p in parts:
        if "säädöskokoelma" in p.lower():
            return None
    for p in parts:
        if p in SUBCORPUS_BY_DIR:
            return SUBCORPUS_BY_DIR[p]
    return None


# Amendment date marker like "30.4.1993/391:" or "16.1.2026/15:"
AMENDMENT_HEADING_RE = re.compile(r"^\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*/\s*(\d+)\s*:?\s*$")


def _extract_dom_id(tag: Tag) -> str | None:
    raw = tag.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _gather_text_until(children: list[Tag], start: int, stop: set) -> Tuple[str, int]:
    """Concatenate <p> text from start until we hit a heading whose name is in stop.

    Returns (joined_text, index_after_last_consumed).
    """
    parts: list[str] = []
    j = start
    while j < len(children) and children[j].name not in stop:
        ch = children[j]
        if ch.name in {"p", "ul", "ol"}:
            t = get_text(ch)
            if t:
                parts.append(t)
        elif ch.name in {"div", "section"}:
            # Some files wrap text — just take its text content as one block.
            t = get_text(ch)
            if t:
                parts.append(t)
        j += 1
    return "\n".join(parts), j


def parse(path: str, rel_path: str) -> Tuple[List[Node], List[SectionBundle]]:
    subcorpus = detect_subcorpus(rel_path) or "laki"
    source = "finlex"
    with open(path, "rb") as f:
        raw = f.read()
    soup = parse_html(raw)
    body = soup.body or soup

    h1 = body.find("h1")
    title = get_text(h1) if h1 else Path(rel_path).stem
    law_root = law_id(source, subcorpus, doc_slug_from_path(rel_path))

    law_node = Node(
        id=law_root,
        type=LAW,
        text="",
        parent_id=None,
        order=0,
        label=None,
        title=title,
        source=source,
        source_subcorpus=subcorpus,
        source_file=rel_path,
        source_html_id=_extract_dom_id(h1) if h1 else None,
        law_id=law_root,
    )
    nodes: List[Node] = [law_node]
    bundles: List[SectionBundle] = []

    children = list(iter_block_children(body))
    n = len(children)
    i = 0
    current_chapter_id: str | None = None
    chapter_order = 0
    section_order = 0
    amendment_order = 0

    # Per-parent uniqueness: if "5 §" appears twice under the same chapter
    # (happens when amendment files restate a section across luvut without
    # a new <h2>), append a suffix to disambiguate.
    used_markers: dict[tuple[str, str], int] = {}

    def disambiguate(parent: str, kind: str, marker: str) -> str:
        key = (parent, kind + "/" + marker)
        used_markers[key] = used_markers.get(key, 0) + 1
        if used_markers[key] == 1:
            return marker
        return f"{marker}-{used_markers[key]}"

    while i < n:
        ch = children[i]
        name = ch.name

        if name == "h1":
            i += 1
            continue

        if name == "h2":
            txt = get_text(ch)
            chapter_order += 1
            parsed = parse_chapter_heading(txt)
            if parsed:
                ch_num, ch_title = parsed
            else:
                ch_num = str(chapter_order)
                ch_title = txt
            cid = child_id(law_root, "c", disambiguate(law_root, "c", ch_num))
            chapter_node = Node(
                id=cid,
                type=CHAPTER,
                text="",
                parent_id=law_root,
                order=chapter_order,
                label=txt if "muutoss" in txt.lower() else f"{ch_num} luku",
                title=ch_title or txt,
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=law_root,
            )
            nodes.append(chapter_node)
            current_chapter_id = cid
            i += 1
            continue

        if name == "h3":
            # Treat as a § SECTION.
            txt = get_text(ch)
            section_order += 1
            parsed = parse_section_heading(txt)
            if parsed:
                marker, sec_title = parsed
            else:
                marker, sec_title = str(section_order), txt
            sec_parent = current_chapter_id or law_root
            sec_id = child_id(sec_parent, "s", disambiguate(sec_parent, "s", marker))
            sec_node = Node(
                id=sec_id,
                type=SECTION,
                text="",
                parent_id=sec_parent,
                order=section_order,
                label=f"{marker} §",
                title=sec_title or None,
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=law_root,
            )
            nodes.append(sec_node)
            members: List[Node] = []
            j = i + 1
            momentti_n = 0
            while j < n and children[j].name not in {"h1", "h2", "h3", "h4"}:
                cj = children[j]
                if cj.name == "p":
                    txt_p = get_text(cj)
                    if txt_p:
                        momentti_n += 1
                        sub_id = child_id(sec_id, "m", str(momentti_n))
                        sub_type = DEFINITION if looks_like_definition(txt_p) else SUBSECTION
                        members.append(Node(
                            id=sub_id,
                            type=sub_type,
                            text=txt_p,
                            parent_id=sec_id,
                            order=momentti_n,
                            label=f"{momentti_n} momentti",
                            source=source,
                            source_subcorpus=subcorpus,
                            source_file=rel_path,
                            source_html_id=_extract_dom_id(cj),
                            law_id=law_root,
                        ))
                elif cj.name in {"ul", "ol"}:
                    for k, li in enumerate(cj.find_all("li", recursive=False), start=1):
                        li_text = get_text(li)
                        if not li_text:
                            continue
                        item_id = child_id(sec_id, "i", str(len(members) + 1))
                        members.append(Node(
                            id=item_id,
                            type=ITEM,
                            text=li_text,
                            parent_id=sec_id,
                            order=len(members) + 1,
                            label=str(k),
                            source=source,
                            source_subcorpus=subcorpus,
                            source_file=rel_path,
                            source_html_id=_extract_dom_id(li),
                            law_id=law_root,
                        ))
                j += 1
            nodes.extend(members)
            head = f"{title} — {marker} §"
            if sec_title:
                head = f"{head} {sec_title}"
            bundles.append(SectionBundle(section=sec_node, head_text=head, members=members))
            i = j
            continue

        if name == "h4":
            # Amendment block.
            txt = get_text(ch).rstrip(":")
            amendment_order += 1
            # Build amendment id from the date/number if it matches the pattern,
            # else fall back to a hashed slug.
            m = AMENDMENT_HEADING_RE.match(txt + ":")
            if m:
                marker = f"{m.group(1)}-{m.group(2)}"
            else:
                marker = slug(txt, max_len=30) or str(amendment_order)
            amt_parent = current_chapter_id or law_root
            amt_id = child_id(amt_parent, "a", disambiguate(amt_parent, "a", marker))
            body_text, new_i = _gather_text_until(children, i + 1, stop={"h1", "h2", "h3", "h4"})
            amt = Node(
                id=amt_id,
                type=AMENDMENT_BLOCK,
                text=body_text,
                parent_id=amt_parent,
                order=amendment_order,
                label=txt,
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=law_root,
            )
            nodes.append(amt)
            bundles.append(SectionBundle(
                section=amt,
                head_text=f"{title} — muutos {txt}",
                members=[],
            ))
            i = new_i
            continue

        if name == "p":
            # Floating <p>: attach to the law as a preamble-style SUBSECTION.
            txt = get_text(ch)
            if txt:
                p_id = child_id(law_root, "p", str(i))
                ptype = DEFINITION if looks_like_definition(txt) else SUBSECTION
                pn = Node(
                    id=p_id,
                    type=ptype,
                    text=txt,
                    parent_id=law_root,
                    order=i,
                    label=None,
                    source=source,
                    source_subcorpus=subcorpus,
                    source_file=rel_path,
                    source_html_id=_extract_dom_id(ch),
                    law_id=law_root,
                )
                nodes.append(pn)
            i += 1
            continue

        # Anything else: skip silently.
        i += 1

    # Files with no sections/amendments at all (rare) — emit one bundle so the
    # law title still produces a chunk.
    if not bundles:
        orphan = [n_ for n_ in nodes if n_.type in {SUBSECTION, DEFINITION} and n_.parent_id == law_root]
        if orphan or title:
            bundles.append(SectionBundle(
                section=law_node,
                head_text=title,
                members=orphan,
            ))

    return nodes, bundles
