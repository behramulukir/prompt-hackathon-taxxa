"""Step 10 / Move 1 — Extract operative payload from amendment instruments.

A "Laki X muuttamisesta" / "Laki X kumoamisesta" instrument-LAW contains:

  - A short paragraph header (``/p1`` "Eduskunnan päätöksen mukaisesti")
  - One or more directive paragraphs (``/p2`` … "muutetaan / kumotaan /
    lisätään <law-name>:n <§-list> [, sellaisena kuin … ,] seuraavasti:")
  - One SECTION child per amended §, carrying the *new wording* in its
    own momentti/item subtree.

This script turns each directive into a stream of ``AmendmentOp`` records
(one per (verb, target §) pair) and writes them to
``output/amendment_ops.jsonl``. Move 2
(``scripts/resolve_amendment_targets.py``) then resolves each op's
``target_section_label`` to a concrete ``target_section_id`` in the
graph and emits ``amends_section`` edges.

We deliberately *do not* parse the AMENDMENT_BLOCK nodes that live
inside consolidated laws (``/c<n>/a14-5-2010-409``-style). Those carry
only voimaantulo clauses, not directives — verified by sampling. The
operative payload lives exclusively in amendment-instrument LAW roots.

Outputs:
- ``output/amendment_ops.jsonl`` (one op per line, Pydantic-validated)
- ``output/amendment_ops_stats.json`` (per-verb counts, parse failures)

CLI::

    .venv/bin/python -m scripts.extract_amendment_ops             # full
    .venv/bin/python -m scripts.extract_amendment_ops --dry-run   # report only
    .venv/bin/python -m scripts.extract_amendment_ops --limit 50  # smoke test
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction.dates import parse_any, parse_numeric, parse_spelled
from src.models import AmendmentOp

OUTPUT_DIR = PROJECT_ROOT / "output"
GRAPH_DB = OUTPUT_DIR / "graph.db"
OPS_JSONL = OUTPUT_DIR / "amendment_ops.jsonl"
STATS_OUT = OUTPUT_DIR / "amendment_ops_stats.json"


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------
#
# Directive paragraph anatomy:
#
#   muutetaan 25 päivänä heinäkuuta 1986 annetun potilasvahinkolain
#   ( 585/1986 ) 11 a §:n 4 momentti, sellaisena kuin se on laissa 640/2000,
#   seuraavasti:
#
#                 ^^^^^^^^^^^^^^^^^^^^^^^^
#                       verb            target identifier
#
# We pick the operative *scope* as the substring from a verb keyword up
# to either ``seuraavasti:`` (the colon that introduces the new wording)
# or a sentence-ending period that isn't inside parens. Inside the scope
# we then find every § identifier.
#
# The verbs are matched as inflected stems: muutetaan/muutetaan,
# kumotaan/kumotaan, lisätään/lisätään. Finnish doesn't conjugate these
# heavily in legal prose (they're 4-person passive), so a non-greedy
# stem match is enough.

_VERB_RE = re.compile(
    r"\b(muutetaan|kumotaan|lis[äa]t[äa][äa]n)\b",
    re.IGNORECASE,
)

# Section identifier inside a directive scope:
#   - "11 §" — base
#   - "11 a §" / "11a §" — letter suffix (with or without space)
#   - "11–14 §" — range (not handled in v1; flagged as chain_complex)
#   - "§ 11" — leading § (rare in Finnish legal prose, but seen in
#     translated material)
#
# Capture groups:
#   1 = number (always present)
#   2 = optional letter suffix (a..z, with optional whitespace before)
#
_SECTION_RE = re.compile(
    r"\b(\d+)\s*([a-zäöå])?\s*§",
    re.IGNORECASE,
)

# Range marker — `5–8`, `5—8`, `5-8`. Used only to detect chain_complex,
# not to expand the range. Expanding a range needs metadata we don't have
# in v1 (do § 5, 6, 7 exist in the target law? what are their labels?),
# and a wrong expansion is worse than a missed one.
_RANGE_RE = re.compile(r"\d+\s*[\-–—]\s*\d+")

# Momentti: "§:n 4 momentti" / "11 a §:n 4 momentti".
# Used to enrich the most-recently-seen § identifier with a subsection
# pointer. ``11 a §:n 4 momentti`` lands on the § identifier capture
# above; the trailing momentti goes through this regex.
_MOMENTTI_RE = re.compile(
    r"§:n\s+(\d+)\s+momentti",
    re.IGNORECASE,
)

# Effective date — same window as backfill_amendment_edges. The amendment
# instrument's effective date typically lives in the *last* momentti of
# the *last* section (the "Tämä laki tulee voimaan 1 päivänä …" clause).
_VOIMAAN_WINDOW_RE = re.compile(
    r"tulee\s+voimaan[^.<]{0,160}", re.IGNORECASE
)


# --------------------------------------------------------------------------
# Data shapes
# --------------------------------------------------------------------------


@dataclass
class _Instrument:
    """One amendment-instrument LAW with its child paragraphs and sections.

    Holds enough context for ``parse_instrument`` to emit AmendmentOps
    without re-querying the DB per section.
    """

    law_id: str
    title: str | None
    # Paragraph children (``/p1``, ``/p2``, …) carrying the directives.
    # Joined into one string so a directive that spans p1 and p2 still
    # parses cleanly.
    directive_text: str
    # SECTION children (``/s11a``, ``/s7``, …) carrying the new wording.
    # Keyed by *normalized* label ("11a", "7", "5_a") so the parser can
    # match a directive's "§ 11 a" → the right SECTION.
    sections: dict[str, "_Section"] = field(default_factory=dict)


@dataclass
class _Section:
    id: str
    label: str | None
    text: str
    momenttis: list[str] = field(default_factory=list)  # concatenated subsection bodies


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------


def _open_db() -> sqlite3.Connection:
    if not GRAPH_DB.exists():
        raise SystemExit(
            f"ERROR: {GRAPH_DB} not found — run scripts.load_graph first."
        )
    # Read-only connection — Move 1 doesn't write to the graph.
    conn = sqlite3.connect(GRAPH_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _is_instrument_id(law_id: str) -> bool:
    lower = law_id.lower()
    return "muuttamisesta" in lower or "kumoamisesta" in lower


def _iter_instrument_laws(conn: sqlite3.Connection) -> Iterator[tuple[str, str | None]]:
    """Yield (law_id, title) for every amendment-instrument LAW."""
    cur = conn.execute(
        "SELECT id, label FROM nodes "
        "WHERE type='LAW' AND source='finlex' "
        "AND (id LIKE '%-muuttamisesta-%' OR id LIKE '%-kumoamisesta-%')"
    )
    for row in cur:
        yield row[0], row[1]


def _load_children(
    conn: sqlite3.Connection, law_id: str
) -> tuple[str, dict[str, _Section]]:
    """Return (joined paragraph text, sections-by-label).

    Paragraphs are children with ids like ``{law}/p<n>``. Their text is
    the directive prose. We join in order so multi-paragraph directives
    (rare but present) still parse as one scope.

    Sections are children with ids like ``{law}/s<n>`` or ``{law}/c<m>/s<n>``;
    the SECTION text alone is sometimes empty (when the entire body lives
    in momentti children) so we also fold in concatenated momentti bodies.
    """
    # All children — we paginate by id LIKE prefix because the schema has
    # parent_id columns but no full-subtree index. ``{law}/_%`` would be
    # nicer SQL but SQLite's ``LIKE`` doesn't have a regex equivalent.
    cur = conn.execute(
        "SELECT id, type, label, text FROM nodes WHERE id LIKE ?",
        (law_id + "/%",),
    )
    paragraph_texts: list[tuple[int, str]] = []
    section_rows: list[tuple[str, str | None, str | None]] = []
    momenttis_by_section: dict[str, list[str]] = {}
    for row in cur:
        nid = row["id"]
        ntype = row["type"]
        label = row["label"]
        text = row["text"] or ""
        rel = nid[len(law_id) + 1:]  # strip "law_id/"
        if "/" not in rel and rel.startswith("p"):
            # Top-level paragraph child (``/p1``, ``/p2``, …)
            try:
                idx = int(rel[1:])
            except ValueError:
                idx = 999
            paragraph_texts.append((idx, text))
        elif ntype == "SECTION":
            section_rows.append((nid, label, text))
        elif ntype == "SUBSECTION":
            # Find the SECTION ancestor: drop one path segment to get
            # ``{law}/s11a/m2`` → ``{law}/s11a``. Robust to chapter wrapping.
            parent = nid.rsplit("/", 1)[0]
            momenttis_by_section.setdefault(parent, []).append(text)

    paragraph_texts.sort(key=lambda t: t[0])
    directive_text = "\n".join(t for _, t in paragraph_texts)

    sections: dict[str, _Section] = {}
    for sid, lab, txt in section_rows:
        sec = _Section(
            id=sid,
            label=lab,
            text=txt or "",
            momenttis=momenttis_by_section.get(sid, []),
        )
        key = _normalize_section_label(lab) if lab else None
        if key:
            sections[key] = sec
    return directive_text, sections


# --------------------------------------------------------------------------
# Label normalization
# --------------------------------------------------------------------------


def _normalize_section_label(label: str) -> str | None:
    """Map "11 a §", "11a §", "§ 11 a" → canonical "11a".

    Used to match directive section identifiers against SECTION labels.
    Both sides go through the same function so cosmetic differences
    (whitespace, leading §) cancel out.
    """
    if not label:
        return None
    s = label.lower().strip()
    s = s.replace("§", "").strip()
    # "11 a" → "11a"; preserve digits and a..z, drop whitespace.
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        # Skip everything else (whitespace, hyphens, dots).
    if not out:
        return None
    res = "".join(out)
    # Must start with a digit — pure-letter labels aren't § identifiers.
    if not res[0].isdigit():
        return None
    return res


# --------------------------------------------------------------------------
# Directive parsing
# --------------------------------------------------------------------------


def _normalize_verb(raw: str) -> str:
    """Map the matched verb stem to one of {muutetaan, kumotaan, lisätään}."""
    v = raw.lower()
    if v.startswith("muutetaan"):
        return "muutetaan"
    if v.startswith("kumotaan"):
        return "kumotaan"
    # lisätään / lisätaan / lisätään — Finnish ä/a folding seen in some sources
    return "lisätään"


def _directive_scopes(text: str) -> list[tuple[str, int, int]]:
    """Split text into per-verb scopes.

    Yields ``(verb, start, end)`` for each verb occurrence; the scope
    runs from just after the verb to either the next verb, the next
    sentence-ending period at top level, or ``seuraavasti:``, whichever
    comes first.
    """
    verbs = [(m.start(), m.end(), _normalize_verb(m.group(1)))
             for m in _VERB_RE.finditer(text)]
    if not verbs:
        return []

    out: list[tuple[str, int, int]] = []
    for i, (vs, ve, verb) in enumerate(verbs):
        # End of scope candidates:
        next_verb_start = verbs[i + 1][0] if i + 1 < len(verbs) else len(text)
        # ``seuraavasti:`` is the canonical terminator; everything after
        # it is the *new wording*, not part of the directive.
        seur = text.lower().find("seuraavasti", ve)
        if seur == -1 or seur > next_verb_start:
            seur = next_verb_start
        # Sentence-ending period (not inside parens). We approximate by
        # finding a ``. `` at top level via a simple depth counter.
        depth = 0
        period = next_verb_start
        for j in range(ve, min(next_verb_start, seur)):
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "." and depth == 0:
                # Real sentence break only if followed by whitespace + capital
                # or end-of-text. Otherwise it's a decimal in "( 585/1986 )"
                # — but those are inside parens, so they shouldn't reach here.
                rest = text[j + 1: j + 3]
                if not rest or rest[0] in (" ", "\n", "\t"):
                    period = j
                    break
        end = min(seur, period, next_verb_start)
        out.append((verb, ve, end))
    return out


@dataclass
class _DirectiveHit:
    """One (verb, section) pair extracted from a directive scope."""

    verb: str
    section_label: str           # raw "11 a §" / "11a §"
    section_norm: str            # "11a"
    target_subsection: int | None
    chain_complex: bool          # range/list ambiguity caught


def _parse_directive_scope(verb: str, scope: str) -> list[_DirectiveHit]:
    """Pull every § identifier out of one verb's scope.

    Records ``chain_complex=True`` on hits when the scope contains a
    range marker — the LLM/UI should treat those ops as advisory.
    """
    has_range = bool(_RANGE_RE.search(scope))
    hits: list[_DirectiveHit] = []
    # Build a per-section momentti map: if a momentti reference like
    # "§:n 4 momentti" appears within ~80 chars after a section
    # identifier, attach it. Otherwise None.
    momenttis: list[tuple[int, int]] = [
        (m.start(), int(m.group(1))) for m in _MOMENTTI_RE.finditer(scope)
    ]
    for m in _SECTION_RE.finditer(scope):
        num = m.group(1)
        letter = (m.group(2) or "").lower()
        raw = f"{num}{(' ' + letter) if letter else ''} §"
        norm = f"{num}{letter}"
        subsection: int | None = None
        for mom_start, mom_n in momenttis:
            if 0 <= mom_start - m.end() <= 80:
                subsection = mom_n
                break
        hits.append(
            _DirectiveHit(
                verb=verb,
                section_label=raw,
                section_norm=norm,
                target_subsection=subsection,
                chain_complex=has_range,
            )
        )
    return hits


def _parse_effective_date(instrument: _Instrument) -> date | None:
    """Find the instrument's effective date.

    Search order:
      1. The *last* SECTION's last momentti — that's where the
         ``Tämä laki tulee voimaan …`` clause typically lives.
      2. Any momentti in any SECTION (some instruments inline the
         voimaantulo in the first SECTION).
      3. Anywhere in the directive text (very rare).
    """
    sections_in_order = sorted(
        instrument.sections.values(),
        key=lambda s: s.id,
    )
    if sections_in_order:
        # Last momentti of last section.
        last_section = sections_in_order[-1]
        for body in reversed(last_section.momenttis or [last_section.text]):
            d = _date_from_voimaantulo(body)
            if d is not None:
                return d
        # Any momentti, any section.
        for sec in sections_in_order:
            for body in sec.momenttis or [sec.text]:
                d = _date_from_voimaantulo(body)
                if d is not None:
                    return d
    # Last-ditch: scan the directive text itself.
    return _date_from_voimaantulo(instrument.directive_text)


def _date_from_voimaantulo(text: str) -> date | None:
    if not text:
        return None
    for m in _VOIMAAN_WINDOW_RE.finditer(text):
        d = parse_any(m.group(0))
        if d is not None:
            return d
    return None


# --------------------------------------------------------------------------
# Main per-instrument routine
# --------------------------------------------------------------------------


def parse_instrument(instrument: _Instrument) -> list[AmendmentOp]:
    """Turn one amendment-instrument LAW into a list of AmendmentOps."""
    if not instrument.directive_text.strip():
        return []
    scopes = _directive_scopes(instrument.directive_text)
    if not scopes:
        return []
    effective = _parse_effective_date(instrument)

    out: list[AmendmentOp] = []
    for verb, start, end in scopes:
        scope = instrument.directive_text[start:end]
        hits = _parse_directive_scope(verb, scope)
        for h in hits:
            # Pair the hit against a SECTION child by normalized label.
            # For ``muutetaan``/``lisätään`` we want the new wording;
            # ``kumotaan`` has no new text by construction.
            section = instrument.sections.get(h.section_norm)
            new_text: str | None = None
            confidence = 1.0
            if h.verb != "kumotaan":
                if section is not None:
                    # Concatenate section body + momenttis to preserve
                    # the full new wording. Strip any trailing
                    # "Tämä laki tulee voimaan …" momentti since that's
                    # metadata, not the operative content. Heuristic:
                    # drop a trailing chunk that matches the voimaantulo
                    # window pattern.
                    parts = ([section.text] if section.text else []) + section.momenttis
                    parts = [p for p in parts
                             if not _VOIMAAN_WINDOW_RE.search(p or "")]
                    body = "\n".join(p.strip() for p in parts if p and p.strip())
                    new_text = body or None
                    # Found the section → confidence stays 1.0 unless
                    # chain_complex flagged it.
                    if new_text is None:
                        confidence = 0.7
                else:
                    # Directive points to a section we couldn't find as
                    # a child — likely the directive parser over-matched
                    # (e.g. caught a § inside the operative scope that
                    # was actually a citation). Drop the op rather than
                    # emit a noisy one.
                    continue

            if h.chain_complex:
                # We have a verb + target, but the directive also
                # contains a range — the LLM should treat ``new_text``
                # as approximate.
                confidence = min(confidence, 0.6)

            op = AmendmentOp(
                block_id=instrument.law_id,
                block_law_id=instrument.law_id,
                verb=h.verb,  # type: ignore[arg-type]
                target_section_label=h.section_label,
                target_subsection=h.target_subsection,
                new_text=new_text,
                effective_date=effective,
                confidence=confidence,
                chain_complex=h.chain_complex,
            )
            out.append(op)
    return out


# --------------------------------------------------------------------------
# Streaming runner
# --------------------------------------------------------------------------


def run(
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict:
    conn = _open_db()
    try:
        t0 = time.time()
        laws = list(_iter_instrument_laws(conn))
        print(f"[ops] found {len(laws):,} amendment-instrument LAWs "
              f"in {time.time()-t0:.1f}s")
        if limit:
            laws = laws[:limit]
            print(f"[ops] limited to {len(laws):,} (smoke run)")

        counts = Counter()
        verb_counts = Counter()
        records: list[dict] = []
        instruments_emitting = 0
        no_directive = 0
        no_section_children = 0

        t1 = time.time()
        for i, (law_id, label) in enumerate(laws):
            if i and i % 1000 == 0:
                rate = i / max(time.time() - t1, 1e-6)
                eta = (len(laws) - i) / rate if rate else 0
                print(
                    f"[ops]   {i:>6,}/{len(laws):,} "
                    f"({rate:.0f}/s, eta {eta:.0f}s)",
                    flush=True,
                )
            directive, sections = _load_children(conn, law_id)
            if not directive.strip():
                no_directive += 1
                continue
            if not sections:
                # Pure-repeal instruments often have no SECTION children
                # (the directive is the whole thing). We still emit the
                # ``kumotaan`` op — the parser will see a verb without a
                # matching section_norm and we'll allow it through with
                # ``new_text=None``. To support that we add a synthetic
                # entry to the instrument.sections map below.
                pass
            instrument = _Instrument(
                law_id=law_id,
                title=label,
                directive_text=directive,
                sections=sections,
            )
            ops = parse_instrument(instrument)
            # Special case: kumotaan instruments may have no SECTION
            # children at all. ``parse_instrument`` ``continue``s for
            # missing sections, but for kumotaan the directive itself
            # is enough — re-parse and emit kumotaan ops without a
            # section_norm guard.
            if not ops and "kumotaan" in directive.lower():
                for verb, start, end in _directive_scopes(directive):
                    if verb != "kumotaan":
                        continue
                    scope = directive[start:end]
                    for h in _parse_directive_scope(verb, scope):
                        ops.append(
                            AmendmentOp(
                                block_id=law_id,
                                block_law_id=law_id,
                                verb="kumotaan",
                                target_section_label=h.section_label,
                                target_subsection=h.target_subsection,
                                new_text=None,
                                effective_date=_parse_effective_date(instrument),
                                confidence=0.9,
                                chain_complex=h.chain_complex,
                            )
                        )
            if ops:
                instruments_emitting += 1
                for op in ops:
                    counts["ops_total"] += 1
                    verb_counts[op.verb] += 1
                    if op.chain_complex:
                        counts["chain_complex"] += 1
                    if op.target_subsection is not None:
                        counts["subsection_targeted"] += 1
                    records.append(op.model_dump(mode="json"))
            else:
                no_section_children += 1

        dur = time.time() - t1
        print(f"[ops] parsed {instruments_emitting:,} instruments → "
              f"{counts['ops_total']:,} ops in {dur:.1f}s")
        print(f"[ops]   no-directive instruments:   {no_directive:,}")
        print(f"[ops]   no-ops instruments:         {no_section_children:,}")
        print(f"[ops]   chain_complex:              {counts['chain_complex']:,}")
        print(f"[ops]   subsection-targeted:        {counts['subsection_targeted']:,}")
        print(f"[ops]   verbs: {dict(verb_counts)}")

        stats = {
            "instruments_scanned": len(laws),
            "instruments_with_ops": instruments_emitting,
            "no_directive": no_directive,
            "no_ops": no_section_children,
            "ops_total": counts["ops_total"],
            "by_verb": dict(verb_counts),
            "chain_complex": counts["chain_complex"],
            "subsection_targeted": counts["subsection_targeted"],
            "dry_run": dry_run,
        }
        if not dry_run:
            OPS_JSONL.parent.mkdir(parents=True, exist_ok=True)
            with OPS_JSONL.open("w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str))
                    f.write("\n")
            print(f"[ops] wrote {len(records):,} records → {OPS_JSONL}")
            STATS_OUT.write_text(json.dumps(stats, indent=2), encoding="utf-8")
            print(f"[ops] stats → {STATS_OUT}")
        return stats
    finally:
        conn.close()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and report; do not write outputs.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N instrument LAWs (smoke run).")
    args = ap.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)
    print("[ops] DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
