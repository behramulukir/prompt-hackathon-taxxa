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
W_NOT_USABLE = 0.50  # subtracted when usable=false (repealed)

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
) -> list[RerankedHit]:
    """Reorder hits by ``cosine_sim + authority + recency + term - repealed``.

    Stable for equal scores (Python's sort is stable). The input list is not
    mutated.
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
        # ``usable`` is True for current/binding chunks. None means unknown —
        # don't penalize unknowns, only confirmed repealed.
        not_usable_pen = W_NOT_USABLE if hit.usable is False else 0.0

        components = {
            "cosine": hit.cosine_sim,
            "authority": W_AUTHORITY * auth,
            "recency": W_RECENCY * rec,
            "term_bonus": W_TERM_BONUS * term,
            "not_usable_penalty": -not_usable_pen,
        }
        score = sum(components.values())
        out.append(RerankedHit(hit=hit, score=score, components=components))

    out.sort(key=lambda r: r.score, reverse=True)
    return out


def top_n(reranked: list[RerankedHit], n: int) -> list[RerankedHit]:
    """Convenience — keep the top ``n`` and re-emit. No tie-breaking change."""
    return reranked[:n]


# Re-export so callers don't have to know about ``dataclasses.replace``.
__all__ = ["RerankedHit", "rerank", "top_n", "replace"]
