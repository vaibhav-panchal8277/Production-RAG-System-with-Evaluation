"""FastAPI backend for RAG Evaluation System."""
import os
import time
import uuid
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from rag.vector_store import hybrid_search, dense_search, bm25_search, index_stats
from rag.generator import generate_answer
from rag.observability import trace_rag, score_trace
from rag.ingest import ingest_document, rebuild_bm25_from_db
from rag.evaluator import evaluate_conversations
from seed_docs.test_set import TEST_SET

# ---------- setup ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rag-eval")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="RAG Evaluation System")
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- models ----------
class QueryIn(BaseModel):
    query: str
    top_k: int = 5
    mode: str = "hybrid"  # hybrid | dense | keyword


class SeedOut(BaseModel):
    ingested: list[dict]


class EvalRunIn(BaseModel):
    scope: str = "recent"  # recent | testset
    limit: int = 20


# ---------- startup ----------
_startup_done = False


@app.on_event("startup")
async def on_startup():
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    try:
        await rebuild_bm25_from_db(db)
        logger.info("BM25 index rebuilt from Mongo")
    except Exception as e:
        logger.warning(f"BM25 rebuild skipped: {e}")


# ---------- routes ----------
@api.get("/")
async def root():
    return {"service": "rag-eval", "status": "ok"}


@api.get("/health")
async def health():
    stats = index_stats()
    doc_count = await db.documents.count_documents({})
    conv_count = await db.conversations.count_documents({})
    return {
        "mongo_docs": doc_count,
        "mongo_conversations": conv_count,
        "pinecone": stats,
        "langfuse_configured": bool(os.environ.get("LANGFUSE_SECRET_KEY")),
    }


# ----- documents -----
@api.get("/documents")
async def list_documents():
    docs = await db.documents.find({}, {"_id": 0}).sort("source", 1).to_list(500)
    return {"documents": docs}


@api.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    try:
        result = await ingest_document(
            db, source=file.filename, content_bytes=content,
            content_type=file.content_type or "", title=file.filename,
        )
    except Exception as e:
        logger.exception("Ingest failed")
        raise HTTPException(500, f"Ingest failed: {e}")
    return result


@api.post("/documents/seed", response_model=SeedOut)
async def seed_documents():
    seed_dir = ROOT_DIR / "seed_docs"
    ingested = []
    for path in sorted(seed_dir.glob("*.md")):
        with open(path, "rb") as f:
            content = f.read()
        try:
            r = await ingest_document(
                db, source=path.name, content_bytes=content,
                content_type="text/markdown", title=path.stem.replace("_", " ").title(),
            )
            ingested.append(r)
        except Exception as e:
            logger.error(f"seed failed for {path.name}: {e}")
            ingested.append({"source": path.name, "error": str(e)})
    return {"ingested": ingested}


@api.delete("/documents/{source}")
async def delete_document(source: str):
    from rag.vector_store import delete_by_source
    delete_by_source(source)
    await db.chunks.delete_many({"source": source})
    r = await db.documents.delete_one({"source": source})
    await rebuild_bm25_from_db(db)
    return {"deleted": r.deleted_count, "source": source}


