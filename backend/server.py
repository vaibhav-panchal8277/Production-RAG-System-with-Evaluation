"""FastAPI backend for RAG Evaluation System."""
import asyncio
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from rag.evaluator import ALL_METRICS, evaluate_conversations
from rag.generator import NO_CONTEXT_ANSWER, generate_answer
from rag.guardrails import check_input, guardrails_status
from rag.ingest import delete_document as remove_document
from rag.ingest import ingest_document, rebuild_bm25_from_db
from rag.llm_client import LLM_MODEL, provider_info
from rag.observability import score_eval_rows, shutdown_tracing, trace_rag
from rag.rate_limit import SlidingWindowLimiter, client_ip
from rag.vector_store import (
    VectorStoreError,
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
# Test-set questions answered concurrently during an evaluation run.
EVAL_CONCURRENCY = max(1, int(os.environ.get("EVAL_CONCURRENCY", "4")))
UPLOAD_CHUNK = 1024 * 1024


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


# Public demo mode: /query is open to anyone (rate limited) while every other
# protected route still needs X-API-Key. Conversation history stays private
# because it holds every visitor's questions.
PUBLIC_QUERY = _env_flag("PUBLIC_QUERY")
QUERY_RATE_PER_MIN = int(os.environ.get("QUERY_RATE_PER_MIN", "10"))
QUERY_GLOBAL_RATE_PER_MIN = int(os.environ.get("QUERY_GLOBAL_RATE_PER_MIN", "25"))
_query_limiter = SlidingWindowLimiter(QUERY_RATE_PER_MIN, QUERY_GLOBAL_RATE_PER_MIN)

_RAW_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").strip()
CORS_ORIGINS = [o.strip() for o in _RAW_ORIGINS.split(",") if o.strip()]
# A wildcard origin cannot be combined with credentialed requests (the browser
# rejects it), so only allow credentials when explicit origins are configured.
ALLOW_WILDCARD = "*" in CORS_ORIGINS
ALLOW_CREDENTIALS = not ALLOW_WILDCARD


async def require_api_key(x_api_key: str | None = Header(default=None)):
    """Guard mutating, expensive or private endpoints.

    That is: upload/seed/delete, evaluations, /query (spends LLM quota) and
    /conversations (holds every user's questions and answers).

    When RAG_API_KEY is unset the dependency is a no-op so local development and
    the existing test suite keep working; startup logs a prominent warning in
    that case. Set RAG_API_KEY before exposing this service to a network.
    """
    if not API_KEY:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _has_valid_key(x_api_key: str | None) -> bool:
    return bool(API_KEY and x_api_key and secrets.compare_digest(x_api_key, API_KEY))


async def query_access(request: Request, x_api_key: str | None = Header(default=None)):
    """Who may call /query.

    Normally the same as require_api_key. With PUBLIC_QUERY on, anyone may, but
    requests without a valid key are rate limited (per client and globally) so
    a public demo can't drain the Groq quota.
    """
    if not PUBLIC_QUERY:
        await require_api_key(x_api_key)
        return
    if _has_valid_key(x_api_key):
        return
    client = client_ip(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client else None,
    )
    retry_after = _query_limiter.check(client)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many questions right now; please wait a moment and try again.",
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )


