"""Shared HTML helpers for parsers."""
from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag


# Whitespace normaliser: collapses runs of spaces/newlines/tabs into a single
# space. Applied to extracted text to clean up the Finnish HTML's heavy
# indentation and stray nbsp.
_WS = re.compile(r"\s+", re.UNICODE)


def normalize_ws(text: str) -> str:
    if not text:
        return ""
    # Replace nbsp variants up front so the regex catches them.
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return _WS.sub(" ", text).strip()


def parse_html(raw: str | bytes) -> BeautifulSoup:
    """Parse with lxml when available, fall back to html.parser."""
    try:
        return BeautifulSoup(raw, "lxml")
    except Exception:  # pragma: no cover
        return BeautifulSoup(raw, "html.parser")


def get_text(node: Tag) -> str:
    """Extract plain text from a BS4 node, normalised."""
    return normalize_ws(node.get_text(" ", strip=True))


def iter_block_children(parent: Tag) -> Iterable[Tag]:
    """Yield direct block children that matter for structure extraction.

    Skips comment nodes and script/style.
    """
    for child in parent.children:
        if isinstance(child, NavigableString):
            continue
        if not isinstance(child, Tag):
            continue
        if child.name in ("script", "style"):
            continue
        yield child


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def heading_level(tag: Tag) -> int | None:
    if tag.name in HEADING_TAGS:
        return int(tag.name[1])
    return None


# Patterns ---------------------------------------------------------------------

# Match a § marker. Finnish documents use "5 §", "5 §.", "§5", and combinations
# with subsection letters (e.g. "5 a §"). We capture the numeric body + optional
# letter qualifier.
SECTION_RE = re.compile(
    r"""^\s*
        (?P<num>\d+)
        \s*(?P<sub>[a-zA-Z]?)\s*
        §\.?
        \s*
        (?P<title>.*?)\s*$
    """,
    re.VERBOSE,
)

# "5 § Adoption tarkoitus" (number first, then § then title)
SECTION_TITLE_RE = re.compile(
    r"""^\s*
        (?P<num>\d+)
        \s*(?P<sub>[a-zA-Z]?)\s*
        §
        \s*
        (?P<title>.+?)\s*$
    """,
    re.VERBOSE,
)

# Chapter heading: "1 luku Yleiset säännökset" or "2 osa: …"
CHAPTER_RE = re.compile(
    r"""^\s*
        (?P<num>[IVXLCDM]+|\d+)\s+(?:luku|osa|kapitel)
        \s*[:\-]?\s*
        (?P<title>.*?)\s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def parse_section_heading(text: str) -> tuple[str, str] | None:
    """Return (number_marker, title) if text looks like a § section heading.

    number_marker is the canonical "5" or "5 a"; title may be empty if the
    heading is bare ("9 §" with no descriptive title).
    """
    if "§" not in text:
        return None
    m = SECTION_TITLE_RE.match(text)
    if not m:
        m = SECTION_RE.match(text)
        if not m:
            return None
    num = m.group("num")
    sub = m.group("sub").lower() if m.group("sub") else ""
    title = (m.group("title") or "").strip()
    marker = f"{num}{sub}" if sub else num
    return marker, title


def parse_chapter_heading(text: str) -> tuple[str, str] | None:
    """Return (number_marker, title) if text looks like a chapter heading."""
    m = CHAPTER_RE.match(text)
    if not m:
        return None
    return m.group("num"), (m.group("title") or "").strip()


# Numbered-list item detection inside text: "1)", "a)", "1.", "(1)"
ITEM_PREFIX_RE = re.compile(r"^\s*(?:\(?(\d+|[a-zA-Z])\)?\.?)\s+")


def looks_like_item_prefix(text: str) -> str | None:
    """Return the item marker (e.g. "1", "a") if the paragraph starts with one."""
    m = ITEM_PREFIX_RE.match(text)
    if not m:
        return None
    return m.group(1).lower()
