"""Read-only lookup over `output/nodes.jsonl`.

Memory budget: the file is 1.3 GB and 1.97M nodes; we cannot load the full
records. We keep a small per-node tuple (parent_id, source, subcorpus,
law_id, source_file, source_html_id, type, label) plus four reverse indexes:

    by_source_file        rel_path -> [node_id, ...]
    by_law_year_number    (year, number) -> law_id        (Finlex statutes)
    by_law_title          slug(title) -> law_id
    by_law_kho            (year, n) -> case_id            (KHO precedents)
    by_chunk_section      chunk_id -> section_id  (from chunks.jsonl)

The indexes are derived from titles and filenames using regexes tuned to
the actual on-disk shapes from Step 1. They are *best-effort* — when the
title doesn't carry a year/number, that law simply isn't reachable via
numeric citation. NodeIndex still resolves anchors via the (year, number)
URL form when the index has the entry.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .ids import CitationKey


@dataclass(frozen=True)
class NodeRecord:
    id: str
    type: str
    parent_id: Optional[str]
    source: str
    source_subcorpus: str
    source_file: str
    source_html_id: Optional[str]
    law_id: Optional[str]
    label: Optional[str]
    title: Optional[str]


# ---- Filename-based year/number extraction --------------------------------
#
# Finlex säädöskokoelma filenames in Step 1's slug form look like:
#   finlex-laki-skk-rajavyohykelaki-html-<hash>
#   finlex-laki-skk-rajavyohykelaki-<hash>
#
# Title-based, e.g. `Rajavyöhykelaki (403/1947)` — we extract (403, 1947).
# Filenames don't always carry the number; titles sometimes do.
# ---------------------------------------------------------------------------

_TITLE_YEAR_NUM = re.compile(r"\((\d{1,4})/(\d{4})\)")
_TITLE_NAKED_YEAR_NUM = re.compile(r"\b(\d{1,4})/(\d{4})\b")

_KHO_TITLE = re.compile(r"KHO[:\s]+(\d{4})[:\s\-/]+(\d+)", re.IGNORECASE)

# Folded version of slug() — matches src/pipeline/nodes.py
_FINNISH_MAP = str.maketrans({"ä": "a", "ö": "o", "å": "a", "Ä": "a", "Ö": "o", "Å": "a"})


def title_slug(text: str) -> str:
    """Same shape as pipeline.nodes.slug() — used as a lookup key.

    Kept duplicated rather than importing from `pipeline` to avoid a hard
    dependency from src/ → pipeline/ — Step 2 should be runnable with just
    the JSONL outputs.
    """
    if not text:
        return ""
    s = text.translate(_FINNISH_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


class NodeIndex:
    """Streamed loader + lookup tables. Build once, query many."""

    def __init__(self) -> None:
        self.nodes: dict[str, NodeRecord] = {}
        self.by_source_file: dict[str, list[str]] = {}
        # Map a (year, number) statute key to the LAW node id.
        self.by_law_year_number: dict[tuple[int, int], str] = {}
        # Map a slug of the law title to the LAW node id.
        self.by_law_title: dict[str, str] = {}
        # KHO precedents: (year, n) -> CASE id.
        self.by_law_kho: dict[tuple[int, int], str] = {}
        # Section index inside one law: (law_id, section_marker) -> section node id
        # section_marker is e.g. "5" or "5a".
        self.by_law_section: dict[tuple[str, str], str] = {}
        # All node IDs grouped by (law_id, type) for definition-edge scanning.
        self.by_law_type: dict[tuple[str, str], list[str]] = {}

    # -- loading ------------------------------------------------------------

    def load(self, nodes_jsonl: Path) -> "NodeIndex":
        with nodes_jsonl.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                rec = NodeRecord(
                    id=d["id"],
                    type=d["type"],
                    parent_id=d.get("parent_id"),
                    source=d.get("source", ""),
                    source_subcorpus=d.get("source_subcorpus", ""),
                    source_file=d.get("source_file", ""),
                    source_html_id=d.get("source_html_id"),
                    law_id=d.get("law_id"),
                    label=d.get("label"),
                    title=d.get("title"),
                )
                self.nodes[rec.id] = rec
                if rec.source_file:
                    self.by_source_file.setdefault(rec.source_file, []).append(rec.id)
                if rec.law_id:
                    self.by_law_type.setdefault((rec.law_id, rec.type), []).append(rec.id)

                # Root-document indexing.
                if rec.type in {"LAW", "GUIDE", "CASE", "TREATY"} and rec.title:
                    self._index_root(rec)

                # Section indexing.
                if rec.type == "SECTION" and rec.law_id and rec.label:
                    marker = _section_marker_from_label(rec.label)
                    if marker:
                        self.by_law_section[(rec.law_id, marker)] = rec.id

        return self

    def _index_root(self, rec: NodeRecord) -> None:
        title = rec.title or ""
        # Title-slug index — both full title and shortened "name only" form.
        slug_full = title_slug(title)
        if slug_full:
            self.by_law_title.setdefault(slug_full, rec.id)
        # Also index a shortened form by dropping trailing "(NNN/YYYY)" and any
        # parenthetical suffix.
        short = re.sub(r"\s*\([^)]*\)\s*", " ", title).strip()
        slug_short = title_slug(short)
        if slug_short and slug_short != slug_full:
            self.by_law_title.setdefault(slug_short, rec.id)

        # Year/number from title.
        for pat in (_TITLE_YEAR_NUM, _TITLE_NAKED_YEAR_NUM):
            m = pat.search(title)
            if m:
                try:
                    num = int(m.group(1))
                    year = int(m.group(2))
                    self.by_law_year_number.setdefault((year, num), rec.id)
                    break
                except ValueError:
                    pass

        # KHO precedents.
        if rec.type == "CASE":
            m = _KHO_TITLE.search(title)
            if m:
                self.by_law_kho.setdefault(
                    (int(m.group(1)), int(m.group(2))), rec.id,
                )

    # -- lookup -------------------------------------------------------------

    def resolve(self, key: CitationKey, default_law_id: str | None = None) -> str | None:
        """Resolve a CitationKey to a node id, or None if not present.

        `default_law_id` is the source node's own law — used when the
        citation only carries a section marker (intra-law reference).
        """
        law_id = self._resolve_law(key, default_law_id)
        if law_id is None:
            return None

        # If a section marker was given, try to land on the SECTION node.
        if key.section:
            section_marker = key.section.replace(" ", "").lower()
            sec_id = self.by_law_section.get((law_id, section_marker))
            if sec_id:
                # Refine to subsection / item if the index has it.
                if key.subsection is not None:
                    sub_id = f"{sec_id}/m{key.subsection}"
                    if sub_id in self.nodes:
                        if key.item:
                            item_id = f"{sub_id}/i{_item_position(key.item)}"
                            if item_id in self.nodes:
                                return item_id
                        return sub_id
                return sec_id
        return law_id

    def _resolve_law(self, key: CitationKey, default_law_id: str | None) -> str | None:
        if key.kho_year and key.kho_n:
            return self.by_law_kho.get((key.kho_year, key.kho_n))
        if key.year and key.number:
            return self.by_law_year_number.get((key.year, key.number))
        if key.law_hint:
            return self.by_law_title.get(title_slug(key.law_hint))
        # Pure section-only — must be intra-law.
        if key.section and default_law_id:
            return default_law_id
        return None

    # -- iteration helpers used by structural / definition passes ----------

    def iter_records(self) -> Iterator[NodeRecord]:
        return iter(self.nodes.values())

    def nodes_in_law(self, law_id: str, types: Iterable[str]) -> list[NodeRecord]:
        out: list[NodeRecord] = []
        for t in types:
            for nid in self.by_law_type.get((law_id, t), ()):
                rec = self.nodes.get(nid)
                if rec:
                    out.append(rec)
        return out


# ---- helpers ---------------------------------------------------------------

_SECTION_LABEL = re.compile(r"^\s*(\d+)\s*([a-z]?)\s*§", re.IGNORECASE)


def _section_marker_from_label(label: str) -> str | None:
    """Turn "5 §" / "5 a §" labels into the index key "5" / "5a"."""
    m = _SECTION_LABEL.match(label)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2).lower()}" if m.group(2) else m.group(1)


def _item_position(marker: str) -> str:
    """Map an item marker ('1', 'a', etc.) to its child_id position string.

    Step 1 IDs items by *order* under their parent, not by the natural marker.
    Without re-reading the chunk we cannot know the order, so we just pass
    the marker through; the caller's downstream lookup will miss and produce
    a dangling edge. Item-level resolution is best-effort.
    """
    return marker
