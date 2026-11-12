"""Deterministic vector IDs, grouped by source under a common ID prefix.

IDs used to carry a random suffix, so the only record of which vectors belonged
to a document lived in Mongo. Whenever Mongo and Pinecone diverged (fresh CI
database, reset Docker volume, a shared index) re-seeding wrote a second full
copy of every chunk, and dense search returned near-identical duplicates.

Now an ID is `<source-key>#<chunk index>`:

* re-ingesting a document overwrites its vectors in place (idempotent), and
* every vector of a document can be found from Pinecone alone by listing the
  `<source-key>#` prefix (Pinecone's recommended pattern for serverless).

The source key is a hash so IDs stay ASCII and bounded in length for any
filename (Pinecone rejects non-ASCII IDs). The real source name lives in the
vector metadata.
"""
import hashlib


def source_id_prefix(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16] + "#"


def make_chunk_id(source: str, chunk_idx: int) -> str:
    return f"{source_id_prefix(source)}{chunk_idx}"


def legacy_id_prefix(source: str) -> str | None:
    """Prefix of IDs written before they were deterministic (`<source>::<n>::<hex>`).

    Used to clean those vectors up on the next re-ingest or delete. Non-ASCII
    sources could never have been written under the old scheme.
    """
    return f"{source}::" if source.isascii() else None
