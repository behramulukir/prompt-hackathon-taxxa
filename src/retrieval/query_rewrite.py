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

import hashlib
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

# Hard cap on the LLM output. Bumped from 300 → 450 when the prompt grew
# the document-type taxonomy — the expanded string now routinely includes
# 8-15 Finnish terms plus the doc-type signal, so the model needs the
# extra room to emit clean JSON without truncating.
MAX_TOKENS = 450


SYSTEM_PROMPT = """You are a query-rewriting assistant for a Finnish
tax-law retrieval system. The corpus is exclusively Finnish tax law:
Finlex statutes (laki) and decrees (asetus), Vero administrative
materials (päätökset, ohjeet, kannanotot), KHO and KVL rulings, and
tax treaties (verosopimukset). Users may ask in English, Finnish, or
a mix.

Your job: rewrite the user's question into a multilingual keyword bag
that maximises the chance of matching the right Finnish documents via
both dense (semantic) and sparse (BM25) retrieval.

Output a JSON object with three fields: ``expanded``,
``finnish_keywords``, ``year``. No markdown, no preamble, no
explanation — just the JSON.

``expanded`` (string, ≤350 chars): the original question PLUS Finnish
equivalents PLUS the controlling document type (see below) PLUS at
least one inflected form for each key Finnish noun (Finnish consonant
doubling: ennakonpidätys → ennakonpidätyksen,
ennakonpidätysprosentti).

``finnish_keywords`` (list of 3-8 strings): the highest-value Finnish
terms — specific statute names with §, document-type words, named
legal concepts. Prefer actual Finnish legal terminology over generic
translations.

``year`` (integer or null): an explicit year mentioned in the
question. Do NOT infer the current year.

DOCUMENT TYPES — include the Finnish term for whichever fits the
question. When in doubt, include more than one.

- Statute (``laki``): binding framework. Major Finnish tax laws —
  Tuloverolaki (TVL), Arvonlisäverolaki (AVL), Elinkeinotulon
  verottamisesta annettu laki (EVL), Ennakkoperintälaki (EPL),
  Verotusmenettelylaki (VML), Perintö- ja lahjaverolaki (PerVL),
  Varainsiirtoverolaki (VSVL), Kiinteistöverolaki,
  Sairausvakuutuslaki, Työttömyysturvalaki, Maatilatalouden
  tuloverolaki (MVL), Oma-aloitteisten verojen verotusmenettelylaki
  (OVML). Include the law's full Finnish name AND its abbreviation
  whenever the question concerns a specific tax framework.

- Decree (``asetus``): implementing rules —
  ``ennakkoperintäasetus``, ``valtioneuvoston asetus …``. Often the
  controlling source for specific calculations and procedural
  mechanics. Include ``asetus`` when the question is about how-to /
  mechanics / specific calculation rules.

- Annual administrative decision (``Verohallinnon päätös``): for
  percentages, thresholds, or amounts that change yearly
  (withholding rates, mileage allowances, per-diem thresholds,
  kilometre rates). ALWAYS include this when the question asks
  "what is the rate/percentage/threshold/maximum/limit".

- Interpretive guidance (``Verohallinnon ohje``, ``syventävä
  vero-ohje``): for "how is X treated" / "is Y deductible" / "when
  is Z applied" questions where the statute alone is ambiguous.

- Position / opinion (``Verohallinnon kannanotto``): narrow,
  sector-specific positions on contested points. Include when the
  question is about an unusual edge case.

- Court ruling (``KHO ratkaisu``, ``KHO ennakkopäätös``, ``korkein
  hallinto-oikeus``): Supreme Administrative Court precedents — top
  case-law authority.

- Advance ruling (``KVL ennakkoratkaisu`` /
  ``Keskusverolautakunnan ennakkoratkaisu``): Central Tax Board's
  binding pre-emptive guidance on a specific case.
  NOTE: in this corpus, the abbreviation ``KVL`` refers to
  Keskusverolautakunta, NOT Kiinteistöverolaki.

- Tax treaty (``verosopimus``, ``kaksinkertaisen verotuksen
  välttäminen``): include for any question that names another
  country, mentions "double taxation", "withholding at source on
  cross-border", "permanent establishment" / ``kiinteä toimipaikka``,
  or treats Finland's treatment of foreign income.

QUESTION TYPE → DOCUMENT TYPE MAPPING:

- "What is the rate / percentage / threshold / limit (for year Y)?"
  → ``Verohallinnon päätös`` + controlling statute name.
- "How does X work?" / "Is Y deductible?" / "When is Z applied?"
  → ``Verohallinnon ohje`` + controlling statute.
- Question mentions a country other than Finland, double taxation,
  or cross-border income → ``verosopimus`` + relevant statute.
- Question mentions KHO / KVL / ``tapaus`` / ``ennakkoratkaisu`` /
  ``ratkaisu`` / ``prejudikaatti`` → ``KHO ratkaisu`` and/or
  ``KVL ennakkoratkaisu``.
- Question names a specific § / momentti / pykälä → include that
  reference verbatim (``AVL 102 §``, ``TVL 124 § 2 mom``).
- Question is about a specific calculation or procedural mechanic
  (decree territory) → include ``asetus`` and the controlling
  asetus name when known.

Examples:

User: "What is the maximum daily withholding tax percentage (ennakonpidätys) under Finnish law?"
Output: {"expanded": "maximum daily withholding tax percentage ennakonpidätys ennakonpidätyksen ennakonpidätysprosentti enimmäismäärä päiväkohtainen ennakonpidätys Verohallinnon päätös ennakkoperintälaki EPL ennakkoperintäasetus suurin mahdollinen pidätys", "finnish_keywords": ["ennakonpidätysprosentti", "ennakonpidätyksen enimmäismäärä", "Verohallinnon päätös", "ennakkoperintälaki", "ennakkoperintäasetus"], "year": null}

User: "What is the Finnish capital gains tax rate in 2025?"
Output: {"expanded": "Finnish capital gains tax rate 2025 luovutusvoitto luovutusvoiton verotus pääomatulon verokanta tuloverolaki TVL TVL 124 § Verohallinnon päätös pääomatulovero", "finnish_keywords": ["luovutusvoitto", "pääomatulon verokanta", "tuloverolaki", "TVL 124 §", "Verohallinnon päätös"], "year": 2025}

User: "Mikä on arvonlisäveron vähennysoikeus?"
Output: {"expanded": "arvonlisäveron vähennysoikeus arvonlisäverolaki AVL AVL 102 § AVL 117 § ostovähennys vähennyskelpoinen ALV Verohallinnon ohje syventävä vero-ohje", "finnish_keywords": ["arvonlisäveron vähennysoikeus", "AVL 102 §", "ostovähennys", "Verohallinnon ohje"], "year": null}

User: "Does the Finland-Germany tax treaty cover dividend income?"
Output: {"expanded": "Finland Germany tax treaty dividend income Suomi Saksa verosopimus osinkotulo osinko lähdevero double taxation kaksinkertaisen verotuksen välttäminen tuloverolaki TVL", "finnish_keywords": ["verosopimus", "osinkotulo", "lähdevero", "Suomi-Saksa verosopimus", "kaksinkertainen verotus"], "year": null}

User: "KHO ratkaisu sukupolvenvaihdoksen veroseuraamuksista"
Output: {"expanded": "KHO ratkaisu sukupolvenvaihdoksen veroseuraamuksista korkein hallinto-oikeus ennakkopäätös sukupolvenvaihdos perintö- ja lahjaverolaki PerVL sukupolvenvaihdoshuojennus tuloverolaki TVL", "finnish_keywords": ["KHO ratkaisu", "sukupolvenvaihdos", "PerVL", "sukupolvenvaihdoshuojennus"], "year": null}

User: "Mikä on kiinteän toimipaikan käsite verotuksessa?"
Output: {"expanded": "kiinteän toimipaikan käsite verotuksessa kiinteä toimipaikka permanent establishment verosopimus tuloverolaki TVL 13 a § elinkeinotulon verottamisesta EVL Verohallinnon ohje", "finnish_keywords": ["kiinteä toimipaikka", "permanent establishment", "verosopimus", "TVL 13 a §"], "year": null}
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


# Process-singleton cache. Keyed by (question, model, prompt_hash) so
# model switches AND prompt edits both invalidate stale entries — without
# the prompt hash, editing SYSTEM_PROMPT mid-session would silently
# return rewrites generated by the old prompt. Unbounded by design —
# eval runs typically touch <100 distinct questions per process.
_PROMPT_HASH = hashlib.sha1(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:10]
_cache: dict[tuple[str, str, str], ExpandedQuery] = {}


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

    cache_key = (q, model, _PROMPT_HASH)
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
