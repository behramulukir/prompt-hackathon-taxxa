Rretrieval system for Finnish tax-law research.

<img width="1878" height="956" alt="image" src="https://github.com/user-attachments/assets/a7344922-3979-486f-88e2-5d4ec3354671" />

## Results

- Winner, Taxxa.ai Challenge, €2,000+ prize
- Winner, Featherless.ai Challenge

## What this is

This repository implements a legal retrieval and answer-generation pipeline for Finnish tax law. It indexes a corpus of Finlex statutes, KHO case law, Vero guidance, and tax treaties into:

- 402,088 embedded chunks
- 1.97M graph nodes
- LanceDB vector storage
- SQLite graph storage

The system compares two retrieval approaches under the same answer schema:

1. `v1`, a vector-only baseline using cosine retrieval and metadata reranking.
2. `v2`, a GraphRAG pipeline that starts from vector seeds, expands through legal-document relationships, reranks the expanded candidate pool, and returns cited answers.

The main analytical question is simple: can graph expansion recover legally relevant context that plain vector similarity misses. In tax research, the answer often depends on relationships between sources, not just semantic similarity inside one paragraph. Relevant connections include amendments, definitions, case law, Vero guidance, jurisdiction, exceptions, repealed provisions, and conflicting authority.

## System design

| Layer | Role |
|---|---|
| Corpus | Finnish tax statutes, KHO case law, Vero guidance, treaties |
| Chunking | Preserves local legal context while keeping retrieval units small enough for reranking |
| Vector retrieval | Finds semantically similar chunks from the LanceDB store |
| Graph retrieval | Expands from seed chunks to connected legal sources in SQLite |
| Reranking | Uses either metadata scoring or a multilingual cross-encoder |
| Generation | Produces Finnish legal answers with citations through DeepSeek-V4-Flash via Featherless |
| Output | Shared `AnswerResult` schema for both v1 and v2 |

## Why GraphRAG

Vector search is useful for finding nearby language. Legal research needs more than nearby language.

A tax question can depend on whether a statute has been amended, whether a Vero guidance page narrows the rule, whether KHO has interpreted it, or whether an exception applies. Those dependencies are structural. The graph layer makes those relationships explicit and lets the retrieval pipeline inspect nearby authority before the answer is generated.

The graph is not used as decoration. It is used to test whether relationship-aware retrieval improves source selection against a vector-only baseline.

## Retrieval modes

| Command | Pipeline | Reranker | Default store |
|---|---|---|---|
| `python -m scripts.ask "..."` | v1 vector-only | metadata reranker | `output/lancedb` |
| `python -m scripts.ask --v2 "..."` | v2 GraphRAG | cross-encoder and weighted combine | `output/lancedb` |
| `python -m scripts.ask --v2 --rerank vector "..."` | v2 GraphRAG | metadata reranker after graph expansion | `output/lancedb` |
| `python -m scripts.ask_v1 "..."` | v1 vector-only | metadata reranker | hard-coded full store |

`scripts.ask` is the main entry point. `scripts.ask_v1` is a stable v1 baseline that pins the full store path and avoids config drift.

## Quick start

```bash
# v1, vector-only baseline
.venv/bin/python -m scripts.ask "Mikä on arvonlisäveron vähennysoikeus?"

# v2, GraphRAG retrieval
.venv/bin/python -m scripts.ask --v2 "Mikä on arvonlisäveron vähennysoikeus?"

# v2, GraphRAG retrieval without the cross-encoder
.venv/bin/python -m scripts.ask --v2 --rerank vector "Mikä on arvonlisäveron vähennysoikeus?"

# v1 standalone baseline
.venv/bin/python -m scripts.ask_v1 "Mikä on arvonlisäveron vähennysoikeus?"
```

The first cross-encoder run may load the `BAAI/bge-reranker-v2-m3` model from Hugging Face cache. If the model is already cached, set:

```bash
export HF_HUB_OFFLINE=1
```

## Example comparisons

### Compare v1 against v2

```bash
Q="KHO ratkaisu arvonlisäveron vähennysoikeudesta"

.venv/bin/python -m scripts.ask "$Q"
.venv/bin/python -m scripts.ask --v2 "$Q"
.venv/bin/python -m scripts.ask --v2 --rerank vector "$Q"
```

### Compare cited sources as JSON

```bash
.venv/bin/python -m scripts.ask --json "$Q" > /tmp/v1.json
.venv/bin/python -m scripts.ask --v2 --json "$Q" > /tmp/v2.json

jq -r '.cited_source_ids[]' /tmp/v1.json
jq -r '.cited_source_ids[]' /tmp/v2.json
```

