"""Metadata reranker — the single biggest quality lever in v1.

Without this step current Finlex sections sit at equal rank with old Vero
guidance because the embedding model can't tell which one is authoritative.
The weights below come from 05_retrieval_v1_vector_only.md §B5.3; they are
starting points to be tuned once the eval harness exists.

Pure functions: input ``RetrievedHit`` list + the query, output the same
list re-sorted with each hit's score promoted to a ``RerankedHit``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime

from src.retrieval.vector_retriever import RetrievedHit


# --------------------------------------------------------------------------
# Weights — see brief §B5.3. Treat as starting point, tune on eval set.
# --------------------------------------------------------------------------
W_AUTHORITY = 0.10  # multiplied by (authority_rank / 100)
W_RECENCY = 0.05  # multiplied by recency_signal in [0, 1]
W_TERM_BONUS = 0.05  # added if query term appears in section title/path
W_NOT_USABLE = 0.50  # subtracted when usable=false — legacy fallback

# Graded temporal penalty driven by ``temporal_status.effective_usable``
# from ``scripts.compute_temporal_status``. Replaces the binary
# W_NOT_USABLE penalty when a status map is supplied to ``rerank``.
#
# Rationale (the "ancestor-aware" piece of the design):
#   * "repealed" is a confirmed self- or ancestor-level repeal — never
#     usable for current-law queries, but kept retrievable. Same magnitude
#     as the old W_NOT_USABLE so legacy behavior matches when only repeals
#     are present.
#   * "stale" — the LAW root is superseded by a real successor act. The
#     section text the user sees may still be on-paper but the citation
#     should not be relied on without checking the successor.
#   * "suspect" — the section's LAW has amendments dated after this
#     chunk's publication_date. The chunk text *may* already reflect them
#     (consolidated Finlex usually does), so the penalty is gentle.
#   * "ok" — no temporal concerns.
W_TEMPORAL_PENALTY: dict[str, float] = {
    "ok":       0.00,
    "suspect":  0.10,
    "stale":    0.25,
    "repealed": 0.50,
}

# Recency: linearly decay from 1.0 at the most recent publication_date in
# the result set to 0.0 at this many days older. ~10 years gives older Vero
# ohjeet a non-zero (but small) contribution without erasing them entirely.
RECENCY_HALFLIFE_DAYS = 3650.0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RerankedHit:
    """A ``RetrievedHit`` with the composite rerank score attached.

    ``components`` is kept around for debugging — the CLI ``--verbose`` flag
    surfaces it so reranker tuning isn't blind.
    """

    hit: RetrievedHit
    score: float
    components: dict[str, float]


_WORD_RE = re.compile(r"[\wäöåÄÖÅ§]+", re.UNICODE)
# Tokens that carry no retrieval signal — stripped from the query before the
# exact-term bonus check so we don't reward chunks for containing "mikä".
_STOPWORDS = frozenset(
    {
        # Finnish question words / common particles
        "mikä", "mitä", "mikä?", "miten", "milloin", "missä", "onko", "voi",
        "voiko", "saako", "saa", "joko", "ja", "tai", "on", "ei", "se", "se?",
        "että", "kun", "vai", "kuin", "kuinka", "paljon", "monta",
        # English equivalents
        "what", "which", "when", "where", "why", "how", "is", "are", "the",
        "a", "an", "of", "in", "on", "to", "for", "by", "do", "does",
    }
)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def _content_terms(query: str) -> list[str]:
    """Lowercase tokens with stopwords removed and length > 2."""
    return [t for t in _tokenize(query) if t not in _STOPWORDS and len(t) > 2]


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        # Accept full ISO timestamps too, in case Step 3 ever widens the field.
        return datetime.fromisoformat(s).date()
    except ValueError:
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None


def _recency_signal(hit_date: date | None, newest: date | None) -> float:
    """Map publication_date to [0, 1] relative to the freshest in the set.

    Returns 0.0 when either date is missing — i.e. an unknown-date hit gets
    no recency bump, which is the safe default (we don't punish it either).
    """
    if hit_date is None or newest is None:
        return 0.0
    delta_days = (newest - hit_date).days
    if delta_days <= 0:
        return 1.0
    return max(0.0, 1.0 - (delta_days / RECENCY_HALFLIFE_DAYS))


def _exact_term_bonus(query_terms: list[str], embedded_text: str | None) -> float:
    """Return 1.0 when any content-bearing query term appears in the title
    or path lines of the embedded_text, 0.0 otherwise.

    We deliberately limit to the prefix — looking at the full chunk body
    would reward generic vocabulary that appears in many chunks. The
    title/path lines are where the *named* legal handle lives.
    """
    if not embedded_text or not query_terms:
        return 0.0
    # The composition format prepends ``[Source ...]``, ``[Path ...]``,
    # ``[Title ...]`` then a blank line, then the body. Slice to the prefix.
    prefix_end = embedded_text.find("\n\n")
    prefix = embedded_text[:prefix_end] if prefix_end > 0 else embedded_text
    prefix_lc = prefix.lower()
    return 1.0 if any(t in prefix_lc for t in query_terms) else 0.0


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def rerank(
    query: str,
    hits: list[RetrievedHit],
    *,
    temporal_status_map: dict[str, dict | None] | None = None,
) -> list[RerankedHit]:
    """Reorder hits by ``cosine_sim + authority + recency + term - temporal``.

    Stable for equal scores (Python's sort is stable). The input list is not
    mutated.

    ``temporal_status_map`` is keyed by ``section_id`` and maps to the
    ``temporal_status`` dict written by ``scripts.compute_temporal_status``.
    When supplied, the temporal penalty is graded by
    ``effective_usable`` (ok/suspect/stale/repealed) — see
    ``W_TEMPORAL_PENALTY``. When omitted (or when the entry is missing for
    a given hit), we fall back to the legacy binary penalty driven by
    ``hit.usable``, so callers without graph-store access keep working.
    """
    if not hits:
        return []

    dates = [_parse_iso_date(h.publication_date) for h in hits]
    known_dates = [d for d in dates if d is not None]
    newest = max(known_dates) if known_dates else None

    query_terms = _content_terms(query)

    out: list[RerankedHit] = []
    for hit, hit_date in zip(hits, dates):
        # ``authority_rank`` is None for nodes Step 3 couldn't classify. Treat
        # as 0 — neutral rather than penalizing, matching the spec.
        auth = (hit.authority_rank or 0) / 100.0
        rec = _recency_signal(hit_date, newest)
        term = _exact_term_bonus(query_terms, hit.embedded_text)
        temporal_pen, temporal_grade = _temporal_penalty(hit, temporal_status_map)

        components = {
            "cosine": hit.cosine_sim,
            "authority": W_AUTHORITY * auth,
            "recency": W_RECENCY * rec,
            "term_bonus": W_TERM_BONUS * term,
            # Keep the legacy name in --verbose output so existing dashboards
            # don't break, but the value is now graded.
            "not_usable_penalty": -temporal_pen,
            "temporal_grade": temporal_grade,
        }
        score = sum(v for k, v in components.items()
                    if k != "temporal_grade" and isinstance(v, (int, float)))
        out.append(RerankedHit(hit=hit, score=score, components=components))

    out.sort(key=lambda r: r.score, reverse=True)
    return out


def _temporal_penalty(
    hit: RetrievedHit,
    status_map: dict[str, dict | None] | None,
) -> tuple[float, float]:
    """Return ``(penalty, grade_as_float)``.

    ``grade_as_float`` is a debug-only encoding so the rerank diagnostics
    can show which bucket fired — 0=ok, 1=suspect, 2=stale, 3=repealed,
    -1=unknown (no status, legacy binary applied).
    """
    grade_to_num = {"ok": 0.0, "suspect": 1.0, "stale": 2.0, "repealed": 3.0}

    if status_map is not None:
        status = status_map.get(hit.section_id)
        if isinstance(status, dict):
            grade = str(status.get("effective_usable") or "ok")
            return W_TEMPORAL_PENALTY.get(grade, 0.0), grade_to_num.get(grade, 0.0)

    # Legacy path — no graph-store map. Honor the old binary signal.
    if hit.usable is False:
        return W_NOT_USABLE, 3.0
    return 0.0, -1.0


def top_n(reranked: list[RerankedHit], n: int) -> list[RerankedHit]:
    """Convenience — keep the top ``n`` and re-emit. No tie-breaking change."""
    return reranked[:n]


# Re-export so callers don't have to know about ``dataclasses.replace``.
__all__ = ["RerankedHit", "rerank", "top_n", "replace"]
