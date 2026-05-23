"""Canonical-ID normalization for edge extraction.

Two jobs:

1. Parse the citation strings we see in text (e.g. "§ 117", "AVL 102 §",
   "KHO 2023:55", "2006/112/EY", an `<a href>` URL) into a structured
   `CitationKey`. The key carries either a (year, number) pair, a KHO
   reference, an EU directive ref, or just a section marker — whatever
   the raw form provided.

2. Map a CitationKey to one of:
     - a canonical node id present in our corpus (resolved)
     - `out_of_corpus`         (definitely outside what we ingest)
     - `not_yet_parsed`        (looks in-corpus but the lookup missed)
     - `normalization_failed`  (we can't even form a key)

   The mapping is delegated to `NodeIndex` (it owns the reverse lookups).
   This module just builds the keys.

Finnish statutes are addressed in a few ways and we collapse them into one
key shape. The truth source is the `https://www.finlex.fi/akn/fi/act/statute/YYYY/NNN`
URL form — anchors give us that exactly. Plain-text citations like
"AVL 102 §" or "tuloverolain 4 §" map to a (law-abbreviation/name, section)
pair that NodeIndex must resolve via its title index.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Common Finnish-legal abbreviations → canonical full names.
# Used by the regex extractors when they see something like "AVL 102 §".
# Keep small and high-precision — this is *recall* via the abbreviation
# index; precision via NodeIndex's title lookup.
# ---------------------------------------------------------------------------
LAW_ABBREVIATIONS: dict[str, str] = {
    # tax
    "avl": "arvonlisäverolaki",
    "tvl": "tuloverolaki",
    "evl": "laki elinkeinotulon verottamisesta",
    "mvl": "maatilatalouden tuloverolaki",
    "kpl": "kirjanpitolaki",
    "vml": "laki verotusmenettelystä",
    "ovml": "laki oma-aloitteisten verojen verotusmenettelystä",
    "ennpl": "ennakkoperintälaki",
    "perintövl": "perintö- ja lahjaverolaki",
    "varainsl": "varainsiirtoverolaki",
    # corporate / civil
    "oyl": "osakeyhtiölaki",
    "ayl": "asunto-osakeyhtiölaki",
    "okl": "osuuskuntalaki",
    "kkl": "kuluttajansuojalaki",
    "vkl": "velkakirjalaki",
    # general / procedural
    "hl":  "hallintolaki",
    "okhl": "oikeudenkäymiskaari",
    "rl":  "rikoslaki",
    "tsl": "työsopimuslaki",
}


# ---------------------------------------------------------------------------
# CitationKey
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CitationKey:
    """Structured form of a citation, before resolution.

    Exactly one of (year+number), (kho_year+kho_n), (eu_directive),
    (he_ref), (law_hint) is set; section / subsection / item refine within.
    """

    # Statute coordinate (Finlex)
    year: Optional[int] = None
    number: Optional[int] = None
    section: Optional[str] = None     # "5" or "5a"
    subsection: Optional[int] = None  # momentti
    item: Optional[str] = None        # kohta marker

    # Plain-name hint, e.g. "tuloverolaki" — looked up via title index
    law_hint: Optional[str] = None

    # KHO precedent
    kho_year: Optional[int] = None
    kho_n: Optional[int] = None

    # Out-of-corpus refs we still record
    eu_directive: Optional[str] = None  # e.g. "2006/112/EY"
    he_ref: Optional[str] = None        # e.g. "88/1993"

    def is_out_of_corpus(self) -> bool:
        return bool(self.eu_directive or self.he_ref)


# ---------------------------------------------------------------------------
# URL parsing (anchor extractor's input)
# ---------------------------------------------------------------------------

_ACT_URL = re.compile(
    r"finlex\.fi/(?:akn/fi/act/statute|fi/laki/(?:ajantasa|alkup|smur))/(\d{4})/(\d+)",
    re.IGNORECASE,
)
_KHO_URL = re.compile(
    r"finlex\.fi/(?:akn/fi/judg/kho|fi/oikeus/kho)/(\d{4})[/:](\d+)",
    re.IGNORECASE,
)
_EURLEX_URL = re.compile(r"eur-lex\.europa\.eu/.*?\b(\d{4}/\d{1,4}/(?:EY|EU|ETY))", re.IGNORECASE)
_VERO_URL = re.compile(r"vero\.fi/.*?/syventavat[-_]vero[-_]ohjeet/([^/?#]+)", re.IGNORECASE)


def parse_href(href: str) -> CitationKey | None:
    """Best-effort parse of an `<a href>` value into a CitationKey.

    Returns None when the href is clearly an external site we don't ingest
    *and* doesn't fit any known pattern.
    """
    if not href:
        return None
    s = href.strip()

    m = _ACT_URL.search(s)
    if m:
        return CitationKey(year=int(m.group(1)), number=int(m.group(2)))

    m = _KHO_URL.search(s)
    if m:
        return CitationKey(kho_year=int(m.group(1)), kho_n=int(m.group(2)))

    m = _EURLEX_URL.search(s)
    if m:
        return CitationKey(eu_directive=m.group(1).upper().replace("ETY", "EY"))

    return None


# ---------------------------------------------------------------------------
# Section-marker parsing (refines an existing CitationKey with chapter/section)
# ---------------------------------------------------------------------------

# "10 luvun 7 §" / "10 luvun 7 §:n 1 momentti" / "7 §:ssä"
_SECTION_DEEP = re.compile(
    r"(?:(?P<chapter>\d+)\s*luvun\s+)?"
    r"(?P<section>\d+\s*[a-z]?)\s*§"
    r"(?::n)?"
    r"(?:\s*(?P<momentti>\d+)\s*momentin)?"
    r"(?:\s*(?P<kohta>\d+|[a-z])\s*kohdan)?",
    re.IGNORECASE,
)


def refine_with_section(key: CitationKey, text_around: str) -> CitationKey:
    """If text near a known law cite contains "10 luvun 7 §", carry it back."""
    m = _SECTION_DEEP.search(text_around)
    if not m:
        return key
    sec_raw = (m.group("section") or "").replace(" ", "").lower()
    return CitationKey(
        year=key.year,
        number=key.number,
        law_hint=key.law_hint,
        section=sec_raw or key.section,
        subsection=int(m.group("momentti")) if m.group("momentti") else key.subsection,
        item=m.group("kohta").lower() if m.group("kohta") else key.item,
        kho_year=key.kho_year,
        kho_n=key.kho_n,
        eu_directive=key.eu_directive,
        he_ref=key.he_ref,
    )
