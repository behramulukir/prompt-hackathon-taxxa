"""Query-time filter inference for v1 retrieval.

Keyword-based, intentionally narrow. Only emits filters that can actually be
pushed down into the LanceDB ``where`` clause — i.e. fields that exist on
``VectorRecord``. Year-as-of style filters (``effective_date <= 2024``) are
deferred to Step 8's Clarifier because ``effective_date`` only lives on
``NodeMetadata``, never on the vector row.

The inference is deliberately conservative: when a query is ambiguous we
prefer to retrieve more and let the reranker (and the LLM) sort it out
rather than over-filter and starve the retriever.
"""
from __future__ import annotations

import re
from typing import Any


# --------------------------------------------------------------------------
# Trigger sets — Finnish first, English as a courtesy for mixed prompts.
# --------------------------------------------------------------------------

# Phrases that signal the user wants the *currently in force* rule, not
# historical or repealed text. Matched as substrings on the lowercased query.
_USABLE_TRIGGERS = (
    # English. ``"current "`` (trailing space) catches "current rule",
    # "current rate", "current VAT...", "current threshold" without firing
    # on "current account" / "current year alone".
    "current ",
    "currently",
    "right now",
    "as of today",
    "in force",
    # Finnish
    "nykyinen",
    "nykyiset",
    "voimassa",
    "tällä hetkellä",
    "nyt voimassa",
)

# Phrases that signal the user *wants* repealed/historical content. When this
# fires we deliberately do not add an ``in_force`` filter (otherwise we'd hide
# what the user asked for).
_HISTORICAL_TRIGGERS = (
    "repealed",
    "former",
    "previous",
    "old version",
    "kumottu",
    "aiempi",
    "entinen",
    "vanha",
)

# Source-publisher triggers. Note these gate on the *publisher* (finlex vs
# vero), not the subcorpus — finer-grained intent (e.g. "give me a Vero ohje")
# is rare in user queries and best left to the agent layer.
#
# Bare ``"law"`` / ``"act"`` were previously here and proved catastrophically
# ambiguous: "under Finnish **law**" or "an **act** of Parliament" — generic
# English phrases that mention statutes only incidentally — flipped the
# filter to ``source=finlex`` and silently excluded every Vero document.
# The actual Finlex-specific markers are the publisher name and the
# Finnish vocabulary; English ``statute`` is kept because no one uses it
# casually. Multi-word ``of law`` / ``the law`` are explicitly excluded.
_FINLEX_TRIGGERS = (
    "finlex",
    "statute",
    "laki",
    "säädös",
    "asetus",
)
_VERO_TRIGGERS = (
    "vero guidance",
    "vero ohje",
    "vero päätös",
    "tax administration",
    "verohallinto",
    "verohallinnon päätös",
    "ohje",
    "syventävä",
)

# Language triggers. Default is None (no filter) because the corpus is
# overwhelmingly Finnish and the embedding model is multilingual — filtering
# on language=fi by default would hide the rare authoritative sv/en chunk.
_LANGUAGE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "fi": ("in finnish", "suomeksi", "suomen kielellä"),
    "sv": ("in swedish", "på svenska", "ruotsiksi"),
    "en": ("in english", "englanniksi"),
}


# Finland mention is too broad to act on alone — most queries about Finnish
# tax don't say "in Finland". We only fire a language filter when the user
# explicitly asks for a language, not when they merely mention the country.


def infer_filters(query: str) -> dict[str, Any]:
    """Map free-text query → equality filter dict for ``VectorStore.search``.

    Only keys present on ``VectorRecord`` are returned: ``usable``,
    ``in_force``, ``source``, ``language``. The caller may merge in
    additional filters or drop these entirely.

    Returns an empty dict when no trigger matches — meaning "no narrowing".
    """
    q = query.lower()
    filters: dict[str, Any] = {}

    asks_historical = any(t in q for t in _HISTORICAL_TRIGGERS)
    asks_current = any(t in q for t in _USABLE_TRIGGERS)

    if asks_current and not asks_historical:
        # ``usable`` is the strongest "current" signal — repealed law is
        # ``usable=false`` regardless of in_force semantics in mixed corpora.
        filters["usable"] = True
        filters["in_force"] = True

    asks_finlex = any(t in q for t in _FINLEX_TRIGGERS)
    asks_vero = any(t in q for t in _VERO_TRIGGERS)
    # Only commit to a publisher when exactly one side fires — if both fire
    # the query is genuinely cross-source and we shouldn't narrow.
    if asks_finlex and not asks_vero:
        filters["source"] = "finlex"
    elif asks_vero and not asks_finlex:
        filters["source"] = "vero"

    for lang, triggers in _LANGUAGE_TRIGGERS.items():
        if any(t in q for t in triggers):
            filters["language"] = lang
            break

    return filters


# --------------------------------------------------------------------------
# Year extraction — returned alongside filters for the reranker, not pushed
# into LanceDB. The reranker uses it to bump rows whose publication_date is
# at or before the asked-about year and to push down newer-than-question rows
# slightly. This is the closest we can get to effective_date at v1.
# --------------------------------------------------------------------------

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def infer_as_of_year(query: str) -> int | None:
    """Extract an explicit four-digit year from the query, if any.

    Returns the most-recent year mentioned (handles "between 2019 and 2024"
    by preferring 2024 — the answer is usually framed around the later
    bound). Returns None when no year is present.
    """
    hits = _YEAR_RE.findall(query)
    if not hits:
        return None
    # findall returns the captured group only; rescan with finditer to get
    # the full 4-digit match.
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(query)]
    return max(years) if years else None
