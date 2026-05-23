"""Node dataclass + deterministic ID/slug helpers.

A Node is one entry in the legal-structure graph. IDs are derived from the
document path + hierarchical position so the same input always yields the
same id (no UUIDs).
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from hashlib import blake2b
from typing import Any


# ----- Node types -----------------------------------------------------------

# Hierarchical
LAW = "LAW"
CHAPTER = "CHAPTER"
SECTION = "SECTION"
SUBSECTION = "SUBSECTION"
ITEM = "ITEM"

# Semantic (only if structurally indicated — see DEFINITION_PATTERNS below)
DEFINITION = "DEFINITION"

# Metadata
TITLE = "TITLE"
AMENDMENT_BLOCK = "AMENDMENT_BLOCK"

# Vero / KHO have weaker hierarchy — we still use these types but interpret:
#   GUIDE  ~ LAW
#   H1/H2  ~ CHAPTER
#   H3     ~ SECTION
GUIDE = "GUIDE"
CASE = "CASE"
TREATY = "TREATY"


# Patterns that, if matched at the start of a paragraph, qualify a node as a
# DEFINITION (per step-1 spec: only when structurally indicated, never inferred).
DEFINITION_PATTERNS = (
    "tarkoitetaan",
    "tarkoittaa",
    "määritellään",
    "defined as",
    "means",
)


@dataclass
class Node:
    id: str
    type: str
    text: str
    parent_id: str | None = None
    order: int = 0
    label: str | None = None
    title: str | None = None
    source: str = ""           # "finlex" | "vero"
    source_subcorpus: str = ""  # e.g. "laki_skk", "vero_ohje"
    source_file: str = ""       # relative path under data/
    source_html_id: str | None = None  # DOM anchor (id=...) when present
    law_id: str | None = None   # id of the LAW/GUIDE/CASE root for fast lookup
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # drop falsy/None metadata? keep — they help downstream consumers.
        return d


# ----- Slug + ID helpers ----------------------------------------------------

_FINNISH_MAP = str.maketrans({"ä": "a", "ö": "o", "å": "a", "Ä": "a", "Ö": "o", "Å": "a"})


def slug(value: str, max_len: int = 80) -> str:
    """Deterministic, ASCII-safe slug for use in node IDs.

    Finnish diacritics are folded (ä -> a, ö -> o) so IDs stay readable in
    English-language tools, but the original text is preserved on the Node.
    """
    if not value:
        return ""
    s = value.translate(_FINNISH_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def law_id(source: str, subcorpus: str, doc_slug: str) -> str:
    return f"{source}/{subcorpus}/{doc_slug}"


def doc_slug_from_path(rel_path: str, *, slug_max_len: int = 80) -> str:
    """Build a collision-free document slug from a relative file path.

    The path's filename is slugified for readability, then a 4-byte BLAKE2b
    hash of the *full* relative path is appended so that two files with
    identical truncated prefixes (very common in the Finnish corpus where
    asetus filenames run 200+ chars) end up with distinct ids.
    """
    base = slug(rel_path.replace(os.sep, "-"), max_len=slug_max_len)
    h = blake2b(rel_path.encode("utf-8"), digest_size=4).hexdigest()
    return f"{base}-{h}" if base else h


def child_id(parent: str, kind: str, marker: str) -> str:
    """Build a child id from parent + a one-char kind + marker slug.

    Kind codes:
      c=chapter, s=section, m=subsection (momentti), i=item, a=amendment,
      d=definition, t=title, p=paragraph, x=appendix/other.
    """
    return f"{parent}/{kind}{slug(marker, max_len=40)}"


# ----- Definition detection -------------------------------------------------

_DEF_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in DEFINITION_PATTERNS) + r")\b",
    re.IGNORECASE,
)


def looks_like_definition(text: str) -> bool:
    """Return True only if the text *explicitly* signals a definition."""
    if not text:
        return False
    head = text[:200].lower()
    return bool(_DEF_RE.search(head))
