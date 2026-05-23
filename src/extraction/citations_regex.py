"""B2.3 — Regex citation extractors.

Run a small ordered list of named regex extractors over a node's text and
yield `RawMatch` records. Patterns are ordered most-specific first; each
pattern marks consumed character spans so later, broader patterns skip
overlapping text. No I/O, no resolution — resolution is done downstream
by `src.extraction.resolve` via `NodeIndex`.
"""
from __future__ import annotations

import re
import sys
from typing import Callable, Iterator

from src.extraction.ids import LAW_ABBREVIATIONS, CitationKey
from src.extraction.resolve import RawMatch
from src.models import EdgeType, ExtractionMethod

EXTRACTED_BY: ExtractionMethod = "regex"

# Reverse abbreviation index: full-name lemma -> abbreviation.
LAW_ABBR_BY_NAME: dict[str, str] = {full: abbr for abbr, full in LAW_ABBREVIATIONS.items()}

# Finnish nominal endings to strip when lemmatizing a *laki word. Longest first.
_LAW_SUFFIXES: tuple[str, ...] = (
    "laissaan", "laissamme", "laeissaan",
    "laissa", "laista", "laille", "lailla", "laiksi",
    "lakeja", "lakien", "laeissa", "laeista",
    "lakia", "lakiin", "lakina",
    "lain", "laki",
)


def _lemmatize_law_word(word: str) -> str | None:
    """Stem a Finnish *laki word to its lemma (e.g. tuloverolain -> tuloverolaki)."""
    if not word:
        return None
    w = word.lower()
    for suf in _LAW_SUFFIXES:
        if w.endswith(suf) and len(w) > len(suf):
            return w[: -len(suf)] + "laki"
    return w if w.endswith("laki") else None


# ---------------------------------------------------------------------------
# Compiled patterns. Priority order is defined by PATTERNS at the bottom.
# ---------------------------------------------------------------------------

_F = re.IGNORECASE | re.UNICODE

_RE_KHO = re.compile(r"\bKHO\s*[: ]?\s*(\d{4})\s*[:/ ]\s*(\d+)\b", _F)
_RE_EU_DIR = re.compile(r"\b(\d{4})/(\d{1,4})/(EY|EU|ETY)\b", _F)
_RE_HE = re.compile(r"\bHE\s+(\d+)/(\d{4})(?:\s*vp)?\b", _F)
_RE_MUUT_KUMOT = re.compile(r"\b(muutettu|kumottu)\s+lailla\s+(\d+)/(\d{4})\b", _F)
_RE_PAREN_YN = re.compile(r"\((\d{1,4})/(\d{4})\)")
_RE_LAW_WORD = re.compile(r"(\w*(?:laki|asetus|säädös|saados)\w*)", _F)
_RE_CHAPTER_SECTION_FULL = re.compile(
    r"(\d+)\s+luvun\s+(\d+\s*[a-z]?)\s*§(?::n|:ssä|:ssa)?"
    r"(?:\s+(\d+)\s*momentin)?(?:\s+(\d+|[a-zäöå])\s*kohdan)?"
    r"\s+([A-Za-zÄÖÅäöå-]{4,})",
    _F,
)
_RE_SECTION_AVL_INLINE = re.compile(r"§\s*(\d+\s*[a-z]?)\s*,?\s+([A-ZÄÖÅ]{2,8})\b", re.UNICODE)
_RE_AVL_SECTION_ALT = re.compile(r"\b([A-ZÄÖÅ]{2,8})\s+(\d+\s*[a-z]?)\s*§", re.UNICODE)
_RE_NATURAL_LAW = re.compile(
    r"\b([A-Za-zÄÖÅäöå-]+lai(?:n|ssa|sta|lle|lla|ksi|kia)|[A-Za-zÄÖÅäöå-]+laki)"
    r"\s+(\d+\s*[a-z]?)\s*§",
    _F,
)
_RE_BARE_SECTION = re.compile(r"§\s*(\d+\s*[a-z]?)\b", _F)


# ---------------------------------------------------------------------------
# Span-tracking helpers
# ---------------------------------------------------------------------------

def _is_consumed(span: tuple[int, int], consumed: list[tuple[int, int]]) -> bool:
    """Skip a match if its midpoint sits inside any consumed span."""
    mid = (span[0] + span[1]) // 2
    return any(a <= mid < b for a, b in consumed)


def _snippet(text: str, start: int, end: int, pad: int = 25) -> str:
    return text[max(0, start - pad): end + pad]


