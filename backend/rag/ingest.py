"""Document ingestion: parse -> chunk -> embed -> upsert -> rebuild BM25.

Everything CPU- or network-bound here (PDF parsing, chunking, local embedding,
Pinecone calls, BM25 rebuild) runs in a worker thread. These coroutines run on
the server's event loop, and with a single uvicorn worker a blocking call there
stalls every other request — one large upload used to freeze /query for its
whole duration.

All corpus mutations (ingest, delete) are serialised by `corpus_lock`. Once the
blocking work yields the event loop, two ingests could otherwise interleave:
two uploads of the same file would race on delete-then-insert, and a slower
BM25 rebuild from an older Mongo snapshot could overwrite a newer one.
"""
import asyncio
import io
import logging
from datetime import UTC, datetime

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from rag.chunk_ids import make_chunk_id
from rag.chunker import split_text
from rag.guardrails import looks_like_injection
from rag.vector_store import (
    VectorStoreError,
    delete_source_vectors,
    rebuild_bm25,
    upsert_chunks,
)

logger = logging.getLogger(__name__)

# Ingest is rare and heavy; one global lock keeps it simple and correct.
corpus_lock = asyncio.Lock()

# Mongo cursor page size. Previously these were hard `.to_list(2000)` /
# `.to_list(10000)` caps that silently dropped data: chunks beyond the cap were
# orphaned in Pinecone on re-ingest, and corpora over 10k chunks were partially
# missing from the BM25 index (making those documents keyword-unsearchable).
_PAGE = 1000


def parse_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except (PdfReadError, AttributeError, TypeError, ValueError) as e:
            logger.warning("PDF page %d text extraction failed: %s", i, e)
            t = ""
        if t.strip():
            parts.append(t)
    return "\n\n".join(parts)


def parse_markdown(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="ignore")


def _guess_section(chunk_text: str) -> str:
    lines = [l.strip() for l in chunk_text.split("\n") if l.strip()]
    for l in lines:
        if l.startswith("#") or (len(l) < 60 and not l.endswith(".")):
            return l.lstrip("#").strip()
    return "General"


async def _all_chunk_ids(db, source: str) -> list[str]:
    """Page through every existing chunk id for a source (no silent cap)."""
    ids: list[str] = []
    cursor = db.chunks.find({"source": source}, {"_id": 0, "id": 1})
    while True:
        batch = await cursor.to_list(_PAGE)
        if not batch:
            break
        ids.extend(c["id"] for c in batch if c.get("id"))
        if len(batch) < _PAGE:
            break
    return ids


async def ingest_document(
    db,
    source: str,
    content_bytes: bytes,
    content_type: str,
    title: str | None = None,
) -> dict:
    async with corpus_lock:
        return await _ingest_locked(db, source, content_bytes, content_type, title)


async def _ingest_locked(
    db,
    source: str,
    content_bytes: bytes,
    content_type: str,
    title: str | None,
) -> dict:
    if content_type == "application/pdf" or source.lower().endswith(".pdf"):
        text = await asyncio.to_thread(parse_pdf, content_bytes)
        kind = "pdf"
    else:
        text = parse_markdown(content_bytes)
        kind = "markdown"

    if not text.strip():
        raise ValueError("No extractable text in document")

    chunks_text = await asyncio.to_thread(split_text, text)
    if not chunks_text:
        raise ValueError("Document produced no usable chunks")

    chunk_records = []
    for i, ch in enumerate(chunks_text):
        chunk_records.append(
            {
                "id": make_chunk_id(source, i),
                "text": ch,
                "metadata": {
                    "source": source,
                    "title": title or source,
                    "section": _guess_section(ch),
                    "kind": kind,
                    "injection_suspect": looks_like_injection(ch),
                },
            }
        )

    # --- replace any previous version of this source ---------------------------
    # Ordering matters: drop old vectors first, then old Mongo rows, then write
    # the new ones. Chunk IDs are deterministic, so even if the vector delete
    # fails the upsert below overwrites the old vectors in place; only a tail of
    # extra chunks from a longer previous version could linger, and the next
    # delete/re-ingest finds those by ID prefix.
    old_ids = await _all_chunk_ids(db, source)
    if not await asyncio.to_thread(delete_source_vectors, source, old_ids):
        logger.warning(
            "Could not delete old vectors for %s; leftovers beyond the new chunk "
            "count may remain until the next successful delete.",
            source,
        )
    await db.chunks.delete_many({"source": source})

    # --- write new chunks -----------------------------------------------------
    upsert_result = await asyncio.to_thread(upsert_chunks, chunk_records)

    db_records = [
        {
            "id": c["id"],
            "source": source,
            "text": c["text"],
            "metadata": c["metadata"],
        }
        for c in chunk_records
    ]
    if db_records:
        await db.chunks.insert_many(db_records)

    now = datetime.now(UTC).isoformat()
    await db.documents.update_one(
        {"source": source},
        {
            "$set": {
                "source": source,
                "title": title or source,
                "kind": kind,
                "n_chunks": len(chunk_records),
                "updated_at": now,
                "dense_indexed": upsert_result.get("upserted", 0),
            }
        },
        upsert=True,
    )

    await rebuild_bm25_from_db(db)

    result = {
        "source": source,
        "title": title or source,
        "kind": kind,
        "n_chunks": len(chunk_records),
    }
    warnings = []
    suspect = sum(1 for c in chunk_records if c["metadata"]["injection_suspect"])
    if suspect:
        logger.warning("%s: %d chunk(s) contain instruction-like text", source, suspect)
        warnings.append(
            f"{suspect} chunk(s) contain instruction-like text (possible prompt "
            "injection); they are marked as untrusted when used as context."
        )
    # Surface degraded dense retrieval instead of pretending everything worked.
    if not upsert_result.get("available", True):
        warnings.append(
            "Vector store unavailable — this document is keyword-searchable only."
        )
    elif upsert_result.get("failed"):
        warnings.append(
            f"{upsert_result['failed']} of {len(chunk_records)} chunks failed to "
            f"index for dense search ({upsert_result.get('error')})."
        )
    if warnings:
        result["warning"] = " ".join(warnings)
    return result


async def delete_document(db, source: str) -> dict:
    """Remove a document's vectors, chunks and record, then rebuild BM25.

    Vectors go first, and if that fails nothing else is touched: deleting the
    Mongo chunks anyway (as before) destroyed the only record of the orphaned
    vector IDs, leaving the "deleted" document in dense search permanently.
    Raises VectorStoreError so the caller can report a retryable failure.
    """
    async with corpus_lock:
        known_ids = await _all_chunk_ids(db, source)
        if not await asyncio.to_thread(delete_source_vectors, source, known_ids):
            raise VectorStoreError(
                f"Could not delete vectors for {source!r}; nothing was removed."
            )
        await db.chunks.delete_many({"source": source})
        result = await db.documents.delete_one({"source": source})
        await rebuild_bm25_from_db(db)
        return {"deleted": result.deleted_count, "source": source}


async def rebuild_bm25_from_db(db):
    """Rebuild the in-process BM25 index from every chunk in Mongo.

    Callers that mutate the corpus must hold `corpus_lock` (startup, which runs
    before any request, need not).
    """
    records: list[dict] = []
    cursor = db.chunks.find({}, {"_id": 0, "id": 1, "text": 1, "metadata": 1})
    while True:
        batch = await cursor.to_list(_PAGE)
        if not batch:
            break
        records.extend(batch)
        if len(batch) < _PAGE:
            break
    await asyncio.to_thread(rebuild_bm25, records)
    return len(records)
