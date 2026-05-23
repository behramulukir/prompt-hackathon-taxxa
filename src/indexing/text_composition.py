"""Hierarchy-prefixed embedding text composition (Step 4a.2, Option B).

Pure function — no I/O. Used both during the embedding pass and for spot
checks. Format::

    [Source: finlex_laki · in force]
    [Path: Arvonlisaverolaki > Luku 10 > § 102]
    [Title: Vahennysoikeus]

    {chunk.text}

The prefix is the only mitigation we have for jurisdiction-blindness; the
embedding model uses these signals to disambiguate near-identical legal text
across statutes, subcorpora, and amendment chains.
"""
from __future__ import annotations

from src.indexing.node_index import NodeIdxEntry, walk_to_root


def _source_tag(entry: NodeIdxEntry) -> str:
    """Render the publisher/subcorpus as a single legacy-style tag for the
    Source line, matching the brief's example (finlex_laki, vero_ohje, ...).
    """
    return f"{entry.source}_{entry.source_subcorpus}"


def _path_titles(chain: list[NodeIdxEntry]) -> list[str]:
    """Collect title/label strings up the parent chain, root first.

    The chain comes in leaf->root order; we reverse for display. We skip
    nodes that contribute nothing useful (no title and no label).
    """
    titles: list[str] = []
    for entry in reversed(chain):
        if entry.title:
            titles.append(entry.title)
        elif entry.label:
            titles.append(entry.label)
    return titles


def compose_embedding_text(
    *,
    chunk_text: str,
    section_id: str,
    node_index: dict[str, NodeIdxEntry],
) -> str:
    """Build the hierarchy-prefixed text that gets embedded.

    Pure function: only reads from the supplied node_index. Missing fields
    simply collapse — the relevant brackets are omitted rather than faked.
    """
    chain = walk_to_root(section_id, node_index)
    primary = chain[0] if chain else None

    lines: list[str] = []

    # --- [Source: ... · in force] -----------------------------------------
    if primary is not None:
        source_tag = _source_tag(primary)
        if primary.in_force is True:
            lines.append(f"[Source: {source_tag} · in force]")
        elif primary.in_force is False:
            lines.append(f"[Source: {source_tag} · repealed]")
        else:
            lines.append(f"[Source: {source_tag}]")

    # --- [Path: A > B > C] ------------------------------------------------
    titles = _path_titles(chain)
    if titles:
        lines.append(f"[Path: {' > '.join(titles)}]")

    # --- [Title: ...] -----------------------------------------------------
    # Title line is the leaf's own title/label when meaningful.
    if primary is not None:
        leaf_title = primary.title or primary.label
        if leaf_title:
            lines.append(f"[Title: {leaf_title}]")

    prefix = "\n".join(lines)
    if not prefix:
        return chunk_text
    return f"{prefix}\n\n{chunk_text}"
