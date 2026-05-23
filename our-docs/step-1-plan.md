STEP 1: NODE CREATION + CHUNKING PLAN (FINNISH LEGAL HTML)
🎯 Objective
Transform raw HTML legal documents into:
Stable canonical nodes (legal structure graph)
Deterministic, token-safe chunks aligned to legal meaning
No LLMs required at this stage.

1. CORE DESIGN PRINCIPLE
Nodes follow legal structure. Chunks follow nodes. Never the opposite.
So:
HTML → legal structure → nodes → chunks
NOT:
HTML → text → chunks → nodes ❌

2. INPUT ASSUMPTIONS
You receive HTML from:
Finlex (laws, statutes)
Vero (tax instructions, guidance)
Each document may contain:
headings (h1–h6)
§ markers
nested lists
anchors (id, href)
paragraphs

3. NODE TAXONOMY (STRICT SCHEMA)
Every node MUST belong to one of these types:
3.1 Hierarchical legal nodes
LAW
CHAPTER
SECTION (pykälä §)
SUBSECTION (momentti)
ITEM (kohta / alakohta)

3.2 Semantic nodes
DEFINITION
RULE
OBLIGATION
EXCEPTION
(Only created if clearly structurally indicated in text — NOT inferred)

3.3 Metadata nodes
TITLE
AMENDMENT_BLOCK
VERSION

4. NODE CREATION RULES (DETERMINISTIC)
4.1 LAW NODE
Created from:
document title / metadata
{
  "id": "law_1234_2020",
  "type": "LAW",
  "title": "...",
  "source": "finlex",
  "url": "..."
}


4.2 SECTION NODE (§)
Created when:
“§” appears in HTML or text
or numbered legal section detected
{
  "id": "law_1234_2020_5",
  "type": "SECTION",
  "label": "§5",
  "text": "...",
  "parent": "law_1234_2020"
}


4.3 SUBSECTION (momentti)
Created when:
paragraph indentation or numbering exists under §
{
  "id": "law_1234_2020_5_1",
  "type": "SUBSECTION",
  "text": "...",
  "parent": "law_1234_2020_5"
}


4.4 ITEM (kohta / bullet points)
Created from:
<li>
numbered lists (1), (2), a), b)
{
  "id": "law_1234_2020_5_1_a",
  "type": "ITEM",
  "text": "...",
  "parent": "law_1234_2020_5_1"
}


4.5 DEFINITION NODE (STRICT RULE)
ONLY create if:
text contains explicit definition pattern:
“tarkoitetaan”
“määritellään”
“defined as”
Otherwise DO NOT create.

5. NODE STABILITY RULES
Each node MUST have:
Required fields
{
  "id": "stable_string_id",
  "type": "SECTION",
  "text": "raw extracted text",
  "parent_id": "...",
  "order": 123,
  "source_html_id": "dom_anchor_if_exists"
}


Stability requirement
Node IDs MUST be:
deterministic
reproducible
based on:
law id
section number
hierarchy path
❌ Do NOT use random UUIDs

6. CHUNKING STRATEGY (VERY IMPORTANT)
🎯 Key idea:
Chunking is a function of nodes, not text.

6.1 Chunk unit = SECTION level first
Default rule:
Each SECTION (§) = base chunk unit

6.2 Token budget per chunk
Hard limits:
target: 800–1500 tokens per chunk
max: 2000 tokens

6.3 Chunk construction rule
For each SECTION:
Step 1: gather children
subsections
items
Step 2: pack sequentially
chunk = []
tokens = 0

for node in section.children:
    if tokens + node.tokens > LIMIT:
        emit(chunk)
        reset

    add node


6.4 NEVER split rules
You must NEVER split:
sentence
bullet point
ITEM node
citation span
legal phrase

6.5 Chunk boundaries priority (strong → weak)
SECTION (§)
SUBSECTION (momentti)
ITEM (kohta)
paragraph fallback

7. SPECIAL RULES FOR FINLEX VS VERO
7.1 Finlex (laws)
Strong structure:
§ is primary unit
amendments often embedded
Chunking is:
very clean, section-based

7.2 Vero (tax guidance)
Weaker structure:
Use:
headings
paragraph clusters
semantic grouping fallback
BUT still respect:
paragraph integrity

8. OUTPUT ARTIFACTS (MANDATORY)
Your system MUST output:
8.1 nodes.jsonl
One line per node:
{...}


8.2 chunks.jsonl
Each chunk:
{
  "chunk_id": "...",
  "node_ids": ["..."],
  "text": "...",
  "token_count": 1234
}


8.3 hierarchy index
{
  "law_id": {
    "sections": [...],
    "subsections": [...]
  }
}


9. QUALITY CHECKS(must reject)
Reject output if:
chunk contains partial ITEM node
section split across chunks incorrectly
node missing parent linkage
text not traceable to DOM
random node IDs used

10. FINAL ARCHITECTURE (THIS STEP ONLY)
HTML
 ↓
DOM parsing
 ↓
Legal structure extraction
 ↓
NODE creation (LAW → § → momentti → item)
 ↓
Hierarchical linking
 ↓
Chunk construction (SECTION-first packing)
 ↓
Output JSONL


11. KEY TAKEAWAY
Nodes = legal truth structure
Chunks = compression layer over nodes
If you reverse this, your graph will become unreliable.

If you want next step, I can design:
Step 2 (recommended next)
👉 Deterministic edge extraction rules for Finnish legal verbs (muutetaan / kumotaan / viitataan)
or
Step 2b
👉 Exact Codex prompt + pseudocode implementation for this node/chunk system
