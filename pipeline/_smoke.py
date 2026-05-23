"""Tiny smoke test: parse one file and dump a quick summary to stdout."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pipeline.parsers import finlex_konsolidoitu
from pipeline.chunks import pack_sections


def main(path: str, rel: str) -> None:
    nodes, bundles = finlex_konsolidoitu.parse(path, rel)
    chunks = pack_sections(bundles)
    print(f"file: {rel}")
    print(f"nodes: {len(nodes)}")
    print(f"bundles: {len(bundles)}")
    print(f"chunks: {len(chunks)}")
    by_type: dict = {}
    for n in nodes:
        by_type[n.type] = by_type.get(n.type, 0) + 1
    print("by_type:", by_type)
    if chunks:
        c = chunks[0]
        print("--- first chunk ---")
        print(f"id={c.chunk_id} section={c.section_id} tokens={c.token_count} oversized={c.oversized}")
        print(c.text[:800])
        print("--- last chunk ---")
        c2 = chunks[-1]
        print(f"id={c2.chunk_id} section={c2.section_id} tokens={c2.token_count} oversized={c2.oversized}")
        print(c2.text[:400])
    # Spot check: print first 3 nodes
    print("--- first 3 nodes ---")
    for n in nodes[:5]:
        d = n.to_dict()
        d.pop("metadata", None)
        d["text"] = d["text"][:120]
        print(json.dumps(d, ensure_ascii=False))


if __name__ == "__main__":
    path = sys.argv[1]
    rel = sys.argv[2] if len(sys.argv) > 2 else str(Path(path).name)
    main(path, rel)
