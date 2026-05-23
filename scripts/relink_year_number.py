"""Step 2.5 — close dangling `(year, number)` edges.

Step 2 left ~34k anchor edges and ~10k regex edges with reason
``not_yet_parsed`` because ``NodeIndex.by_law_year_number`` only contained
the laws whose *titles* carry an explicit ``(NNN/YYYY)`` form (~1.2k of
1.97M). The actual bridge between numeric statute references and the
consolidated law nodes lives in the *amendment* files under
``data/finlex/{Laki,Asetus}/``: every amendment file has an ``<a href>``
pointing at the base law's canonical ``act/statute/YYYY/NNN`` URL, and
its title carries the base-law name in Finnish genitive form.

Pipeline:

    1. Walk amendment HTML files; from each, lemmatize the title to a
       base-law slug and look it up via ``NodeIndex.by_law_title``. Record
       every anchor ``(year, number)`` in the file as → that base law's
       ``law_id`` (only when the title resolved).
    2. (Optional) Cross-check year against the consolidated law's
       ``publication_date`` from ``output/nodes_enriched.jsonl``.
    3. Stream ``output/dangling_edges.log``: for each entry, parse a
       ``(year, number)`` out of ``target_ref`` and look it up in the new
       index. Hits become resolved edges appended to ``output/edges.jsonl``;
       misses stay in ``output/dangling_edges.log``.
    4. Update ``output/edge_stats.json``.

Purely additive — never deletes edges, never changes ``source_id`` /
``type`` / ``confidence``. Backs up both touched files before rewriting.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from src.extraction.ids import parse_href
from src.extraction.node_index import NodeIndex, title_slug


# ---------------------------------------------------------------------------
# Amendment-file scanning
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"<h1>([^<]+)</h1>", re.IGNORECASE)
_ACT_URL_RE = re.compile(
    r"finlex\.fi/(?:akn/fi/act/statute|fi/laki/(?:ajantasa|alkup|smur))/(\d{4})/(\d+)",
    re.IGNORECASE,
)
_TARGET_REF_YN = re.compile(r"\b(\d{4})/(\d{1,4})\b")

# Finnish nominal endings → lemma. Order: longest first. Each row maps a
# (suffix tuple) → replacement base ("laki" / "kaari" / "asetus").
_LEMMA_RULES: list[tuple[tuple[str, ...], str]] = [
    (("laissaan", "laissamme", "laissa", "laista", "laille", "lailla", "laiksi",
      "lakeja", "lakien", "laeissa", "laeista", "lakia", "lakiin", "lakina",
      "lain", "laki"), "laki"),
    (("kaaressa", "kaaresta", "kaareen", "kaaren", "kaari"), "kaari"),
]


def _lemma(word: str) -> Optional[str]:
    w = word.lower()
    for suffixes, base in _LEMMA_RULES:
        for suf in suffixes:
            if w.endswith(suf) and len(w) > len(suf) + 2:
                return w[: -len(suf)] + base
    return None


def _base_law_slug_from_title(title: str) -> Optional[str]:
    """Lemmatize the first '*lai-' / '*kaar-' word in the amendment title."""
    for token in re.findall(r"[A-Za-zÄÖÅäöå-]{5,}", title.lower()):
        lemma = _lemma(token)
        if lemma:
            return title_slug(lemma)
    return None


def build_year_number_index(
    node_index: NodeIndex,
    data_root: Path,
    *,
    pub_year_by_law: dict[str, int] | None = None,
) -> dict[tuple[int, int], str]:
    """Walk amendment files and build (year, number) → consolidated law_id.

    When the same key is observed across multiple amendments, the first
    encountered mapping wins. With ``pub_year_by_law`` supplied, we ignore
    candidate matches whose consolidated law's publication_date.year is
    more than 5 years away from the anchor year (likely a wrong slug).
    """
    out: dict[tuple[int, int], str] = {}
    skipped_no_title = 0
    skipped_year_mismatch = 0
    files_seen = 0

    for sub in ("finlex/Laki", "finlex/Asetus"):
        sub_root = data_root / sub
        if not sub_root.exists():
            continue
        for path in sub_root.glob("*.html"):
            files_seen += 1
            try:
                html = path.read_bytes().decode("utf-8", errors="ignore")
            except OSError:
                continue
            t_match = _TITLE_RE.search(html)
            if not t_match:
                continue
            base_slug = _base_law_slug_from_title(t_match.group(1))
            if not base_slug:
                skipped_no_title += 1
                continue
            base_law_id = node_index.by_law_title.get(base_slug)
            if not base_law_id:
                skipped_no_title += 1
                continue
            for year_s, num_s in _ACT_URL_RE.findall(html):
                year, num = int(year_s), int(num_s)
                if (year, num) in out:
                    continue
                if pub_year_by_law is not None:
                    base_year = pub_year_by_law.get(base_law_id)
                    if base_year is not None and abs(base_year - year) > 5:
                        skipped_year_mismatch += 1
                        continue
                out[(year, num)] = base_law_id

    print(f"  scanned {files_seen:,} amendment files")
    print(f"  built {len(out):,} (year, number) → law_id pairs")
    print(f"  skipped: no_title={skipped_no_title:,} year_mismatch={skipped_year_mismatch:,}")
    return out


# ---------------------------------------------------------------------------
# Dangling re-resolution
# ---------------------------------------------------------------------------


def _extract_year_number(target_ref: str) -> Optional[tuple[int, int]]:
    """Pull a (year, number) out of a dangling edge's target_ref.

    Handles both URL-shaped refs (anchor extractor) and plain text refs
    (regex extractor, e.g. "(403/1947)" or "lailla 533/1976").
    """
    if not target_ref:
        return None
    key = parse_href(target_ref) if target_ref.startswith("http") else None
    if key and key.year and key.number:
        return (key.year, key.number)
    m = _TARGET_REF_YN.search(target_ref)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    # The anchor convention is YYYY/NNN; in our text the order can be either.
    # Prefer the (year, number) ordering when one side is a 4-digit plausible year.
    if 1800 <= a <= 2100 and not (1800 <= b <= 2100):
        return (a, b)
    if 1800 <= b <= 2100 and not (1800 <= a <= 2100):
        return (b, a)
    return (a, b)


def relink_dangling(
    dangling_log: Path,
    edges_jsonl: Path,
    new_index: dict[tuple[int, int], str],
) -> tuple[int, int, Counter[str]]:
    """Re-resolve dangling entries. Returns (upgraded, still_dangling, by_type)."""
    upgraded = 0
    still_dangling = 0
    by_type: Counter[str] = Counter()

    new_dangling = dangling_log.with_suffix(".log.new")
    edges_append_path = edges_jsonl.with_suffix(".jsonl.append")

    with dangling_log.open("r", encoding="utf-8") as f_in, \
         new_dangling.open("w", encoding="utf-8") as f_dang, \
         edges_append_path.open("w", encoding="utf-8") as f_add:
        for line in f_in:
            if not line.strip():
                continue
            d = json.loads(line)
            # Only attempt to upgrade edges that previously failed for
            # in-corpus reasons. Out-of-corpus refs stay dangling — they
            # are genuinely outside what we ingest.
            if d.get("dangling_reason") != "not_yet_parsed":
                f_dang.write(line)
                still_dangling += 1
                continue
            yn = _extract_year_number(d.get("target_ref", ""))
            if yn is None:
                f_dang.write(line)
                still_dangling += 1
                continue
            target_id = new_index.get(yn)
            if not target_id:
                f_dang.write(line)
                still_dangling += 1
                continue
            d["target_id"] = target_id
            d.pop("dangling_reason", None)
            f_add.write(json.dumps(d, ensure_ascii=False) + "\n")
            upgraded += 1
            by_type[d.get("type", "?")] += 1

    return upgraded, still_dangling, by_type, new_dangling, edges_append_path


# ---------------------------------------------------------------------------
# Pub-year lookup helper
# ---------------------------------------------------------------------------


def load_pub_year_by_law(nodes_enriched: Path) -> dict[str, int]:
    """Read publication_date.year per LAW from nodes_enriched.jsonl (if present)."""
    if not nodes_enriched.exists():
        return {}
    out: dict[str, int] = {}
    with nodes_enriched.open("r", encoding="utf-8") as f:
        for line in f:
            if '"LAW"' not in line:
                continue
            d = json.loads(line)
            if d.get("type") != "LAW":
                continue
            meta = d.get("metadata") or {}
            pub = meta.get("publication_date")
            if not pub:
                continue
            try:
                out[d["id"]] = int(pub[:4])
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# Stats rewrite
# ---------------------------------------------------------------------------


def rewrite_stats(stats_path: Path, edges_jsonl: Path, dangling_log: Path) -> dict:
    by_type: Counter[str] = Counter()
    by_method: Counter[str] = Counter()
    incoming: Counter[str] = Counter()
    resolved = 0
    dangling = 0
    by_reason: Counter[str] = Counter()

    with edges_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            resolved += 1
            by_type[d["type"]] += 1
            by_method[d["extracted_by"]] += 1
            if d.get("target_id"):
                incoming[d["target_id"]] += 1

    with dangling_log.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            dangling += 1
            by_type[d["type"]] += 1
            by_method[d["extracted_by"]] += 1
            if d.get("dangling_reason"):
                by_reason[d["dangling_reason"]] += 1

    stats = {
        "total": resolved + dangling,
        "by_type": dict(by_type),
        "by_method": dict(by_method),
        "resolved": resolved,
        "dangling": dangling,
        "resolved_fraction": round(resolved / max(1, resolved + dangling), 3),
        "dangling_by_reason": dict(by_reason),
        "top_cited": [
            {"node_id": nid, "incoming_count": cnt}
            for nid, cnt in incoming.most_common(50)
        ],
    }
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="output")
    ap.add_argument("--no-pub-year-check", action="store_true",
                    help="skip the publication_date year cross-check")
    args = ap.parse_args()

    data_root = Path(args.data).resolve()
    out_dir = Path(args.out).resolve()
    nodes_jsonl = out_dir / "nodes.jsonl"
    nodes_enriched = out_dir / "nodes_enriched.jsonl"
    edges_jsonl = out_dir / "edges.jsonl"
    dangling_log = out_dir / "dangling_edges.log"
    stats_path = out_dir / "edge_stats.json"
    index_dump = out_dir / "year_number_index.json"

    if not (edges_jsonl.exists() and dangling_log.exists()):
        print("missing edges.jsonl or dangling_edges.log — run Step 2 first")
        return 1

    print(f"loading NodeIndex from {nodes_jsonl}…")
    t0 = time.time()
    index = NodeIndex().load(nodes_jsonl)
    print(f"  loaded {len(index.nodes):,} nodes in {time.time()-t0:.1f}s")

    pub_year_by_law: dict[str, int] = {}
    if not args.no_pub_year_check and nodes_enriched.exists():
        print(f"loading publication years from {nodes_enriched}…")
        t0 = time.time()
        pub_year_by_law = load_pub_year_by_law(nodes_enriched)
        print(f"  {len(pub_year_by_law):,} laws with publication_date.year in {time.time()-t0:.1f}s")

    print(f"walking amendment files under {data_root}/finlex/{{Laki,Asetus}}…")
    t0 = time.time()
    yn_index = build_year_number_index(
        index, data_root,
        pub_year_by_law=pub_year_by_law or None,
    )
    print(f"  built in {time.time()-t0:.1f}s")

    index_dump.write_text(json.dumps(
        {f"{y}/{n}": lid for (y, n), lid in yn_index.items()},
        ensure_ascii=False, indent=2,
    ))

    # --- back up the two files we're about to rewrite -------------------
    edges_bak = edges_jsonl.with_suffix(".jsonl.before-relink")
    dang_bak = dangling_log.with_suffix(".log.before-relink")
    print("backing up edges.jsonl + dangling_edges.log…")
    shutil.copy2(edges_jsonl, edges_bak)
    shutil.copy2(dangling_log, dang_bak)

    print("re-resolving dangling edges…")
    t0 = time.time()
    upgraded, still_dangling, by_type, new_dang_path, append_path = relink_dangling(
        dangling_log, edges_jsonl, yn_index,
    )
    print(f"  upgraded {upgraded:,} dangling → resolved")
    print(f"  still dangling: {still_dangling:,}")
    print(f"  by_type upgraded: {dict(by_type)}")
    print(f"  in {time.time()-t0:.1f}s")

    # Append upgraded edges to edges.jsonl, swap new dangling log into place.
    with edges_jsonl.open("a", encoding="utf-8") as f_edges, \
         append_path.open("r", encoding="utf-8") as f_add:
        shutil.copyfileobj(f_add, f_edges)
    append_path.unlink()
    new_dang_path.replace(dangling_log)

    print("rewriting edge_stats.json…")
    stats = rewrite_stats(stats_path, edges_jsonl, dangling_log)
    print(f"  resolved={stats['resolved']:,} "
          f"dangling={stats['dangling']:,} "
          f"resolved_fraction={stats['resolved_fraction']:.1%}")
    print()
    print(f"backups: {edges_bak.name}, {dang_bak.name}")
    print(f"index dump: {index_dump.name} ({len(yn_index):,} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
