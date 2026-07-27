"""
Tests for the observability layer (Module 3): the metrics registry, structured JSON logs,
request ids, and the middleware + /metrics endpoint that expose them. No API key or network
needed — the Metrics class and formatter are pure, and /health + /metrics make no model call.
"""

import json
import logging
import sys

from fastapi.testclient import TestClient

from main import app
from obs import Metrics, JsonFormatter, new_request_id

client = TestClient(app)


# --- Metrics registry --------------------------------------------------------
def test_metrics_counts_requests_and_statuses():
    m = Metrics()
    m.record_request("/health", 200, 5.0)
    m.record_request("/chat", 502, 10.0)
    snap = m.snapshot()
    assert snap["total_requests"] == 2
    assert snap["status_counts"] == {"2xx": 1, "5xx": 1}
    assert snap["requests_by_path"] == {"/health": 1, "/chat": 1}


def test_metrics_latency_percentiles():
    m = Metrics()
    for ms in [10, 20, 30, 40, 100]:
        m.record_request("/x", 200, ms)
    lat = m.snapshot()["latency_ms"]
    assert lat["p50"] == 30.0          # middle of 5 sorted samples
    assert lat["p95"] == 100.0         # top of the distribution
    assert lat["samples"] == 5


def test_metrics_latency_none_when_empty():
    assert Metrics().snapshot()["latency_ms"]["p50"] is None


def test_metrics_chat_economics_accumulate():
    m = Metrics()
    m.record_chat(answered=True, input_tokens=1000, output_tokens=200, cost_usd=0.002)
    m.record_chat(answered=False, input_tokens=0, output_tokens=0, cost_usd=0.0)
    chat = m.snapshot()["chat"]
    assert chat["answers"] == 1 and chat["refusals"] == 1
    assert chat["input_tokens"] == 1000 and chat["output_tokens"] == 200
    assert chat["total_cost_usd"] == 0.002


def test_metrics_latency_is_bounded():
    m = Metrics()
    for i in range(Metrics.LATENCY_CAP + 50):
        m.record_request("/x", 200, float(i))
    assert m.snapshot()["latency_ms"]["samples"] == Metrics.LATENCY_CAP


# --- Structured logging ------------------------------------------------------
def test_json_formatter_emits_one_parseable_object_with_fields():
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "request", None, None)
    rec.fields = {"request_id": "abc123", "status": 200}
    obj = json.loads(JsonFormatter().format(rec))   # must be valid JSON
    assert obj["msg"] == "request"
    assert obj["request_id"] == "abc123"             # structured fields merged in
    assert obj["status"] == 200
    assert obj["level"] == "INFO"


def test_json_formatter_includes_exception_text():
    try:
        raise ValueError("boom")
    except ValueError:
        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    obj = json.loads(JsonFormatter().format(rec))
    assert "ValueError" in obj["exc"] and "boom" in obj["exc"]


def test_request_id_is_short_and_unique():
    ids = {new_request_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(len(i) == 12 for i in ids)


# --- Middleware + endpoint ---------------------------------------------------
def test_every_response_carries_a_unique_request_id_header():
    r1 = client.get("/health")
    r2 = client.get("/health")
    assert r1.status_code == 200
    assert r1.headers.get("X-Request-ID")                      # present
    assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]   # unique per request


def test_metrics_endpoint_shape_and_increments():
    before = client.get("/metrics").json()["total_requests"]
    client.get("/health")
    after = client.get("/metrics").json()
    assert after["total_requests"] > before                   # requests are counted
    assert "since" in after and "T" in after["since"]         # honest window label (ISO timestamp)
    assert "uptime_seconds" in after and "latency_ms" in after and "chat" in after


def test_metrics_endpoint_leaks_no_secrets():
    text = client.get("/metrics").text.lower()
    for forbidden in ["password", "api_key", "database_url", "postgres", "sk-"]:
        assert forbidden not in text
