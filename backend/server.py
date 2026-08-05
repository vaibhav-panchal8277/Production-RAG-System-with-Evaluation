"""FastAPI backend for RAG Evaluation System."""
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from pymongo.errors import PyMongoError
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from rag.evaluator import evaluate_conversations
from rag.generator import generate_answer
from rag.ingest import ingest_document, rebuild_bm25_from_db
from rag.observability import trace_rag
from rag.vector_store import bm25_search, dense_search, hybrid_search, index_stats
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
    except (PyMongoError, RuntimeError, ValueError) as e:
        logger.warning("BM25 rebuild skipped: %s", e)


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
async def upload_document(file: UploadFile = File(...)):  # noqa: B008
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    try:
        result = await ingest_document(
            db, source=file.filename, content_bytes=content,
            content_type=file.content_type or "", title=file.filename,
        )
    except (PyMongoError, RuntimeError, ValueError) as e:
        logger.exception("Ingest failed")
        raise HTTPException(500, f"Ingest failed: {e}")
    return result


@api.post("/documents/seed", response_model=SeedOut)
async def seed_documents():
    seed_dir = ROOT_DIR / "seed_docs"
    ingested = []
    for path in sorted(seed_dir.glob("*.md")):
        content = path.read_bytes()
        try:
            r = await ingest_document(
                db, source=path.name, content_bytes=content,
                content_type="text/markdown", title=path.stem.replace("_", " ").title(),
            )
            ingested.append(r)
        except (ValueError, PyMongoError, RuntimeError) as e:
            logger.error("seed failed for %s: %s", path.name, e)
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
    else:
        contexts = hybrid_search(body.query, top_k=body.top_k)

    answer, model = generate_answer(body.query, contexts)
    latency_ms = int((time.time() - t0) * 1000)

    trace_id = trace_rag(
        query=body.query,
        contexts=contexts,
        answer=answer,
        model=model,
        latency_ms=latency_ms,
    )

    conv_id = str(uuid.uuid4())
    doc = {
        "id": conv_id,
        "query": body.query,
        "answer": answer,
        "contexts": contexts,
        "mode": body.mode,
        "latency_ms": latency_ms,
        "trace_id": trace_id,
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.conversations.insert_one(doc)

    return {
        "id": conv_id,
        "answer": answer,
        "contexts": contexts,
        "mode": body.mode,
        "latency_ms": latency_ms,
        "trace_id": trace_id,
        "model": model,
    }


@api.get("/conversations")
async def list_conversations(limit: int = 50):
    convs = await db.conversations.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return {"conversations": convs}


@api.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = await db.conversations.find_one({"id": conv_id}, {"_id": 0})
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


# ----- evaluations -----
@api.get("/testset")
async def get_testset():
    return {"testset": TEST_SET}


@api.post("/evaluations/run")
async def run_evaluation(body: EvalRunIn):
    t0 = time.time()
    if body.scope == "testset":
        rows = [
            {
                "query": item["question"],
                "answer": generate_answer(item["question"], hybrid_search(item["question"], top_k=5))[0],
                "contexts": hybrid_search(item["question"], top_k=5),
            }
            for item in TEST_SET[:body.limit]
        ]
    else:
        # recent conversations
        recent = await db.conversations.find({}, {"_id": 0}).sort("created_at", -1).to_list(body.limit)
        if not recent:
            raise HTTPException(400, "No recent conversations found to evaluate")
        rows = [
            {
                "query": c["query"],
                "answer": c["answer"],
                "contexts": c.get("contexts", []),
            }
            for c in recent
        ]

    per_row = await evaluate_conversations(rows)

    # compute aggregates
    valid_f = [r["faithfulness"] for r in per_row if r["faithfulness"] is not None]
    valid_ar = [r["answer_relevancy"] for r in per_row if r["answer_relevancy"] is not None]
    valid_cp = [r["context_precision"] for r in per_row if r["context_precision"] is not None]

    agg_f = sum(valid_f) / len(valid_f) if valid_f else None
    agg_ar = sum(valid_ar) / len(valid_ar) if valid_ar else None
    agg_cp = sum(valid_cp) / len(valid_cp) if valid_cp else None

    duration = int(time.time() - t0)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    eval_doc = {
        "id": run_id,
        "scope": body.scope,
        "n_samples": len(per_row),
        "faithfulness": round(agg_f, 4) if agg_f is not None else None,
        "answer_relevancy": round(agg_ar, 4) if agg_ar is not None else None,
        "context_precision": round(agg_cp, 4) if agg_cp is not None else None,
        "duration_s": duration,
        "created_at": now,
        "per_row": per_row,
    }

    await db.eval_runs.insert_one(eval_doc)

    # remove _id from response
    eval_doc.pop("_id", None)
    return eval_doc


@api.get("/evaluations")
async def list_evaluations(limit: int = 30):
    runs = await db.eval_runs.find({}, {"_id": 0, "per_row": 0}).sort("created_at", -1).to_list(limit)
    return {"runs": runs}


app.include_router(api)

