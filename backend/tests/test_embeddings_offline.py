"""Offline tests: one shared MiniLM instance for retrieval and RAGAS."""
import threading
import time

import numpy as np

from rag import llm_client


class FakeST:
    loads = 0

    def __init__(self, name):
        time.sleep(0.05)  # widen the race window
        FakeST.loads += 1

    def encode(self, texts, normalize_embeddings=True, batch_size=32):
        return np.ones((len(texts), 3))


def test_model_loaded_once_under_concurrency(monkeypatch):
    FakeST.loads = 0
    monkeypatch.setattr(llm_client, "SentenceTransformer", FakeST)
    monkeypatch.setattr(llm_client, "_st_instance", None)
    threads = [threading.Thread(target=llm_client.embed_text, args=("q",)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert FakeST.loads == 1


def test_ragas_embeddings_share_the_retrieval_model(monkeypatch):
    FakeST.loads = 0
    monkeypatch.setattr(llm_client, "SentenceTransformer", FakeST)
    monkeypatch.setattr(llm_client, "_st_instance", None)
    emb = llm_client.get_embeddings()
    assert emb.embed_query("q") == [1.0, 1.0, 1.0]
    assert emb.embed_documents(["a", "b"]) == [[1.0] * 3, [1.0] * 3]
    llm_client.embed_texts(["c"])
    assert FakeST.loads == 1
