# RAG Evaluation Lab — PRD

## Original Problem Statement
A Retrieval-Augmented Generation system built over a real document corpus (internal policy docs / technical manuals) — with the FOCUS on the evaluation layer rather than the RAG pipeline itself. Measures whether retrieved context is actually relevant and whether generated answers are faithful to that context, using RAGAS (Faithfulness, Context Precision, Answer Relevancy) + Langfuse traces + a live dashboard.

## User Choices
- Frontend: Streamlit (served on port 3000 via yarn start) + a React dashboard
- LLM: Groq (`openai/gpt-oss-120b` by default, set via `LLM_MODEL`), consumed through Groq's OpenAI-compatible endpoint `https://api.groq.com/openai/v1`. Reasoning output is suppressed via `LLM_REASONING_FORMAT=hidden` so chain-of-thought never reaches answers or RAGAS.
- Embeddings: local sentence-transformers/all-MiniLM-L6-v2 (Groq serves no embeddings endpoint — MiniLM is the "local HF for cost control" option from the tech stack, dim 384)
- Vector Store: Pinecone (serverless, aws us-east-1, index `rag-eval-index`, dim 384, cosine)
- Observability: Langfuse (US cloud)
- Corpus: pre-seeded with 4 sample policy/technical docs

## Architecture
- Backend: FastAPI on 0.0.0.0:8001, all routes prefixed /api
- Frontend: Streamlit on 3000 (yarn start invokes `/root/.venv/bin/streamlit run /app/streamlit_app.py`)
- Storage: MongoDB (chunks, documents, conversations, eval_runs) + Pinecone (vectors)
- Retrieval: hybrid dense (MiniLM) + BM25 (rank_bm25) with Reciprocal Rank Fusion
- Generation: strict grounding prompt with inline [chunk N] citations, temperature 0
- Evaluation: RAGAS (Faithfulness, ResponseRelevancy, LLMContextPrecisionWithoutReference) wrapped around ChatOpenAI (pointed at Groq) + HuggingFaceEmbeddings
- Observability: Langfuse traces per query (retrieve + generate spans) + per-metric scores after eval runs

## Implemented (2026-02-01)
- /api/health, /api/documents (list/upload/seed/delete)
- /api/query (hybrid | dense | keyword modes)
- /api/conversations (list/get)
- /api/testset (45-item golden set: 10 questions per seed doc + 5 out-of-scope refusal probes)
- /api/evaluations/run (scope=testset|recent) + /api/evaluations (history)
- 4 seed markdown docs: remote_work_policy, data_retention_standard, widget_3000_manual, incident_response_runbook
- Streamlit UI: Chat, Documents, Evaluation Dashboard (metrics + historical trend chart), Query History
- Editorial "paper + amber" visual design with IBM Plex + Fraunces fonts

## Hardening / migration pass (2026-09-04)
- Provider migrated off the Emergent universal key onto Groq; all Emergent
  packages, branding, analytics and platform cron scaffolding removed.
- Optional shared-secret auth: `RAG_API_KEY` guards upload/seed/delete/eval.
  Unset = open (dev default) with a loud startup warning.
- Stored-XSS fix in the Streamlit UI (all interpolated values HTML-escaped).
- Guardrails no longer bypass retrieval or fail open; they return a decision.
- Retrieval contexts expose a flattened `source`/`section` alongside `metadata`.
- `/api/evaluations/run` returns metrics nested under `aggregate` (what both
  UIs and the test suite read) while Mongo keeps a flat copy for cheap listing.
- Mongo indexes created at startup; ingest paginates instead of silently
  truncating at 2,000/10,000 chunks.
- Docker: non-root users, static production frontend build, loopback-bound
  ports, explicit CORS origins.

## Tested
- Backend pytest suite (`backend/tests/`) — drives a live server over HTTP
- E2E UI query flow verified via Playwright (Streamlit)
- Real integration outputs verified: Pinecone vectors, Langfuse trace UUIDs, RAGAS 0-1 scores

## Backlog (P1)
- Batch delete: use single db.chunks.find({_id: {$in: ids}}) instead of per-chunk Mongo lookup in keyword mode
- Add per-source metric drill-down chart
- Support .docx and .html ingestion
- Add regression alerting when a metric drops > X% vs. last run

## Backlog (P2)
- Real per-user authentication (the current `RAG_API_KEY` is a single shared secret)
- Multi-tenant document namespacing
- Query cache
