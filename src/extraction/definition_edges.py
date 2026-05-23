"""B2.6 — Definition edges.

Step 1 emits `DEFINITION` nodes whenever a paragraph's first 200 chars
contain `tarkoitetaan` / `määritellään` / `defined as`. Step 2 connects
each such definition to the SECTION/SUBSECTION/ITEM nodes in the same
LAW that use the defined term.

Term extraction is intentionally simple — the noun phrase immediately
following `tarkoitetaan` / `määritellään` (the most common Finnish
definition pattern is "X:llä tarkoitetaan ..." or "Tässä laissa
tarkoitetaan: 1) X ..."). We don't attempt cross-LAW propagation in v1;
the same word can carry different meanings in different statutes.

Confidence is 0.7 — lower than regex citations because term matching
is fuzzy: case-insensitive substring against the consumer node's text,
no morphological agreement, no word-boundary check beyond Finnish-aware
stripping.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from src.extraction.node_index import NodeIndex
from src.models import Edge


# A handful of Finnish suffixes we strip to get a search stem. Order matters —
# longest first.
_FI_SUFFIXES = (
    "llaan", "lleen", "ksensa", "nsa", "nsä",
    "lla", "llä", "lle", "ssa", "ssä", "sta", "stä",
    "han", "hin", "an", "in", "en", "on",
    "a", "ä", "n", "t",
)


_TRIGGER_RE = re.compile(
    r"\b(?:tarkoitetaan|tarkoittaa|m[äa][äa]ritell[äa][äa]n|defined\s+as|means)\b",
    re.IGNORECASE,
)
_PUNCT_TAIL = re.compile(r"[\.,;:\!\?]+$")
_TERM_TOKEN = re.compile(r"^[a-zäöåA-ZÄÖÅ\-]{4,}$")  # at least 4 chars; word-like


def extract_defined_terms(text: str) -> list[str]:
    """Return candidate defined-term lemmas from a DEFINITION node text.

    Looks at the word *immediately preceding* (most common: "X:llä
    tarkoitetaan …") and immediately following the trigger. Returns up to
    two lemmas, longest-first.
    """
    if not text:
        return []
    terms: list[str] = []
    for m in _TRIGGER_RE.finditer(text):
        before = text[: m.start()].rstrip()
        after = text[m.end():].lstrip()
        # Word before trigger — strip a possible ":lla" / ":llä" qualifier.
        if before:
            tail_match = re.search(r"([A-Za-zÄÖÅäöå\-]{4,})(?:[:\s][a-zäö]{2,4})?\s*$", before)
            if tail_match:
                terms.append(tail_match.group(1))
        # Word after trigger — first non-puncutation token > 4 chars.
        if after:
            head_match = re.match(r"\s*([A-Za-zÄÖÅäöå\-]{4,})", after)
            if head_match:
                terms.append(head_match.group(1))
    return _dedup_and_clean(terms)


def _dedup_and_clean(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for w in raw:
        w = _PUNCT_TAIL.sub("", w).lower()
        if not _TERM_TOKEN.match(w):
            continue
        stem = _stem(w)
        if len(stem) < 4 or stem in seen:
            continue
        seen.add(stem)
        out.append(stem)
    # Longest first so partial overlaps don't double-count.
    out.sort(key=len, reverse=True)
    return out


def _stem(word: str) -> str:
    w = word.lower()
    for suf in _FI_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


# ---------------------------------------------------------------------------

def extract_definition_edges(
    node_index: NodeIndex,
    nodes_jsonl: Path,
    *,
    max_consumers_per_def: int = 200,
) -> Iterator[Edge]:
    """For every DEFINITION node, emit `defines` edges to same-law users.

    We re-stream `nodes.jsonl` (rather than holding all text in memory)
    once per LAW that has at least one DEFINITION. Memory cost is the
    pre-built map ``defs_by_law: law_id -> [(def_id, [stem...])]``.
    """
    defs_by_law: dict[str, list[tuple[str, list[str]]]] = {}
    consumer_types = ("SECTION", "SUBSECTION", "ITEM")

    # First pass: collect DEFINITION node terms.
    with nodes_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if '"DEFINITION"' not in line:
                continue
            d = json.loads(line)
            if d.get("type") != "DEFINITION":
                continue
            law_id = d.get("law_id")
            if not law_id:
                continue
            stems = extract_defined_terms(d.get("text", ""))
            if not stems:
                continue
            defs_by_law.setdefault(law_id, []).append((d["id"], stems))

    if not defs_by_law:
        return

    # Second pass: scan consumer nodes once. Per matching law, test each
    # definition's stems against the consumer's text.
    emitted: dict[str, int] = {}  # def_id -> count, capped at max_consumers_per_def
    with nodes_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("type") not in consumer_types:
                continue
            law_id = d.get("law_id")
            if not law_id or law_id not in defs_by_law:
                continue
            text_lc = (d.get("text") or "").lower()
            if not text_lc:
                continue
            consumer_id = d["id"]
            for def_id, stems in defs_by_law[law_id]:
                if def_id == consumer_id:
                    continue
                if emitted.get(def_id, 0) >= max_consumers_per_def:
                    continue
                # First matching stem wins — avoids quadratic per-term scan.
                if any(stem in text_lc for stem in stems):
                    emitted[def_id] = emitted.get(def_id, 0) + 1
                    yield Edge(
                        source_id=def_id,
                        target_id=consumer_id,
                        target_ref=consumer_id,
                        type="defines",
                        confidence=0.7,
                        extracted_by="regex",  # term-matching is regex-ish, not LLM
                        context_snippet=None,
                    )


if __name__ == "__main__":
    import sys
    samples = [
        "Tässä laissa työkyvyttömyyden uhkalla tarkoitetaan tilannetta, jossa…",
        "Arvonlisäverolla tarkoitetaan tämän lain mukaista veroa.",
        "Kiinteistöllä tarkoitetaan: 1) maata, 2) rakennuksia ja 3) huoneistoja.",
    ]
    print("[self-test] extract_defined_terms:")
    for s in samples:
        terms = extract_defined_terms(s)
        print(f"  {s!r}\n    -> {terms}")
    if not all(extract_defined_terms(s) for s in samples):
        print("FAIL: some samples produced no terms")
        sys.exit(1)
    print("OK")
