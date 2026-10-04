"""The in-house fixed-window limiter (replaces slowapi)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from agentdossier.server.ratelimit import RateLimiter, client_key, parse_limit


class _Req:
    def __init__(self, auth: str | None = None, host: str = "10.0.0.1"):
        self.headers = {"authorization": auth} if auth else {}
        self.client = type("C", (), {"host": host})()


def test_parse_limit():
    assert parse_limit("120/minute") == (120, 60) and parse_limit("3/seconds") == (3, 1)
    for bad in ("fast", "x/minute", "10/fortnight"):
        with pytest.raises(ValueError):
            parse_limit(bad)


def test_keys_tokens_are_hashed_and_addresses_fall_back():
    k = client_key(_Req("Bearer secret-token"))
    assert k.startswith("tok:") and "secret" not in k
    assert client_key(_Req(host="1.2.3.4")) == "ip:1.2.3.4"


def test_window_counts_per_key_and_sets_retry_after():
    rl = RateLimiter("2/minute")
    a, b = _Req("Bearer a"), _Req("Bearer b")
    rl.check(a)
    rl.check(a)
    with pytest.raises(HTTPException) as exc:
        rl.check(a)
    assert exc.value.status_code == 429 and 1 <= int(exc.value.headers["Retry-After"]) <= 60
    rl.check(b)  # another client is unaffected


def test_key_table_is_bounded():
    rl = RateLimiter("1000/minute", max_keys=3)
    for i in range(10):
        rl.check(_Req(host=f"10.0.0.{i}"))
    assert len(rl._hits) == 3  # noqa: SLF001
