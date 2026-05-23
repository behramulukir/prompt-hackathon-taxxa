"""SECTION-first chunk packing.

Rules (from step-1-plan.md, §6):
  - Chunk unit = SECTION (§) by default.
  - Target 800–1500 tokens; hard max 2000.
  - Never split a sentence / bullet / ITEM / citation span.
  - Boundary priority: SECTION > SUBSECTION > ITEM > paragraph fallback.

A "section bundle" is a list of node ids in document order: the section's own
head text first (if any), then each child (SUBSECTION/ITEM/...) in order. We
pack children into chunks greedily; if a single child by itself exceeds the
hard cap we emit it as its own oversized chunk (and flag it) rather than
splitting it.

For documents without §-sections (Vero guides, KHO cases), the caller wraps
each "leaf grouping" (a numbered heading section, a case decision) as a
SECTION-equivalent and passes it the same way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .nodes import Node, ITEM
from .tokens import count_tokens


TARGET_MIN = 800
TARGET_MAX = 1500
HARD_MAX = 2000


# Finnish abbreviations that end in '.' but don't end a sentence. Conservative
# list — only the very common ones — to avoid false negatives.
_FI_ABBR = {
    "esim", "ks", "yms", "ym", "mm", "jne", "ml", "ns", "vrt", "tms", "n",
    "nro", "ent", "vs", "yht", "tjsp", "tarv", "ko", "tk",
}

# Sentence boundary: a terminal punctuation followed by whitespace and then
# something that *starts* a sentence (uppercase / digit / quote).
_SENT_SPLIT_RE = re.compile(
    r"(?<=[\.\!\?])\s+(?=[A-ZÄÖÅ0-9«\"'\(])",
    re.UNICODE,
)


def _split_sentences(text: str) -> list[str]:
    """Best-effort sentence splitter. Never splits an item-marker citation span."""
    if not text:
        return []
    parts = _SENT_SPLIT_RE.split(text)
    # Reattach abbreviation false-splits: if the previous chunk ends in a
    # short token from _FI_ABBR followed by '.', glue it back.
    merged: list[str] = []
    for p in parts:
        if merged:
            tail = merged[-1].rstrip()
            last_word = re.split(r"\s+", tail)[-1].rstrip(".").lower()
            if last_word in _FI_ABBR:
                merged[-1] = merged[-1].rstrip() + " " + p.lstrip()
                continue
        merged.append(p)
    return [m.strip() for m in merged if m.strip()]


def _pack_sentences(sentences: list[str], budget: int) -> list[str]:
    """Greedy: pack sentences into pieces of at most `budget` tokens each.

    A sentence larger than `budget` is emitted alone (oversized but
    unsplittable per the never-split-a-sentence rule).
    """
    pieces: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for s in sentences:
        st = count_tokens(s)
        if cur and cur_tok + st + 1 > budget:
            pieces.append(" ".join(cur))
            cur = []
            cur_tok = 0
        cur.append(s)
        cur_tok += st + 1
    if cur:
        pieces.append(" ".join(cur))
    return pieces


@dataclass
class Chunk:
    chunk_id: str
    section_id: str
    law_id: str
    node_ids: list[str]
    text: str
    token_count: int
    source: str
    source_subcorpus: str
    source_file: str
    oversized: bool = False  # single-node chunk exceeds HARD_MAX

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "section_id": self.section_id,
            "law_id": self.law_id,
            "node_ids": list(self.node_ids),
            "text": self.text,
            "token_count": self.token_count,
            "source": self.source,
            "source_subcorpus": self.source_subcorpus,
            "source_file": self.source_file,
            "oversized": self.oversized,
        }


@dataclass
class SectionBundle:
    """A section + the ordered list of nodes that belong inside it."""
    section: Node                  # the SECTION (or equivalent root) node
    head_text: str = ""            # text rendered at the top of every chunk (the § label/title)
    members: list[Node] = field(default_factory=list)  # ordered atomic units


def _render_node(node: Node) -> str:
    """Materialise a single node as the text the chunk should contain.

    Includes a one-line label when present so chunks remain self-describing
    after packing (e.g. "1 momentti: …" or "kohta a) …").
    """
    parts: list[str] = []
    if node.label:
        # Keep label terse — it's a navigation hint, not duplicated content.
        if node.title:
            parts.append(f"{node.label} {node.title}")
        else:
            parts.append(node.label)
    elif node.title:
        parts.append(node.title)
    if node.text:
        parts.append(node.text.strip())
    return "\n".join(p for p in parts if p)


def pack_section(bundle: SectionBundle) -> list[Chunk]:
    """Pack one SectionBundle into one or more Chunks.

    Greedy: walks the members in order. Starts a new chunk whenever the
    next member would push the current chunk over TARGET_MAX. A single
    member larger than HARD_MAX is emitted as its own oversized chunk.
    """
    sec = bundle.section
    head = bundle.head_text.strip()
    head_tokens = count_tokens(head) if head else 0

    # Pre-compute per-member text + tokens.
    rendered: list[tuple[Node, str, int]] = []
    for m in bundle.members:
        t = _render_node(m)
        if not t:
            continue
        rendered.append((m, t, count_tokens(t)))

    if not rendered:
        # Section has no children — emit head alone if there's anything.
        if not head:
            return []
        cid = f"{sec.id}#0"
        return [Chunk(
            chunk_id=cid,
            section_id=sec.id,
            law_id=sec.law_id or sec.id,
            node_ids=[sec.id],
            text=head,
            token_count=head_tokens,
            source=sec.source,
            source_subcorpus=sec.source_subcorpus,
            source_file=sec.source_file,
        )]

    chunks: list[Chunk] = []
    cur_nodes: list[Node] = []
    cur_texts: list[str] = []
    cur_tokens = head_tokens

    def emit():
        nonlocal cur_nodes, cur_texts, cur_tokens
        if not cur_nodes:
            return
        body = "\n\n".join(cur_texts)
        text = f"{head}\n\n{body}" if head else body
        idx = len(chunks)
        chunks.append(Chunk(
            chunk_id=f"{sec.id}#{idx}",
            section_id=sec.id,
            law_id=sec.law_id or sec.id,
            node_ids=[sec.id] + [n.id for n in cur_nodes],
            text=text,
            token_count=count_tokens(text),
            source=sec.source,
            source_subcorpus=sec.source_subcorpus,
            source_file=sec.source_file,
        ))
        cur_nodes = []
        cur_texts = []
        cur_tokens = head_tokens

    for node, text, toks in rendered:
        # Oversized single member: flush the current chunk first.
        if toks > HARD_MAX:
            emit()
            # ITEM nodes must never be split (spec §6.4). Emit oversized + flag.
            # For non-ITEM nodes (long paragraphs in treaties etc.), fall back
            # to sentence-level splitting so we stay under the hard cap.
            if node.type == ITEM:
                idx = len(chunks)
                standalone_text = f"{head}\n\n{text}" if head else text
                chunks.append(Chunk(
                    chunk_id=f"{sec.id}#{idx}",
                    section_id=sec.id,
                    law_id=sec.law_id or sec.id,
                    node_ids=[sec.id, node.id],
                    text=standalone_text,
                    token_count=count_tokens(standalone_text),
                    source=sec.source,
                    source_subcorpus=sec.source_subcorpus,
                    source_file=sec.source_file,
                    oversized=True,
                ))
                continue

            # Budget for sentence packing = HARD_MAX minus head overhead.
            budget = HARD_MAX - head_tokens - 4
            sentences = _split_sentences(text)
            pieces = _pack_sentences(sentences, max(200, budget))
            for piece in pieces:
                idx = len(chunks)
                piece_text = f"{head}\n\n{piece}" if head else piece
                ptoks = count_tokens(piece_text)
                chunks.append(Chunk(
                    chunk_id=f"{sec.id}#{idx}",
                    section_id=sec.id,
                    law_id=sec.law_id or sec.id,
                    node_ids=[sec.id, node.id],
                    text=piece_text,
                    token_count=ptoks,
                    source=sec.source,
                    source_subcorpus=sec.source_subcorpus,
                    source_file=sec.source_file,
                    oversized=ptoks > HARD_MAX,
                ))
            continue

        projected = cur_tokens + (2 if cur_texts else 0) + toks  # +2 for the "\n\n" join
        if cur_nodes and projected > TARGET_MAX:
            emit()

        cur_nodes.append(node)
        cur_texts.append(text)
        cur_tokens = head_tokens + sum(count_tokens(t) for t in cur_texts) + 2 * (len(cur_texts) - 1)

    emit()
    return chunks


def pack_sections(bundles: Iterable[SectionBundle]) -> list[Chunk]:
    out: list[Chunk] = []
    for b in bundles:
        out.extend(pack_section(b))
    return out
