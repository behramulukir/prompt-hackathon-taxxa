"""Parser for Vero (Verohallinto) tax-guidance HTML.

Source layout: data/vero/Syventävät vero-ohjeet/<bucket>/<doc-folder>/*.html
Where <bucket> is one of:
    Ohjeet                       (in-depth guidance — primary)
    Päätökset                    (decisions)
    Kannanotot                   (positions)
    Keskusverolautakunnan ennakkoratkaisut  (advance rulings)

HTML shape:
    <h1 class="taxxa-title">Title - vero.fi</h1>
    <h1 id="1-johdanto">1 Johdanto</h1>
    <p>...</p>
    <h3 id="2.1-...">2.1 ...</h3>
    <p>...</p>
    <ol><li>...</li>...</ol>
    <section class="example"><p>Esimerkki 1: ...</p></section>

The first <h1> is the document title; the second h1 onward are section
headings (note the document uses h1 for top-level numbered sections and h3
for sub-sections — no h2 in practice). We treat any h1 *after* the title as
CHAPTER, h2/h3/h4 as SECTION at decreasing depth. Each leaf heading section
becomes one SectionBundle.

Inline <section class="example"> blocks are captured as SUBSECTION nodes
with label "Esimerkki" so retrieval can boost or filter them.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

from bs4 import Tag

from ..chunks import SectionBundle
from ..html_utils import get_text, iter_block_children, parse_html
from ..nodes import (
    CHAPTER,
    DEFINITION,
    GUIDE,
    ITEM,
    SECTION,
    SUBSECTION,
    Node,
    child_id,
    doc_slug_from_path,
    law_id,
    looks_like_definition,
    slug,
)


SUBCORPUS_BY_BUCKET = {
    "Ohjeet": "vero_ohje",
    "Päätökset": "vero_paatos",
    "Kannanotot": "vero_kannanotto",
    "Keskusverolautakunnan ennakkoratkaisut": "vero_kvl",
}


def detect_subcorpus(rel_path: str) -> str | None:
    parts = rel_path.split(os.sep)
    if not any("vero" in p.lower() for p in parts[:2]):
        return None
    for p in parts:
        if p in SUBCORPUS_BY_BUCKET:
            return SUBCORPUS_BY_BUCKET[p]
    # Anything else under data/vero/ — generic.
    return "vero_other"


# Strip the trailing " - vero.fi" suffix from the document title.
_TITLE_SUFFIX_RE = re.compile(r"\s*-\s*vero\.fi\s*$", re.IGNORECASE)

# Detect a numbered heading like "2.1 Henkilön mediamaksun määrä".
NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.+?)\s*$")


def _extract_dom_id(tag: Tag) -> str | None:
    raw = tag.get("id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _is_doc_title(tag: Tag) -> bool:
    """True if the tag looks like the doc's main title (vs. a section)."""
    if tag.name != "h1":
        return False
    cls = tag.get("class") or []
    if "taxxa-title" in cls:
        return True
    txt = get_text(tag)
    # Heuristic: the title contains " - vero.fi"; numbered sections don't.
    return "vero.fi" in txt.lower()


