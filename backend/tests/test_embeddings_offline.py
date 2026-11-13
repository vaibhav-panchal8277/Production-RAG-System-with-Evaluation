"""Offline tests: one shared MiniLM instance for retrieval and RAGAS."""
import threading
import time

import numpy as np
import pytest

from rag import llm_client


class FakeEmbedder:
    loads = 0

    def __init__(self, name, cache_dir=None):
        time.sleep(0.05)  # widen the race window
        FakeEmbedder.loads += 1

    def embed(self, texts, batch_size=32):
        # Not unit length: embed_* must normalize for the cosine index.
        return (np.full(3, 2.0) for _ in texts)


def test_model_loaded_once_under_concurrency(monkeypatch):
    FakeEmbedder.loads = 0
    monkeypatch.setattr(llm_client, "TextEmbedding", FakeEmbedder)
    monkeypatch.setattr(llm_client, "_embed_instance", None)
    threads = [threading.Thread(target=llm_client.embed_text, args=("q",)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert FakeEmbedder.loads == 1


def test_ragas_embeddings_share_the_retrieval_model(monkeypatch):
    FakeEmbedder.loads = 0
    monkeypatch.setattr(llm_client, "TextEmbedding", FakeEmbedder)
    monkeypatch.setattr(llm_client, "_embed_instance", None)
    emb = llm_client.get_embeddings()
    unit = [pytest.approx(3 ** -0.5)] * 3
    assert emb.embed_query("q") == unit
    assert emb.embed_documents(["a", "b"]) == [unit, unit]
    assert llm_client.embed_texts([]) == []
    llm_client.embed_texts(["c"])
    assert FakeEmbedder.loads == 1
