"""Edge extraction package (Step 2).

Turns the per-document trees produced by Step 1 into a cross-document graph
by emitting typed `Edge` records into `output/edges.jsonl`.

Modules
-------
ids              Canonical-ID normalization (Finlex act URLs, statute citations).
node_index       In-memory lookup over `output/nodes.jsonl` (id → record + reverse indexes).
structural_edges B2.1 — parent_of edges from `parent_id`.
anchor_edges     B2.2 — <a href> walking of raw HTML.
citations_regex  B2.3 — Finnish-legal citation regexes.
refine           B2.5 — generic→typed edge refinement.
definition_edges B2.6 — DEFINITION → term-user edges.
resolve          B2.7 — citation-string → canonical node, with dangling reason.

Use `scripts/extract_edges.py` to run the full pipeline.
"""
