# RAG Evaluation Lab — PRD

## Original Problem Statement
A Retrieval-Augmented Generation system built over a real document corpus (internal policy docs / technical manuals) — with the FOCUS on the evaluation layer rather than the RAG pipeline itself. Measures whether retrieved context is actually relevant and whether generated answers are faithful to that context, using RAGAS (Faithfulness, Context Precision, Answer Relevancy) + Langfuse traces + a live dashboard.

## User Choices
- Frontend: Streamlit (served on port 3000 via yarn start)
- LLM: OpenAI gpt-5.4-mini via Emergent Universal Key
- Embeddings: fell back to local sentence-transformers/all-MiniLM-L6-v2 (Emergent proxy does not expose embedding models — MiniLM is the "local HF for cost control" option from the tech stack)
- Vector Store: Pinecone (serverless, aws us-east-1, index `rag-eval-index`, dim 384, cosine)
- Observability: Langfuse (US cloud)
- Corpus: pre-seeded with 4 sample policy/technical docs

## Architecture
- Backend: FastAPI on 0.0.0.0:8001, all routes prefixed /api
- Frontend: Streamlit on 3000 (yarn start invokes `/root/.venv/bin/streamlit run /app/streamlit_app.py`)
- Storage: MongoDB (chunks, documents, conversations, eval_runs) + Pinecone (vectors)
- Retrieval: hybrid dense (MiniLM) + BM25 (rank_bm25) with Reciprocal Rank Fusion
- Generation: strict grounding prompt with inline [chunk N] citations, temperature 0
- Evaluation: RAGAS (Faithfulness, ResponseRelevancy, LLMContextPrecisionWithoutReference) wrapped around ChatOpenAI + HuggingFaceEmbeddings
- Observability: Langfuse traces per query (retrieve + generate spans) + per-metric scores after eval runs

## Implemented (2026-02-01)
- /api/health, /api/documents (list/upload/seed/delete)
- /api/query (hybrid | dense | keyword modes)
- /api/conversations (list/get)
- /api/testset (8-item golden set)
- /api/evaluations/run (scope=testset|recent) + /api/evaluations (history)
- 4 seed markdown docs: remote_work_policy, data_retention_standard, widget_3000_manual, incident_response_runbook
- Streamlit UI: Chat, Documents, Evaluation Dashboard (metrics + historical trend chart), Query History
- Editorial "paper + amber" visual design with IBM Plex + Fraunces fonts

## Tested
- 13/13 backend pytest cases pass (see /app/backend/tests/test_rag_eval.py)
- E2E UI query flow verified via Playwright (Streamlit)
- Real integration outputs verified: Pinecone vectors, Langfuse trace UUIDs, RAGAS 0-1 scores

## Backlog (P1)
- Batch delete: use single db.chunks.find({_id: {$in: ids}}) instead of per-chunk Mongo lookup in keyword mode
- Migrate FastAPI on_event to lifespan context manager
- Add per-source metric drill-down chart
- Support .docx and .html ingestion
- Add regression alerting when a metric drops > X% vs. last run

## Backlog (P2)
- User authentication (currently open, all endpoints public)
- Multi-tenant document namespacing
- Query cache
