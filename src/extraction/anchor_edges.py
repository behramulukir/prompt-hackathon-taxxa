"""B2.2 — Anchor-based edge extraction.

Walk one raw HTML file, find every `<a href>`, attribute the anchor to a
source node from `NodeIndex`, normalize the href into a `CitationKey`, and
yield `RawMatch` records for the downstream resolver.

Each emitted match also carries a `(start_char, end_char)` span — used by
the regex pass to avoid double-extracting the same reference. For anchor
edges we always return `(-1, -1)` (no span); the regex pass falls back to
substring de-duplication using each match's `target_ref` instead. Tradeoff:
cheaper than re-computing per-node text offsets across two passes, and
good enough since explicit anchor text rarely overlaps a different regex
form within the same node.
"""
from __future__ import annotations

import pathlib
from typing import Iterable, Iterator, Optional

from bs4 import Tag

from pipeline.html_utils import (
    get_text,
    parse_chapter_heading,
    parse_html,
    parse_section_heading,
)

from src.extraction.ids import CitationKey, parse_href
from src.extraction.node_index import NodeIndex, NodeRecord
from src.extraction.resolve import RawMatch


_ROOT_TYPES = {"LAW", "GUIDE", "CASE", "TREATY"}
_SECTION_LIKE = ("SECTION", "SUBSECTION", "ITEM", "CHAPTER", "LAW")
_NO_SPAN: tuple[int, int] = (-1, -1)


def extract_anchor_edges(
    abs_html_path: pathlib.Path,
    rel_path: str,
    node_index: NodeIndex,
) -> Iterator[tuple[RawMatch, tuple[int, int]]]:
    """Yield (RawMatch, span) pairs for every resolvable `<a href>` in the file.

    Anchors with `href` pointing to fragments (`#…`), or that `parse_href`
    cannot interpret, are skipped. Anchors whose href is a known out-of-corpus
    pattern (e.g. EU directives) are still emitted — the resolver will mark
    them dangling with `out_of_corpus`.
    """
    try:
        raw = abs_html_path.read_bytes()
    except OSError:
        return
    soup = parse_html(raw)
    body = soup.body or soup

    candidates = node_index.by_source_file.get(rel_path, [])
    if not candidates:
        return

    by_html_id: dict[str, list[NodeRecord]] = {}
    root_rec: Optional[NodeRecord] = None
    records: list[NodeRecord] = []
    for nid in candidates:
        rec = node_index.nodes.get(nid)
        if rec is None:
            continue
        records.append(rec)
        if rec.source_html_id:
            by_html_id.setdefault(rec.source_html_id, []).append(rec)
        if root_rec is None and rec.type in _ROOT_TYPES:
            root_rec = rec

    if root_rec is None:
        return

    for a in body.find_all("a"):
        href = a.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        if href.lstrip().startswith("#"):
            continue
        key = parse_href(href)
        if key is None:
            continue

        attributed = _attribute_anchor(a, by_html_id, records, root_rec)
        if attributed is None:
            attributed = root_rec

        text = a.get_text(" ", strip=True)
        snippet: Optional[str] = text[:64] if text else None

        yield (
            RawMatch(
                source_id=attributed.id,
                target_ref=href.strip(),
                key=key,
                type="cites",
                confidence=1.0,
                extracted_by="anchor",
                context_snippet=snippet,
                source_law_id=attributed.law_id,
            ),
            _NO_SPAN,
        )


def extract_anchor_edges_many(
    files: Iterable[tuple[pathlib.Path, str]],
    node_index: NodeIndex,
) -> Iterator[tuple[RawMatch, tuple[int, int]]]:
    """Convenience fan-out for runners that drive multiple files sequentially."""
    for abs_path, rel_path in files:
        yield from extract_anchor_edges(abs_path, rel_path, node_index)


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def _attribute_anchor(
    anchor: Tag,
    by_html_id: dict[str, list[NodeRecord]],
    records: list[NodeRecord],
    root_rec: NodeRecord,
) -> Optional[NodeRecord]:
    """Walk up from the anchor to find the most-specific attributable node."""
    cur: Optional[Tag] = anchor.parent if isinstance(anchor.parent, Tag) else None
    while cur is not None and cur.name not in (None, "[document]"):
        raw_id = cur.get("id") if hasattr(cur, "get") else None
        if isinstance(raw_id, str) and raw_id.strip():
            rec = _attribute_by_html_id(raw_id.strip(), by_html_id)
            if rec is not None:
                return rec
        if cur.name in {"h1", "h2", "h3", "h4"}:
            heading_text = get_text(cur)
            rec = _attribute_by_heading_text(heading_text, records)
            if rec is not None:
                return rec
        if cur.name == "body":
            break
        nxt = cur.parent
        cur = nxt if isinstance(nxt, Tag) else None
    return root_rec


def _attribute_by_html_id(
    html_id: str,
    by_html_id: dict[str, list[NodeRecord]],
) -> Optional[NodeRecord]:
    """Pick the closest-to-leaf NodeRecord whose source_html_id matches."""
    recs = by_html_id.get(html_id)
    if not recs:
        return None
    if len(recs) == 1:
        return recs[0]
    type_rank = {t: i for i, t in enumerate(_SECTION_LIKE)}
    return min(recs, key=lambda r: type_rank.get(r.type, len(_SECTION_LIKE)))


def _attribute_by_heading_text(
    heading_text: str,
    records: list[NodeRecord],
) -> Optional[NodeRecord]:
    """Best-effort match of a heading's text to a SECTION/CHAPTER label."""
    if not heading_text:
        return None
    section = parse_section_heading(heading_text)
    chapter = parse_chapter_heading(heading_text) if section is None else None

    if section is not None:
        marker, _ = section
        label = f"{marker} §"
        return _pick_by_label(records, label, preferred_types=("SECTION", "SUBSECTION"))

    if chapter is not None:
        marker, _ = chapter
        label = f"{marker} luku"
        return _pick_by_label(records, label, preferred_types=("CHAPTER",))

    return None


def _pick_by_label(
    records: list[NodeRecord],
    label: str,
    preferred_types: tuple[str, ...],
) -> Optional[NodeRecord]:
    matches = [r for r in records if r.label == label]
    if not matches:
        return None
    for t in preferred_types:
        for r in matches:
            if r.type == t:
                return r
    return matches[0]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _self_test() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    nodes_jsonl = repo_root / "output" / "nodes.jsonl"
    sample_rel = "finlex/Laki/Laki rajavyöhykelain 10 §_n muuttamisesta.html"
    sample_abs = repo_root / "data" / sample_rel

    if not nodes_jsonl.exists() or not sample_abs.exists():
        print(f"[self-test] missing input(s): {nodes_jsonl} / {sample_abs}")
        return 1

    index = NodeIndex().load(nodes_jsonl)
    matches = list(extract_anchor_edges(sample_abs, sample_rel, index))
    if not matches:
        print("[self-test] no matches produced")
        return 1

    print(f"[self-test] {len(matches)} anchor matches; first 5:")
    for match, span in matches[:5]:
        print(
            "  source_id={src} target_ref={ref} key={key} snippet={snip!r} span={span}".format(
                src=match.source_id,
                ref=match.target_ref,
                key=match.key,
                snip=match.context_snippet,
                span=span,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
