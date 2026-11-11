"""Per-client-IP limit on FAILED sign-ins (sliding window), in addition to the per-account lockout.

In-memory, so it applies per server process: run a single worker (the Docker image does). Behind a trusted edge proxy
set UIAD_CLIENT_IP_HEADERS so the real client address is used (see client_ip).
"""
from __future__ import annotations

import threading
import time
from collections import deque


class FailedLoginLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 50_000):
        self.limit, self.window, self.max_keys = limit, window_seconds, max_keys
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque | None:
        q = self._hits.get(key)
        if q is None:
            return None
        while q and q[0] <= now - self.window:
            q.popleft()
        if not q:
            del self._hits[key]
            return None
        return q

    def retry_after(self, key: str | None) -> int:
        """Seconds until another attempt is allowed; 0 if not blocked."""
        if not key or self.limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if q is None or len(q) < self.limit:
                return 0
            return max(1, int(q[0] + self.window - now) + 1)

    def record_failure(self, key: str | None) -> None:
        if not key or self.limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            if key not in self._hits and len(self._hits) >= self.max_keys:     # bound memory: drop expired keys first
                for k in list(self._hits):
                    self._prune(k, now)
                if len(self._hits) >= self.max_keys:
                    self._hits.pop(next(iter(self._hits)))
            self._hits.setdefault(key, deque()).append(now)


def client_ip(request) -> str | None:
    """Client address for rate limiting and auditing: a configured trusted edge header, else the socket peer."""
    from .config import get_settings
    for h in get_settings().client_ip_headers:
        v = (request.headers.get(h) or "").split(",")[0].strip()
        if v:
            return v[:64]
    return request.client.host if request.client else None


_limiter: FailedLoginLimiter | None = None


def login_limiter() -> FailedLoginLimiter:
    global _limiter
    if _limiter is None:
        from .config import get_settings
        s = get_settings()
        _limiter = FailedLoginLimiter(s.login_rate_limit, s.login_rate_window_minutes * 60)
    return _limiter


def reset_login_limiter():                          # tests
    global _limiter
    _limiter = None
