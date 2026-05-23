"""Build ``AmendmentCaveat`` records from cited chunks' temporal_status.

Move 5. Lives in its own module so both ``pipeline.py`` (v1) and
``pipeline_v2.py`` can call it without duplicating the rendering logic.

Inputs:
- The list of cited chunks (post-generation, ``Generation.cited_chunk_ids``).
- A mapping from chunk_id → section_id (the assembled-context sources).
- A ``GraphStore`` to look up each section's ``temporal_status``.

Output:
- ``list[AmendmentCaveat]`` — empty when every cited chunk's parent chain
  is clean.
"""
from __future__ import annotations

import re

from src.indexing.graph_store import GraphStore
from src.models import AmendmentCaveat
from src.retrieval.assemble import AssembledContext


# Lowest grade that warrants a caveat. ``ok`` never produces one — the
# absence of the entry in ``amendment_caveats`` is the signal.
_FLAGGED = {"suspect", "stale", "repealed"}


def _law_root_of(node_id: str) -> str:
    parts = node_id.split("/")
    return "/".join(parts[:3]) if len(parts) >= 3 else node_id


def _is_amendment_instrument(law_id: str) -> bool:
    """True when the LAW root is itself a one-shot amendment instrument.

    Pattern: ``finlex/laki/...-muuttamisesta-...``. These are stable in
    isolation — their own ``temporal_status`` will be "ok" — but the
    *target* consolidated LAW they amend may have a richer amendment
    history we want to surface as a caveat for citations that quote them.
    """
    return "muuttamisesta" in law_id.lower()


# Match a Finnish-legal-name stem in the *genitive* (`-lain` / `-uksen`)
# embedded in an amendment-instrument law id. Anchors on word boundaries
# (`-`) on both sides so the publisher prefix and section-number suffix
# don't get swept in. Examples that should match:
#   - rikoslain                       (from "...-rikoslain-muuttamisesta-...")
#   - tuloverolain                    ("...-tuloverolain-77-n-muuttamisesta-...")
#   - arvonlisaverolain               ("...-arvonlisaverolain-114-n-...")
_GENITIVE_TOKEN_PAT = re.compile(
    r"-([a-zäöå]+(?:lain|uksen))(?:-|$)", re.IGNORECASE
)


def _genitive_to_nominative(slug: str) -> str | None:
    """Turn ``rikoslain`` → ``rikoslaki``, ``tuloverolain`` → ``tuloverolaki``.

    Finnish rule of thumb: a noun in -lain (genitive of -laki) → -laki.
    The same applies to -säädöksen / -asetuksen but we focus on -lain
    because amendment-instrument acts mostly target laws.
    """
    if slug.endswith("lain"):
        # rikoslain → rikoslaki (strip ``in``, append ``ki``)
        return slug[:-2] + "ki"
    # ``asetuksen`` → ``asetus`` (genitive of -us): strip ``ksen``, add ``s``.
    if slug.endswith("uksen"):
        return slug[:-4] + "s"
    return None


def _interpreted_or_cited_law_targets(
    graph: GraphStore, section_id: str
) -> list[str]:
    """Return distinct LAW roots that this section (or its descendants)
    interprets or cites.

    Used for cross-source caveats: a Vero ohje that interprets AVL § 102
    is "indirectly suspect" if AVL has been amended after the ohje's
    publication. The actual interprets/cites edges almost always live on
    leaf SUBSECTION / ITEM descendants of the cited SECTION (the chunk
    anchors at SECTION level, but the typed edges live one structural
    hop down), so we ``LIKE`` on the section's id prefix to sweep them up.
    """
    # Match both ``section_id`` itself and anything under it.
    cur = graph.conn.execute(
        "SELECT DISTINCT target_id FROM edges "
        "WHERE (source_id = ? OR source_id LIKE ?) "
        "AND type IN ('interprets','cites') "
        "AND target_id IS NOT NULL",
        (section_id, section_id + "/%"),
    )
    roots: list[str] = []
    seen: set[str] = set()
    for (tgt,) in cur:
        root = _law_root_of(tgt)
        if root and root not in seen:
            seen.add(root)
            roots.append(root)
    return roots


