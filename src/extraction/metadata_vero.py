"""B3.1 — Vero metadata extractor.

Vero HTML layouts vary by sub-source (ohje vs päätös vs KVL) but share a
common shell:

    <article id="content-main">
        <h1 class="taxxa-title">…</h1>
        <div class="main-body">
            <p>…</p>  (often containing dates like "Ennakkoratkaisu ajalle
                       1.1.1995 - 31.12.1995" or "tulee voimaan 1 päivänä
                       joulukuuta 2017")
            …
        </div>
    </article>

What we extract:

- ``publication_date`` — first parseable date in the body, preferring
  the start of a date range when present.
- ``effective_date`` — same as publication for most Vero docs.
- ``repeal_date`` — end of an explicit validity range (KVL
  "Ennakkoratkaisu ajalle … – …"), else null.
- ``in_force`` — False if the body contains ``KUMOTTU`` / ``(kumottu)``
  / ``poistettu`` markers near the top, else True (Vero guidance is
  assumed current unless explicitly retired).
- ``superseded_by`` — left null; the pipeline runner fills this from
  ``tämä ohje korvaa`` markers when present (B3.1 Vero notes).
- ``language`` — Vero HTML rarely carries a ``lang`` attribute; default
  to ``"fi"``, override if Swedish / English content is detected.
"""
from __future__ import annotations

import re
from datetime import date

from .dates import latest_year, parse_any, parse_numeric, parse_spelled
from .metadata_finlex import RootMetadata

# Validity range: "ajalle 1.1.1995 - 31.12.1995" / "ajalle 8.4.2016–31.12.2017"
_RANGE_RE = re.compile(
    r"ajalle\s+(\d{1,2}\.\d{1,2}\.\d{4})\s*[-–—]\s*(\d{1,2}\.\d{1,2}\.\d{4})",
    re.IGNORECASE,
)

# "Ennakkoratkaisu vuodelle 2008" → annual ruling, repeal at year end.
_YEAR_RE = re.compile(
    r"(?:Ennakkoratkaisu|Ennakkotieto)\s+vuodelle\s+(\d{4})",
    re.IGNORECASE,
)

# Body publication marker — Vero päätökset use the same Finnish form.
_VOIMAAN_RE = re.compile(
    r"tulee\s+voimaan[^<.]{0,80}",
    re.IGNORECASE,
)

# Heading sometimes carries an issue date like "Antopäivä 8.5.2017"
_ANTOPAIVA_RE = re.compile(
    r"Antopäivä[^<\d]{0,10}(\d{1,2}\.\d{1,2}\.\d{4})",
    re.IGNORECASE,
)

_KUMOTTU_RE = re.compile(
    r"\bKUMOTTU\b|\(kumottu\)|\bpoistettu\b",
    re.IGNORECASE,
)

# "tämä ohje korvaa …" — supersession marker. We just flag presence; the
# actual target document is resolved in a later pass when Step 2 edges are
# available. For now we don't try to parse the referenced ohje from prose.
_KORVAA_RE = re.compile(r"tämä\s+ohje\s+korvaa", re.IGNORECASE)


def extract(html: str, *, title: str | None = None) -> RootMetadata:
    publication = _extract_publication(html)
    repeal = _extract_repeal(html)
    in_force = _extract_in_force(html, repeal)

    return RootMetadata(
        publication_date=publication,
        effective_date=publication,    # for Vero, no separate effective marker
        repeal_date=repeal,
        in_force=in_force,
        language=_extract_language(html),
        superseded_by=None,
    )


def _extract_language(html: str) -> str:
    # Vero HTML rarely has a lang attr. Could heuristically detect Swedish
    # by looking for åäö clusters specific to Swedish vs Finnish — skip
    # for v1, treat all Vero docs as Finnish until a real Swedish doc
    # shows up in the corpus.
    return "fi"


def _extract_publication(html: str) -> date | None:
    # Prefer explicit "Antopäivä" if present (Vero päätös shell).
    m = _ANTOPAIVA_RE.search(html)
    if m:
        d = parse_numeric(m.group(0))
        if d is not None:
            return d

    # Range start (KVL ennakkoratkaisu).
    m = _RANGE_RE.search(html)
    if m:
        d = parse_numeric(m.group(1))
        if d is not None:
            return d

    # Year-only ruling: place at Jan 1 of that year.
    m = _YEAR_RE.search(html)
    if m:
        return date(int(m.group(1)), 1, 1)

    # Body "tulee voimaan" clause.
    for vm in _VOIMAAN_RE.finditer(html):
        d = parse_any(vm.group(0))
        if d is not None:
            return d

    # Generic fallback: first numeric date anywhere in the body.
    d = parse_numeric(html)
    if d is not None:
        return d

    # Last resort: latest year mentioned in the body. Vero kannanotot
    # and KVL rulings often state effective tax year ("verovuodesta
    # 2026") without a structured publication marker.
    y = latest_year(html)
    if y is not None:
        return date(y, 1, 1)

    return None


def _extract_repeal(html: str) -> date | None:
    m = _RANGE_RE.search(html)
    if m:
        d = parse_numeric(m.group(2))
        if d is not None:
            return d

    m = _YEAR_RE.search(html)
    if m:
        return date(int(m.group(1)), 12, 31)

    return None


def _extract_in_force(html: str, repeal: date | None) -> bool:
    if _KUMOTTU_RE.search(html):
        return False
    # If we have a fixed repeal date and it's in the past, the runner
    # will downgrade in_force in the composite step. Leave True here so
    # the composite step is the sole gate.
    _ = repeal
    return True


def has_korvaa_marker(html: str) -> bool:
    """True if the body contains 'tämä ohje korvaa' — used by the runner
    to flag supersession candidates for follow-up resolution."""
    return bool(_KORVAA_RE.search(html))
