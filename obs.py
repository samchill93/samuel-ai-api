"""
Observability (Module 3): structured logging, request IDs, per-request timing, and a
small in-memory metrics registry — so every request is traceable and the system can report
its own health without an external APM.

Two honesty constraints shape this:
  - Everything here is process-local and resets when the process restarts (each Render
    deploy is a fresh process). The /metrics snapshot is labelled with the process start
    time, so a reader knows exactly what window the numbers cover — an honest "since live"
    figure, never a fabricated lifetime total.
  - Logs and metrics carry operational data only (timings, token counts, status codes).
    No request bodies, no secrets, no PII — the same discipline the error handlers already
    follow when they refuse to echo a driver message to the caller.
"""

import json
import logging
import sys
import threading
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Structured JSON logging — one JSON object per line, so Render's log stream is
# machine-parseable (greppable by request_id, filterable by status, etc.).
# ---------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Structured fields are attached via logger.info(..., extra={"fields": {...}}).
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(name: str = "samuel-ai-api", level: int = logging.INFO) -> logging.Logger:
    """Send our app logger through the JSON formatter to stdout, once.

    Only our namespace is touched — uvicorn's own loggers are left alone, so this doesn't
    fight the server's logging. propagate=False keeps lines from double-printing via root.
    """
    log = logging.getLogger(name)
    log.setLevel(level)
    log.propagate = False
    if not any(getattr(h, "_json_obs", False) for h in log.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler._json_obs = True   # marker so repeated calls don't stack handlers
        log.addHandler(handler)
    return log


def new_request_id() -> str:
    """Short, unique id for correlating a request's log lines with its trace."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# In-memory metrics registry — thread-safe and bounded, so it can't grow without
# limit. FastAPI runs sync handlers in a threadpool, so record() may be called from
# many threads at once; every mutation is under a lock.
# ---------------------------------------------------------------------------
class Metrics:
    LATENCY_CAP = 500   # keep the last N latencies for percentiles (bounded memory)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._t0 = time.monotonic()
        self.total_requests = 0
        self.status_counts: Counter = Counter()     # "2xx" / "4xx" / "5xx"
        self.path_counts: Counter = Counter()
        self._latencies: deque = deque(maxlen=self.LATENCY_CAP)
        # Chat economics — the honest running tally behind the cost footer.
        self.chat_answers = 0
        self.chat_refusals = 0
        self.chat_input_tokens = 0
        self.chat_output_tokens = 0
        self.chat_cost_usd = 0.0

    def record_request(self, path: str, status: int, latency_ms: float) -> None:
        with self._lock:
            self.total_requests += 1
            self.status_counts[f"{status // 100}xx"] += 1
            self.path_counts[path] += 1
            self._latencies.append(latency_ms)

    def record_chat(self, *, answered: bool, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        with self._lock:
            if answered:
                self.chat_answers += 1
            else:
                self.chat_refusals += 1
            self.chat_input_tokens += input_tokens
            self.chat_output_tokens += output_tokens
            self.chat_cost_usd += cost_usd

    def snapshot(self) -> dict:
        with self._lock:
            lat = sorted(self._latencies)

            def pct(p: int):
                if not lat:
                    return None
                k = max(0, min(len(lat) - 1, int(round((p / 100) * (len(lat) - 1)))))
                return round(lat[k], 1)

            return {
                "since": self.started_at,
                "uptime_seconds": round(time.monotonic() - self._t0, 1),
                "total_requests": self.total_requests,
                "status_counts": dict(self.status_counts),
                "requests_by_path": dict(self.path_counts),
                "latency_ms": {"p50": pct(50), "p95": pct(95), "samples": len(lat)},
                "chat": {
                    "answers": self.chat_answers,
                    "refusals": self.chat_refusals,
                    "input_tokens": self.chat_input_tokens,
                    "output_tokens": self.chat_output_tokens,
                    "total_cost_usd": round(self.chat_cost_usd, 6),
                },
            }


metrics = Metrics()   # process-wide singleton
