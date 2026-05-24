# Lex Atlas

> The second brain for Finnish tax law.

Lex Atlas replaces top-k chunk retrieval over Finlex + Vero with a typed temporal
graph, walked by a four-agent loop running locally on Gemma 3 27B. Every claim
cites a node id and a `finlex.fi` / `vero.fi` URL. Local cost: ~€0.005 / query.
Hosted cost (Sonnet): ~€0.045 / query. Both fit comfortably under the brief's
€1 cap.

**Built for the Aalto · Prompt Finance Hackathon 2026 · Challenge by [Taxxa AI](https://taxxa.ai).**

## 30 seconds in

1. **63,660 docs** parsed via Vero's pre-baked `<taxfi-table-of-contents-mobile>` JSON
   TOCs and Finlex's Akoma Ntoso `akn/fi/…` cross-references — 95% of edges from
   regex over real data, €0 ingest cost.
2. **LRMoo / SAT-Graph RAG ontology** (Work / Expression / Component / CTV /
   Action) mirrored from `data.finlex.fi/sparql`'s ELI schema.
3. **Hybrid retrieval** — BGE-M3 (dense + sparse + ColBERT) → RRF k=60 →
   bge-reranker-v2-m3 → CRAG evaluator with Semantic Finlex SPARQL fallback.
4. **DSPy ReAct loop** — Planner / Drafter / Verifier / Clarifier with Self-RAG
   reflection tokens. Refuses uncited sentences at draft time.
5. **The Debate** — when sources disagree, two Drafter agents present opposing
   interpretations side-by-side; a Judge agent resolves via the priority lattice.
   Modeled on AgenticSimLaw (arXiv:2601.21936, Jan 2026).
6. **GPU-accelerated viz** — 63,660-node Constellation Map via `@cosmos.gl/graph`
   (MIT). Provenance Orbit styled after Anthropic's open-source circuit-tracer.
   Drag a date slider and the answer rewrites itself live via Cypher temporal
   queries.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Webapp | Next.js 15 (App Router) + React 19 | Server-stream SSE, edge runtime |
| Styling | Tailwind CSS v4 + shadcn/ui | CSS-first `@theme`, no config file |
| Theme | `next-themes` | Dark default, no flash |
| Constellation viz | `@cosmos.gl/graph` v3 | GPU force layout, 60fps @ 63k nodes |
| Orbit viz | D3 + Framer Motion v12 | SVG paths, arc transitions, React 19 |
| Attribution graph | `@xyflow/react` + ELK.js | DAG layout for agent reasoning |
| State | Zustand | Cross-component without Redux ceremony |
| PDF receipts | `@react-pdf/renderer` | Fiduciary-grade exports |
| Graph store | Neo4j 5.26 / 2026.01+ | Native vector index + `SEARCH` clause |
| Ingest | Python 3.11 + BeautifulSoup + lxml | Robust HTML parsing for Vero/Finlex |
| NLP | Voikko + spaCy fi_core_news_lg + finbert-ner | Finnish-first |
| Embeddings | BGE-M3 (BAAI) | Multilingual hybrid (dense + sparse + ColBERT) |
| Reranker | bge-reranker-v2-m3 | 568M, multilingual, 80ms/query |
| Drafter LLM | Gemma 3 27B Q4_K_M (Ollama, local) | ~€0 marginal cost, 32 tok/s on RTX |
| Worker LLM | Gemma 3 4B Q4_K_M | Planner/Verifier/Clarifier |
| Agent framework | DSPy ReAct + MIPROv2 | Optimizable, Bayesian search over prompts |

## Try it

- Live: `https://lex-atlas.vercel.app` *(deployed Sunday afternoon)*
- 90-sec demo: `docs/demo.mp4`
- Live eval on all 83 question-bank entries: `/eval`
- Methodology: `/methodology`

## Run locally

```bash
# 1. Clone and install
git clone https://github.com/<you>/lex-atlas
cd lex-atlas
pnpm install
uv sync           # or: pip install -e .

# 2. Fetch the corpus (provided by Taxxa)
python scripts/fetch_data.py

# 3. Start Neo4j + Ollama
docker compose up -d
ollama pull gemma3:27b gemma3:4b bge-m3 bge-reranker-v2-m3

# 4. Ingest (~5 min on the core 3 statutes; ~25 min full corpus)
uv run python scripts/ingest.py

# 5. Optimize prompts against the question bank (~30 min, optional)
uv run python scripts/optimize_prompts.py

# 6. Run the eval (~10 min)
uv run python scripts/run_eval.py

# 7. Boot the webapp + agent sidecar
pnpm dev                                          # frontend: localhost:3000
python -m scripts.serve_api --reload              # sidecar: localhost:8000
# (or: uv run uvicorn src.api.server:app --reload --port 8000)

# Frontend reads AGENT_SIDECAR_URL (default http://localhost:8000). Set it in
# lex-atlas-frontend/.env.local if the sidecar is elsewhere. With no sidecar
# reachable, /api/ask falls back to a built-in fixture replay so the UI still
# animates, but answers are not real.
```

## What this builds on

| Layer | Citation |
|---|---|
| Schema & temporal modeling | de Martim, H. (2025). *SAT-Graph RAG* (JURIX 2025). arXiv:2505.00039 |
| Temporal knowledge graphs | Han et al. (2025). *TG-RAG*. arXiv:2510.13590 |
| Ontology | IFLA *LRMoo v1.1.1* (CIDOC CRM 7.1.3-aligned, 2026) |
| Ground truth RDF | Semantic Finlex / ELI ontology · `data.finlex.fi` |
| Self-critique | Asai et al. (2024). *Self-RAG*. ICLR 2024 oral |
| Retrieval correction | Yan et al. (2024). *CRAG*. arXiv:2401.15884 |
| Query expansion | Gao et al. (2022). *HyDE* |
| Agent framework | Khattab et al. *DSPy + MIPROv2* (Stanford NLP) |
| Multi-agent debate | Du et al. (2023). *Improving Factuality and Reasoning through Multiagent Debate*. NeurIPS |
| Adversarial debate | Liang et al. (2023). *Encouraging Divergent Thinking via Multi-Agent Debate (MAD)*. arXiv:2305.19118 |
| Courtroom-style debate | *AgenticSimLaw* (Jan 2026). arXiv:2601.21936 |
| Hybrid embeddings | Chen et al. (2024). *BGE-M3* (BAAI) |
| Visualization metaphor | Anthropic (2025). *Circuit Tracing: Attribution Graphs*. `github.com/anthropics/attribution-graphs-frontend` (MIT) |
| GPU graph engine | `@cosmos.gl/graph` v3 (MIT) — luma.gl WebGL2 |
| Finnish NER | Kansallisarkisto/finbert-ner + TurkuNLP turku-ner |
| Finnish morphology | Voikko v0.4.0 (Rust + WASM, FOSS) |

## License

MIT
