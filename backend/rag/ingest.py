"""Document ingestion: parse -> chunk -> embed -> upsert -> rebuild BM25."""
import io
from datetime import datetime, timezone
from typing import Optional
from pypdf import PdfReader

from rag.chunker import split_text
from rag.vector_store import (
    upsert_chunks,
    delete_by_ids,
    rebuild_bm25,
    make_chunk_id,
)


def parse_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            parts.append(t)
    return "\n\n".join(parts)


def parse_markdown(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="ignore")


async def ingest_document(
    db,
    source: str,
    content_bytes: bytes,
    content_type: str,
    title: Optional[str] = None,
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
                    "chunk_index": i,
                    "section": section,
                    "kind": kind,
                },
            }
        )

    # Store in Mongo (for BM25 corpus + traceability)
    existing_ids = [d["_id"] async for d in db.chunks.find({"source": source}, {"_id": 1})]
    await db.chunks.delete_many({"source": source})
    docs = [
        {
            "_id": c["id"],
            "source": source,
            "chunk_index": c["metadata"]["chunk_index"],
            "section": c["metadata"]["section"],
            "text": c["text"],
            "kind": kind,
        }
        for c in chunk_records
    ]
    if docs:
        await db.chunks.insert_many(docs)

    # Push to Pinecone
    delete_by_ids(existing_ids)
    upsert_chunks(chunk_records)

    # Track document
    await db.documents.update_one(
        {"source": source},
        {
            "$set": {
                "source": source,
                "title": title or source,
                "kind": kind,
                "n_chunks": len(chunk_records),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )

    # Rebuild BM25 index from all chunks
    await rebuild_bm25_from_db(db)

    return {"source": source, "n_chunks": len(chunk_records), "kind": kind}


async def rebuild_bm25_from_db(db):
    cursor = db.chunks.find({}, {"_id": 1, "text": 1})
    records = [{"id": d["_id"], "text": d["text"]} async for d in cursor]
    rebuild_bm25(records)


def _guess_section(chunk: str) -> str:
    for line in chunk.split("\n")[:3]:
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()[:80]
    return ""
