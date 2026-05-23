"""Step 4a.7 — Index sanity checks for the full LanceDB embedding pass.

Reports written to ``findings/04a_index_sanity.md``. Four checks per the
doc:

1. Row count in LanceDB equals embedded-chunk count in ``chunks.jsonl``
   (with rounding for ``oversized=True`` chunks that were deliberately
   skipped — we report both numbers and the delta).
2. For 100 random vectors: ``chunk_id`` resolves to a chunk in
   ``chunks.jsonl`` and ``section_id`` resolves to a node in
   ``nodes_enriched.jsonl``.
3. 20 Finnish tax queries (10 from the pilot + 10 new) — top-5 each.
   Human eyeball needed for "at least one relevant" per query.
4. Metadata filter test: ``source="finlex_laki"`` → only finlex_laki chunks;
   ``node_type="SECTION"`` → only SECTION-anchored chunks.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.indexing.vector_store import VectorStore

OUTPUT_DIR = PROJECT_ROOT / "output"
CHUNKS_IN = OUTPUT_DIR / "chunks.jsonl"
NODES_IN = OUTPUT_DIR / "nodes_enriched.jsonl"
NODES_FALLBACK = OUTPUT_DIR / "nodes.jsonl"
REPORT = PROJECT_ROOT / "findings" / "04a_index_sanity.md"

# 20 Finnish tax queries — first 10 are the pilot set (for continuity), last
# 10 are new and probe topics not exercised in the pilot.
QUERIES = [
    # --- pilot set (continuity) ---
    "Mikä on arvonlisäveron vähennysoikeus?",
    "Verovähennys yritystoiminnan kuluista",
    "Kuolinpesän verotus ja jälkiverotus",
    "Kiinteä toimipaikka kansainvälisessä verosopimuksessa",
    "Asianomistajan oikeus nostaa syyte",
    "Korkein hallinto-oikeus arvonlisävero KHO päätös",
    "Vero-ohje työsuhde-edun verotus",
    "Säädöskokoelma muutos arvonlisäverolakiin",
    "Verovapaa lahja perintö",
    "Yrityksen sukupolvenvaihdos verotuksellisesti",
    # --- 10 new queries ---
    "Arvonlisäveron palautus ulkomaiselle yritykselle",
    "Yhteisön luovutusvoittoverotus osakkeiden myynnistä",
    "Henkilökohtaisen tulon ja pääomatulon verotus",
    "Ennakonpidätys palkasta ja eläkkeestä",
    "Verotusmenettelylaki muutoksenhaku",
    "Yleishyödyllinen yhteisö verovapaus",
    "Kiinteistöveron määrääminen ja perusteet",
    "Tuloverolain 28 §:n soveltaminen",
    "Siirtohinnoittelu konserniyhtiöt",
    "Maakuntavero ja kunnallisvero",
]


def _count_jsonl(path: Path) -> tuple[int, int]:
    """Return (total_lines, oversized_count)."""
    n = 0
    n_oversized = 0
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            n += 1
            if '"oversized": true' in line or '"oversized":true' in line:
                n_oversized += 1
    return n, n_oversized


def _load_random_chunk_ids(path: Path, n: int, seed: int = 7) -> set[str]:
    """Reservoir-sample n chunk_ids from the JSONL."""
    rng = random.Random(seed)
    reservoir: list[str] = []
    count = 0
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            # Pull just the chunk_id field cheaply.
            d = json.loads(line)
            cid = d["chunk_id"]
            count += 1
            if len(reservoir) < n:
                reservoir.append(cid)
            else:
                j = rng.randrange(count)
                if j < n:
                    reservoir[j] = cid
    return set(reservoir)


def _node_ids(path: Path) -> set[str]:
    """Stream node ids into a set."""
    out: set[str] = set()
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            out.add(json.loads(line)["id"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="output/lancedb")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--n-random", type=int, default=100)
    args = ap.parse_args()

    out: list[str] = []
    out.append("# 04a Index sanity — full embedding pass\n")
    out.append(f"Vector store: `{args.db}`\n")

    # --- Check 1: row count parity ---
    print("[sanity] Check 1: row count parity ...")
    t0 = time.time()
    store = VectorStore(args.db)
    n_db = store.count()
    n_file, n_oversized = _count_jsonl(CHUNKS_IN)
    expected = n_file - n_oversized  # we deliberately skip oversized chunks
    delta = n_db - expected
    print(
        f"[sanity]   db={n_db:,}  file={n_file:,}  "
        f"oversized={n_oversized:,}  expected={expected:,}  delta={delta:+d}"
    )
    out.append("\n## 1. Row-count parity\n")
    out.append(f"- LanceDB rows: **{n_db:,}**")
    out.append(f"- chunks.jsonl lines: {n_file:,}")
    out.append(f"- oversized (skipped by design): {n_oversized:,}")
    out.append(f"- expected (file − oversized): {expected:,}")
    out.append(f"- delta (db − expected): **{delta:+d}**")
    out.append(
        f"- verdict: {'PASS' if delta == 0 else 'FAIL'} "
        f"(needs |delta| == 0)\n"
    )

    # --- Check 2: random-vector resolution ---
    print(f"[sanity] Check 2: {args.n_random} random vectors resolve ...")
    nodes_path = NODES_IN if NODES_IN.exists() else NODES_FALLBACK
    print(f"[sanity]   loading node ids from {nodes_path.name} ...")
    t1 = time.time()
    all_node_ids = _node_ids(nodes_path)
    print(f"[sanity]   {len(all_node_ids):,} node ids loaded in {time.time()-t1:.1f}s")

    print(f"[sanity]   sampling {args.n_random} chunk_ids from {CHUNKS_IN.name} ...")
    sample_cids = _load_random_chunk_ids(CHUNKS_IN, args.n_random)
    print(f"[sanity]   sampled {len(sample_cids)} chunk_ids")

    # Fetch those chunk_ids from LanceDB via a filter.
    # We use a single equality filter per id via individual searches — cheap
    # for 100 rows but use IN clause for the whole set.
    quoted = ",".join("'" + cid.replace("'", "''") + "'" for cid in sample_cids)
    if store.table is None:
        raise RuntimeError("vector table missing")
    arrow = store.table.search().where(f"chunk_id IN ({quoted})", prefilter=True).limit(
        len(sample_cids) + 5
    ).to_arrow()
    n_returned = arrow.num_rows
    returned_cids = set(arrow["chunk_id"].to_pylist())
    section_ids = list(arrow["section_id"].to_pylist())
    missing_in_db = sample_cids - returned_cids
    missing_section_in_nodes = [
        sid for sid in section_ids if sid not in all_node_ids
    ]
    print(
        f"[sanity]   chunks found in db: {n_returned}/{len(sample_cids)} | "
        f"missing in db: {len(missing_in_db)} | "
        f"section_ids missing in nodes: {len(missing_section_in_nodes)}"
    )
    out.append("## 2. Random-vector resolution\n")
    out.append(f"- sampled chunk_ids: {len(sample_cids)}")
    out.append(f"- found in LanceDB: **{n_returned}**")
    out.append(f"- missing from LanceDB: {len(missing_in_db)}")
    out.append(
        f"- section_ids missing from nodes_enriched.jsonl: "
        f"**{len(missing_section_in_nodes)}**"
    )
    out.append(
        f"- verdict: "
        f"{'PASS' if not missing_in_db and not missing_section_in_nodes else 'FAIL'}\n"
    )

    # --- Check 4: metadata filter test ---
    print("[sanity] Check 4: metadata filters ...")
    # source_subcorpus == 'laki'
    laki_results = store.table.search().where(
        "source_subcorpus = 'laki'", prefilter=True
    ).limit(50).to_arrow()
    laki_other = sum(
        1 for sc in laki_results["source_subcorpus"].to_pylist() if sc != "laki"
    )
    # node_type == 'SECTION'
    sec_results = store.table.search().where(
        "node_type = 'SECTION'", prefilter=True
    ).limit(50).to_arrow()
    sec_other = sum(
        1 for nt in sec_results["node_type"].to_pylist() if nt != "SECTION"
    )
    print(
        f"[sanity]   source_subcorpus=laki sample: {laki_results.num_rows} returned, "
        f"{laki_other} non-laki leaks"
    )
    print(
        f"[sanity]   node_type=SECTION sample: {sec_results.num_rows} returned, "
        f"{sec_other} non-SECTION leaks"
    )
    out.append("## 4. Metadata filters\n")
    out.append(
        f"- `source_subcorpus=='laki'` → {laki_results.num_rows} sampled, "
        f"non-laki leaks: **{laki_other}**"
    )
    out.append(
        f"- `node_type=='SECTION'` → {sec_results.num_rows} sampled, "
        f"non-SECTION leaks: **{sec_other}**"
    )
    out.append(
        f"- verdict: "
        f"{'PASS' if (laki_other == 0 and sec_other == 0) else 'FAIL'}\n"
    )

    # --- Check 3: 20-query spot-check ---
    print(f"[sanity] Check 3: {len(QUERIES)} Finnish tax queries ...")
    out.append("## 3. 20-query spot-check\n")
    out.append(
        "Top-5 per query, written below. Lower distance = closer. Eyeball gate: "
        "at least one plausibly-relevant chunk in top-3 for the strong majority "
        "of queries (the pilot gate was 7/10).\n"
    )
    for i, q in enumerate(QUERIES, 1):
        print(f"[sanity]   Q{i}: {q}")
        hits = store.search_by_text(q, k=args.k)
        out.append(f"\n### Q{i}. {q}\n")
        for rank, (row, dist) in enumerate(hits, 1):
            label = f"{row.get('source_subcorpus')} / {row.get('node_type')}"
            snip = (row.get("embedded_text") or "")[:280].replace("\n", " ")
            out.append(
                f"- **{rank}** (d={dist:.4f}, {label}) `{row.get('chunk_id')}`\n"
                f"  > {snip}\n"
            )

    # --- write report ---
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print(f"[sanity] wrote {REPORT}")
    print(f"[sanity] total wall: {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
