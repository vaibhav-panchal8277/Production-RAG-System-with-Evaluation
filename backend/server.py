"""FastAPI backend for RAG Evaluation System."""
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from rag.evaluator import evaluate_conversations
from rag.generator import generate_answer
from rag.guardrails import guardrails_status
from rag.ingest import ingest_document, rebuild_bm25_from_db
from rag.llm_client import provider_info
from rag.observability import shutdown_tracing, trace_rag
from rag.vector_store import (
    bm25_search,
    bm25_size,
    dense_search,
    hybrid_search,
    index_stats,
)
from seed_docs.test_set import TEST_SET

# ---------- setup ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rag-eval")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ---------- security / limits ----------
API_KEY = (os.environ.get("RAG_API_KEY") or "").strip()
MAX_UPLOAD_BYTES = int(float(os.environ.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024)
MAX_PAGE_LIMIT = int(os.environ.get("MAX_PAGE_LIMIT", "200"))
MAX_EVAL_SAMPLES = int(os.environ.get("MAX_EVAL_SAMPLES", "100"))
UPLOAD_CHUNK = 1024 * 1024

_RAW_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").strip()
CORS_ORIGINS = [o.strip() for o in _RAW_ORIGINS.split(",") if o.strip()]
# A wildcard origin cannot be combined with credentialed requests (the browser
# rejects it), so only allow credentials when explicit origins are configured.
ALLOW_WILDCARD = "*" in CORS_ORIGINS
ALLOW_CREDENTIALS = not ALLOW_WILDCARD


async def require_api_key(x_api_key: str | None = Header(default=None)):
    """Guard mutating / expensive endpoints.

    When RAG_API_KEY is unset the dependency is a no-op so local development and
    the existing test suite keep working; startup logs a prominent warning in
    that case. Set RAG_API_KEY before exposing this service to a network.
    """
    if not API_KEY:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


# ---------- lifespan ----------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not API_KEY:
        logger.warning(
            "RAG_API_KEY is not set — mutating endpoints (upload/seed/delete/"
            "evaluations) are UNAUTHENTICATED. Set RAG_API_KEY before exposing "
            "this service beyond localhost."
        )
    if ALLOW_WILDCARD:
        logger.warning(
            "CORS_ORIGINS is '*' — credentials are disabled. Configure explicit "
            "origins for production."
        )
    logger.info("LLM provider: %s", provider_info())

    try:
        n = await rebuild_bm25_from_db(db)
        logger.info("BM25 index rebuilt from Mongo (%s chunks)", n)
    except (PyMongoError, RuntimeError, ValueError) as e:
        logger.warning("BM25 rebuild skipped: %s", e)

    try:
        await _ensure_mongo_indexes()
    except PyMongoError as e:
        logger.warning("Mongo index creation skipped: %s", e)

    yield

    await run_in_threadpool(shutdown_tracing)


async def _ensure_mongo_indexes():
    """Indexes for the fields we filter/sort on (avoids full collection scans)."""
    await db.documents.create_index("source", unique=True)
    await db.chunks.create_index("source")
    await db.chunks.create_index("id")
    await db.conversations.create_index("id", unique=True)
    await db.conversations.create_index([("created_at", -1)])
    await db.eval_runs.create_index([("created_at", -1)])


app = FastAPI(title="RAG Evaluation System", lifespan=lifespan)
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)


# ---------- models ----------
class QueryIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: str = Field(default="hybrid", pattern="^(hybrid|dense|keyword)$")


class SeedOut(BaseModel):
    ingested: list[dict]


class EvalRunIn(BaseModel):
    scope: str = Field(default="recent", pattern="^(recent|testset)$")
    limit: int = Field(default=20, ge=1, le=1000)


# ---------- helpers ----------
def _retrieve(query: str, mode: str, top_k: int) -> list[dict]:
    if mode == "dense":
        return dense_search(query, top_k=top_k)
    if mode == "keyword":
        return bm25_search(query, top_k=top_k)
    return hybrid_search(query, top_k=top_k)


async def _retrieve_and_generate(query: str, mode: str, top_k: int) -> tuple[list[dict], str, str]:
    """Retrieve once, then generate from exactly those contexts.

    Both calls are synchronous and network-bound, so they run in a worker thread
    to avoid blocking the event loop (which would serialise all requests).
    """
    contexts = await run_in_threadpool(_retrieve, query, mode, top_k)
    answer, model = await run_in_threadpool(generate_answer, query, contexts)
    return contexts, answer, model


# ---------- routes ----------
@api.get("/")
async def root():
    return {"service": "rag-eval", "status": "ok"}


@api.get("/health")
async def health():
    stats = await run_in_threadpool(index_stats)
    doc_count = await db.documents.count_documents({})
    conv_count = await db.conversations.count_documents({})
    return {
        "mongo_docs": doc_count,
        "mongo_conversations": conv_count,
        "pinecone": stats,
        "bm25_chunks": bm25_size(),
        "langfuse_configured": bool(os.environ.get("LANGFUSE_SECRET_KEY")),
        "llm": provider_info(),
        "guardrails": guardrails_status(),
        "auth_required": bool(API_KEY),
    }


# ----- documents -----
@api.get("/documents")
async def list_documents():
    docs = await db.documents.find({}, {"_id": 0}).sort("source", 1).to_list(500)
    return {"documents": docs}


