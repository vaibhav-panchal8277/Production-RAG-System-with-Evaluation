"""Shared fixtures for the offline and integration suites."""
import os

import pytest
import requests

# Offline tests import backend modules that read these at import time. Setting
# them here, before anything imports `server`, also matters because server.py
# calls load_dotenv(backend/.env), which never overrides a variable that is
# already set. Without this, a developer's real .env leaked into the "offline"
# run: live Groq/Pinecone/Langfuse keys, and REACT_APP_BACKEND_URL, which
# switched the integration suite on mid-run. Values exported in the shell (as CI
# does for the integration run) still win, because setdefault keeps them.
for _name, _value in {
    "GROQ_API_KEY": "test-dummy",
    "PINECONE_API_KEY": "",
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
    "RAG_API_KEY": "",
    "REACT_APP_BACKEND_URL": "",
    "MONGO_URL": "mongodb://127.0.0.1:1",
    "DB_NAME": "rag_eval_test",
}.items():
    os.environ.setdefault(_name, _value)


def backend_url() -> str | None:
    url = (os.environ.get("REACT_APP_BACKEND_URL") or "").strip()
    return url.rstrip("/") or None


def api_headers() -> dict:
    # Mutating routes require X-API-Key only when the server has RAG_API_KEY set.
    key = (os.environ.get("RAG_API_KEY") or "").strip()
    return {"X-API-Key": key} if key else {}


@pytest.fixture
def fake_db():
    from tests.fakes import FakeDB

    return FakeDB()


@pytest.fixture
def fake_index(monkeypatch):
    """Point the vector store at an in-memory index with dummy embeddings."""
    from rag import vector_store
    from tests.fakes import FakeIndex

    index = FakeIndex()
    monkeypatch.setattr(vector_store, "_pc", object())
    monkeypatch.setattr(vector_store, "_index", index)
    monkeypatch.setattr(vector_store, "embed_texts", lambda texts: [[0.0] * 3 for _ in texts])
    monkeypatch.setattr(vector_store, "embed_text", lambda text: [0.0] * 3)
    vector_store.rebuild_bm25([])
    yield index
    vector_store.rebuild_bm25([])


@pytest.fixture(scope="session")
def seeded_corpus():
    """Seed the bundled corpus once, before any integration test needs it.

    Tests used to rely on TestDocuments running first. Ingest is idempotent
    (deterministic chunk IDs), so re-seeding an already-seeded backend is safe.
    """
    url = backend_url()
    if not url:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    r = requests.post(f"{url}/api/documents/seed", headers=api_headers(), timeout=300)
    assert r.status_code == 200, f"seed failed: {r.status_code} {r.text}"
    errors = [d for d in r.json()["ingested"] if "error" in d]
    assert not errors, f"seed errors: {errors}"