def _section_norm(raw: str) -> str:
    return raw.replace(" ", "").lower()


def _mk(
    *, source_id: str, source_law_id: str | None, raw: str,
    key: CitationKey, type_: EdgeType, confidence: float,
    text: str, start: int, end: int,
) -> RawMatch:
    return RawMatch(
        source_id=source_id,
        target_ref=raw,
        key=key,
        type=type_,
        confidence=confidence,
        extracted_by=EXTRACTED_BY,
        context_snippet=_snippet(text, start, end),
        source_law_id=source_law_id,
    )


# ---------------------------------------------------------------------------
# Pattern functions. Each yields (RawMatch, span).
# Signature: (text, consumed, *, source_id, source_law_id) -> Iterator[...].
# ---------------------------------------------------------------------------

def _iter_simple(
    regex: re.Pattern[str], text: str, consumed: list[tuple[int, int]],
    *, build_key: Callable[[re.Match[str]], CitationKey | None],
    type_: EdgeType | Callable[[re.Match[str]], EdgeType],
    confidence: float,
    source_id: str, source_law_id: str | None,
) -> Iterator[tuple[RawMatch, tuple[int, int]]]:
    for m in regex.finditer(text):
        span = m.span()
        if _is_consumed(span, consumed):
            continue
        key = build_key(m)
        if key is None:
            continue
        t = type_(m) if callable(type_) else type_
        yield (
            _mk(source_id=source_id, source_law_id=source_law_id,
                raw=m.group(0), key=key, type_=t, confidence=confidence,
                text=text, start=span[0], end=span[1]),
            span,
        )


def kho_case(text, consumed, *, source_id, source_law_id):
    yield from _iter_simple(
        _RE_KHO, text, consumed,
        build_key=lambda m: CitationKey(kho_year=int(m.group(1)), kho_n=int(m.group(2))),
        type_="cites", confidence=0.95,
        source_id=source_id, source_law_id=source_law_id,
    )


def eu_directive(text, consumed, *, source_id, source_law_id):
    yield from _iter_simple(
        _RE_EU_DIR, text, consumed,
        build_key=lambda m: CitationKey(
            eu_directive=f"{m.group(1)}/{m.group(2)}/{m.group(3).upper()}",
        ),
        type_="cites", confidence=0.95,
        source_id=source_id, source_law_id=source_law_id,
    )


def he_government_bill(text, consumed, *, source_id, source_law_id):
    yield from _iter_simple(
        _RE_HE, text, consumed,
        build_key=lambda m: CitationKey(he_ref=f"{m.group(1)}/{m.group(2)}"),
        type_="cites", confidence=0.95,
        source_id=source_id, source_law_id=source_law_id,
    )


def muutettu_kumottu_lailla(text, consumed, *, source_id, source_law_id):
    yield from _iter_simple(
        _RE_MUUT_KUMOT, text, consumed,
        build_key=lambda m: CitationKey(year=int(m.group(3)), number=int(m.group(2))),
        type_=lambda m: "amends" if m.group(1).lower() == "muutettu" else "repeals",
        confidence=0.95,
        source_id=source_id, source_law_id=source_law_id,
    )


def statute_paren_year_number(text, consumed, *, source_id, source_law_id):
    def build(m: re.Match[str]) -> CitationKey | None:
        window = text[max(0, m.start() - 30): m.start()]
        words = _RE_LAW_WORD.findall(window)
        if not words:
            return None
        return CitationKey(
            year=int(m.group(2)), number=int(m.group(1)),
            law_hint=words[-1].lower(),
        )
    yield from _iter_simple(
        _RE_PAREN_YN, text, consumed,
        build_key=build, type_="cites", confidence=0.9,
        source_id=source_id, source_law_id=source_law_id,
    )


def chapter_section_full(text, consumed, *, source_id, source_law_id):
    def build(m: re.Match[str]) -> CitationKey | None:
        lemma = _lemmatize_law_word(m.group(5))
        if not lemma or lemma not in LAW_ABBR_BY_NAME:
            return None
        return CitationKey(
            law_hint=lemma,
            section=_section_norm(m.group(2)),
            subsection=int(m.group(3)) if m.group(3) else None,
            item=m.group(4).lower() if m.group(4) else None,
        )
    yield from _iter_simple(
        _RE_CHAPTER_SECTION_FULL, text, consumed,
        build_key=build, type_="cites", confidence=0.85,
        source_id=source_id, source_law_id=source_law_id,
    )


