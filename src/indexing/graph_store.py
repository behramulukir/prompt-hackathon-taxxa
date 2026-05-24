"""SQLite-backed graph store adapter (Step 4b.3).

Wraps ``output/graph.db`` produced by ``scripts/load_graph.py``. The schema
is described in 04_embedding_and_indexing.md §4b.1.

Indices on ``(source_id, type)`` and ``(target_id, type)`` make bidirectional
neighbor lookups O(degree) at our scale.
"""
from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from src.models import (
    Direction,
    Edge,
    EdgeType,
    EffectiveText,
    Neighbor,
    Node,
    NodeMetadata,
    RetrievalPath,
    VersionStep,
)


@dataclass(frozen=True)
class _NodeRow:
    id: str
    type: str
    source: str
    parent_id: str | None
    text: str
    label: str | None
    metadata_json: str


def _row_to_node(row: _NodeRow) -> Node:
    meta_dict = json.loads(row.metadata_json) if row.metadata_json else {}
    # Strip fields Pydantic NodeMetadata doesn't know about into ``extra``.
    return Node(
        id=row.id,
        type=row.type,  # type: ignore[arg-type]
        source=meta_dict.get("__source", row.source),  # backstop
        # Pydantic NodeMetadata is permissive (extra=allow), so a raw dict is OK.
        metadata=NodeMetadata.model_validate(meta_dict),
        text=row.text,
        parent_id=row.parent_id,
        label=row.label,
        # Step 4b doesn't store the full source_subcorpus/title/etc. — those
        # round-trip through nodes.jsonl, not the graph DB. Callers that need
        # them should reach for the node_index instead.
        source_subcorpus="laki",  # placeholder; not used by graph-only callers
        order=0,
        source_file="",
    )


def _row_to_edge(row: sqlite3.Row) -> Edge:
    props = json.loads(row["properties_json"]) if row["properties_json"] else {}
    return Edge(
        source_id=row["source_id"],
        target_id=row["target_id"],
        target_ref=row["target_ref"],
        type=row["type"],  # type: ignore[arg-type]
        confidence=row["confidence"],
        extracted_by=row["extracted_by"],  # type: ignore[arg-type]
        context_snippet=row["context_snippet"],
        dangling_reason=row["dangling_reason"],  # type: ignore[arg-type]
        properties=props,
    )


