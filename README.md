# RAG Evaluation Lab

> **The eval-first RAG.** Retrieval-augmented generation over your document corpus, with **RAGAS metrics you can point to** instead of vibes.

An end-to-end RAG system built to answer the question that most RAG demos dodge: *"is your answer actually right, and did you actually retrieve the right stuff?"* Hybrid dense + BM25 retrieval, grounded generation with inline `[chunk N]` citations, RAGAS-scored faithfulness / answer relevancy / context precision, Langfuse traces for every query, and a live dashboard that plots your metrics over time.

![python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/fastapi-0.110-009688?logo=fastapi&logoColor=white)
![react](https://img.shields.io/badge/react-19-61DAFB?logo=react&logoColor=black)
![pinecone](https://img.shields.io/badge/pinecone-6.0-0F172A)
![langfuse](https://img.shields.io/badge/langfuse-2.60-6366F1)
![ragas](https://img.shields.io/badge/ragas-0.2-EAB308)
![license](https://img.shields.io/badge/license-MIT-green)

---

## Screens

- **Ask** — dual-pane chat: answer on the left with clickable `[N]` citations, retrieved chunks on the right (hover a citation → the source chunk highlights).
- **Corpus** — upload PDF/Markdown, seed a sample corpus, delete docs. Every ingest re-chunks, re-embeds, upserts to Pinecone, and rebuilds the in-memory BM25 index.
- **Eval Dashboard** — run RAGAS on the golden test-set or your recent queries. Three metric cards + a Recharts trend line + per-question drilldown.
- **History** — every query persisted in MongoDB + linked to its Langfuse trace.

---

## Why "eval-first"?

Most RAG demos assume "we got an answer back → we're done". This project treats evaluation as **first-class**:

- **Faithfulness** — is the answer actually supported by the retrieved chunks?
- **Answer Relevancy** — does the answer address the question that was asked?
- **Context Precision** — was the retrieved context actually relevant, or padding?

Every prompt change, retrieval-mode change, or embedding-model swap should be benchmarked against a held-out test set **before** it ships. This app makes that a one-click flow.

---

## Tech stack

| Layer            | Choice                                                                    |
| ---------------- | ------------------------------------------------------------------------- |
| LLM              | OpenAI `gpt-5.4-mini` via Emergent Universal Key (any OpenAI-compatible proxy also works) |
| Embeddings       | `sentence-transformers/all-MiniLM-L6-v2` (local, 384-dim, CPU)            |
| Chunking         | LangChain `RecursiveCharacterTextSplitter` (800 / 120 overlap)            |
| Vector store     | **Pinecone** serverless, cosine, `aws/us-east-1`                          |
| Keyword search   | `rank_bm25` (in-memory, rebuilt on every ingest)                          |
| Retrieval        | Hybrid — dense + BM25 fused with **Reciprocal Rank Fusion** (α = 0.6)     |
| Evaluation       | **RAGAS** — Faithfulness, ResponseRelevancy, LLMContextPrecisionWithoutReference |
| Observability    | **Langfuse** — traces + per-metric scores                                 |
| Backend          | **FastAPI** (Motor / AsyncIOMotorClient) on port 8001                     |
| Frontend         | **React 19** + Tailwind + shadcn/ui + Recharts on port 3000               |
| Persistence      | **MongoDB** — documents, chunks, conversations, eval runs                 |

---

## Getting started

### 1) Prerequisites

- Python 3.11
- Node 18+ and `yarn`
- MongoDB running locally (or a URI you can point at)
- Accounts + API keys for:
  - **Emergent Universal Key** (free) — [help.emergent.sh/universal-key](https://help.emergent.sh/universal-key)
  - **Pinecone** — [app.pinecone.io](https://app.pinecone.io)
  - **Langfuse** — [cloud.langfuse.com](https://cloud.langfuse.com) → Project Settings → API keys

### 2) Clone & configure

```bash
git clone <your-repo-url> rag-eval-lab
cd rag-eval-lab

# Backend env
cp backend/env.example.txt backend/.env
# Now open backend/.env and paste your real keys

# Frontend env
cp frontend/env.example.txt frontend/.env
```

### 3) Run with Docker (Recommended - Zero Local DB Install)

```bash
docker compose up --build
```
*(Note: MongoDB runs inside Docker on port `27018` to avoid conflicting with any local instances on `27017`)*

Open **http://localhost:3000** → sidebar should show `langfuse: connected` and vectors will be `0`. Click **02 · Corpus → Seed sample corpus**, then head to **01 · Ask** and try:

> *What is the retention period for Confidential-tier data?*

You should get an answer like `7 years from creation [1]` with the source chunk highlighted on the right.

---

## Project structure

```
.
├── backend/
│   ├── server.py              # FastAPI app (all routes under /api)
│   ├── rag/
│   │   ├── llm_client.py      # OpenAI (Emergent proxy) + local HF embeddings
│   │   ├── chunker.py         # RecursiveCharacterTextSplitter
│   │   ├── vector_store.py    # Pinecone + BM25 + Reciprocal Rank Fusion
│   │   ├── generator.py       # grounding prompt with [chunk N] citation enforcement
│   │   ├── evaluator.py       # RAGAS wrapper
│   │   ├── observability.py   # Langfuse traces + scores
│   │   └── ingest.py          # parse → chunk → embed → upsert → rebuild BM25
│   ├── seed_docs/             # 4 sample policy/manual markdown files
│   │   └── test_set.py        # 8-item golden Q&A set
│   ├── tests/                 # pytest suite
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.js
│   │   ├── lib/api.js         # axios wrapper
│   │   └── components/        # Sidebar, ChatPanel, DocumentsPanel, EvalDashboard, HistoryPanel, CitedText
│   ├── package.json
│   └── .env.example
├── design_guidelines.json     # UI/UX rules used to build the frontend
└── LICENSE
```

---

## API cheatsheet

All routes are under `/api`.

| Method | Path                        | Purpose                                                       |
| ------ | --------------------------- | ------------------------------------------------------------- |
| GET    | `/health`                   | Mongo + Pinecone + Langfuse status                            |
| GET    | `/documents`                | List ingested documents                                       |
| POST   | `/documents/upload`         | Multipart PDF/MD/TXT upload → chunk → embed → upsert          |
| POST   | `/documents/seed`           | Ingest the 4 sample markdown docs                             |
| DELETE | `/documents/{source}`       | Remove doc from Mongo + Pinecone + rebuild BM25               |
| POST   | `/query`                    | Body: `{query, top_k, mode: "hybrid" \| "dense" \| "keyword"}`|
| GET    | `/conversations`            | Recent queries                                                |
| GET    | `/testset`                  | 8-item golden Q&A                                             |
| POST   | `/evaluations/run`          | Body: `{scope: "testset" \| "recent", limit}` → RAGAS scores  |
| GET    | `/evaluations`              | Historical eval runs                                          |

### Example

```bash
curl -X POST http://localhost:8001/api/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"What does fault code E03 mean?","top_k":5,"mode":"hybrid"}'
```

Returns:

```json
{
  "id": "...",
  "answer": "E03 means a config CRC error. Recover by restoring from CFG-B [1].",
  "contexts": [{"id":"...","text":"...","source":"widget_3000_manual.md","section":"5. Fault Codes and Recovery","score":0.31}],
  "mode": "hybrid",
  "latency_ms": 984,
  "trace_id": "16c6b421-4856-...",
  "model": "gpt-5.4-mini"
}
```

---

## Key engineering decisions

- **Hybrid > pure vector.** Pure embedding search misses exact-keyword queries like policy numbers (`POL-HR-014`) or codes (`E03`). BM25 catches those; RRF fuses both.
- **Grounded prompt, not "helpful assistant".** The system prompt bans out-of-context knowledge and requires inline `[chunk N]` citations. Every claim traces back to a chunk.
- **Eval as a first-class endpoint.** `POST /api/evaluations/run` scores against a held-out test set (RAGAS) *and* pushes each metric back to Langfuse as a per-trace score, so regressions surface immediately in the trend chart.
- **Local embeddings, remote LLM.** Chat generation is expensive and stays with the LLM; embeddings are cheap enough to run on CPU, avoiding a per-token embedding bill.

---

## Deploy notes

- **Secrets** — everything server-side. Never expose `EMERGENT_LLM_KEY`, `PINECONE_API_KEY`, or `LANGFUSE_SECRET_KEY` to the browser.
- **Pinecone index** — created automatically on first startup (`rag-eval-index`, 384-dim, cosine, serverless `aws/us-east-1`). Delete the index in the Pinecone console if you want to reset.
- **MongoDB** — three collections: `documents`, `chunks`, `conversations`, `eval_runs`. Drop the DB to reset the app.
- **CORS** — `CORS_ORIGINS` env var. Currently `*` in dev; tighten before production.

---

## Roadmap

- Chunk-level highlighting inside citations
- Automatic regression alerts (Slack / email) when a metric drops > 10%
- Per-source metric drilldown
- Manual answer grading UI that feeds back into a weekly benchmark
- `.docx` / `.html` ingestion

---

## License

MIT — see [LICENSE](LICENSE).

Made with the [Emergent](https://emergent.sh) platform.