@api.post("/documents/upload", dependencies=[Depends(require_api_key)])
async def upload_document(file: UploadFile = File(...)):  # noqa: B008
    # Stream the upload so an oversized file can't exhaust memory.
    chunks: list[bytes] = []
    total = 0
    while True:
        block = await file.read(UPLOAD_CHUNK)
        if not block:
            break
        total += len(block)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                413,
                f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit",
            )
        chunks.append(block)

    content = b"".join(chunks)
    if not content:
        raise HTTPException(400, "Empty file")

    try:
        return await ingest_document(
            db,
            source=file.filename,
            content_bytes=content,
            content_type=file.content_type or "",
            title=file.filename,
        )
    except ValueError as e:
        # Genuinely user-actionable (e.g. no extractable text).
        raise HTTPException(400, str(e)) from e
    except (PyMongoError, RuntimeError) as e:
        # Log details server-side; don't leak internals to the client.
        logger.exception("Ingest failed for %s", file.filename)
        raise HTTPException(500, "Ingest failed due to a server error") from e


@api.post("/documents/seed", response_model=SeedOut, dependencies=[Depends(require_api_key)])
async def seed_documents():
    seed_dir = ROOT_DIR / "seed_docs"
    ingested = []
    for path in sorted(seed_dir.glob("*.md")):
        content = path.read_bytes()
        try:
            r = await ingest_document(
                db,
                source=path.name,
                content_bytes=content,
                content_type="text/markdown",
                title=path.stem.replace("_", " ").title(),
            )
            ingested.append(r)
        except (ValueError, PyMongoError, RuntimeError) as e:
            logger.error("seed failed for %s: %s", path.name, e)
            ingested.append({"source": path.name, "error": str(e)})
    return {"ingested": ingested}


@api.delete("/documents/{source}", dependencies=[Depends(require_api_key)])
async def delete_document(source: str):
    from rag.vector_store import delete_by_source

    vectors_deleted = await run_in_threadpool(delete_by_source, source)
    await db.chunks.delete_many({"source": source})
    r = await db.documents.delete_one({"source": source})
    await rebuild_bm25_from_db(db)
    out = {"deleted": r.deleted_count, "source": source}
    if not vectors_deleted:
        out["warning"] = "Vector store delete failed; stale vectors may remain."
    return out


# ----- query / RAG -----
@api.post("/query")
async def query(body: QueryIn):
    t0 = time.time()
    contexts, answer, model = await _retrieve_and_generate(
        body.query, body.mode, body.top_k
    )
    latency_ms = int((time.time() - t0) * 1000)

    trace_id = await run_in_threadpool(
        trace_rag,
        body.query,
        contexts,
        answer,
        model,
        latency_ms,
    )

    conv_id = str(uuid.uuid4())
    doc = {
        "id": conv_id,
        "query": body.query,
        "answer": answer,
        "contexts": contexts,
        "mode": body.mode,
        "latency_ms": max(latency_ms, 1),
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
        "latency_ms": max(latency_ms, 1),
        "trace_id": trace_id,
        "model": model,
    }


@api.get("/conversations")
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
):
    convs = (
        await db.conversations.find({}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(limit)
    )
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


@api.post("/evaluations/run", dependencies=[Depends(require_api_key)])
async def run_evaluation(body: EvalRunIn):
    t0 = time.time()
    n = min(body.limit, MAX_EVAL_SAMPLES)

    if body.scope == "testset":
        rows = []
        for item in TEST_SET[:n]:
            # Retrieve ONCE and reuse for both generation and scoring, so the
            # contexts RAGAS grades are exactly those the answer came from.
            contexts, answer, _ = await _retrieve_and_generate(
                item["question"], "hybrid", 5
            )
            rows.append(
                {"query": item["question"], "answer": answer, "contexts": contexts}
            )
    else:
        recent = (
            await db.conversations.find({}, {"_id": 0})
            .sort("created_at", -1)
            .to_list(n)
        )
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

    def _mean(key: str):
        vals = [r[key] for r in per_row if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    duration = int(time.time() - t0)
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    aggregate = {
        "scope": body.scope,
        "n_samples": len(per_row),
        "faithfulness": _mean("faithfulness"),
        "answer_relevancy": _mean("answer_relevancy"),
        "context_precision": _mean("context_precision"),
        "duration_s": duration,
    }

    # Stored flat so /api/evaluations can project summary columns cheaply.
    eval_doc = {
        "id": run_id,
        "created_at": now,
        **aggregate,
        "per_row": per_row,
    }
    await db.eval_runs.insert_one(eval_doc)

    # Responded nested under "aggregate" — the shape both UIs and the test suite
    # expect. (Previously the API returned these flat while every consumer read
    # res["aggregate"], so the dashboard never showed the run it just executed.)
    return {
        "id": run_id,
        "created_at": now,
        "scope": body.scope,
        "aggregate": aggregate,
        "per_row": per_row,
    }


@api.get("/evaluations")
async def list_evaluations(limit: int = Query(default=30, ge=1, le=MAX_PAGE_LIMIT)):
    runs = (
        await db.eval_runs.find({}, {"_id": 0, "per_row": 0})
        .sort("created_at", -1)
        .to_list(limit)
    )
    return {"runs": runs}


app.include_router(api)
