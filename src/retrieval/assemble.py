"""Annotated context assembly — Layer 5 of the cross-reference architecture.

A flat list of chunks lets the LLM treat sources as independent. Inline
cross-references between sources are what make the LLM reason about the
*graph* instead of just the nodes. At v1 we render edges only between
already-retrieved sections; at v2 the expansion step will widen this.

Format (mandated by 05_retrieval_v1_vector_only.md §B5.4)::

    [Source 1] Finlex · AVL § 114 (in force, authority_rank=100)
      Path: Arvonlisäverolaki > Luku 10 > § 114
      Cites: §117 AVL → [Source 3]
      Interpreted by: Vero 2019 → [Source 2]

      <chunk body — minus the embedded_text prefix>

The Source label is the LLM's stable handle for citations. The header carries
authority signals so the LLM (and the Verifier later) can reason about rank
without us re-stating it in prose.

Path and Title are parsed back out of ``embedded_text`` instead of loading
the full 1.97M-node index — see the constraint notes in the plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from src.indexing.graph_store import GraphStore
from src.models import EffectiveText, Neighbor, VersionStep
from src.retrieval.rerank import RerankedHit


# Edge types we render between retrieved sources. ``parent_of`` is structural
# (everyone has a parent) — including it would clutter the prompt without
# adding signal. The four below are the cross-document relationships that
# make the graph load-bearing.
RENDERED_EDGE_TYPES: tuple[str, ...] = ("cites", "interprets", "amends", "defines")


# --------------------------------------------------------------------------
# Source — one rendered block in the assembled context.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """One numbered block in the assembled context. ``label`` is the
    ``[Source N]`` string the LLM cites back with.

    Step 10 extension: each source carries the ``version_chain`` that
    produced its rendered body (empty when the section has no chain) and
    a ``has_future_amendments`` flag for the UI. ``effective_text`` is
    the actual body string the LLM saw — may differ from the section's
    raw ``text`` when amendments have been applied.
    """

    label: str  # "[Source 1]"
    index: int  # 1-based for human readability
    chunk_id: str
    section_id: str
    rerank_score: float
    cosine_sim: float
    rendered_block: str

    # Step 10 — point-in-time provenance for the rendered body.
    effective_text: str | None = None
    version_chain: tuple[VersionStep, ...] = field(default_factory=tuple)
    has_future_amendments: bool = False


@dataclass(frozen=True)
class AssembledContext:
    """The text handed to the LLM, plus the mapping back to chunk_ids.

    ``as_of_used`` (Step 10) is the date the assembler passed to
    ``GraphStore.text_at`` when fetching effective bodies — pipeline
    callers forward it onto ``AnswerResult.as_of_date_used`` so the UI
    and the Verifier can see which point-in-time the prompt was built
    against.
    """

    text: str
    sources: list[Source]
    as_of_used: date | None = None

    def chunk_id_for_label(self, label: str) -> str | None:
        """Resolve ``[Source N]`` back to the underlying chunk_id.

        Tolerant of common LLM citation variants — ``Source 1``,
        ``[source 1]``, ``[Source 1].`` — so the parser in ``generate.py``
        doesn't have to duplicate this normalization.
        """
        norm = label.strip().lower().strip("[]().,;:")
        norm = norm.removeprefix("source").strip()
        if not norm.isdigit():
            return None
        idx = int(norm)
        for s in self.sources:
            if s.index == idx:
                return s.chunk_id
        return None


# --------------------------------------------------------------------------
# Dedup
# --------------------------------------------------------------------------


def dedup_by_section(reranked: list[RerankedHit]) -> list[RerankedHit]:
    """Keep the highest-scoring chunk per section_id.

    Two chunks of the same section in the LLM context produce near-duplicate
    ``[Source N]``s and degrade citation accuracy. ``reranked`` is assumed to
    be already sorted (rerank.rerank sorts descending), so the first
    occurrence of each section_id is the keeper.
    """
    seen: set[str] = set()
    out: list[RerankedHit] = []
    for r in reranked:
        sid = r.hit.section_id
        if sid in seen:
            continue
        seen.add(sid)
        out.append(r)
    return out


# --------------------------------------------------------------------------
# Prefix parsing — extract Path and Title from embedded_text
# --------------------------------------------------------------------------


_PATH_RE = re.compile(r"^\[Path:\s*(.+?)\]\s*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^\[Title:\s*(.+?)\]\s*$", re.MULTILINE)


def _split_prefix_body(embedded_text: str | None) -> tuple[str, str]:
    """Return (prefix, body). Prefix is the bracketed lines + blank line."""
    if not embedded_text:
        return "", ""
    parts = embedded_text.split("\n\n", 1)
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], parts[1]


def _extract_path(prefix: str) -> str | None:
    m = _PATH_RE.search(prefix)
    return m.group(1).strip() if m else None


def _extract_title(prefix: str) -> str | None:
    m = _TITLE_RE.search(prefix)
    return m.group(1).strip() if m else None


# --------------------------------------------------------------------------
# Header rendering
# --------------------------------------------------------------------------


def _short_subcorpus(sub: str) -> str:
    """Human-friendly publisher name. ``vero_ohje`` → "Vero ohje", etc."""
    table = {
        "laki": "Finlex laki",
        "asetus": "Finlex asetus",
        "laki_skk": "Finlex SK",
        "asetus_skk": "Finlex SK asetus",
        "kho": "KHO",
        "vero_ohje": "Vero ohje",
        "vero_paatos": "Vero päätös",
        "vero_kannanotto": "Vero kannanotto",
        "vero_kvl": "Vero KVL",
        "vero_other": "Vero",
        "treaty": "Treaty",
    }
    return table.get(sub, sub)


def _header_line(
    index: int,
    hit_subcorpus: str,
    title: str | None,
    in_force: bool | None,
    usable: bool | None,
    authority_rank: int | None,
    publication_date: str | None,
    temporal_status: dict | None = None,
) -> str:
    """``[Source 1] Vero ohje · Mainoslahjat (in force, authority_rank=60, 2019-04-12)``

    When ``temporal_status`` is supplied (Move 2 output), the header
    surfaces ``effective_usable`` (suspect/stale/repealed) so the LLM sees
    the ancestor-aware grade alongside the binary ``in force`` flag.
    """
    publisher = _short_subcorpus(hit_subcorpus)
    head = f"[Source {index}] {publisher}"
    if title:
        head += f" · {title}"

    flags: list[str] = []
    if in_force is True:
        flags.append("in force")
    elif in_force is False:
        flags.append("repealed")
    if usable is False:
        flags.append("not usable")
    if authority_rank is not None:
        flags.append(f"authority_rank={authority_rank}")
    if publication_date:
        flags.append(publication_date)
    # Ancestor-aware grade. ``ok`` is the silent default; only flag the
    # interesting buckets so the prompt stays compact.
    if isinstance(temporal_status, dict):
        grade = temporal_status.get("effective_usable")
        if grade and grade != "ok":
            flags.append(f"status={grade}")
    if flags:
        head += f" ({', '.join(flags)})"
    return head


def _temporal_lines(temporal_status: dict | None) -> list[str]:
    """Render the amendment + interpretation history as bullet lines.

    These come straight from the ``temporal_status`` dict written by
    ``scripts.compute_temporal_status`` — no DB hops here. Lines are
    emitted only when there's something to say; sources with a clean
    history stay compact.
    """
    if not isinstance(temporal_status, dict):
        return []
    lines: list[str] = []
    count = temporal_status.get("amendment_count_in_law") or 0
    after = temporal_status.get("ancestor_amended_after")
    if count and after:
        lines.append(
            f"  Amendments to parent LAW: {count} "
            f"(latest effective {after} — may post-date this text)"
        )
    elif count:
        lines.append(f"  Amendments to parent LAW: {count}")

    interp_count = temporal_status.get("interpreted_count") or 0
    interp_latest = temporal_status.get("latest_interpretation_date")
    if interp_count and interp_latest:
        lines.append(
            f"  Interpretations on file: {interp_count} "
            f"(latest {interp_latest})"
        )
    elif interp_count:
        lines.append(f"  Interpretations on file: {interp_count}")

    grade = temporal_status.get("effective_usable")
    if grade == "stale":
        lines.append("  Note: parent LAW has been superseded — verify before citing.")
    elif grade == "repealed":
        lines.append("  Note: this section or its parent LAW has been repealed.")
    return lines


# --------------------------------------------------------------------------
# Version-chain rendering — Step 10 / Move 5b
# --------------------------------------------------------------------------


def _version_chain_lines(
    effective: EffectiveText | None, as_of: date | None
) -> list[str]:
    """Render the section's version chain as inline annotation lines.

    Silent when the chain has only the ``original`` step — that's the
    overwhelming majority of sections and we don't want to clutter the
    prompt. For sections with applied amendments, we list each step on
    its own line and mark the one that produced the current text. Future
    (post-``as_of``) amendments get a separate line that's deliberately
    short so the LLM doesn't quote from them.
    """
    if effective is None or not effective.chain:
        return []
    # Only original step + nothing applied? Skip.
    interesting = [s for s in effective.chain if s.provenance != "original"]
    if not interesting and not effective.has_future_amendments:
        return []

    lines: list[str] = []
    header = "  Version chain"
    if as_of is not None:
        header += f" (as of {as_of.isoformat()})"
    lines.append(header + ":")
    last_applied = effective.chain[-1] if effective.chain else None
    for step in effective.chain:
        marker = "·"
        date_str = step.effective_date.isoformat() if step.effective_date else "undated"
        verb = step.provenance
        tag = " — current text used" if step is last_applied and verb != "original" else ""
        lines.append(f"    {marker} {date_str} {verb}{tag}")
    if effective.has_future_amendments:
        lines.append(
            f"    · future amendments exist (effective after {as_of.isoformat() if as_of else 'today'} — not applied)"
        )
    return lines


def _kumotaan_placeholder(as_of: date | None) -> str:
    """Body to render when the most recent applied step was ``kumotaan``.

    The LLM should not confabulate text for a repealed section, so we
    write a short, explicit placeholder it can cite.
    """
    when = f"as of {as_of.isoformat()}" if as_of else "as of the requested date"
    return f"[Section repealed {when} — no operative text.]"


# --------------------------------------------------------------------------
# Edge rendering — Layer 5
# --------------------------------------------------------------------------


def _edge_arrow_phrase(edge_type: str, outgoing: bool) -> str:
    """Map (edge_type, direction) → a human-readable verb phrase.

    Outgoing means "this source has the edge pointing out at the other
    source" — e.g. source A *cites* source B. Incoming flips voice.
    """
    if outgoing:
        return {
            "cites": "Cites",
            "interprets": "Interprets",
            "amends": "Amends",
            "defines": "Defines",
        }.get(edge_type, edge_type)
    return {
        "cites": "Cited by",
        "interprets": "Interpreted by",
        "amends": "Amended by",
        "defines": "Defined by",
    }.get(edge_type, f"Reverse-{edge_type}")


def _render_edges_for_source(
    section_id: str,
    section_id_to_index: dict[str, int],
    graph: GraphStore,
) -> list[str]:
    """Return one rendered edge line per inter-source edge.

    De-duplicates parallel edges (multiple ``cites`` between the same pair
    collapse into a single line — the LLM doesn't benefit from seeing the
    same arrow twice).
    """
    own_index = section_id_to_index[section_id]
    seen: set[tuple[str, str, int]] = set()
    lines: list[str] = []

    neighbors: list[Neighbor] = graph.get_neighbors(
        section_id,
        edge_types=list(RENDERED_EDGE_TYPES),
        direction="both",
    )
    for nbr in neighbors:
        target_index = section_id_to_index.get(nbr.node_id)
        if target_index is None or target_index == own_index:
            continue
        outgoing = nbr.direction == "out"
        key = (nbr.edge.type, "out" if outgoing else "in", target_index)
        if key in seen:
            continue
        seen.add(key)
        verb = _edge_arrow_phrase(nbr.edge.type, outgoing)
        arrow = "→" if outgoing else "←"
        lines.append(f"  {verb}: {arrow} [Source {target_index}]")
    return lines


# --------------------------------------------------------------------------
# Body trimming
# --------------------------------------------------------------------------


# Soft cap per source. Whole-chunk bodies in this corpus average ~1k chars
# but some run to 5k+; capping at 1200 keeps the assembled prompt within
# LLM-friendly budgets at N=8 sources. Sentence-aware truncation: prefer
# cutting at a paragraph or sentence boundary.
MAX_BODY_CHARS = 1200


def _trim_body(body: str, limit: int = MAX_BODY_CHARS) -> str:
    if len(body) <= limit:
        return body
    head = body[:limit]
    # Prefer trimming at the last sentence boundary inside the window.
    cut = max(head.rfind(". "), head.rfind(".\n"), head.rfind("\n\n"))
    if cut > limit // 2:
        return head[: cut + 1].rstrip() + " […]"
    return head.rstrip() + " […]"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def assemble(
    reranked: list[RerankedHit],
    *,
    graph: GraphStore,
    n: int = 8,
    as_of: date | None = None,
) -> AssembledContext:
    """Take the top-N reranked hits and render the LLM context.

    Dedups by section_id first (so N is the number of *distinct sections*,
    not chunks), renders the prescribed header/path/edges/body format, and
    returns the assembled string + the Source→chunk_id mapping.

    Each rendered block carries:
      * ancestor-aware temporal_status lines (Step 9 / Move 4)
      * the version chain that produced its body (Step 10 / Move 5b)

    ``as_of`` (Step 10): when supplied, the assembler calls
    ``GraphStore.text_at(section_id, as_of=as_of)`` for every cited
    SECTION and uses the resulting effective text as the body — so
    a question about 2019-era rules gets 2019-era wording, not the
    consolidated current text. Defaults to None, which means
    ``text_at`` uses today.
    """
    deduped = dedup_by_section(reranked)[:n]
    if not deduped:
        return AssembledContext(text="", sources=[], as_of_used=as_of)

    section_id_to_index = {r.hit.section_id: i + 1 for i, r in enumerate(deduped)}

    # One DB roundtrip for the temporal_status of every shown section.
    # Mirrors what the rerank step already does; results are tiny so this
    # is cheap enough to repeat.
    temporal_status_map = graph.get_temporal_status_map(
        [r.hit.section_id for r in deduped]
    )

    sources: list[Source] = []
    blocks: list[str] = []
    for idx, r in enumerate(deduped, start=1):
        hit = r.hit
        prefix, body = _split_prefix_body(hit.embedded_text)
        path = _extract_path(prefix)
        title = _extract_title(prefix)
        temporal_status = temporal_status_map.get(hit.section_id)

        # Effective text via the version chain. Cheap when the chain
        # is empty (no extra DB hits beyond the one Read). For sections
        # *with* a chain, this is what makes the answer reflect the
        # right point in time.
        effective: EffectiveText = graph.text_at(hit.section_id, as_of=as_of)
        # Use the effective body when (a) there is a chain that changes
        # things, or (b) the chunk's embedded body is empty. Otherwise
        # the chunk's embedded body is the safer choice — it includes
        # all the subsection/item children that pack_section bundled,
        # which text_at on a SECTION alone may not.
        chain_changed = len(effective.chain) > 1 or any(
            s.provenance != "original" for s in effective.chain
        )
        if effective.text is None and chain_changed:
            # kumotaan as of as_of — write the placeholder explicitly.
            body_for_render = _kumotaan_placeholder(as_of)
        elif chain_changed and effective.text:
            body_for_render = effective.text
        else:
            body_for_render = body

        header = _header_line(
            index=idx,
            hit_subcorpus=hit.source_subcorpus,
            title=title,
            in_force=hit.in_force,
            usable=hit.usable,
            authority_rank=hit.authority_rank,
            publication_date=hit.publication_date,
            temporal_status=temporal_status,
        )

        lines: list[str] = [header]
        if path:
            lines.append(f"  Path: {path}")

        edge_lines = _render_edges_for_source(
            hit.section_id, section_id_to_index, graph
        )
        lines.extend(edge_lines)
        lines.extend(_temporal_lines(temporal_status))
        lines.extend(_version_chain_lines(effective, as_of))

        body_text = _trim_body(body_for_render) if body_for_render else ""
        lines.append("")  # blank line between header block and body
        lines.append(body_text)

        block = "\n".join(lines)
        blocks.append(block)
        sources.append(
            Source(
                label=f"[Source {idx}]",
                index=idx,
                chunk_id=hit.chunk_id,
                section_id=hit.section_id,
                rerank_score=r.score,
                cosine_sim=hit.cosine_sim,
                rendered_block=block,
                effective_text=effective.text if chain_changed else (body or None),
                version_chain=tuple(effective.chain) if chain_changed else (),
                has_future_amendments=effective.has_future_amendments,
            )
        )

    text = "\n\n".join(blocks)
    return AssembledContext(text=text, sources=sources, as_of_used=as_of)
