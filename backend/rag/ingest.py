"""Document ingestion: parse -> chunk -> embed -> upsert -> rebuild BM25."""
import io
import logging
from datetime import datetime, timezone

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from rag.chunker import split_text
from rag.vector_store import (
    delete_by_ids,
    make_chunk_id,
    rebuild_bm25,
    upsert_chunks,
)

logger = logging.getLogger(__name__)

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
    if content_type == "application/pdf" or source.lower().endswith(".pdf"):
        text = parse_pdf(content_bytes)
        kind = "pdf"
    else:
        text = parse_markdown(content_bytes)
        kind = "markdown"

    if not text.strip():
        raise ValueError("No extractable text in document")

    chunks_text = split_text(text)
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
                },
            }
        )

    # --- replace any previous version of this source ---------------------------
    # Ordering matters: drop old vectors first, then old Mongo rows, then write
    # the new ones. A failure mid-way leaves the source re-ingestable (idempotent
    # by design) rather than half-visible.
    old_ids = await _all_chunk_ids(db, source)
    if old_ids:
        if not delete_by_ids(old_ids):
            logger.warning(
                "Could not delete %d old vectors for %s; stale vectors may remain "
                "in Pinecone until the next successful delete.",
                len(old_ids),
                source,
            )
        await db.chunks.delete_many({"source": source})

    # --- write new chunks -----------------------------------------------------
    upsert_result = upsert_chunks(chunk_records)

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

    now = datetime.now(timezone.utc).isoformat()
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
    # Surface degraded dense retrieval instead of pretending everything worked.
    if not upsert_result.get("available", True):
        result["warning"] = (
            "Vector store unavailable — this document is keyword-searchable only."
        )
    elif upsert_result.get("failed"):
        result["warning"] = (
            f"{upsert_result['failed']} of {len(chunk_records)} chunks failed to "
            f"index for dense search ({upsert_result.get('error')})."
        )
    return result


async def rebuild_bm25_from_db(db):
    """Rebuild the in-process BM25 index from every chunk in Mongo."""
    records: list[dict] = []
    cursor = db.chunks.find({}, {"_id": 0, "id": 1, "text": 1, "metadata": 1})
    while True:
        batch = await cursor.to_list(_PAGE)
        if not batch:
            break
        records.extend(batch)
        if len(batch) < _PAGE:
            break
    rebuild_bm25(records)
    return len(records)
