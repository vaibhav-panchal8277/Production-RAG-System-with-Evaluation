# RAG Evaluation Lab

> **The eval-first RAG.** Retrieval-augmented generation over your document corpus, with **RAGAS metrics you can point to** instead of vibes.

An end-to-end RAG system built to answer the question that most RAG demos dodge: *"is your answer actually right, and did you actually retrieve the right stuff?"* Hybrid dense + BM25 retrieval with Reciprocal Rank Fusion, grounded generation with inline `[chunk N]` citations, RAGAS-scored faithfulness / answer relevancy / context precision, Langfuse traces for every query, optional NeMo Guardrails input validation, and a live dashboard that plots your metrics over time.

![python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/fastapi-0.110-009688?logo=fastapi&logoColor=white)
![groq](https://img.shields.io/badge/groq-llama--3.3--70b-F55036)
![react](https://img.shields.io/badge/react-19-61DAFB?logo=react&logoColor=black)
![pinecone](https://img.shields.io/badge/pinecone-6.0-0F172A)
![langfuse](https://img.shields.io/badge/langfuse-2.60-6366F1)
![ragas](https://img.shields.io/badge/ragas-0.2-EAB308)
![license](https://img.shields.io/badge/license-MIT-green)

---

## How it works

| Stage | What runs |
| --- | --- |
| Ingest | PDF/Markdown → `RecursiveCharacterTextSplitter` (800 chars, 120 overlap) → MiniLM embeddings → Pinecone upsert + BM25 rebuild |
| Retrieve | `dense` (Pinecone), `keyword` (BM25), or `hybrid` (Reciprocal Rank Fusion, `k=60`, `alpha=0.6`) |
| Generate | Groq chat completion, temperature 0, strict "answer only from context" prompt with `[chunk N]` citations |
| Evaluate | RAGAS `Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithoutReference` over the 45-item golden set or your recent queries |
| Observe | One Langfuse trace per query (retrieve + generate spans); eval metrics pushed back as trace scores |

**Generation runs on Groq; embeddings run locally.** Groq serves no embeddings
endpoint, so `sentence-transformers/all-MiniLM-L6-v2` (384-dim) runs in-process.
The first request downloads ~90 MB of model weights and is therefore slow; every
request after that is local and fast.

---

## Getting started

### 1) Clone & configure

```bash
git clone <your-repo-url> rag-eval-lab
cd rag-eval-lab

cp backend/env.example.txt backend/.env
```

Open `backend/.env` and set at minimum:

```ini
GROQ_API_KEY=gsk_...          # https://console.groq.com/keys
PINECONE_API_KEY=pcsk_...     # https://app.pinecone.io
MONGO_URL=mongodb://localhost:27018
DB_NAME=rag_eval
```

`backend/.env` is gitignored — keep real keys out of every other file. Verify
your Groq key and see which models your account can use:

```bash
curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
```

If `openai/gpt-oss-120b` is not in that list, set `LLM_MODEL` in
`backend/.env` to one that is. Nothing in the code hard-codes a model name.

`gpt-oss` is a reasoning model, so `LLM_REASONING_FORMAT=hidden` is set by
default to keep chain-of-thought out of `message.content`. Leave it on: without
it the reasoning text is spliced into answers and into whatever RAGAS grades.
Both reasoning params are dropped automatically if the model rejects them, so
switching `LLM_MODEL` to a non-reasoning model needs no other change.

### 2) Start MongoDB (port 27018)

```bash
docker compose up -d mongo
```

Runs Mongo on host port **27018**, so a local 27017 instance is untouched.

### 3) Backend — Terminal 1

```bash
cd backend
python3.11 -m venv .venv

source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### 4) Frontend — Terminal 2

```bash
cd frontend
yarn install
yarn start                          # http://localhost:3000
```

Or the Streamlit UI instead:

```bash
streamlit run streamlit_app.py      # http://localhost:8501
```

Then click **Seed sample documents** to ingest the four bundled policy/manual
docs, and start asking questions.

`make help` lists the equivalent shortcuts for all of the above.

---

## Configuration

Everything is environment-driven; see `backend/env.example.txt` for the full list.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Any chat model your Groq account can access |
| `LLM_REASONING_FORMAT` | `hidden` | Reasoning models only: keeps chain-of-thought out of the answer. Blank to omit |
| `LLM_REASONING_EFFORT` | *(unset)* | Reasoning models only: `low`, `medium` or `high` |
| `GROQ_API_BASE` | `https://api.groq.com/openai/v1` | Override to proxy or to use another OpenAI-compatible provider |
| `LLM_TIMEOUT_S` | `60` | Per-request timeout, so a hung provider can't pin a worker |
| `PINECONE_API_KEY` | *(required)* | Vector store |
| `RAG_API_KEY` | *(empty)* | When set, `X-API-Key` is required on upload/seed/delete/eval |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist; avoid `*` |
| `MAX_UPLOAD_MB` | `20` | Upload cap, enforced while streaming |
| `ENABLE_NEMO_RAILS` | `false` | Opt in to the NeMo Guardrails config in `backend/config/` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | *(empty)* | Tracing; silently disabled when unset |

### Securing a non-local deployment

The API ships open so the test suite and local dev work with zero setup. Before
exposing it to anything but localhost:

```bash
# backend/.env
RAG_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
CORS_ORIGINS=https://your-frontend.example.com
```

The backend logs a warning at startup while `RAG_API_KEY` is unset. Both UIs
send the header automatically — Streamlit reads `RAG_API_KEY`, React reads
`REACT_APP_RAG_API_KEY` (note that any `REACT_APP_*` value is baked into the
browser bundle, so treat it as a network-level control, not per-user auth).

---

## Docker

```bash
docker compose up --build       # mongo + backend + static frontend
```

The frontend image builds the React bundle and serves it with nginx; both app
containers run as non-root and all published ports bind to `127.0.0.1`. Because
Create React App inlines `REACT_APP_*` at build time, changing the backend URL
means rebuilding: `REACT_APP_BACKEND_URL=... docker compose up --build frontend`.
For hot reload, use `make dev-frontend` on the host instead of Docker.

---

## Testing

```bash
cd backend && pytest -q
```

The suite is integration-style: it drives a **running** backend over HTTP
(`REACT_APP_BACKEND_URL`) and calls Groq and Pinecone for real, so start the
server first and expect it to consume API quota. It covers hybrid/dense/keyword
retrieval, citation formatting, out-of-scope refusals, and the shape of the
evaluation response.

---

## Project structure

```
.
├── backend/
│   ├── server.py              # FastAPI app (all routes under /api)
│   ├── config/                # NeMo Guardrails (config.yml, rails.co) — optional
│   ├── rag/
│   │   ├── llm_client.py      # Groq chat client + local HF embeddings
│   │   ├── chunker.py         # RecursiveCharacterTextSplitter
│   │   ├── vector_store.py    # Pinecone + BM25 + Reciprocal Rank Fusion
│   │   ├── generator.py       # grounded prompt with citations
│   │   ├── guardrails.py      # input validation → allow/block decision
│   │   ├── evaluator.py       # RAGAS wrapper
│   │   ├── observability.py   # Langfuse traces + scores
│   │   └── ingest.py          # parse → chunk → embed → upsert → rebuild BM25
│   ├── seed_docs/             # 4 sample policy/manual markdown files
│   │   └── test_set.py        # 45-item golden Q&A set (incl. 5 out-of-scope)
│   ├── tests/                 # pytest suite
│   ├── requirements.txt
│   └── env.example.txt
├── frontend/                  # React 19 + Tailwind + shadcn/ui (craco)
├── streamlit_app.py           # alternative Streamlit UI
├── docker-compose.yml         # mongo (27018) + backend (8001) + frontend (3000)
└── LICENSE
```

---

## API

| Method | Route | Notes |
| --- | --- | --- |
| `GET` | `/api/health` | Index stats, BM25 size, provider info, whether auth is on |
| `GET` | `/api/documents` | Indexed documents |
| `POST` | `/api/documents/upload` | multipart PDF/MD/TXT · auth |
| `POST` | `/api/documents/seed` | Ingest the bundled corpus · auth |
| `DELETE` | `/api/documents/{source}` | Remove doc, chunks and vectors · auth |
| `POST` | `/api/query` | `{query, mode, top_k}` → answer + contexts + trace id |
| `GET` | `/api/conversations` | Query history |
| `GET` | `/api/testset` | The golden set |
| `POST` | `/api/evaluations/run` | `{scope: testset\|recent, limit}` · auth |
| `GET` | `/api/evaluations` | Historical runs (aggregates only) |

Routes marked *auth* require `X-API-Key` when `RAG_API_KEY` is set.

---

## License

MIT — see [LICENSE](LICENSE).