# ----- query / RAG -----
@api.post("/query")
async def query(body: QueryIn):
    t0 = time.time()
    if body.mode == "dense":
        contexts = dense_search(body.query, top_k=body.top_k)
    elif body.mode == "keyword":
        contexts = bm25_search(body.query, top_k=body.top_k)
        # bm25 results lack pinecone metadata; enrich text is already stored
        for c in contexts:
            c["metadata"] = c.get("metadata") or {}
    else:
        contexts = hybrid_search(body.query, top_k=body.top_k)

    if not contexts:
        raise HTTPException(404, "No documents indexed. Please seed or upload documents first.")

    # Ensure metadata has source (bm25 path)
    for c in contexts:
        if not c.get("metadata", {}).get("source"):
            doc = await db.chunks.find_one({"_id": c["id"]}, {"source": 1, "section": 1, "chunk_index": 1})
            if doc:
                c["metadata"] = {
                    "source": doc.get("source"),
                    "section": doc.get("section"),
                    "chunk_index": doc.get("chunk_index"),
                }

    gen = generate_answer(body.query, contexts)
    latency_ms = int((time.time() - t0) * 1000)

    trace_id = trace_rag(body.query, contexts, gen["answer"], gen["model"], latency_ms)

    conv_id = str(uuid.uuid4())
    conv = {
        "_id": conv_id,
        "query": body.query,
        "answer": gen["answer"],
        "contexts": [
            {"id": c["id"], "text": c["text"], "score": c.get("fused_score", c.get("score")),
             "source": c.get("metadata", {}).get("source"),
             "section": c.get("metadata", {}).get("section"),
             "chunk_index": c.get("metadata", {}).get("chunk_index")}
            for c in contexts
        ],
        "mode": body.mode,
        "top_k": body.top_k,
        "model": gen["model"],
        "prompt_tokens": gen["prompt_tokens"],
        "completion_tokens": gen["completion_tokens"],
        "latency_ms": latency_ms,
        "trace_id": trace_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.conversations.insert_one(conv)

    return {
        "id": conv_id,
        "answer": gen["answer"],
        "contexts": conv["contexts"],
        "mode": body.mode,
        "latency_ms": latency_ms,
        "trace_id": trace_id,
        "model": gen["model"],
    }


@api.get("/conversations")
async def list_conversations(limit: int = 30):
    cursor = db.conversations.find({}, {"contexts": 0}).sort("created_at", -1).limit(limit)
    out = []
    async for d in cursor:
        d["id"] = d.pop("_id")
        out.append(d)
    return {"conversations": out}


@api.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    d = await db.conversations.find_one({"_id": conv_id})
    if not d:
        raise HTTPException(404, "not found")
    d["id"] = d.pop("_id")
    return d


# ----- test set / evaluation -----
@api.get("/testset")
async def get_testset():
    return {"testset": TEST_SET}


@api.post("/evaluations/run")
async def run_evaluation(body: EvalRunIn):
    """Run RAGAS evaluation.
    scope=recent  -> evaluate the last `limit` conversations
    scope=testset -> run each test-set question through RAG first, then evaluate.
    """
    t0 = time.time()

    if body.scope == "testset":
        conv_rows = []
        for tc in TEST_SET[: body.limit or len(TEST_SET)]:
            contexts = hybrid_search(tc["question"], top_k=5)
            if not contexts:
                continue
            gen = generate_answer(tc["question"], contexts)
            conv_id = str(uuid.uuid4())
            trace_id = trace_rag(tc["question"], contexts, gen["answer"], gen["model"], 0)
            conv = {
                "_id": conv_id,
                "query": tc["question"],
                "answer": gen["answer"],
                "reference": tc["reference"],
                "expected_source": tc["expected_source"],
                "contexts": [
                    {"id": c["id"], "text": c["text"],
                     "score": c.get("fused_score", c.get("score")),
                     "source": c.get("metadata", {}).get("source")}
                    for c in contexts
                ],
                "mode": "hybrid",
                "top_k": 5,
                "model": gen["model"],
                "trace_id": trace_id,
                "is_testset": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.conversations.insert_one(conv)
            conv_rows.append(conv)
        rows_for_eval = [
            {"query": c["query"], "answer": c["answer"],
             "contexts": [x["text"] for x in c["contexts"]],
             "conv_id": c["_id"], "trace_id": c.get("trace_id")}
            for c in conv_rows
        ]
    else:
        cursor = db.conversations.find({}).sort("created_at", -1).limit(body.limit)
        conv_rows = [d async for d in cursor]
        rows_for_eval = [
            {"query": c["query"], "answer": c["answer"],
             "contexts": [x["text"] for x in c.get("contexts", [])],
             "conv_id": c["_id"], "trace_id": c.get("trace_id")}
            for c in conv_rows
        ]

    if not rows_for_eval:
        raise HTTPException(400, "No conversations available to evaluate")

    # Run RAGAS off the event loop (it's synchronous)
    def _do_eval():
        return evaluate_conversations(rows_for_eval)

    scored = await asyncio.to_thread(_do_eval)

    # Push per-row scores to Langfuse
    for orig, s in zip(rows_for_eval, scored):
        if orig.get("trace_id"):
            for metric in ["faithfulness", "answer_relevancy", "context_precision"]:
                v = s.get(metric)
                if v is not None:
                    score_trace(orig["trace_id"], metric, v)

    # Aggregate
    def _avg(key):
        vs = [s[key] for s in scored if s.get(key) is not None]
        return round(sum(vs) / len(vs), 4) if vs else None

    aggregate = {
        "faithfulness": _avg("faithfulness"),
        "answer_relevancy": _avg("answer_relevancy"),
        "context_precision": _avg("context_precision"),
        "n_samples": len(scored),
        "scope": body.scope,
        "duration_s": round(time.time() - t0, 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    run_id = str(uuid.uuid4())
    await db.eval_runs.insert_one({
        "_id": run_id,
        **aggregate,
        "per_row": scored,
    })

    return {"run_id": run_id, "aggregate": aggregate, "per_row": scored}


@api.get("/evaluations")
async def list_evaluations(limit: int = 30):
    cursor = db.eval_runs.find({}, {"per_row": 0}).sort("created_at", -1).limit(limit)
    out = []
    async for d in cursor:
        d["id"] = d.pop("_id")
        out.append(d)
    return {"runs": out}


@api.get("/evaluations/{run_id}")
async def get_evaluation(run_id: str):
    d = await db.eval_runs.find_one({"_id": run_id})
    if not d:
        raise HTTPException(404, "not found")
    d["id"] = d.pop("_id")
    return d


app.include_router(api)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
