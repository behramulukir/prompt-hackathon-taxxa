"""Spot-check the pilot LanceDB table with 10 Finnish tax queries.

Per 4a.3: writes findings/04a_pilot.md with the 10 queries and top-5 hits per
query, so a human can eyeball whether the embedding/composition is sane.

The criteria from the doc:

    For at least 7 of 10 queries, top-3 results contain at least one
    plausibly-relevant chunk

Picking the queries: a mix of statute lookups (Arvonlisaverolaki sections),
broader concept queries ("input VAT deduction"), KHO precedent queries, and
multilingual phrasing to exercise the legal-domain retrieval.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.indexing.vector_store import VectorStore

QUERIES = [
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
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db", default="output/lancedb_pilot", help="Path to LanceDB directory"
    )
    ap.add_argument(
        "--out", default="findings/04a_pilot.md", help="Markdown report path"
    )
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    store = VectorStore(args.db)
    print(f"[spot] {store.count()} rows in {args.db}")

    out_lines: list[str] = []
    out_lines.append("# 04a Pilot — spot-check findings\n")
    out_lines.append(
        f"Pilot vector store: `{args.db}` with {store.count()} chunks. "
        "10 Finnish tax queries, top-5 results each. Lower distance = closer.\n"
    )

    for i, q in enumerate(QUERIES, 1):
        print(f"[spot] {i}. {q}")
        hits = store.search_by_text(q, k=args.k)
        out_lines.append(f"\n## Q{i}. {q}\n")
        for rank, (row, dist) in enumerate(hits, 1):
            label = f"{row.get('source_subcorpus')} / {row.get('node_type')}"
            text_snip = (row.get("embedded_text") or "")[:300].replace("\n", " ")
            out_lines.append(
                f"- **{rank}** (d={dist:.4f}, {label}) "
                f"`{row.get('chunk_id')}`\n  > {text_snip}\n"
            )

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"[spot] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
