"""
Tests for the in-memory rate limiter (hardening for the paid LLM endpoints). The clock is
passed in, so the sliding window is tested deterministically without sleeping.
"""

from ratelimit import RateLimiter


def test_allows_up_to_the_limit_then_blocks():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    t = 1000.0
    assert all(rl.check("ip", t)[0] for _ in range(3))   # first three allowed
    allowed, retry = rl.check("ip", t)
    assert not allowed and retry > 0                      # fourth blocked, with a retry hint


def test_window_slides_and_reallows():
    rl = RateLimiter(max_requests=2, window_seconds=10)
    assert rl.check("ip", 100.0)[0]
    assert rl.check("ip", 100.0)[0]
    assert not rl.check("ip", 105.0)[0]                   # still inside the window
    assert rl.check("ip", 111.0)[0]                       # the first hit aged out -> allowed again


def test_keys_are_independent():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.check("a", 0.0)[0]
    assert rl.check("b", 0.0)[0]                          # a different key has its own budget
    assert not rl.check("a", 0.0)[0]


def test_blocked_request_does_not_extend_its_own_lockout():
    """A denied request must not be recorded, or a persistent caller could never recover."""
    rl = RateLimiter(max_requests=1, window_seconds=10)
    assert rl.check("ip", 0.0)[0]
    assert not rl.check("ip", 5.0)[0]                     # blocked at t=5 (not recorded)
    assert rl.check("ip", 11.0)[0]                        # only the t=0 hit aged out -> allowed


def test_retry_after_is_within_the_window():
    rl = RateLimiter(max_requests=1, window_seconds=30)
    rl.check("ip", 100.0)
    allowed, retry = rl.check("ip", 110.0)
    assert not allowed and 0 < retry <= 30
