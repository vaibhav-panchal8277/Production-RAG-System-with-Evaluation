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


def parse_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except (PdfReadError, AttributeError, TypeError) as e:
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

    # Detect sections from markdown headings for better metadata
    chunks_text = split_text(text)
    chunk_records = []
    for i, ch in enumerate(chunks_text):
        section = _guess_section(ch)
        cid = make_chunk_id(source, i)
        chunk_records.append(
            {
                "id": cid,
                "text": ch,
                "metadata": {
                    "source": source,
                    "title": title or source,
                    "section": section,
                    "kind": kind,
                },
            }
        )

    # Remove old chunks for this source if any
    old_chunks = await db.chunks.find({"source": source}, {"id": 1}).to_list(2000)
    if old_chunks:
        old_ids = [c["id"] for c in old_chunks]
        delete_by_ids(old_ids)
        await db.chunks.delete_many({"source": source})

    # Upsert new chunks to vector store
    upsert_chunks(chunk_records)

    # Save to MongoDB chunks
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

    # Upsert document summary
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
            }
        },
        upsert=True,
    )

    # Rebuild BM25 index from all documents in db
    await rebuild_bm25_from_db(db)

    return {
        "source": source,
        "title": title or source,
        "kind": kind,
        "n_chunks": len(chunk_records),
    }


async def rebuild_bm25_from_db(db):
    all_chunks = await db.chunks.find({}, {"_id": 0, "id": 1, "text": 1}).to_list(10000)
    rebuild_bm25(all_chunks)
