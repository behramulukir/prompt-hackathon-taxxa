"""LLM-driven query expansion — Plan A from step-10's open items.

The Finnish tax corpus has authoritative answers buried in dense Finnish
administrative prose (Verohallinto päätökset, Vero ohjeet). When a user
asks in English — "What is the maximum daily withholding tax percentage?"
— Voyage's multilingual embedding closes some of the lexical distance
but not enough: the relevant päätös chunks rank ~138 in pure vector
search because the English question shares almost no surface tokens
with the Finnish administrative vocabulary
("ennakonpidätysprosentti", "enimmäismäärä", "Verohallinnon päätös").

This module performs one short LLM call before retrieval to rewrite the
question into a multilingual keyword bag — original English/Finnish
terms plus Finnish equivalents plus likely document-type signals. The
expanded string flows into both the embedder and the BM25 (FTS) backend
of the hybrid retriever (step-10 Fix B.2). The dual hit widens the
candidate pool dramatically without changing any other layer.

Key design choices:

- **Original question used for routing + filters, expanded for retrieval.**
  The user's intent should be classified from what they actually wrote,
  not from a possibly-noisier LLM rewrite. Only vector + FTS see the
  expanded form.
- **In-process cache.** Repeated eval queries are common during
  development; caching by ``hash(question, model)`` lets ``ask.py`` be
  run dozens of times without re-burning tokens.
- **Soft failure.** If the LLM call errors (network, rate-limit, JSON
  parse), return an ``ExpandedQuery`` with ``expanded == original`` and
  log a warning. Retrieval keeps working at pre-Plan-A quality; no
  pipeline failure escalates to the user.
- **Featherless / DeepSeek-V4-Flash.** Same OpenAI-compatible client
  used by ``src/retrieval/generate.py`` — reuses its singleton +
  ``.env`` API-key loading so this module works without extra
  environment setup. Round-trip is ~150–300 ms after warmup.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from src.agents._llm import LLMError, parse_json_object
from src.retrieval.generate import get_client


logger = logging.getLogger(__name__)


# Module model override. DeepSeek-V4-Flash is markedly faster than the V3
# agents use elsewhere — query expansion is on the hot path and latency
# matters more than reasoning depth.
MODEL = "deepseek-ai/DeepSeek-V4-Flash"

# Temperature: deterministic. The expansion should be reproducible across
# runs so the eval signal is stable.
TEMPERATURE = 0.0

# Hard cap on the LLM output. We're producing a short JSON object; 300
# tokens is plenty and limits cost if the model misbehaves.
MAX_TOKENS = 300


SYSTEM_PROMPT = """You are a query-rewriting assistant for a Finnish
tax-law retrieval system. The corpus is overwhelmingly in Finnish
(Finlex statutes, Vero ohjeet and päätökset, KHO case law). Users may
ask questions in English, Finnish, or a mix.

Your job: rewrite the user's question into a multilingual keyword bag
that maximises the chance of matching the right Finnish documents via
both dense (semantic) and sparse (BM25) retrieval.

Rules:
- Output a JSON object with three fields: ``expanded``,
  ``finnish_keywords``, ``year``.
- ``expanded``: a single string containing the original question PLUS
  Finnish equivalents of the key concepts PLUS any obvious morphological
  variants (Finnish consonant doubling: ennakonpidätys → ennakonpidätyksen,
  ennakonpidätysprosentti). Keep the string under ~300 characters.
- ``finnish_keywords``: 3-8 high-value Finnish terms specific to this
  question. Prefer the actual Finnish legal/administrative terms over
  generic translations. Examples: "ennakonpidätysprosentti",
  "Verohallinnon päätös", "arvonlisäverolaki 102 §", "luovutusvoitto".
- ``year``: integer if the question references a specific year, else
  null. Don't infer the current year.

Do not include filler like "in Finnish" or "in English". No
explanations, no markdown. Just the JSON object.

Examples:

User: "What is the maximum daily withholding tax percentage (ennakonpidätys) under Finnish law?"
Output: {"expanded": "maximum daily withholding tax percentage ennakonpidätys ennakonpidätysprosentti ennakonpidätyksen enimmäismäärä Verohallinnon päätös ennakkoperintälaki suurin mahdollinen pidätys", "finnish_keywords": ["ennakonpidätysprosentti", "ennakonpidätyksen enimmäismäärä", "Verohallinnon päätös", "ennakkoperintälaki"], "year": null}

User: "What is the Finnish capital gains tax rate in 2025?"
Output: {"expanded": "Finnish capital gains tax rate 2025 luovutusvoitto pääomatulon verokanta tuloverolaki TVL luovutusvoiton verotus", "finnish_keywords": ["luovutusvoitto", "pääomatulon verokanta", "tuloverolaki"], "year": 2025}

User: "Mikä on arvonlisäveron vähennysoikeus?"
Output: {"expanded": "arvonlisäveron vähennysoikeus arvonlisäverolaki AVL 102 § ostovähennys vähennyskelpoinen ALV", "finnish_keywords": ["arvonlisäveron vähennysoikeus", "AVL 102 §", "ostovähennys"], "year": null}
"""


USER_PROMPT_TEMPLATE = """Question: {question}

