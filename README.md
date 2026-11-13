# RAG Evaluation Lab

> **The eval-first RAG.** Retrieval-augmented generation over your document corpus, with **RAGAS metrics you can point to** instead of vibes.

An end-to-end RAG system built to answer the question that most RAG demos dodge: *"is your answer actually right, and did you actually retrieve the right stuff?"* Hybrid dense + BM25 retrieval with Reciprocal Rank Fusion, grounded generation with inline `[chunk N]` citations, RAGAS-scored faithfulness / answer relevancy / context precision, Langfuse traces for every query, optional NeMo Guardrails input validation, and a live dashboard that plots your metrics over time.

![python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![fastapi](https://img.shields.io/badge/fastapi-0.110-009688?logo=fastapi&logoColor=white)
![groq](https://img.shields.io/badge/groq-gpt--oss--120b-F55036)
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
| Evaluate | RAGAS `Faithfulness`, `ResponseRelevancy`, `LLMContextPrecisionWithoutReference` on every in-scope row; on the 45-item golden set also `AnswerCorrectness` + `LLMContextRecall` against the reference answers, retrieval hit-rate / MRR against `expected_source`, and refusal accuracy on the 5 out-of-scope questions (which skip RAGAS) |
| Observe | One Langfuse trace per query (retrieve + generate spans); eval metrics pushed back as trace scores |

**Generation runs on Groq; embeddings run locally.** Groq serves no embeddings
endpoint, so `sentence-transformers/all-MiniLM-L6-v2` (384-dim) runs in-process
on fastembed's ONNX runtime. It produces the same vectors as sentence-transformers
without PyTorch, so the API idles at about 280 MB and fits a 512 MB free-tier
instance. Outside Docker, the first request downloads the ~90 MB model; the
Docker image bakes it in.

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

Reasoning models must keep chain-of-thought out of `message.content`, or it is
spliced into answers and into whatever RAGAS grades. With
`LLM_REASONING_FORMAT=hidden` (the default) the client does the right thing per
model family: `gpt-oss` gets `include_reasoning=false` (Groq does not support
`reasoning_format` there), other reasoning models (qwen3, deepseek-r1) get
`reasoning_format=hidden`. If a model rejects these params they are dropped
automatically, so a non-reasoning model needs no other change.

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

pip install -r requirements-dev.txt   # runtime deps + pytest/ruff
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

`requirements.txt` is the runtime set (what the Docker image installs). To use
the optional NeMo Guardrails layer, also `pip install -r requirements-nemo.txt`.

### 4) Frontend — Terminal 2

```bash
cd frontend
yarn install
yarn start                          # http://localhost:3000
```

Or the Streamlit UI instead:

```bash
pip install -r requirements-streamlit.txt
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
| `LLM_REASONING_FORMAT` | `hidden` | Reasoning models only: keeps chain-of-thought out of the answer (`include_reasoning=false` on gpt-oss). Blank to omit |
| `LLM_REASONING_EFFORT` | *(unset)* | Reasoning models only: `low`, `medium` or `high` |
| `EVAL_LLM_MODEL` | *(= `LLM_MODEL`)* | RAGAS judge model; use a different model to avoid self-grading bias |
| `GROQ_API_BASE` | `https://api.groq.com/openai/v1` | Override to proxy or to use another OpenAI-compatible provider |
| `LLM_TIMEOUT_S` | `60` | Per-request timeout, so a hung provider can't pin a worker |
| `PINECONE_API_KEY` | *(required)* | Vector store |
| `PINECONE_NAMESPACE` | *(empty)* | Isolate vectors within a shared index (CI uses one per run) |
| `RAG_API_KEY` | *(empty)* | When set, `X-API-Key` is required on upload/seed/delete, eval, query and conversation history |
| `PUBLIC_QUERY` | `false` | Public demo mode: `/query` needs no key but is rate limited; everything else still needs `RAG_API_KEY` |
| `QUERY_RATE_PER_MIN` / `QUERY_GLOBAL_RATE_PER_MIN` | `10` / `25` | Public `/query` limits per visitor and in total (requests carrying the key are exempt) |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist; avoid `*` |
| `EVAL_CONCURRENCY` | `4` | Test-set questions answered in parallel during an eval run |
| `EVAL_RAGAS_WORKERS` | `4` | Parallel RAGAS judge calls (RAGAS default 16 trips rate limits) |
| `MAX_UPLOAD_MB` | `20` | Upload cap, enforced while streaming |
| `ENABLE_NEMO_RAILS` | `false` | Opt in to the NeMo Guardrails config in `backend/config/` (needs `requirements-nemo.txt`) |
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

### Deploying publicly

[DEPLOY.md](DEPLOY.md) walks through a free deployment: the API on Render, the
UI on Vercel and MongoDB Atlas, using [render.yaml](render.yaml) and
[frontend/vercel.json](frontend/vercel.json). It runs in public demo mode, where
visitors can chat and admin actions need the key.

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

`tests/test_offline_units.py` needs no backend or keys and always runs. The
rest of the suite skips itself unless `REACT_APP_BACKEND_URL` is set, and then
runs serially (it shares one backend's state).

The integration suite drives a **running** backend over HTTP
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
│   │   ├── llm_client.py      # Groq chat client + shared local MiniLM embeddings (ONNX)
│   │   ├── chunker.py         # RecursiveCharacterTextSplitter
│   │   ├── vector_store.py    # Pinecone + BM25 + Reciprocal Rank Fusion
│   │   ├── generator.py       # grounded prompt with citations
│   │   ├── guardrails.py      # input validation → allow/block decision
│   │   ├── evaluator.py       # RAGAS (reference-free + golden-reference metrics)
│   │   ├── eval_metrics.py    # LLM-free retrieval hit-rate/MRR + refusal scoring
│   │   ├── chunk_ids.py       # deterministic, per-source-prefixed vector IDs
│   │   ├── observability.py   # Langfuse traces + scores
│   │   └── ingest.py          # parse → chunk → embed → upsert → rebuild BM25
│   ├── seed_docs/             # 4 sample policy/manual markdown files
│   │   └── test_set.py        # 45-item golden Q&A set (incl. 5 out-of-scope)
│   ├── tests/                 # offline unit/API tests + integration suite
│   ├── requirements.txt       # runtime (Docker image)
│   ├── requirements-dev.txt   # + pytest, httpx, requests, ruff
│   ├── requirements-nemo.txt  # optional NeMo Guardrails
│   └── env.example.txt
├── frontend/                  # React 19 + Tailwind + shadcn/ui (craco)
├── streamlit_app.py           # alternative Streamlit UI
├── requirements-streamlit.txt # Streamlit UI deps (talks to the API over HTTP)
├── ruff.toml                  # lint config (CI: ruff check backend streamlit_app.py)
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
| `POST` | `/api/query` | `{query, mode, top_k}` → answer + contexts + trace id + guardrail · auth |
| `GET` | `/api/conversations` | Query history (also `/{id}`) · auth |
| `GET` | `/api/testset` | The golden set |
| `POST` | `/api/evaluations/run` | `{scope: testset\|recent, limit, background}` · auth. `background: true` → 202 + `job_id` |
| `GET` | `/api/evaluations/jobs/{job_id}` | Job status; `result` once done · auth |
| `GET` | `/api/evaluations` | Historical runs (aggregates only) |

Routes marked *auth* require `X-API-Key` when `RAG_API_KEY` is set.

---

## License

MIT — see [LICENSE](LICENSE).
