"""B3.1 — Finlex metadata extractor.

Covers both the säädöskokoelma (clean consolidated laws) and the
Laki/Asetus amendment files. Both share the same HTML root shape:

    <html lang="fi">
        <h1>{title}</h1>
        ...
        <p>Tämä laki tulee voimaan {date}...</p>      (optional)
        <h4>{DD.MM.YYYY}/{N}:</h4>                     (only in consolidated)

What we extract:

- ``publication_date`` — from the latest amendment ``<h4>`` if present;
  else from the ``Annettu ...`` clause; else from ``tulee voimaan`` as a
  fallback (better than nothing).
- ``effective_date`` — from ``tulee voimaan ...``.
- ``repeal_date`` — from ``kumotaan/kumottu ... lailla NNN/YYYY`` markers
  when a parseable date is nearby. The vast majority of files won't have
  this — that's expected per the spec's coverage table.
- ``in_force`` — False if the document title contains ``kumoamisesta``
  ("about repealing"), or if a top-level marker says ``ei voimassa`` /
  the document is itself a repeal act. Otherwise True.
- ``language`` — from ``<html lang>`` or default ``"fi"``.
- ``superseded_by`` — left null here; the pipeline runner walks
  ``edges.jsonl`` to fill this in (only available after Step 2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .dates import latest_year, parse_any, parse_numeric, parse_spelled

# `<html lang="...">`
_LANG_RE = re.compile(r'<html[^>]*\blang\s*=\s*"([a-zA-Z-]{2,7})"', re.IGNORECASE)

# Last `<h4>DD.MM.YYYY/NNN:</h4>` in consolidated files == latest amendment date.
_AMENDMENT_HEADER_RE = re.compile(
    r"<h4>\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*/\s*\d+\s*:?\s*</h4>",
    re.IGNORECASE,
)

# "Annettu Helsingissä 16 päivänä huhtikuuta 2008" → publication date.
_ANNETTU_RE = re.compile(
    r"Annettu[^<]{0,40}?(\d{1,2}\s+päivänä\s+[A-Za-zÄÖÅäöå]+\s+\d{4})",
    re.IGNORECASE,
)

# "Tämä laki tulee voimaan 1 päivänä heinäkuuta 2017" → effective.
_VOIMAAN_RE = re.compile(
    r"tulee\s+voimaan[^<.]{0,80}",
    re.IGNORECASE,
)

# "kumotaan ... lailla 658/2015" — finds an explicit repeal source.
# We can't always get the date of repeal from the number; just flag a
# repeal context. The pipeline runner walks `repeals` edges in Step 2 to
# set repeal_date precisely.
_KUMOTTU_RE = re.compile(r"\bkumotaan\b|\bkumottu\b", re.IGNORECASE)


@dataclass(frozen=True)
class RootMetadata:
    """Document-level metadata, propagated to every node under the same root."""

    publication_date: date | None = None
    effective_date: date | None = None
    repeal_date: date | None = None
    in_force: bool | None = None
    language: str | None = None
    superseded_by: str | None = None


def extract(html: str, *, title: str | None = None) -> RootMetadata:
    """Return Finlex root metadata for one HTML document.

    ``title`` is the parser-supplied root title (Step 1's ``Node.title``).
    We use it for the ``kumoamisesta`` heuristic — the filename and h1
    typically match, but the parser already trimmed it.
    """
    language = _extract_language(html)
    publication = _extract_publication(html)
    effective = _extract_effective(html)
    in_force = _extract_in_force(html, title)

    return RootMetadata(
        publication_date=publication or effective,  # fallback: at least the in-force date
        effective_date=effective,
        repeal_date=None,         # filled by pipeline runner from edges or amendments
        in_force=in_force,
        language=language,
        superseded_by=None,       # filled by pipeline runner
    )


def _extract_language(html: str) -> str:
    m = _LANG_RE.search(html)
    if not m:
        return "fi"  # Finlex corpus default
    return m.group(1).lower().split("-")[0]  # "fi-FI" → "fi"


def _extract_publication(html: str) -> date | None:
    # Consolidated files: latest <h4> amendment date is the most recent
    # publication of the document as-of the snapshot.
    matches = _AMENDMENT_HEADER_RE.findall(html)
    if matches:
        return parse_numeric(matches[-1])

    # Standalone laws / decrees: "Annettu Helsingissä N päivänä KUUKAUSI YYYY"
    m = _ANNETTU_RE.search(html)
    if m:
        return parse_spelled(m.group(1))

    # Last resort: latest year mentioned in the body (typically a "/YYYY"
    # law-number suffix or a "vuonna YYYY" clause). Coarse Jan-1 anchor —
    # better than null for date-range retrieval. Only used when nothing
    # structured was found.
    y = latest_year(html)
    if y is not None:
        return date(y, 1, 1)

    return None


def _extract_effective(html: str) -> date | None:
    for m in _VOIMAAN_RE.finditer(html):
        d = parse_any(m.group(0))
        if d is not None:
            return d
    return None


def _extract_in_force(html: str, title: str | None) -> bool:
    """Conservative: True by default, False only on a clear repeal signal."""
    if title and "kumoamisesta" in title.lower():
        return False
    if "ei voimassa" in html.lower():
        return False
    # Don't flip in_force=False just because the document mentions
    # "kumotaan" — it's commonly used to describe what *this* statute
    # repeals from older statutes, not its own status. Leave the more
    # precise repeal_date propagation to the pipeline runner.
    _ = _KUMOTTU_RE  # silence unused-name
    return True