def parse(path: str, rel_path: str) -> Tuple[List[Node], List[SectionBundle]]:
    subcorpus = detect_subcorpus(rel_path) or "vero_other"
    source = "vero"
    with open(path, "rb") as f:
        raw = f.read()
    soup = parse_html(raw)
    body = soup.body or soup

    # Find the actual content root — Vero pages wrap in <article id="content-main">.
    article = soup.find("article", id="content-main") or body

    # Title: first taxxa-title h1 or first h1 with " - vero.fi"
    title_tag = None
    for h1 in article.find_all("h1"):
        if _is_doc_title(h1):
            title_tag = h1
            break
    if title_tag is None:
        title_tag = article.find("h1")
    title = _TITLE_SUFFIX_RE.sub("", get_text(title_tag)) if title_tag else Path(rel_path).stem

    root_id = law_id(source, subcorpus, doc_slug_from_path(rel_path))

    guide_node = Node(
        id=root_id,
        type=GUIDE,
        text="",
        parent_id=None,
        order=0,
        label=None,
        title=title,
        source=source,
        source_subcorpus=subcorpus,
        source_file=rel_path,
        source_html_id=_extract_dom_id(title_tag) if title_tag else None,
        law_id=root_id,
    )
    nodes: List[Node] = [guide_node]
    bundles: List[SectionBundle] = []

    # Flatten all interesting tags inside the article. Vero pages use <div
    # class="main-body"> wrapping content; walk inside it but also accept the
    # article-level children to be defensive.
    container = article.find("div", class_="main-body") or article
    children = list(iter_block_children(container))
    # Skip any top-of-body widgets like taxfi-table-of-contents-mobile.
    children = [c for c in children if c.name not in {"taxfi-table-of-contents-mobile"}]

    # State: a stack of "heading scopes" (level, node_id) so we can attach the
    # currently-collecting members to the right parent. Each time we hit a
    # heading we emit the previous bundle.
    current_section: Node | None = None
    current_members: List[Node] = []
    current_path: List[Tuple[int, str]] = []  # (level, node_id) ancestors

    def flush():
        nonlocal current_section, current_members
        if current_section is None:
            return
        head_parts = [title]
        if current_section.label:
            head_parts.append(current_section.label)
        if current_section.title and current_section.title != current_section.label:
            head_parts.append(current_section.title)
        head = " — ".join(p for p in head_parts if p)
        bundles.append(SectionBundle(
            section=current_section,
            head_text=head,
            members=list(current_members),
        ))
        current_section = None
        current_members = []

    # Per-parent monotonic counter so ids stay unique even when the same
    # parent collects content across multiple flush cycles (most often the
    # GUIDE root for preamble paragraphs that appear before any heading).
    counters: dict[tuple[str, str], int] = {}

    def next_counter(parent: str, kind: str) -> int:
        key = (parent, kind)
        counters[key] = counters.get(key, 0) + 1
        return counters[key]

    # Heading-marker disambiguator: vero slug()s the heading text to ~30 chars,
    # and two long, distinct headings can collide at that prefix.
    used_markers: dict[tuple[str, str], int] = {}

    def disambiguate(parent: str, kind: str, marker: str) -> str:
        key = (parent, kind + "/" + marker)
        used_markers[key] = used_markers.get(key, 0) + 1
        if used_markers[key] == 1:
            return marker
        return f"{marker}-{used_markers[key]}"

    seen_title = False
    for ch in children:
        name = ch.name or ""
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            txt = get_text(ch)
            # The first h1 we encounter is the doc title — skip it.
            if not seen_title and _is_doc_title(ch):
                seen_title = True
                continue
            seen_title = True
            level = int(name[1])
            # Parse number prefix: "2.1 ..." -> ("2.1", "...").
            m = NUMBERED_HEADING_RE.match(txt)
            if m:
                marker = m.group(1)
                heading_title = m.group(2)
            else:
                marker = slug(txt, max_len=30) or f"h{len(bundles)+1}"
                heading_title = txt

            # Pop the heading-path stack to the right depth.
            while current_path and current_path[-1][0] >= level:
                current_path.pop()
            parent_id = current_path[-1][1] if current_path else root_id

            # All headings under Vero are SECTION-equivalents for chunking
            # purposes. We still tag top-level (h1) as CHAPTER to preserve the
            # hierarchy in the node graph; deeper levels are SECTION.
            node_type = CHAPTER if level <= 2 else SECTION
            kind = "s" if node_type == SECTION else "c"
            sec_id = child_id(parent_id, kind, disambiguate(parent_id, kind, marker))
            sec_node = Node(
                id=sec_id,
                type=node_type,
                text="",
                parent_id=parent_id,
                order=len(nodes),
                label=marker,
                title=heading_title or None,
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=root_id,
            )
            nodes.append(sec_node)
            current_path.append((level, sec_id))

            # Emit the previous section's bundle before starting a new one.
            flush()
            current_section = sec_node
            current_members = []
            continue

        # Body content — attach to the current section, or to the guide root if
        # we haven't seen a heading yet (intro text).
        target_parent = current_section.id if current_section else root_id
        if name == "p":
            txt = get_text(ch)
            if not txt:
                continue
            momentti_n = next_counter(target_parent, "m")
            sub_id = child_id(target_parent, "m", str(momentti_n))
            sub_type = DEFINITION if looks_like_definition(txt) else SUBSECTION
            n_ = Node(
                id=sub_id,
                type=sub_type,
                text=txt,
                parent_id=target_parent,
                order=momentti_n,
                label=f"kappale {momentti_n}",
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=root_id,
            )
            nodes.append(n_)
            if current_section:
                current_members.append(n_)
        elif name in {"ul", "ol"}:
            list_n = next_counter(target_parent, "il")
            for k, li in enumerate(ch.find_all("li", recursive=False), start=1):
                li_text = get_text(li)
                if not li_text:
                    continue
                item_id = child_id(target_parent, "i", f"{list_n}-{k}")
                n_ = Node(
                    id=item_id,
                    type=ITEM,
                    text=li_text,
                    parent_id=target_parent,
                    order=k,
                    label=str(k),
                    source=source,
                    source_subcorpus=subcorpus,
                    source_file=rel_path,
                    source_html_id=_extract_dom_id(li),
                    law_id=root_id,
                )
                nodes.append(n_)
                if current_section:
                    current_members.append(n_)
        elif name == "section" and "example" in (ch.get("class") or []):
            txt = get_text(ch)
            if not txt:
                continue
            ex_n = next_counter(target_parent, "esim")
            ex_id = child_id(target_parent, "p", f"esim-{ex_n}")
            n_ = Node(
                id=ex_id,
                type=SUBSECTION,
                text=txt,
                parent_id=target_parent,
                order=ex_n,
                label="Esimerkki",
                source=source,
                source_subcorpus=subcorpus,
                source_file=rel_path,
                source_html_id=_extract_dom_id(ch),
                law_id=root_id,
                metadata={"kind": "example"},
            )
            nodes.append(n_)
            if current_section:
                current_members.append(n_)
        elif name in {"div", "table"}:
            # Tables: keep as a single ITEM-equivalent.
            txt = get_text(ch)
            if txt:
                misc_n = next_counter(target_parent, "misc")
                p_id = child_id(target_parent, "p", f"misc-{misc_n}")
                n_ = Node(
                    id=p_id,
                    type=SUBSECTION,
                    text=txt,
                    parent_id=target_parent,
                    order=misc_n,
                    label=None,
                    source=source,
                    source_subcorpus=subcorpus,
                    source_file=rel_path,
                    source_html_id=_extract_dom_id(ch),
                    law_id=root_id,
                    metadata={"kind": name},
                )
                nodes.append(n_)
                if current_section:
                    current_members.append(n_)
        # Anything else: ignore (script tags, mobile-toc widgets, etc.).

    flush()

    # If no section headings at all — fall back to a single bundle for the
    # whole guide (common for tiny Päätökset / Kannanotot).
    if not bundles:
        orphan = [n_ for n_ in nodes if n_.parent_id == root_id and n_.type in {SUBSECTION, DEFINITION, ITEM}]
        if orphan or title:
            bundles.append(SectionBundle(
                section=guide_node,
                head_text=title,
                members=orphan,
            ))

    return nodes, bundles
