"""B3.3 — Composite ``usable`` flag.

A node is *usable* for default retrieval iff it is currently in force and
has not been superseded by a newer version. Repealed nodes aren't deleted —
historical queries still need them — but the default filter hides them.
"""
from __future__ import annotations

from datetime import date


def usable(
    *,
    in_force: bool | None,
    repeal_date: date | None,
    superseded_by: str | None,
    today: date | None = None,
) -> bool:
    """Return the composite filter flag.

    None ``in_force`` is treated as True (default-current). Pass a
    deterministic ``today`` from the runner to keep batch runs reproducible.
    """
    today = today or date.today()

    if in_force is False:
        return False

    if repeal_date is not None and repeal_date <= today:
        return False

    if superseded_by is not None:
        return False

    return True