# ---------- lifespan ----------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    if PUBLIC_QUERY and not API_KEY:
        logger.warning(
            "PUBLIC_QUERY is on but RAG_API_KEY is not set, so upload/delete/eval are "
            "open too. Set RAG_API_KEY for a public deployment."
        )
    if not API_KEY:
        logger.warning(
            "RAG_API_KEY is not set — upload/seed/delete, evaluations, query and "
            "conversation history are UNAUTHENTICATED. Set RAG_API_KEY before exposing "
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

    try:
        # Background eval jobs live in this process; any still open from a
        # previous run will never finish.
        await db.eval_jobs.update_many(
            {"status": {"$in": ["queued", "running"]}},
            {"$set": {"status": "failed", "error": "Interrupted by a server restart"}},
        )
    except PyMongoError as e:
        logger.warning("Could not close out stale eval jobs: %s", e)

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
    await db.eval_runs.create_index("id")
    await db.eval_jobs.create_index("id", unique=True)


app = FastAPI(title="RAG Evaluation System", lifespan=lifespan)
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    # Lets the UI read how long to wait after a 429.
    expose_headers=["Retry-After"],
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
    background: bool = False


# Aggregate name -> per-row metric key it averages.
_AGGREGATES = {
    "faithfulness": "faithfulness",
    "answer_relevancy": "answer_relevancy",
    "context_precision": "context_precision",
    "answer_correctness": "answer_correctness",
    "context_recall": "context_recall",
    "retrieval_hit_rate": "retrieval_hit",
    "retrieval_mrr": "reciprocal_rank",
    "refusal_accuracy": "refusal_correct",
}


# ---------- helpers ----------
def _retrieve(query: str, mode: str, top_k: int) -> list[dict]:
    if mode == "dense":
        return dense_search(query, top_k=top_k)
    if mode == "keyword":
        return bm25_search(query, top_k=top_k)
    return hybrid_search(query, top_k=top_k)


class RagResult(NamedTuple):
    contexts: list[dict]
    answer: str
    model: str
    guardrail: str  # "allowed", or the reason the input rails blocked it


async def _retrieve_and_generate(query: str, mode: str, top_k: int) -> RagResult:
    """Check the input rails, retrieve once, then generate from those contexts.

    Rails run first so a blocked query (greeting, injection attempt, oversized
    input) costs no embedding, Pinecone or BM25 work and returns no retrieved
    chunks. All steps are synchronous (NeMo, when enabled, is network-bound), so
    they run in worker threads to avoid blocking the event loop.
    """
    decision = await run_in_threadpool(check_input, query)
    if decision.blocked:
        logger.info("Guardrail blocked query (%s)", decision.reason)
        return RagResult([], decision.message or NO_CONTEXT_ANSWER, LLM_MODEL, decision.reason)

    contexts = await run_in_threadpool(_retrieve, query, mode, top_k)
    answer, model = await run_in_threadpool(generate_answer, query, contexts)
    return RagResult(contexts, answer, model, decision.reason)


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
        "public_query": PUBLIC_QUERY,
        "query_rate_per_min": QUERY_RATE_PER_MIN if PUBLIC_QUERY else None,
    }


# ----- documents -----
@api.get("/documents")
async def list_documents():
    docs = await db.documents.find({}, {"_id": 0}).sort("source", 1).to_list(500)
    return {"documents": docs}


@api.post("/documents/upload", dependencies=[Depends(require_api_key)])
async def upload_document(file: UploadFile = File(...)):  # noqa: B008
    if not file.filename:
        raise HTTPException(400, "Uploaded file has no filename")
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
    try:
        return await remove_document(db, source)
    except VectorStoreError as e:
        # Nothing was removed, so the caller can simply retry.
        logger.warning("Delete of %s aborted: %s", source, e)
        raise HTTPException(
            503, "Vector store unavailable; nothing was deleted. Please retry."
        ) from e


# ----- query / RAG -----
@api.post("/query", dependencies=[Depends(query_access)])
async def query(body: QueryIn):
    t0 = time.time()
    contexts, answer, model, guardrail = await _retrieve_and_generate(
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
        "guardrail": guardrail,
        "created_at": datetime.now(UTC).isoformat(),
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
        "guardrail": guardrail,
    }