### Inspect retrieval behavior

```bash
.venv/bin/python -m scripts.ask --verbose "Onko ALV vähennyskelpoinen edustuskuluista?"
.venv/bin/python -m scripts.ask --v2 --verbose "Onko ALV vähennyskelpoinen edustuskuluista?"
```

Verbose mode shows filters, top reranked chunks, assembled context, citations, and timing. In v2, it also shows the selected strategy and graph expansion statistics.

## v2 routing strategies

The v2 router selects a retrieval strategy from the question text. Each strategy changes how graph expansion is used.

| Strategy | Typical trigger | Retrieval behavior |
|---|---|---|
| `case_law` | KHO, KVL, case references | Expands toward related rulings and legal authority |
| `definition` | definition questions | Expands toward definitional sources and referenced provisions |
| `multi_hop` | exceptions, conditions, however-style questions | Expands across linked rules and qualifications |
| `recency` | current, repealed, still valid | Prioritizes validity and time-sensitive relationships |
| `cross_source` | statute plus guidance questions | Connects Finlex-style authority with Vero guidance |
| default | no strong trigger | Reranks vector seeds with limited graph involvement |

Examples:

```bash
.venv/bin/python -m scripts.ask --v2 --verbose "KHO ratkaisu osakeyhtiön sukupolvenvaihdoksesta"
.venv/bin/python -m scripts.ask --v2 --verbose "Mitä tarkoittaa kiinteä toimipaikka verotuksessa?"
.venv/bin/python -m scripts.ask --v2 --verbose "Arvonlisäveron vähennysoikeuden poikkeukset"
.venv/bin/python -m scripts.ask --v2 --verbose "Onko tämä laki yhä voimassa?"
.venv/bin/python -m scripts.ask --v2 --verbose "Vero-ohje tuloverolain 28 § soveltamisesta"
```

## Output schema

Both pipelines return the same `AnswerResult` structure. This makes v1 and v2 easier to compare in the UI, evaluation scripts, and manual inspections.

Core fields:

- `answer`
- `cited_source_ids`
- `retrieved_chunks`
- `retrieval_paths`
- `assumptions`
- `timing_ms`
- `conflicts`

## CLI reference

### `scripts.ask`

| Flag | Default | Description |
|---|---|---|
| `question` | required | Finnish or English tax-law question |
| `--v2` | off | Use the GraphRAG pipeline |
| `--rerank {cross_encoder,vector}` | `cross_encoder` | Reranker for v2 |
| `--db PATH` | `src/retrieval/__init__.py:VECTOR_DB_PATH` | LanceDB directory |
| `--graph-db PATH` | `output/graph.db` | SQLite graph store |
| `-k N` | 20 | Vector retrieval depth for v1 |
| `-n N` | 8 | Number of deduplicated sources sent to the LLM |
| `--verbose`, `-v` | off | Print retrieval diagnostics |
| `--json` | off | Emit the full `AnswerResult` as JSON |

### `scripts.ask_v1`

| Flag | Default | Description |
|---|---|---|
| `question` | required | Finnish or English tax-law question |
| `--db PATH` | `output/lancedb` | LanceDB directory |
| `--graph-db PATH` | `output/graph.db` | SQLite graph store |
| `-k N` | 20 | Vector retrieval depth |
| `-n N` | 8 | Number of deduplicated sources sent to the LLM |
| `--verbose`, `-v` | off | Print retrieval diagnostics |
| `--json` | off | Emit the full `AnswerResult` as JSON |

In v2, `-k` is ignored. The selected strategy controls seed depth through `strategy.seed_k`.

## Environment

Create a `.env` file at the project root:

```bash
VOYAGE_API_KEY=...        # embeddings and query encoding
FEATHERLESS_API_KEY=...   # DeepSeek-V4-Flash generation
```

Optional:

```bash
export HF_HUB_OFFLINE=1
```

## Development notes

Useful project paths:

- `src/retrieval/`, retrieval implementation
- `our-docs/05_retrieval_v1_vector_only.md`, v1 design notes
- `our-docs/07_retrieval_v2_graph_traversal.md`, v2 GraphRAG design notes
- `our-docs/changelog/`, build logs and design changes
- `findings/`, pilot results, baseline failures, sanity checks

## Analytical focus

This project is built around controlled comparison rather than a single demo path. The important comparisons are:

- vector-only retrieval against graph-expanded retrieval
- metadata reranking against cross-encoder reranking
- source coverage before and after graph expansion
- cited-source stability across repeated legal questions
- latency and cost implications of each retrieval stage

That makes the system useful both as a product prototype and as an empirical test of GraphRAG for Finnish tax-law research.
