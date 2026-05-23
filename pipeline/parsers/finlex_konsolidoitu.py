"""Parser for Finlex säädöskokoelma directories.

Source: data/finlex/Laki (säädöskokoelma)/ and data/finlex/Asetus (säädöskokoelma)/

These files contain *consolidated* legal text with the cleanest structure in
the corpus:
    <h1>{Law title}</h1>                  -> LAW
    <h2>1 luku Yleiset säännökset</h2>   -> CHAPTER
    <h3>1 § Adoption tarkoitus</h3>       -> SECTION (§)
    <p>...</p>  (one or more)             -> SUBSECTION (momentti)
    <ul><li>1) ...</li>...</ul>           -> ITEM (kohta)

Subsection numbering: paragraphs inside a § are momentit, numbered 1..N in
document order. Lists nested inside a paragraph are ITEMs of that subsection.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

from bs4 import Tag

from ..chunks import SectionBundle
from ..html_utils import (
    CHAPTER_RE,
    SECTION_RE,
    SECTION_TITLE_RE,
    get_text,
    iter_block_children,
    looks_like_item_prefix,
    normalize_ws,
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


# Subcorpus codes ------------------------------------------------------------
SUBCORPUS_BY_DIR = {
    "Laki (säädöskokoelma)": "laki_skk",
    "Asetus (säädöskokoelma)": "asetus_skk",
}


def detect_subcorpus(rel_path: str) -> str | None:
    """Return the subcorpus code if rel_path is inside a known säädöskokoelma dir."""
    parts = rel_path.split(os.sep)
    for p in parts:
        if p in SUBCORPUS_BY_DIR:
            return SUBCORPUS_BY_DIR[p]
    return None


def _extract_dom_id(tag: Tag) -> str | None:
    raw = tag.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _items_from_list(
    list_tag: Tag,
    *,
    parent_id: str,
    source: str,
    subcorpus: str,
    source_file: str,
    law_root: str,
    order_start: int,
) -> List[Node]:
    """Convert a <ul> or <ol> into a list of ITEM nodes.

    IDs are derived from the global position under the parent (order_start +
    list index) so multiple lists under the same parent cannot collide.
    The doc's natural marker (e.g. "1)", "a)") is preserved on `label`.
    """
    items: List[Node] = []
    for i, li in enumerate(list_tag.find_all("li", recursive=False), start=1):
        text = get_text(li)
        if not text:
            continue
        natural = looks_like_item_prefix(text)
        order = order_start + i - 1
        item = Node(
            id=child_id(parent_id, "i", str(order)),
            type=ITEM,
            text=text,
            parent_id=parent_id,
            order=order,
            label=natural or str(order),
            source=source,
            source_subcorpus=subcorpus,
            source_file=source_file,
            source_html_id=_extract_dom_id(li),
            law_id=law_root,
        )
        items.append(item)
    return items


def _subsection_from_p(
    p_tag: Tag,
    *,
    section_id: str,
    source: str,
    subcorpus: str,
    source_file: str,
    law_root: str,
    momentti_n: int,
    section_item_offset: int,
) -> Tuple[Node | None, List[Node]]:
    """Build a SUBSECTION node from a <p> tag, plus any embedded list items.

    `section_item_offset` is how many items are already attached *directly* to
    the SECTION; new items that fall through to the section (because their
    parent <p> had no text) start numbering after that offset.

    Returns (subsection_node, [item_nodes]). Either may be None / empty.
    """
    # Pull out any nested <ul>/<ol> first; remove them so the SUBSECTION
    # text doesn't duplicate the bullet content.
    list_tags: List[Tag] = []
    for lt in p_tag.find_all(["ul", "ol"], recursive=False):
        list_tags.append(lt.extract())
    text = get_text(p_tag)
    sub_node: Node | None = None
    item_nodes: List[Node] = []
    if text:
        sub_id = child_id(section_id, "m", str(momentti_n))
        sub_type = DEFINITION if looks_like_definition(text) else SUBSECTION
        sub_node = Node(
            id=sub_id,
            type=sub_type,
            text=text,
            parent_id=section_id,
            order=momentti_n,
            label=f"{momentti_n} momentti",
            source=source,
            source_subcorpus=subcorpus,
            source_file=source_file,
            source_html_id=_extract_dom_id(p_tag),
            law_id=law_root,
        )
        parent_for_items = sub_id
        order_start = 1  # items within a subsection start at 1 (parent differs)
    else:
        parent_for_items = section_id
        order_start = section_item_offset + 1

    for lt in list_tags:
        nodes = _items_from_list(
            lt,
            parent_id=parent_for_items,
            source=source,
            subcorpus=subcorpus,
            source_file=source_file,
            law_root=law_root,
            order_start=order_start,
        )
        item_nodes.extend(nodes)
        order_start += len(nodes)
    return sub_node, item_nodes


def _parse_section(
    children: list[Tag],
    start: int,
    *,
    chapter_id: str | None,
    section_heading: Tag,
    source: str,
    subcorpus: str,
    source_file: str,
    law_root: str,
    section_order: int,
    disambiguate,
) -> Tuple[Node, List[Node], SectionBundle, int]:
    """Parse one § section starting at children[start] (the heading)."""
    text = get_text(section_heading)
    parsed = parse_section_heading(text)
    if parsed:
        marker, title = parsed
    else:
        marker, title = (str(section_order), text)

    sec_parent = chapter_id or law_root
    sec_id = child_id(sec_parent, "s", disambiguate(sec_parent, "s", marker))
    sec_label = f"{marker} §"
    sec_node = Node(
        id=sec_id,
        type=SECTION,
        text="",  # body lives on children
        parent_id=sec_parent,
        order=section_order,
        label=sec_label,
        title=title or None,
        source=source,
        source_subcorpus=subcorpus,
        source_file=source_file,
        source_html_id=_extract_dom_id(section_heading),
        law_id=law_root,
    )

    members: List[Node] = []
    i = start + 1
    momentti_n = 0
    section_item_count = 0  # items attached directly to the SECTION (not a SUBSECTION)
    while i < len(children):
        ch = children[i]
        # Stop when we hit the next h2/h3 or the next h1 (new law).
        if ch.name in {"h1", "h2", "h3"}:
            # Could be a § with text="2 § …" but coded as h3 — fine, we'll
            # treat any h3 as a new section boundary.
            break
        if ch.name == "p":
            momentti_n += 1
            sub_node, items = _subsection_from_p(
                ch,
                section_id=sec_id,
                source=source,
                subcorpus=subcorpus,
                source_file=source_file,
                law_root=law_root,
                momentti_n=momentti_n,
                section_item_offset=section_item_count,
            )
            if sub_node:
                members.append(sub_node)
            else:
                # Items fell through to the section directly.
                section_item_count += len(items)
            members.extend(items)
        elif ch.name in {"ul", "ol"}:
            items = _items_from_list(
                ch,
                parent_id=sec_id,
                source=source,
                subcorpus=subcorpus,
                source_file=source_file,
                law_root=law_root,
                order_start=section_item_count + 1,
            )
            section_item_count += len(items)
            members.extend(items)
        elif ch.name == "h4":
            # Inline amendment marker inside a section (rare in skk files).
            amt_text = get_text(ch)
            if amt_text:
                amt = Node(
                    id=child_id(sec_id, "a", slug(amt_text, max_len=30) or str(i)),
                    type=AMENDMENT_BLOCK,
                    text=amt_text,
                    parent_id=sec_id,
                    order=len(members) + 1,
                    label=amt_text,
                    source=source,
                    source_subcorpus=subcorpus,
                    source_file=source_file,
                    law_id=law_root,
                )
                members.append(amt)
        # else: silently skip <i>, <a>, divs we don't care about — they're
        # captured through parent <p> text already.
        i += 1

    # Build the SectionBundle head text: e.g. "5 § Adoption tarkoitus"
    head = sec_label
    if title:
        head = f"{sec_label} {title}"
    bundle = SectionBundle(section=sec_node, head_text=head, members=members)
    return sec_node, members, bundle, i


def parse(path: str, rel_path: str) -> Tuple[List[Node], List[SectionBundle]]:
    """Parse one säädöskokoelma HTML file.

    Returns (all_nodes, section_bundles_ready_for_packing).
    """
    subcorpus = detect_subcorpus(rel_path) or "laki_skk"
    source = "finlex"
    with open(path, "rb") as f:
        raw = f.read()
    soup = parse_html(raw)
    body = soup.body or soup

    # Find the law title (first <h1>) and build the LAW node.
    h1 = body.find("h1")
    title = get_text(h1) if h1 else Path(rel_path).stem
    law_root = law_id(source, subcorpus, doc_slug_from_path(rel_path))

    nodes: List[Node] = []
    bundles: List[SectionBundle] = []
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
    nodes.append(law_node)

    children = list(iter_block_children(body))
    n = len(children)
    i = 0
    current_chapter_id: str | None = None
    chapter_order = 0
    section_order = 0

    # Disambiguator for repeating markers under the same parent (rare in
    # säädöskokoelma but possible with structural defects).
    used_markers: dict[tuple[str, str], int] = {}

    def disambiguate(parent: str, kind: str, marker: str) -> str:
        key = (parent, kind + "/" + marker)
        used_markers[key] = used_markers.get(key, 0) + 1
        if used_markers[key] == 1:
            return marker
        return f"{marker}-{used_markers[key]}"

    # Skip leading preamble (text before first heading) — capture as TITLE node.
    while i < n and children[i].name not in {"h1", "h2", "h3"}:
        # Look for a preamble line like "Eduskunnan päätöksen mukaisesti säädetään:"
        if children[i].name == "p":
            preamble = get_text(children[i])
            if preamble:
                t = Node(
                    id=child_id(law_root, "t", "preamble"),
                    type=TITLE,
                    text=preamble,
                    parent_id=law_root,
                    order=0,
                    label="preamble",
                    source=source,
                    source_subcorpus=subcorpus,
                    source_file=rel_path,
                    law_id=law_root,
                )
                nodes.append(t)
                # Preamble gets its own tiny bundle so it ends up in chunks.
                bundles.append(SectionBundle(section=t, head_text=title, members=[]))
        i += 1

    # If the file's only heading is the h1 we just consumed, treat the
    # whole body text as a single SECTION-equivalent. (Some short statutes
    # have no chapter or § subdivision at all.)

    while i < n:
        ch = children[i]
        if ch.name == "h1":
            # A second h1 means we hit the start of the body again — skip.
            i += 1
            continue
        if ch.name == "h2":
            txt = get_text(ch)
            ch_parsed = parse_chapter_heading(txt)
            chapter_order += 1
            if ch_parsed:
                ch_num, ch_title = ch_parsed
            else:
                ch_num, ch_title = (str(chapter_order), txt)
            cid = child_id(law_root, "c", disambiguate(law_root, "c", ch_num))
            chapter_node = Node(
                id=cid,
                type=CHAPTER,
                text="",
                parent_id=law_root,
                order=chapter_order,
                label=f"{ch_num} luku" if not txt.lower().startswith("muutossäädös") else txt,
                title=ch_title or None,
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
        if ch.name == "h3":
            section_order += 1
            sec_node, members, bundle, new_i = _parse_section(
                children,
                i,
                chapter_id=current_chapter_id,
                section_heading=ch,
                source=source,
                subcorpus=subcorpus,
                source_file=rel_path,
                law_root=law_root,
                section_order=section_order,
                disambiguate=disambiguate,
            )
            nodes.append(sec_node)
            nodes.extend(members)
            bundles.append(bundle)
            i = new_i
            continue
        if ch.name == "h4":
            # Top-level amendment block (rare in skk; common in /Laki/).
            txt = get_text(ch)
            if not txt:
                i += 1
                continue
            amt_marker = slug(txt, max_len=30) or str(i)
            amt_id = child_id(law_root, "a", disambiguate(law_root, "a", amt_marker))
            amt = Node(
                id=amt_id,
                type=AMENDMENT_BLOCK,
                text="",
                parent_id=law_root,
                order=i,
                label=txt,
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=law_root,
            )
            nodes.append(amt)
            # Gather following <p> until next heading as the amendment text.
            j = i + 1
            parts: List[str] = []
            while j < n and children[j].name not in {"h1", "h2", "h3", "h4"}:
                if children[j].name == "p":
                    t = get_text(children[j])
                    if t:
                        parts.append(t)
                j += 1
            amt.text = "\n".join(parts)
            # Emit as a 1-member bundle so amendments end up in chunks too.
            bundles.append(SectionBundle(
                section=amt,
                head_text=f"{title} — muutos {txt}",
                members=[],
            ))
            i = j
            continue
        # Floating <p> at root level (outside any §) — attach to law.
        if ch.name == "p":
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

    # If we found zero sections, fall back to one bundle covering the law
    # title + any orphan paragraphs we just attached — so the file still
    # produces at least one chunk.
    if not bundles:
        orphan_p_nodes = [n_ for n_ in nodes if n_.type in {SUBSECTION, DEFINITION} and n_.parent_id == law_root]
        if orphan_p_nodes or title:
            bundles.append(SectionBundle(
                section=law_node,
                head_text=title,
                members=orphan_p_nodes,
            ))

    return nodes, bundles
