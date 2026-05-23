"""B2.7 — Edge resolution.

Takes the raw `(source_id, CitationKey, raw_target_ref, type, confidence,
extracted_by, context_snippet)` tuples that extractors emit and produces
final `Edge` records. Resolution:

    1. Ask `NodeIndex.resolve(key, default_law_id=source_law)` for a node id.
    2. If found → resolved edge.
    3. If not found → dangling edge with a categorized reason:
         - `out_of_corpus`        : ref clearly outside what we ingest (EU, HE)
         - `not_yet_parsed`       : ref *should* be in our corpus, lookup missed
         - `normalization_failed` : the citation didn't form a usable key

The function is a generator so callers can stream straight to disk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

from src.extraction.ids import CitationKey
from src.extraction.node_index import NodeIndex
from src.models import DanglingReason, Edge, EdgeType, ExtractionMethod


@dataclass
class RawMatch:
    """Pre-resolution extractor output."""

    source_id: str
    target_ref: str               # raw citation string, kept on every edge
    key: Optional[CitationKey]    # None = normalization failed
    type: EdgeType
    confidence: float
    extracted_by: ExtractionMethod
    context_snippet: Optional[str] = None
    source_law_id: Optional[str] = None  # used as default_law_id by the resolver


def resolve_matches(
    matches: Iterable[RawMatch],
    node_index: NodeIndex,
) -> Iterator[Edge]:
    for m in matches:
        if m.key is None:
            yield Edge(
                source_id=m.source_id,
                target_id=None,
                target_ref=m.target_ref,
                type=m.type,
                confidence=m.confidence,
                extracted_by=m.extracted_by,
                context_snippet=m.context_snippet,
                dangling_reason="normalization_failed",
            )
            continue

        target_id = node_index.resolve(m.key, default_law_id=m.source_law_id)
        if target_id is not None:
            yield Edge(
                source_id=m.source_id,
                target_id=target_id,
                target_ref=m.target_ref,
                type=m.type,
                confidence=m.confidence,
                extracted_by=m.extracted_by,
                context_snippet=m.context_snippet,
            )
            continue

        # Lookup miss — classify why.
        if m.key.is_out_of_corpus():
            reason: DanglingReason = "out_of_corpus"
        else:
            reason = "not_yet_parsed"
        yield Edge(
            source_id=m.source_id,
            target_id=None,
            target_ref=m.target_ref,
            type=m.type,
            confidence=m.confidence,
            extracted_by=m.extracted_by,
            context_snippet=m.context_snippet,
            dangling_reason=reason,
        )