Output the JSON object now."""


# Cheap year extractor (1900–2099). Used when the LLM returns no ``year``
# but the original question contains an explicit one — defence in depth.
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


@dataclass(frozen=True)
class ExpandedQuery:
    """Result of one query-rewrite call.

    ``expanded`` is what the retrievers should consume. ``original`` is
    preserved so downstream code (the strategy router, the filter
    inferer, the LLM generator) can keep operating on the user's actual
    intent.
    """

    original: str
    expanded: str
    finnish_keywords: tuple[str, ...]
    year: int | None
    cached: bool
    error: str | None = None  # populated on soft failure; expanded == original then


# Process-singleton cache. Keyed by (question, model) so model switches
# don't return stale rewrites. Unbounded by design — eval runs typically
# touch <100 distinct questions per process.
_cache: dict[tuple[str, str], ExpandedQuery] = {}


def expand_query(
    question: str,
    *,
    model: str = MODEL,
    use_cache: bool = True,
) -> ExpandedQuery:
    """Rewrite ``question`` into a multilingual keyword bag.

    Soft-fails to ``ExpandedQuery(expanded=question, error=...)`` if the
    LLM call fails — retrieval keeps working at pre-Plan-A quality.
    """
    q = question.strip()
    if not q:
        return ExpandedQuery(
            original=q, expanded=q, finnish_keywords=(), year=None, cached=False
        )

    cache_key = (q, model)
    if use_cache and cache_key in _cache:
        prior = _cache[cache_key]
        return ExpandedQuery(
            original=prior.original,
            expanded=prior.expanded,
            finnish_keywords=prior.finnish_keywords,
            year=prior.year,
            cached=True,
            error=prior.error,
        )

    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=model,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": USER_PROMPT_TEMPLATE.format(question=q)},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        parsed = _parse_with_brace_repair(text)
    except (LLMError, Exception) as e:  # noqa: BLE001 — soft-fail by design
        logger.warning("query_rewrite: LLM call failed (%s) — using original", e)
        out = ExpandedQuery(
            original=q,
            expanded=q,
            finnish_keywords=(),
            year=_year_fallback(q),
            cached=False,
            error=str(e),
        )
        _cache[cache_key] = out
        return out

    expanded = parsed.get("expanded")
    if not isinstance(expanded, str) or not expanded.strip():
        # Provider returned a malformed object — fall back rather than
        # propagate. The caller's retrieval still works on the original.
        expanded = q

    raw_keywords = parsed.get("finnish_keywords") or []
    if not isinstance(raw_keywords, list):
        raw_keywords = []
    keywords = tuple(str(k) for k in raw_keywords if isinstance(k, str))

    year = parsed.get("year")
    if not isinstance(year, int):
        year = _year_fallback(q)

    out = ExpandedQuery(
        original=q,
        expanded=expanded.strip(),
        finnish_keywords=keywords,
        year=year,
        cached=False,
    )
    _cache[cache_key] = out
    return out


_BARE_KEY_PREFIX_RE = re.compile(r'^\s*([a-zA-Z_]\w*)\s*"\s*:')


def _parse_with_brace_repair(text: str):
    """JSON parser tolerant of DeepSeek's "missing opening brace" quirks.

    DeepSeek-V4-Flash in JSON mode occasionally returns output like
    ``expanded": "..."}` — both the opening ``{`` and the opening quote
    of the first key are dropped. Less commonly, only ``{`` is missing.
    Try the canonical parsers first; if everything fails, attempt
    several repair prefixes in order.
    """
    try:
        return parse_json_object(text)
    except LLMError:
        pass

    candidate = text.strip()
    if not candidate:
        raise LLMError("empty LLM output")

    repairs: list[str] = []
    if not candidate.startswith("{"):
        # Case 1: missing opening ``{`` only.
        repairs.append("{" + candidate)
        # Case 2: missing both ``{`` and the leading key-quote — text
        # looks like ``expanded": "..."``. Detect a bare-identifier
        # followed by ``":`` and prepend ``{"``.
        if _BARE_KEY_PREFIX_RE.match(candidate):
            repairs.append('{"' + candidate)

    repaired_with_closing: list[str] = []
    for r in repairs:
        if not r.rstrip().endswith("}"):
            repaired_with_closing.append(r.rstrip().rstrip(",") + "}")
        else:
            repaired_with_closing.append(r)
    repairs.extend(repaired_with_closing)

    for r in repairs:
        try:
            obj = json.loads(r)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise LLMError(f"Could not repair JSON: {text!r}")


def _year_fallback(question: str) -> int | None:
    """Extract a four-digit year from ``question`` directly. Used when the
    LLM returns no year — defence in depth in case the model misses an
    explicit numeric year.
    """
    hits = _YEAR_RE.findall(question)
    if not hits:
        return None
    # ``findall`` on this pattern returns the captured group only; rescan
    # via ``finditer`` to get the full 4-digit match.
    years = [int(m.group(0)) for m in _YEAR_RE.finditer(question)]
    return max(years) if years else None


def clear_cache() -> None:
    """Drop the in-process cache. Useful for tests and for forcing a
    re-rewrite when the prompt changes mid-run.
    """
    _cache.clear()