def _amends_target_for(
    graph: GraphStore, amendment_law_id: str
) -> str | None:
    """Find the target LAW for an amendment-instrument LAW.

    Two strategies, in order:
      1. Follow outbound ``amends`` edges (the Step-2 regex extractor
         resolved a few dozen of these).
      2. If no edges exist (the common case — Step 2 missed most),
         infer the target by inverting the Finnish genitive in the
         amendment law's id slug and searching the LAW table.
    """
    # Strategy 1 — outbound edges from anywhere under this amendment law.
    cur = graph.conn.execute(
        "SELECT target_id, COUNT(*) FROM edges "
        "WHERE source_id LIKE ? AND type = 'amends' AND target_id IS NOT NULL "
        "GROUP BY target_id ORDER BY 2 DESC LIMIT 1",
        (amendment_law_id + "%",),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # Strategy 2 — slug-based inference. Robust for the common
    # ``laki-X:n-muuttamisesta-...`` pattern; silently gives up otherwise.
    if "muuttamisesta" not in amendment_law_id.lower():
        return None
    m = _GENITIVE_TOKEN_PAT.search(amendment_law_id)
    if not m:
        return None
    nominative = _genitive_to_nominative(m.group(1).lower())
    if not nominative:
        return None
    # Search both the Laki and Säädöskokoelma subcorpora. Prefer Laki
    # (the consolidated edition) over Säädöskokoelma when both exist.
    cur = graph.conn.execute(
        "SELECT id FROM nodes WHERE type='LAW' "
        "AND id LIKE ? AND source='finlex' "
        "ORDER BY CASE WHEN id LIKE 'finlex/laki/%' THEN 0 ELSE 1 END LIMIT 1",
        (f"%-{nominative}-html-%",),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _format_explanation_fi(status: dict) -> str:
    """One short Finnish sentence per caveat, ready for the answer footer."""
    grade = status.get("effective_usable")
    amendment_count = status.get("amendment_count_in_law") or 0
    after = status.get("ancestor_amended_after")
    interp_count = status.get("interpreted_count") or 0
    latest_interp = status.get("latest_interpretation_date")

    if grade == "repealed":
        # Self- or ancestor-level repeal. Short, direct.
        return (
            "Tämä lähde tai sen emolaki on kumottu — älä käytä nykytilaa "
            "koskevaan vastaukseen ilman varmistusta."
        )

    if grade == "stale":
        return (
            "Tämän lähteen emolaki on korvattu uudemmalla säädöksellä. "
            "Tarkista voimassa oleva versio ennen siteerausta."
        )

    # grade == "suspect"
    parts: list[str] = []
    if amendment_count and after:
        parts.append(
            f"Emolaissa on {amendment_count} muutosta, joista uusin on "
            f"voimassa {after} alkaen ja saattaa olla tuoreempi kuin "
            f"tämä teksti."
        )
    elif amendment_count:
        parts.append(
            f"Emolaissa on {amendment_count} muutosta — varmista, että "
            f"tämä teksti vastaa nykyistä konsolidoitua versiota."
        )
    if interp_count and latest_interp:
        parts.append(
            f"Pykälällä tai sen emolailla on {interp_count} oikeuskäytäntö-"
            f"tulkintaa (uusin {latest_interp})."
        )
    elif interp_count:
        parts.append(
            f"Pykälällä tai sen emolailla on {interp_count} "
            f"oikeuskäytäntötulkintaa."
        )
    return " ".join(parts) or (
        "Lähteen ajallinen status on epävarma — tarkista voimassaolo."
    )


def build_amendment_caveats(
    *,
    cited_chunk_ids: list[str],
    context: AssembledContext,
    graph: GraphStore,
) -> list[AmendmentCaveat]:
    """Build one caveat per cited chunk whose section has a flagged grade.

    Dedupes on ``section_id`` so a question that cites two chunks of the
    same section only produces one caveat. Order follows the order the LLM
    cited the sections in.
    """
    if not cited_chunk_ids:
        return []

    # Build a chunk_id → section_id index from the assembled sources. The
    # generator can cite chunks that landed in the context but not all
    # context chunks are cited — we only fetch the ones we actually need.
    chunk_to_section: dict[str, str] = {
        s.chunk_id: s.section_id for s in context.sources
    }
    cited_sections: list[str] = []
    section_to_chunk: dict[str, str] = {}
    seen_sections: set[str] = set()
    for cid in cited_chunk_ids:
        sid = chunk_to_section.get(cid)
        if sid is None or sid in seen_sections:
            continue
        seen_sections.add(sid)
        cited_sections.append(sid)
        section_to_chunk[sid] = cid

    if not cited_sections:
        return []

    # Three lookups, in fallback order:
    #   1. The cited section's own temporal_status.
    #   2. If the citation lives in an amendment instrument
    #      ("...muuttamisesta..."), the target consolidated LAW's status.
    #   3. If the citation has outbound interprets/cites edges (typical
    #      for Vero ohjeet and KHO cases), the temporal_status of every
    #      LAW it cites. This is what lets a Vero guidance citation
    #      surface "the AVL section it interprets has been amended 149
    #      times" even when the Vero ohje itself is on a clean own-status.
    status_map = graph.get_temporal_status_map(cited_sections)

    amendment_targets: dict[str, str] = {}            # section_id → law_id
    citation_targets: dict[str, list[str]] = {}       # section_id → [law_id]
    extra_lookup_ids: set[str] = set()
    for sid in cited_sections:
        law_id = _law_root_of(sid)
        if _is_amendment_instrument(law_id):
            target = _amends_target_for(graph, law_id)
            if target and target != law_id:
                amendment_targets[sid] = target
                extra_lookup_ids.add(target)
        # Outbound interprets/cites — collect target laws regardless of
        # whether the citation itself is an amendment instrument. The
        # caller will only consult these if the first two lookups don't
        # surface a flagged status.
        cited_laws = _interpreted_or_cited_law_targets(graph, sid)
        if cited_laws:
            # Skip self-reference (interprets within the same LAW).
            citation_targets[sid] = [
                lid for lid in cited_laws if lid != law_id
            ]
            extra_lookup_ids.update(citation_targets[sid])

    if extra_lookup_ids:
        target_status_map = graph.get_temporal_status_map(list(extra_lookup_ids))
    else:
        target_status_map = {}

    caveats: list[AmendmentCaveat] = []
    for sid in cited_sections:
        status = status_map.get(sid)

        # Prefer the cited section's own status when it's flagged.
        if isinstance(status, dict) and status.get("effective_usable") in _FLAGGED:
            chosen_status = status
        else:
            # Amendment-instrument fallback: target consolidated LAW.
            chosen_status = None
            target = amendment_targets.get(sid)
            target_status = target_status_map.get(target) if target else None
            if (
                isinstance(target_status, dict)
                and target_status.get("effective_usable") in _FLAGGED
            ):
                chosen_status = target_status

            # Cross-source fallback: any LAW this citation interprets/cites
            # with a flagged status. Pick the *most-amended* one as the
            # representative — that's the worst-case caveat.
            if chosen_status is None:
                worst_status: dict | None = None
                worst_count = -1
                for tgt_law in citation_targets.get(sid, []):
                    tgt_status = target_status_map.get(tgt_law)
                    if (
                        isinstance(tgt_status, dict)
                        and tgt_status.get("effective_usable") in _FLAGGED
                    ):
                        count = tgt_status.get("amendment_count_in_law") or 0
                        if count > worst_count:
                            worst_count = count
                            worst_status = tgt_status
                if worst_status is not None:
                    chosen_status = worst_status

            if chosen_status is None:
                continue

        caveats.append(
            AmendmentCaveat(
                chunk_id=section_to_chunk[sid],
                section_id=sid,
                kind=chosen_status.get("effective_usable"),  # type: ignore[arg-type]
                nearest_amendment_id=chosen_status.get("nearest_amendment_id"),
                amendment_effective_date=chosen_status.get("ancestor_amended_after"),
                amendment_count_in_law=chosen_status.get("amendment_count_in_law"),
                interpreted_count=chosen_status.get("interpreted_count"),
                latest_interpretation_date=chosen_status.get(
                    "latest_interpretation_date"
                ),
                explanation_fi=_format_explanation_fi(chosen_status),
            )
        )
    return caveats
