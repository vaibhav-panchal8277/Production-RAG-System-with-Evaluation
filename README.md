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

## Getting Started: Hybrid Local Development (Recommended)

To develop locally with hot-reload enabled on your PC while keeping MongoDB cleanly isolated in Docker:

### 1) Clone & Configure Environment
```bash
git clone <your-repo-url> rag-eval-lab
cd rag-eval-lab

# Copy backend environment template
cp backend/env.example.txt backend/.env
```
Open `backend/.env` and fill in your **Direct OpenAI API Key** (`OPENAI_API_KEY=sk-proj-...`) and optional Langfuse keys.

### 2) Start MongoDB in Docker (Port 27018)
Spin up only MongoDB in the background without containerizing the app code:
```bash
docker compose up -d mongo
```
*(This leaves your local port 27017 untouched and runs Mongo on port 27018)*

### 3) Start Backend (FastAPI)
In Terminal 1:
```bash
cd backend
python3.11 -m venv .venv

# Windows activation (Command Prompt):
.venv\Scripts\activate.bat
# Windows activation (PowerShell):
.venv\Scripts\Activate.ps1
# Mac/Linux activation:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### 4) Start Frontend (React)
In Terminal 2:
```bash
cd frontend
yarn install
yarn start
```

Open **http://localhost:3000** in your browser!

---

## Project Structure

```
.
├── backend/
│   ├── server.py              # FastAPI app (all routes under /api)
│   ├── rag/
│   │   ├── llm_client.py      # OpenAI + local HF embeddings
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
│   └── env.example.txt
├── frontend/
│   ├── src/
│   │   ├── App.js
│   │   ├── lib/api.js         # axios wrapper
│   │   └── components/        # Sidebar, ChatPanel, DocumentsPanel, EvalDashboard, HistoryPanel, CitedText
│   ├── package.json
│   ├── env.example.txt
│   └── .gitignore
├── docker-compose.yml         # Isolated MongoDB service on port 27018
├── design_guidelines.json
└── LICENSE
```

---

## License

MIT — see [LICENSE](LICENSE).
