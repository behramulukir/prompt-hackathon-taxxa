"""Finnish-aware date parsing for Step 3 metadata extraction.

Two forms appear in the Finnish legal corpus:

1. Numeric:   ``30.4.1993`` / ``30.4.1993/391``      → Finlex amendment headers
2. Spelled:   ``30 päivänä huhtikuuta 1993``         → "tulee voimaan" clauses

Both resolve to a stdlib ``datetime.date``. Partitive month forms
(``tammikuuta``) are folded to the nominative for lookup.
"""
from __future__ import annotations

import re
from datetime import date

# Partitive month names (… `päivänä <month>ta`). Keys are lowercased stems —
# the regex strips the partitive suffix before lookup.
_FI_MONTHS: dict[str, int] = {
    "tammikuu":  1,
    "helmikuu":  2,
    "maaliskuu": 3,
    "huhtikuu":  4,
    "toukokuu":  5,
    "kesakuu":   6,
    "kesäkuu":   6,
    "heinakuu":  7,
    "heinäkuu":  7,
    "elokuu":    8,
    "syyskuu":   9,
    "lokakuu":  10,
    "marraskuu":11,
    "joulukuu": 12,
}

# Matches "12.3.1993" or "12.3.1993/391:" (Finlex amendment header form).
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")

# Matches "12 päivänä huhtikuuta 2017" (and partitive month variants).
_SPELLED_DATE_RE = re.compile(
    r"(\d{1,2})\s+päivänä\s+([A-Za-zÄÖÅäöå]+?)(?:ta|tä)?\s+(\d{4})",
    re.IGNORECASE,
)


def parse_numeric(s: str) -> date | None:
    """First DD.MM.YYYY occurrence in *s*, or None."""
    m = _NUMERIC_DATE_RE.search(s)
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    return _safe_date(y, mo, d)


def parse_spelled(s: str) -> date | None:
    """First ``N päivänä KUUKAUSI YYYY`` occurrence in *s*, or None."""
    m = _SPELLED_DATE_RE.search(s)
    if not m:
        return None
    d_str, month_word, y_str = m.groups()
    month = _FI_MONTHS.get(month_word.lower())
    if month is None:
        return None
    return _safe_date(int(y_str), month, int(d_str))


def parse_any(s: str) -> date | None:
    """Try spelled form first (more specific), then numeric."""
    return parse_spelled(s) or parse_numeric(s)


# Last-resort year scrape — used when no structured date was found.
# Matches "/YYYY" (law-number suffix), "vuonna YYYY", "verovuosi YYYY",
# and bare four-digit years in a reasonable range. The caller picks the
# *latest* year as a coarse publication proxy.
_YEAR_RE = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d|2100)(?!\d)")


def latest_year(s: str) -> int | None:
    """Most recent plausible publication year in *s*, or None."""
    years = _YEAR_RE.findall(s)
    if not years:
        return None
    return max(int(y) for y in years)


def _safe_date(y: int, m: int, d: int) -> date | None:
    if not (1800 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None