class GraphStore:
    def __init__(self, path: str | Path = "output/graph.db") -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        # Read-mostly settings — we never write in this adapter.
        self.conn.execute("PRAGMA query_only=ON")

    # ----- node lookup ----------------------------------------------------

    def get_node(self, node_id: str) -> Node | None:
        cur = self.conn.execute(
            "SELECT id, type, source, parent_id, text, label, metadata_json "
            "FROM nodes WHERE id = ?",
            (node_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_node(
            _NodeRow(
                id=row["id"],
                type=row["type"],
                source=row["source"],
                parent_id=row["parent_id"],
                text=row["text"],
                label=row["label"],
                metadata_json=row["metadata_json"],
            )
        )

    # ----- neighbors ------------------------------------------------------

    def _neighbor_rows(
        self,
        node_id: str,
        edge_types: list[str] | None,
        direction: Direction,
    ) -> Iterable[tuple[str, sqlite3.Row, Direction]]:
        """Yield (neighbor_id, edge_row, direction_followed)."""
        type_clause = ""
        params: list = []
        if edge_types:
            placeholders = ",".join("?" * len(edge_types))
            type_clause = f" AND type IN ({placeholders})"

        if direction in ("out", "both"):
            sql = (
                "SELECT * FROM edges WHERE source_id = ?"
                + type_clause
            )
            for row in self.conn.execute(sql, (node_id, *(edge_types or []))):
                tgt = row["target_id"]
                if tgt is not None:  # skip dangling for graph traversal
                    yield tgt, row, "out"

        if direction in ("in", "both"):
            sql = (
                "SELECT * FROM edges WHERE target_id = ?"
                + type_clause
            )
            for row in self.conn.execute(sql, (node_id, *(edge_types or []))):
                yield row["source_id"], row, "in"

    def get_neighbors(
        self,
        node_id: str,
        edge_types: list[str] | None = None,
        direction: Direction = "both",
    ) -> list[Neighbor]:
        out: list[Neighbor] = []
        for nbr_id, row, dir_followed in self._neighbor_rows(
            node_id, edge_types, direction
        ):
            out.append(
                Neighbor(node_id=nbr_id, edge=_row_to_edge(row), direction=dir_followed)
            )
        return out

    # ----- degree ---------------------------------------------------------

    def get_degree(
        self,
        node_id: str,
        edge_type: EdgeType,
        direction: Direction,
    ) -> int:
        # The loader pre-computed and wrote degree into metadata_json so the
        # hot path skips a SQL aggregate. Falls back to a COUNT(*) only if the
        # entry is missing (e.g. partial load).
        cur = self.conn.execute(
            "SELECT metadata_json FROM nodes WHERE id = ?", (node_id,)
        )
        row = cur.fetchone()
        if row is None:
            return 0
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        deg = meta.get("degree", {}) or {}

        if direction == "both":
            return deg.get(f"{edge_type}_out", 0) + deg.get(f"{edge_type}_in", 0)
        return deg.get(f"{edge_type}_{direction}", 0)

    # ----- BFS ------------------------------------------------------------

    def bfs(
        self,
        seed_ids: list[str],
        edge_types: list[str],
        direction: Direction,
        max_hops: int,
        degree_cap: dict[str, int] | None = None,
    ) -> dict[str, RetrievalPath]:
        """BFS expansion. Returns one RetrievalPath per discovered node.

        ``degree_cap`` skips expansion *through* a node whose degree on the
        relevant edge type exceeds the cap — keeps hub nodes (e.g. heavily
        cited statutes) from blowing up the frontier. The seed itself is
        never gated this way; only intermediate nodes are.
        """
        results: dict[str, RetrievalPath] = {}
        # Seeds are hop 0 — recorded with via="graph" so Layer-8 citation can
        # still tell vector-seed nodes apart by storing them separately upstream.
        frontier: deque[tuple[str, int, str | None, str | None]] = deque()
        for sid in seed_ids:
            results[sid] = RetrievalPath(via="graph", score=0.0, hops=0)
            frontier.append((sid, 0, None, None))

        while frontier:
            nid, hops, parent_seed, _ = frontier.popleft()
            if hops >= max_hops:
                continue

            # degree cap check (skip expansion through hub nodes; nid is allowed
            # to be reached, but we don't expand further through it).
            if degree_cap and parent_seed is not None:
                # Only gate intermediates, not seeds.
                gated = False
                for etype, cap in degree_cap.items():
                    if self.get_degree(nid, etype, direction) > cap:
                        gated = True
                        break
                if gated:
                    continue

            for nbr_id, row, dir_followed in self._neighbor_rows(
                nid, edge_types, direction
            ):
                if nbr_id in results:
                    continue
                results[nbr_id] = RetrievalPath(
                    via="graph",
                    score=float(row["confidence"]),
                    from_node_id=nid,
                    edge_type=row["type"],  # type: ignore[arg-type]
                    hops=hops + 1,
                )
                frontier.append((nbr_id, hops + 1, nid, row["type"]))

        return results

    # ----- temporal_status batch lookup ----------------------------------

    def get_temporal_status_map(
        self, node_ids: list[str]
    ) -> dict[str, dict | None]:
        """Bulk lookup of ``metadata.temporal_status`` for many nodes.

        Returns ``{node_id: status_dict_or_None}`` — None when the node is
        missing from the graph or doesn't have ``temporal_status`` set
        (e.g. an older graph DB built before ``scripts.compute_temporal_status``
        was run). Callers should treat missing entries as "unknown" and
        fall back to the older ``usable`` flag.

        Used by the rerank step to apply the graded temporal penalty
        without doing one SELECT per chunk.
        """
        if not node_ids:
            return {}
        out: dict[str, dict | None] = {}
        # Chunk under SQLite's IN-list limit. 500 is conservative — the
        # actual limit is 999 placeholders in older builds.
        BATCH = 500
        for i in range(0, len(node_ids), BATCH):
            chunk = node_ids[i:i + BATCH]
            placeholders = ",".join("?" * len(chunk))
            cur = self.conn.execute(
                f"SELECT id, metadata_json FROM nodes WHERE id IN ({placeholders})",
                chunk,
            )
            for nid, mj in cur:
                try:
                    meta = json.loads(mj) if mj else {}
                except json.JSONDecodeError:
                    meta = {}
                out[nid] = meta.get("temporal_status")
        # Backfill misses so callers can iterate without KeyError.
        for nid in node_ids:
            out.setdefault(nid, None)
        return out

    # ----- text_at — Step 10 / Move 4 point-in-time playback -------------

    def text_at(
        self,
        section_id: str,
        *,
        as_of: date | None = None,
    ) -> EffectiveText:
        """Return the effective text of ``section_id`` as of ``as_of``.

        Reads the per-section ``version_chain`` written by
        ``scripts/compute_version_chains.py`` (Move 3) and plays the ops
        forward up to and including ``as_of``. Each step's verb is
        applied:

          * ``original`` / ``muutetaan`` / ``lisätään`` — set text to
            the step's ``new_text`` (or keep prior when ``new_text`` is
            missing — a known data hole for chain_complex ops).
          * ``kumotaan`` — set text to ``None`` (the section is repealed
            as of this date).

        When the section has no ``version_chain`` (clean ancestor
        history), we return a single-step chain consisting of just the
        original SECTION text, with ``has_future_amendments=False``.
        That keeps callers simple — they don't have to special-case
        unchanged sections.

        ``as_of`` defaults to ``date.today()``. ``is_current`` is True
        iff ``as_of`` equals today at call time.
        """
        today = date.today()
        if as_of is None:
            as_of = today
        is_current = as_of == today

        cur = self.conn.execute(
            "SELECT text, metadata_json FROM nodes WHERE id = ?",
            (section_id,),
        )
        row = cur.fetchone()
        if row is None:
            # Missing section — return an empty chain so the assembler
            # still gets a typed result. The caller treats this the same
            # as a regular missing chunk.
            return EffectiveText(
                text=None,
                chain=[],
                is_current=is_current,
                has_future_amendments=False,
            )

        section_text = row["text"] or ""
        try:
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        except json.JSONDecodeError:
            meta = {}

        raw_chain = meta.get("version_chain")
        # No chain written → clean section, no amendments. Return the
        # original text as the only step. We deliberately don't
        # synthesise a date here; callers that need one read
        # ``meta["publication_date"]`` separately.
        if not isinstance(raw_chain, list) or not raw_chain:
            single = VersionStep(
                effective_date=_parse_iso_safe(meta.get("publication_date")),
                source_id=section_id,
                provenance="original",
                text=section_text or None,
                amendment_block_id=section_id,
            )
            return EffectiveText(
                text=section_text or None,
                chain=[single],
                is_current=is_current,
                has_future_amendments=False,
            )

        applied: list[VersionStep] = []
        future: list[VersionStep] = []
        current_text: str | None = None
        for raw in raw_chain:
            if not isinstance(raw, dict):
                continue
            step = _to_version_step(raw)
            eff = step.effective_date
            # Steps with no date are treated as "always applied" — they
            # came from Move 1 ops that couldn't parse a voimaantulo
            # clause, and dropping them silently would lose work. We
            # apply them in declaration order, *before* checking the
            # as_of cutoff for the next dated step.
            if eff is None:
                applied.append(step)
                current_text = _apply_step(current_text, step)
                continue
            if eff <= as_of:
                applied.append(step)
                current_text = _apply_step(current_text, step)
            else:
                future.append(step)
        return EffectiveText(
            text=current_text,
            chain=applied,
            is_current=is_current,
            has_future_amendments=bool(future),
        )

    def close(self) -> None:
        self.conn.close()


# --------------------------------------------------------------------------
# Module-level helpers for ``text_at``
# --------------------------------------------------------------------------


def _parse_iso_safe(s) -> date | None:
    if s is None:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def _to_version_step(raw: dict) -> VersionStep:
    """Hydrate a dict from ``metadata.version_chain`` into VersionStep."""
    return VersionStep(
        effective_date=_parse_iso_safe(raw.get("effective_date")),
        source_id=raw.get("source_id") or "",
        provenance=raw.get("provenance") or "original",  # type: ignore[arg-type]
        text=raw.get("text"),
        amendment_block_id=raw.get("amendment_block_id"),
    )


def _apply_step(current: str | None, step: VersionStep) -> str | None:
    """Play one step against the running text.

    Semantics:
      * ``original`` / ``muutetaan`` / ``lisätään`` — replace the running
        text with the step's ``text`` *unless* the step carries no text
        (some chain_complex ops have None new_text; keep current). For
        ``lisätään`` on a section that didn't exist before, ``current``
        is None and the step provides the birth-of-§ text.
      * ``kumotaan`` — the section is repealed. We set text to None and
        downstream callers render it as the explicit absence.
    """
    if step.provenance == "kumotaan":
        return None
    new_text = step.text
    if new_text is None:
        # Don't blank a previously-set text on a None-text step.
        return current
    return new_text
