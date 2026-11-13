"""Offline tests: the sliding-window limiter behind public /query."""
from rag.rate_limit import SlidingWindowLimiter, client_ip


def test_window_slides():
    lim = SlidingWindowLimiter(per_client=2, global_limit=0, window_s=60)
    assert lim.check("a", now=0) is None
    assert lim.check("a", now=10) is None
    assert lim.check("a", now=20) == 40  # oldest request (t=0) frees up at t=60
    assert lim.check("a", now=60) is None


def test_rejected_requests_do_not_count():
    lim = SlidingWindowLimiter(per_client=1, global_limit=0, window_s=60)
    assert lim.check("a", now=0) is None
    for t in range(1, 50):
        assert lim.check("a", now=t) is not None
    assert lim.check("a", now=60) is None


def test_global_limit_applies_across_clients():
    lim = SlidingWindowLimiter(per_client=10, global_limit=2, window_s=60)
    assert lim.check("a", now=0) is None
    assert lim.check("b", now=1) is None
    assert lim.check("c", now=2) is not None


def test_client_table_is_bounded():
    lim = SlidingWindowLimiter(per_client=1, global_limit=0, window_s=60, max_clients=100)
    for i in range(1000):
        lim.check(f"ip{i}", now=i * 0.001)
    assert len(lim._clients) <= 100


def test_client_ip_prefers_first_forwarded_entry():
    assert client_ip("203.0.113.9, 10.0.0.1", "10.0.0.2") == "203.0.113.9"
    assert client_ip(None, "10.0.0.2") == "10.0.0.2"
    assert client_ip(" , ", None) == "unknown"
