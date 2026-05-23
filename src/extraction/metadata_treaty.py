"""Treaty (Tuloverosopimukset) metadata extractor.

Treaties are signed on a specific day, ratified later, and enter into
force on a third day. The HTML usually contains all three in spelled-out
form ("16 päivänä lokakuuta 2006"). We extract the *first* spelled date
found in the document — for the synthesized text shipped by Finlex, this
is the signing date of the underlying treaty, which is the closest
analogue to ``publication_date`` for this corpus.

If no spelled date is found, we leave publication null; treaties are a
small share of the corpus (~117 files) so QA can flag misses by hand.
"""
from __future__ import annotations

import re

from .dates import parse_spelled
from .metadata_finlex import RootMetadata

_FIRST_SPELLED_DATE_RE = re.compile(
    r"\d{1,2}\s+päivänä\s+[A-Za-zÄÖÅäöå]+\s+\d{4}",
    re.IGNORECASE,
)


def extract(html: str, *, title: str | None = None) -> RootMetadata:
    pub = None
    m = _FIRST_SPELLED_DATE_RE.search(html)
    if m:
        pub = parse_spelled(m.group(0))
    return RootMetadata(
        publication_date=pub,
        effective_date=pub,
        repeal_date=None,
        in_force=True,
        language="fi",
        superseded_by=None,
    )
