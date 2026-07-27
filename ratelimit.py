"""
A small in-memory rate limiter — hardening for the public, paid LLM endpoints.

/chat, /chat/stream, and /agent each cost real money per call and are open to the internet,
so a scripted caller could run up a bill. This caps requests per client key (IP) with a
sliding window. It is process-local: it resets on deploy and is not shared across instances —
honest for a single free-tier instance, and a clear seam to swap in Redis if the app scales out.
"""

import threading

_PURGE_ABOVE = 4096   # when more keys than this are tracked, drop the fully-stale ones


class RateLimiter:
    """Sliding-window request limiter. Thread-safe (FastAPI runs sync handlers in a pool)."""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max = max_requests
        self.window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}   # key -> hit timestamps within the window

    def check(self, key: str, now: float) -> tuple[bool, float]:
        """Allow or deny one request from `key` at time `now` (a monotonic clock).

        Returns (allowed, retry_after_seconds). Records the hit only when it is allowed, so a
        blocked caller doesn't push its own window forward and lock itself out indefinitely.
        """
        cutoff = now - self.window
        with self._lock:
            if len(self._hits) > _PURGE_ABOVE:
                stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
                for k in stale:
                    del self._hits[k]

            recent = [t for t in self._hits.get(key, ()) if t > cutoff]
            if len(recent) >= self.max:
                self._hits[key] = recent
                return False, max(0.0, self.window - (now - recent[0]))
            recent.append(now)
            self._hits[key] = recent
            return True, 0.0