@api.get("/conversations", dependencies=[Depends(require_api_key)])
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
):
    convs = (
        await db.conversations.find({}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(limit)
    )
    return {"conversations": convs}


@api.get("/conversations/{conv_id}", dependencies=[Depends(require_api_key)])
async def get_conversation(conv_id: str):
    conv = await db.conversations.find_one({"id": conv_id}, {"_id": 0})
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


# ----- evaluations -----
@api.get("/testset")
async def get_testset():
    return {"testset": TEST_SET}


async def _testset_row(item: dict, limiter: asyncio.Semaphore) -> dict:
    """Answer one golden question exactly as a live query would be answered."""
    async with limiter:
        t0 = time.time()
        # Retrieve ONCE and reuse for both generation and scoring, so the
        # contexts RAGAS grades are exactly those the answer came from.
        contexts, answer, model, _ = await _retrieve_and_generate(
            item["question"], "hybrid", 5
        )
        # Traced like a live query so eval scores can be attached to it.
        trace_id = await run_in_threadpool(
            trace_rag,
            item["question"],
            contexts,
            answer,
            model,
            int((time.time() - t0) * 1000),
            "rag-eval-testset",
        )
    return {
        "query": item["question"],
        "answer": answer,
        "contexts": contexts,
        "trace_id": trace_id,
        # Golden labels: enable reference-based RAGAS metrics, retrieval
        # hit-rate/MRR and refusal scoring.
        "reference": item["reference"],
        "expected_source": item["expected_source"],
    }


async def _recent_rows(n: int) -> list[dict]:
    # Guardrail-blocked queries got a canned reply, not a RAG answer, so
    # scoring them would only measure the canned text. (None also matches
    # conversations stored before the field existed.)
    recent = (
        await db.conversations.find({"guardrail": {"$in": ["allowed", None]}}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(n)
    )
    if not recent:
        raise HTTPException(400, "No recent conversations found to evaluate")
    return [
        {
            "query": c["query"],
            "answer": c["answer"],
            "contexts": c.get("contexts", []),
            "trace_id": c.get("trace_id"),
        }
        for c in recent
    ]


async def _execute_eval(scope: str, limit: int) -> dict:
    """Build rows, score them, persist the run; returns the API response shape."""
    t0 = time.time()
    n = min(limit, MAX_EVAL_SAMPLES)

    if scope == "testset":
        # Bounded fan-out: sequential generation made a 45-question run take
        # many minutes; unbounded would trip provider rate limits.
        limiter = asyncio.Semaphore(EVAL_CONCURRENCY)
        rows = await asyncio.gather(*(_testset_row(item, limiter) for item in TEST_SET[:n]))
    else:
        rows = await _recent_rows(n)

    per_row = await evaluate_conversations(list(rows))

    def _mean(key: str):
        vals = [r[key] for r in per_row if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    # Means skip None, so each aggregate covers only the rows it applies to
    # (e.g. refusal_accuracy is over out-of-scope questions only).
    aggregate = {
        "scope": scope,
        "n_samples": len(per_row),
        **{name: _mean(key) for name, key in _AGGREGATES.items()},
        "duration_s": int(time.time() - t0),
    }

    # Stored flat so /api/evaluations can project summary columns cheaply.
    await db.eval_runs.insert_one(
        {"id": run_id, "created_at": now, **aggregate, "per_row": per_row}
    )
    await run_in_threadpool(score_eval_rows, per_row, ALL_METRICS, run_id)

    # Metrics are nested under "aggregate" — the shape both UIs and the tests read.
    return {
        "id": run_id,
        "created_at": now,
        "scope": scope,
        "aggregate": aggregate,
        "per_row": per_row,
    }


# One evaluation at a time: a full run makes hundreds of judge calls, and two
# in parallel mostly just trip the provider's rate limits.
_eval_slot = asyncio.Semaphore(1)
# Strong references so running job tasks aren't garbage-collected mid-flight.
_eval_tasks: set[asyncio.Task] = set()


async def _run_eval_job(job_id: str, scope: str, limit: int) -> None:
    def _now():
        return datetime.now(UTC).isoformat()

    async with _eval_slot:
        await db.eval_jobs.update_one(
            {"id": job_id}, {"$set": {"status": "running", "started_at": _now()}}
        )
        try:
            result = await _execute_eval(scope, limit)
        except HTTPException as e:
            update = {"status": "failed", "error": str(e.detail)}
        except Exception:
            logger.exception("Evaluation job %s failed", job_id)
            update = {"status": "failed", "error": "Evaluation failed due to a server error"}
        else:
            update = {"status": "done", "run_id": result["id"]}
        await db.eval_jobs.update_one({"id": job_id}, {"$set": {**update, "finished_at": _now()}})


@api.post("/evaluations/run", dependencies=[Depends(require_api_key)])
async def run_evaluation(body: EvalRunIn, response: Response):
    """Run an evaluation.

    By default the request blocks until the run finishes. With
    `background: true` it returns 202 and a job id at once; poll
    `GET /evaluations/jobs/{job_id}` — a full test-set run can take longer than
    proxies and browsers will hold a request open.
    """
    if not body.background:
        async with _eval_slot:
            return await _execute_eval(body.scope, body.limit)

    job_id = str(uuid.uuid4())
    await db.eval_jobs.insert_one(
        {
            "id": job_id,
            "status": "queued",
            "scope": body.scope,
            "limit": body.limit,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    task = asyncio.create_task(_run_eval_job(job_id, body.scope, body.limit))
    _eval_tasks.add(task)
    task.add_done_callback(_eval_tasks.discard)
    response.status_code = 202
    return {"job_id": job_id, "status": "queued"}


@api.get("/evaluations/jobs/{job_id}", dependencies=[Depends(require_api_key)])
async def get_eval_job(job_id: str):
    """Job status; once done, `result` has the same shape as a blocking run."""
    job = await db.eval_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Evaluation job not found")
    if job["status"] == "done":
        run = await db.eval_runs.find_one({"id": job["run_id"]}, {"_id": 0})
        if run:
            per_row = run.pop("per_row", [])
            run_id, created_at = run.pop("id"), run.pop("created_at")
            job["result"] = {
                "id": run_id,
                "created_at": created_at,
                "scope": run.get("scope"),
                "aggregate": run,
                "per_row": per_row,
            }
    return job


@api.get("/evaluations")
async def list_evaluations(limit: int = Query(default=30, ge=1, le=MAX_PAGE_LIMIT)):
    runs = (
        await db.eval_runs.find({}, {"_id": 0, "per_row": 0})
        .sort("created_at", -1)
        .to_list(limit)
    )
    return {"runs": runs}


app.include_router(api)
