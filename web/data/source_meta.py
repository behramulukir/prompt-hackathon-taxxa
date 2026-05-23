"""Lookup interface for the source_meta.json cache.

Used by source_pill.py to render citation hover tooltips. The cache is loaded
once at import time — it's small (<20 entries today, will scale to <500 when
we cover more demo questions).

When Track D ships the real pipeline, this module will be replaced by a call
to GraphStore.get_chunk(chunk_id) plus a get_node() lookup for authority_rank.
The interface (lookup() returning a SourceMeta dict) stays the same so the
pill component doesn't change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

_CACHE_PATH = Path(__file__).parent / "source_meta.json"


class SourceMeta(TypedDict, total=False):
    publisher: str           # "finlex" | "vero"
    subcorpus: str           # "laki" | "vero_ohje" | …
    label: str               # human-readable, e.g. "§ 124 · Laki tuloverolain…"
    authority_rank: int      # 0–100 (provisional; V3.2 unsigned)
    authority_tier: str      # "binding" | "interpretive"
    excerpt: str             # 1–3 lines for hover preview
    law_id: str | None
    section_id: str | None
    synthetic: bool          # True for MockPipeline-only IDs


_data: dict[str, SourceMeta] | None = None


def _load() -> dict[str, SourceMeta]:
    global _data
    if _data is None:
        if not _CACHE_PATH.exists():
            _data = {}
        else:
            _data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    return _data


def lookup(chunk_id: str) -> SourceMeta:
    """Return metadata for a chunk_id, with sensible defaults if unknown.

    Never raises — if a chunk ID isn't in the cache, returns a stub so the UI
    still renders. The stub flags itself with publisher="unknown" so the
    pill component can mute its styling.
    """
    return _load().get(chunk_id, _stub(chunk_id))


def _stub(chunk_id: str) -> SourceMeta:
    # Derive publisher from the chunk_id prefix for a graceful fallback.
    if chunk_id.startswith("finlex"):
        pub = "finlex"
    elif chunk_id.startswith("vero"):
        pub = "vero"
    else:
        pub = "unknown"
    return {
        "publisher": pub,
        "subcorpus": "",
        "label": chunk_id.split("/")[-1][:60],
        "authority_rank": 0,
        "authority_tier": "unknown",
        "excerpt": "(source metadata not loaded — run web.data.build_source_meta)",
        "synthetic": True,
    }
