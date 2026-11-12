"""Offline tests for BM25 tokenisation and keyword retrieval."""
from rag import vector_store as vs


def test_tokenize_strips_surrounding_punctuation():
    assert vs._tokenize("Is remote work allowed?") == ["is", "remote", "work", "allowed"]
    assert vs._tokenize("(policy), \"quoted\"; end.") == ["policy", "quoted", "end"]


def test_tokenize_keeps_codes_and_their_parts():
    toks = vs._tokenize("Sign Form HR-RW-01 for the Widget-3000 at 10:00.")
    for t in ("hr-rw-01", "hr", "rw", "01", "widget-3000", "widget", "3000", "10:00"):
        assert t in toks, t
    assert "10:00." not in toks


def _corpus():
    return [
        {"id": "1", "text": "Remote work requires six months of tenure.", "metadata": {"source": "remote.md"}},
        {"id": "2", "text": "Reset the Widget-3000 by holding the button.", "metadata": {"source": "widget.md"}},
        {"id": "3", "text": "Retention of confidential data is seven years.", "metadata": {"source": "data.md"}},
    ]


def test_question_mark_query_matches():
    vs.rebuild_bm25(_corpus())
    try:
        hits = vs.bm25_search("Who is eligible for remote work?", top_k=1)
        assert hits and hits[0]["source"] == "remote.md"
    finally:
        vs.rebuild_bm25([])


def test_code_matches_with_and_without_hyphen():
    vs.rebuild_bm25(_corpus())
    try:
        for q in ("How do I reset a Widget-3000?", "widget 3000 reset"):
            hits = vs.bm25_search(q, top_k=1)
            assert hits and hits[0]["source"] == "widget.md", q
    finally:
        vs.rebuild_bm25([])
