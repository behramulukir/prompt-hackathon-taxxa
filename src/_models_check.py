"""Self-check for src/models.py per the brief's 'definition of done'.

Run from repo root:  .venv/bin/python -m src._models_check
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.models import (
    Chunk,
    Edge,
    Neighbor,
    Node,
    NodeMetadata,
    RetrievalPath,
    VectorRecord,
)


def main() -> int:
    print("imports:           OK")

    # 1) Round-trip 100 real nodes ------------------------------------------
    nodes_path = Path("output/nodes.jsonl")
    with nodes_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 100:
                break
            original = json.loads(line)
            parsed = Node.model_validate(original)
            # Round-trip back to JSON; we just want this to not raise.
            json.loads(parsed.model_dump_json(exclude_none=True))
    print(f"round-trip nodes:  OK  (first 100 of {nodes_path})")

    # 2) Round-trip 100 real chunks ----------------------------------------
    chunks_path = Path("output/chunks.jsonl")
    with chunks_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 100:
                break
            Chunk.model_validate(json.loads(line))
    print(f"round-trip chunks: OK  (first 100 of {chunks_path})")

    # 3) Valid resolved edge ------------------------------------------------
    ok = Edge(
        source_id="a",
        target_id="b",
        target_ref="§ 5",
        type="cites",
        confidence=1.0,
        extracted_by="anchor",
    )
    assert ok.target_id == "b"
    print("resolved edge:     OK")

    # 4) Dangling-without-reason should raise ------------------------------
    try:
        Edge(
            source_id="a",
            target_ref="§ 5",
            type="cites",
            confidence=1.0,
            extracted_by="regex",
        )
    except Exception as e:
        print(f"dangling-no-reason rejected:  OK  ({type(e).__name__})")
    else:
        print("FAIL: dangling edge without reason was accepted")
        return 1

    # 5) Out-of-range confidence should raise -------------------------------
    try:
        Edge(
            source_id="a",
            target_id="b",
            target_ref="§ 5",
            type="cites",
            confidence=1.5,
            extracted_by="anchor",
        )
    except Exception as e:
        print(f"confidence>1 rejected:        OK  ({type(e).__name__})")
    else:
        print("FAIL: confidence=1.5 was accepted")
        return 1

    # 6) Resolved-with-dangling-reason should raise -------------------------
    try:
        Edge(
            source_id="a",
            target_id="b",
            target_ref="§ 5",
            type="cites",
            confidence=1.0,
            extracted_by="anchor",
            dangling_reason="out_of_corpus",
        )
    except Exception as e:
        print(f"resolved+reason rejected:     OK  ({type(e).__name__})")
    else:
        print("FAIL: resolved edge with dangling_reason was accepted")
        return 1

    # 7) Sanity: dataclass helpers --------------------------------------
    n = Neighbor(node_id="x", edge=ok, direction="out")
    p = RetrievalPath(via="vector", score=0.87, hops=0)
    assert n.node_id == "x" and p.via == "vector"
    print("helpers (Neighbor, RetrievalPath): OK")

    # 8) Sanity: VectorRecord roundtrip
    vr = VectorRecord(
        chunk_id="c1",
        vector=[0.1, 0.2, 0.3],
        section_id="s1",
        source="finlex",
        source_subcorpus="laki_skk",
        node_type="SECTION",
    )
    VectorRecord.model_validate_json(vr.model_dump_json())
    print("VectorRecord:      OK")

    # 9) NodeMetadata accepts existing Step 1 dicts (empty or with kind=...)
    NodeMetadata.model_validate({})
    NodeMetadata.model_validate({"kind": "example"})
    print("NodeMetadata:      OK")

    print()
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