def section_avl_inline(text, consumed, *, source_id, source_law_id):
    def build(m: re.Match[str]) -> CitationKey | None:
        abbr = m.group(2).lower()
        if abbr not in LAW_ABBREVIATIONS:
            return None
        return CitationKey(
            law_hint=LAW_ABBREVIATIONS[abbr],
            section=_section_norm(m.group(1)),
        )
    yield from _iter_simple(
        _RE_SECTION_AVL_INLINE, text, consumed,
        build_key=build, type_="cites", confidence=0.9,
        source_id=source_id, source_law_id=source_law_id,
    )


def avl_section_alt(text, consumed, *, source_id, source_law_id):
    def build(m: re.Match[str]) -> CitationKey | None:
        abbr = m.group(1).lower()
        if abbr not in LAW_ABBREVIATIONS:
            return None
        return CitationKey(
            law_hint=LAW_ABBREVIATIONS[abbr],
            section=_section_norm(m.group(2)),
        )
    yield from _iter_simple(
        _RE_AVL_SECTION_ALT, text, consumed,
        build_key=build, type_="cites", confidence=0.9,
        source_id=source_id, source_law_id=source_law_id,
    )


def natural_law_section(text, consumed, *, source_id, source_law_id):
    def build(m: re.Match[str]) -> CitationKey | None:
        lemma = _lemmatize_law_word(m.group(1))
        if not lemma or lemma not in LAW_ABBR_BY_NAME:
            return None
        return CitationKey(law_hint=lemma, section=_section_norm(m.group(2)))
    yield from _iter_simple(
        _RE_NATURAL_LAW, text, consumed,
        build_key=build, type_="cites", confidence=0.8,
        source_id=source_id, source_law_id=source_law_id,
    )


def bare_section_ref(text, consumed, *, source_id, source_law_id):
    yield from _iter_simple(
        _RE_BARE_SECTION, text, consumed,
        build_key=lambda m: CitationKey(section=_section_norm(m.group(1))),
        type_="cites", confidence=0.75,
        source_id=source_id, source_law_id=source_law_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

PATTERNS: list[tuple[str, Callable]] = [
    ("kho_case", kho_case),
    ("eu_directive", eu_directive),
    ("he_government_bill", he_government_bill),
    ("muutettu_kumottu_lailla", muutettu_kumottu_lailla),
    ("statute_paren_year_number", statute_paren_year_number),
    ("chapter_section_full", chapter_section_full),
    ("section_avl_inline", section_avl_inline),
    ("avl_section_alt", avl_section_alt),
    ("natural_law_section", natural_law_section),
    ("bare_section_ref", bare_section_ref),
]


def extract_citations(
    text: str,
    *,
    source_id: str,
    source_law_id: str | None,
    anchor_target_refs: set[str] = frozenset(),
) -> Iterator[RawMatch]:
    """Run all patterns in priority order on `text`.

    `anchor_target_refs` is a set of raw href strings already extracted as
    anchors in the same source node; any pattern whose matched substring
    appears verbatim there is dropped as a duplicate.
    """
    if not text:
        return
    consumed: list[tuple[int, int]] = []
    for _name, fn in PATTERNS:
        for raw_match, span in fn(
            text, consumed,
            source_id=source_id, source_law_id=source_law_id,
        ):
            consumed.append(span)
            if raw_match.target_ref in anchor_target_refs:
                continue
            yield raw_match


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _selftest() -> int:
    samples = [
        "Korkein hallinto-oikeus on ratkaisussaan KHO 2023:55 todennut...",
        "Direktiivin 2006/112/EY 168 artiklan mukaan...",
        "Hallituksen esitys HE 88/1993 vp koski arvonlisäverolakia.",
        "Pykälä muutettu lailla 533/1976, joka selvensi soveltamisalaa.",
        "Kuten § 10 AVL säätää, vähennysoikeus on...",
    ]
    all_hit = True
    for sample in samples:
        consumed: list[tuple[int, int]] = []
        any_match = False
        print(f"\nTEXT: {sample}")
        for name, fn in PATTERNS:
            for raw_match, span in fn(
                sample, consumed,
                source_id="test", source_law_id=None,
            ):
                consumed.append(span)
                any_match = True
                print(f"  [{name}] raw={raw_match.target_ref!r} "
                      f"key={raw_match.key} type={raw_match.type} "
                      f"conf={raw_match.confidence}")
        if not any_match:
            print("  (no matches)")
            all_hit = False
    return 0 if all_hit else 1


if __name__ == "__main__":
    sys.exit(_selftest())
