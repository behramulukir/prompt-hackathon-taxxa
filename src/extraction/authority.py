"""B3.2 — Authority tagging.

Fixed mapping from ``(source, source_subcorpus)`` to ``(authority, rank)``.

The spec locks two values:

    finlex_statute  →  authority_rank = 100
    vero_guidance   →  authority_rank = 60

The on-disk corpus also contains KHO precedents and tax treaties under
``source="finlex"`` (different subcorpora). The ``Authority`` literal in
``src/models.py`` already includes ``"KHO"`` and ``"Treaty"``, so we extend
the mapping rather than collapse them into "Finlex". Rationale:

* **Treaty (rank 90)** — international tax treaties have direct legal force
  but are narrower than domestic statute, so they sit just below.
* **KHO (rank 80)** — supreme administrative court precedent is binding in
  similar fact patterns but interprets statute rather than enacting it.

Findings: see ``findings/03_authority_ranks.md``.
"""
from __future__ import annotations

from typing import Literal

Authority = Literal["Finlex", "Vero", "KHO", "Treaty"]

# Authority tier — used by reranker. Higher = more authoritative.
AUTHORITY_RANK: dict[Authority, int] = {
    "Finlex": 100,
    "Treaty":  90,
    "KHO":     80,
    "Vero":    60,
}

# (source, subcorpus_prefix) → Authority
_SUBCORPUS_AUTHORITY: dict[tuple[str, str], Authority] = {
    ("finlex", "laki"):       "Finlex",   # covers laki + laki_skk
    ("finlex", "asetus"):     "Finlex",   # covers asetus + asetus_skk
    ("finlex", "kho"):        "KHO",
    ("finlex", "treaty"):     "Treaty",
    ("vero",   "vero"):       "Vero",     # covers vero_ohje, vero_paatos, …
}


def tag(source: str, source_subcorpus: str) -> tuple[Authority, int]:
    """Return ``(authority, rank)`` for a node.

    Falls back to ``("Finlex", 100)`` if the prefix is unrecognized but the
    source is finlex, and ``("Vero", 60)`` for vero. Unknown sources raise —
    silent fallback would hide a parser regression.
    """
    for (src_pfx, sub_pfx), authority in _SUBCORPUS_AUTHORITY.items():
        if source == src_pfx and source_subcorpus.startswith(sub_pfx):
            return authority, AUTHORITY_RANK[authority]

    if source == "finlex":
        return "Finlex", AUTHORITY_RANK["Finlex"]
    if source == "vero":
        return "Vero", AUTHORITY_RANK["Vero"]

    raise ValueError(f"Unknown source/subcorpus: {source!r}/{source_subcorpus!r}")
