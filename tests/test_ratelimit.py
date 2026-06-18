from __future__ import annotations

import re
import threading
import time

import pytest
import responses

from proxy6 import Proxy6Client, RateLimiter
from proxy6.client import DEFAULT_BASE_URL


API_KEY = "test_key"


def test_burst_then_throttle_blocks_briefly() -> None:
    """Three requests fit in the first second; the fourth must wait."""
    limiter = RateLimiter(max_requests=3, period=1.0)
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    fast = time.monotonic() - start
    assert fast < 0.2, "first 3 acquires should not block"
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 1.0, f"4th acquire should wait until the window slides; got {elapsed:.3f}s"


def test_disabled_when_passed_none() -> None:
    """A None limiter on the client means no throttling at all."""
    with responses.RequestsMock() as r:
        r.add(
            responses.GET,
            re.compile(rf"{re.escape(DEFAULT_BASE_URL)}/{API_KEY}/getcount/.*"),
            json={
                "status": "yes",
                "user_id": "1",
                "balance": "1",
                "currency": "RUB",
                "count": 1,
            },
        )
        client = Proxy6Client(api_key=API_KEY, rate_limiter=None)
        start = time.monotonic()
        for _ in range(10):
            client.get_count("ru")
        assert time.monotonic() - start < 1.0


def test_rejects_bad_config() -> None:
    with pytest.raises(ValueError):
        RateLimiter(max_requests=0)
    with pytest.raises(ValueError):
        RateLimiter(period=0)


def test_shared_limiter_throttles_concurrent_clients() -> None:
    """A single limiter shared across two clients still enforces the global cap."""
    limiter = RateLimiter(max_requests=3, period=1.0)
    with responses.RequestsMock() as r:
        r.add(
            responses.GET,
            re.compile(rf"{re.escape(DEFAULT_BASE_URL)}/.*/getcount/.*"),
            json={
                "status": "yes",
                "user_id": "1",
                "balance": "1",
                "currency": "RUB",
                "count": 1,
            },
        )
        c1 = Proxy6Client(api_key="a", rate_limiter=limiter)
        c2 = Proxy6Client(api_key="b", rate_limiter=limiter)
        start = time.monotonic()

        def hit(c: Proxy6Client) -> None:
            c.get_count("ru")

        threads = [threading.Thread(target=hit, args=(c,)) for c in (c1, c2, c1, c2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        elapsed = time.monotonic() - start
        # 4 calls, cap of 3/s → the 4th must wait roughly a second.
        assert elapsed >= 1.0
