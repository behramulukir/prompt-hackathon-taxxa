"""Targeted re-ingestion for the ~1.7% of chunks that were double-encoded.

The Vero păătŏs HTML files (and a long tail of finlex amendment files)
don't declare ``<!DOCTYPE>`` or ``<meta charset>``; BeautifulSoup's
sniffer mis-detected them as Latin-1 and produced chunks with
``päätös → pรครคtรถs``-style mojibake in both LanceDB ``embedded_text``
and graph.db ``nodes.text``.

``pipeline/html_utils.parse_html`` is now fixed to decode bytes as UTF-8
before handoff (Fix D). But the corrupted chunks already in the stores
need to be regenerated. This script:

  1. Scans LanceDB for chunks whose ``embedded_text`` contains the
     mojibake marker ``"รค"`` and groups them by source_file.
  2. Re-parses each affected file with the fixed parser.
  3. Re-embeds the fresh chunks via Voyage.
  4. Upserts into LanceDB (replacing the bad ones by chunk_id PK).
  5. Updates graph.db ``nodes.text`` for the affected node ids.

After this completes, the FTS index needs rebuilding so the corrected
text is searchable: ``.venv/bin/python -m scripts.build_fts_index --rebuild``.

CLI:

  .venv/bin/python -m scripts.reingest_corrupted_chunks --dry-run
  .venv/bin/python -m scripts.reingest_corrupted_chunks
  .venv/bin/python -m scripts.reingest_corrupted_chunks --only-paths "vero/Syventävät vero-ohjeet/Päätökset"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import lancedb

from pipeline.chunks import pack_sections
from pipeline.ingest import PARSER_MODULES, classify
from src.indexing.voyage_client import embed_batch, get_client

OUTPUT_DIR = PROJECT_ROOT / "output"
LANCEDB_PATH = OUTPUT_DIR / "lancedb"
GRAPH_DB = OUTPUT_DIR / "graph.db"
DATA_ROOT = PROJECT_ROOT / "data"

# The double-encoded ``ä`` marker. Any chunk text containing this triplet
# of code points went through the broken decode path. Other Finnish
# letters (``ö`` → ``รถ``) follow the same pattern but ``ä`` is by far
# the most common; finding any chunk-level mojibake is sufficient.
MOJIBAKE_MARKER = "รค"


def find_affected_files(only_path_prefix: str | None) -> dict[str, list[str]]:
    """Return ``{source_file_rel: [chunk_ids]}`` for every affected file.

    Source file is derived from ``nodes.jsonl`` (chunk → section_id →
    node → source_file). We load just the minimal mapping in memory.
    """
    db = lancedb.connect(str(LANCEDB_PATH))
    t = db.open_table("chunks")
    arr = t.to_arrow()
    ids = arr.column("chunk_id").to_pylist()
    texts = arr.column("embedded_text").to_pylist()
    section_ids = arr.column("section_id").to_pylist()

    bad_chunk_ids: list[str] = []
    bad_section_ids: set[str] = set()
    for cid, sid, tx in zip(ids, section_ids, texts):
        if tx and MOJIBAKE_MARKER in tx:
            bad_chunk_ids.append(cid)
            bad_section_ids.add(sid)
    print(f"[reingest] {len(bad_chunk_ids):,} chunks with mojibake, "
          f"{len(bad_section_ids):,} distinct sections")

    # Look up source_file from graph.db's nodes.source column? No, that's
    # the publisher (finlex/vero). source_file lives in nodes.jsonl. We
    # need a streaming scan keyed by node id.
    section_to_file: dict[str, str] = {}
    nodes_jsonl = OUTPUT_DIR / "nodes.jsonl"
    with nodes_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["id"] in bad_section_ids:
                section_to_file[d["id"]] = d.get("source_file") or ""
                if len(section_to_file) == len(bad_section_ids):
                    break

    files_to_chunks: dict[str, list[str]] = defaultdict(list)
    missing = 0
    for cid, sid in zip(ids, section_ids):
        if cid not in bad_chunk_ids:
            continue
        src_file = section_to_file.get(sid)
        if not src_file:
            missing += 1
            continue
        if only_path_prefix and not src_file.startswith(only_path_prefix):
            continue
        files_to_chunks[src_file].append(cid)

    if missing:
        print(f"[reingest]   {missing} affected chunks had no source_file "
              f"in nodes.jsonl (skipped)")
    print(f"[reingest] {len(files_to_chunks):,} distinct files to re-ingest")
    return files_to_chunks


def reingest_one(rel_path: str) -> tuple[list, list]:
    """Re-parse one file with the fixed parser and pack chunks.

    Returns (nodes_list_dict, chunks_list_dict).
    """
    key = classify(rel_path)
    if key is None:
        return [], []
    parser = PARSER_MODULES[key]
    abs_path = str(DATA_ROOT / rel_path)
    nodes, bundles = parser.parse(abs_path, rel_path)
    chunks = pack_sections(bundles)
    return ([n.to_dict() for n in nodes], [c.to_dict() for c in chunks])


def update_lancedb(
    db_table,
    fresh_chunks: list[dict],
    voyage_client,
    batch_size: int = 64,
) -> int:
    """Re-embed the fresh chunks and upsert into LanceDB.

    Uses ``merge_insert`` so existing chunk_ids are overwritten. Returns
    the number of chunks upserted.
    """
    if not fresh_chunks:
        return 0

    # Pre-compose embedded_text the same way Step 4a does (with the
    # ``[Source:][Path:][Title:]`` prefix). The composer needs node
    # records keyed by id; we pass the parent node dicts the parser just
    # produced.
    # For our targeted re-ingest we already have everything in each chunk
    # dict (text + the section it anchors to). The simplest path is to
    # use the existing compose helper.

    # Build payload rows. We need embedded_text + vector + metadata.
    texts_to_embed: list[str] = []
    payload_skeletons: list[dict] = []
    for cd in fresh_chunks:
        payload_skeletons.append({
            "chunk_id":         cd["chunk_id"],
            "section_id":       cd["section_id"],
            "source":           cd["source"],
            "source_subcorpus": cd["source_subcorpus"],
            "node_type":        cd.get("node_type") or "SECTION",
            "authority_rank":   cd.get("authority_rank"),
            "in_force":         cd.get("in_force"),
            "usable":           cd.get("usable"),
            "publication_date": cd.get("publication_date"),
            "language":         cd.get("language") or "fi",
            "embedded_text":    cd.get("embedded_text") or cd.get("text", ""),
        })
        texts_to_embed.append(
            cd.get("embedded_text") or cd.get("text", "")
        )

    # Embed in batches.
    vectors: list[list[float]] = []
    for i in range(0, len(texts_to_embed), batch_size):
        batch = texts_to_embed[i:i + batch_size]
        vecs, _ = embed_batch(voyage_client, batch, input_type="document")
        vectors.extend(vecs)

    rows = []
    for payload, vec in zip(payload_skeletons, vectors):
        payload["vector"] = vec
        rows.append(payload)

    # merge_insert overwrites by primary key (chunk_id).
    (db_table.merge_insert("chunk_id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute(rows))
    return len(rows)


def update_graph_nodes(conn: sqlite3.Connection, fresh_nodes: list[dict]) -> int:
    """Update ``nodes.text`` for any node in graph.db whose text was
    captured pre-fix. Preserves metadata_json.
    """
    if not fresh_nodes:
        return 0
    updates: list[tuple[str, str]] = []
    for n in fresh_nodes:
        updates.append((n.get("text") or "", n["id"]))
    conn.executemany(
        "UPDATE nodes SET text = ? WHERE id = ? AND text != ?",
        [(t, i, t) for t, i in updates],
    )
    conn.commit()
    return len(updates)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Report scope; do not re-ingest.")
    ap.add_argument("--only-paths", default=None,
                    help="Restrict to source_files starting with this prefix.")
    ap.add_argument("--limit-files", type=int, default=None,
                    help="Cap number of files re-ingested (sanity test).")
    args = ap.parse_args()

    t0 = time.time()
    files_to_chunks = find_affected_files(args.only_paths)

    if args.limit_files:
        keys = list(files_to_chunks.keys())[:args.limit_files]
        files_to_chunks = {k: files_to_chunks[k] for k in keys}
        print(f"[reingest] limiting to {len(files_to_chunks)} files")

    print(f"[reingest] discovery in {time.time()-t0:.1f}s")
    if args.dry_run:
        print("[reingest] DRY RUN — no writes.")
        for fp, cids in list(files_to_chunks.items())[:5]:
            print(f"  {fp} ({len(cids)} chunks)")
        return 0

    if not files_to_chunks:
        print("[reingest] nothing to do.")
        return 0

    db = lancedb.connect(str(LANCEDB_PATH))
    table = db.open_table("chunks")
    voyage = get_client()
    conn = sqlite3.connect(str(GRAPH_DB), timeout=30.0)

    total_chunks_updated = 0
    total_nodes_updated = 0
    total_files_processed = 0
    for fp in sorted(files_to_chunks):
        try:
            fresh_nodes, fresh_chunks = reingest_one(fp)
        except Exception as e:
            print(f"[reingest] FAILED {fp}: {e}")
            continue
        if not fresh_chunks:
            continue
        n_chunks = update_lancedb(table, fresh_chunks, voyage)
        n_nodes = update_graph_nodes(conn, fresh_nodes)
        total_chunks_updated += n_chunks
        total_nodes_updated += n_nodes
        total_files_processed += 1
        if total_files_processed % 25 == 0:
            print(f"[reingest]   processed {total_files_processed} files, "
                  f"chunks={total_chunks_updated:,}, nodes={total_nodes_updated:,}",
                  flush=True)

    print(f"[reingest] DONE. files={total_files_processed:,}, "
          f"chunks updated in LanceDB={total_chunks_updated:,}, "
          f"nodes updated in graph.db={total_nodes_updated:,}")
    print("[reingest] NEXT: rebuild FTS index — "
          ".venv/bin/python -m scripts.build_fts_index --rebuild")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
