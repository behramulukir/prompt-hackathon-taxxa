"""KHO metadata extractor (precedent case law).

KHO files are minimal:

    <h1>KHO:YYYY:NN</h1>            or  <h1>KHO:YYYY-B-NNN</h1>
    <p>…body text, sometimes with "Verovuosi_YYYY"…</p>
    <p>statute reference…</p>

We extract the case year from the h1 (always present) and treat that as
both publication and effective date with Jan 1 of the case year. Precise
day-level dates aren't in the HTML; downstream filtering is year-grained
for case law anyway.
"""
from __future__ import annotations

import re
from datetime import date

from .metadata_finlex import RootMetadata

_CASE_ID_RE = re.compile(r"KHO[:\s]+(\d{4})", re.IGNORECASE)
_VEROVUOSI_RE = re.compile(r"Verovuosi[_\s](\d{4})")


def extract(html: str, *, title: str | None = None, source_file: str = "") -> RootMetadata:
    year = _extract_year(html, title, source_file)
    pub: date | None = date(year, 1, 1) if year else None
    return RootMetadata(
        publication_date=pub,
        effective_date=pub,
        repeal_date=None,
        in_force=True,
        language="fi",
        superseded_by=None,
    )


def _extract_year(html: str, title: str | None, source_file: str) -> int | None:
    for src in (title or "", html, source_file):
        m = _CASE_ID_RE.search(src)
        if m:
            return int(m.group(1))
    m = _VEROVUOSI_RE.search(html)
    if m:
        return int(m.group(1))
    return None
