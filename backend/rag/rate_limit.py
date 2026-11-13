"""In-process sliding-window rate limiter for the public /query route.

Two windows guard every public request:

* per client — so one visitor can't monopolise the demo;
* global — the real backstop for the LLM quota. A client can dodge the
  per-client window by spoofing X-Forwarded-For or rotating IPs; it cannot
  dodge this one.

State lives in this process, which matches the deployment (one instance; BM25
is in-process too). Running several replicas would need a shared store such as
Redis.
"""
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, per_client: int, global_limit: int, window_s: float = 60.0,
                 max_clients: int = 10_000):
        self.per_client = per_client
        self.global_limit = global_limit
        self.window_s = window_s
        self.max_clients = max_clients
        self._clients: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] >= self.window_s:
            q.popleft()

    def check(self, client: str, now: float | None = None) -> float | None:
        """Record a request; return None if allowed, else seconds until retry.

        Not thread-safe by design: it is only called from the event loop.
        """
        now = time.monotonic() if now is None else now

        self._prune(self._global, now)
        if self.global_limit > 0 and len(self._global) >= self.global_limit:
            return self.window_s - (now - self._global[0])

        q = self._clients.get(client)
        if q is None:
            if len(self._clients) >= self.max_clients:
                self._evict(now)
            q = self._clients[client] = deque()
        self._prune(q, now)
        if self.per_client > 0 and len(q) >= self.per_client:
            return self.window_s - (now - q[0])

        q.append(now)
        self._global.append(now)
        return None

    def _evict(self, now: float) -> None:
        """Drop idle clients; if none are idle, drop the oldest half.

        Keeps memory bounded when many distinct (or spoofed) clients appear.
        """
        for key in [k for k, q in self._clients.items() if not q or now - q[-1] >= self.window_s]:
            del self._clients[key]
        if len(self._clients) >= self.max_clients:
            for key in list(self._clients)[: len(self._clients) // 2]:
                del self._clients[key]


def client_ip(forwarded_for: str | None, peer: str | None) -> str:
    """Best-effort client address behind a hosting proxy.

    The first X-Forwarded-For entry is the original client as reported to the
    proxy. It can be spoofed, which is why the limiter also has a global window.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return peer or "unknown"
