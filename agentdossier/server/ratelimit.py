"""A small in-memory rate limiter: fixed window per client key, no third-party dependency.

Limits are written like ``120/minute`` or ``10/second``. The key is the bearer token
(hashed) when the request carries one, otherwise the client address as the server
sees it — which is the real client only when uvicorn trusts the proxy
(``AGENTDOSSIER_TRUSTED_PROXIES``). State lives in the process; a multi-replica
deployment shares nothing, which is fine for a per-client courtesy limit and
documented as such.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict

from fastapi import HTTPException, Request

_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_limit(spec: str) -> tuple[int, int]:
    """``"120/minute"`` → ``(120, 60)``."""
    count, _, unit = spec.strip().partition("/")
    unit = unit.strip().rstrip("s") or "minute"
    if not count.strip().isdigit() or unit not in _UNITS:
        raise ValueError(f"rate limit must look like 120/minute, not {spec!r}")
    return int(count), _UNITS[unit]


def client_key(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer ") and len(header) > 7:
        return "tok:" + hashlib.sha256(header[7:].strip().encode()).hexdigest()[:16]
    return "ip:" + (request.client.host if request.client else "?")


class RateLimiter:
    def __init__(self, spec: str, *, max_keys: int = 10_000):
        self.limit, self.window = parse_limit(spec)
        self.spec = spec
        self._hits: OrderedDict[str, tuple[int, int]] = OrderedDict()  # key -> (window start, count)
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def check(self, request: Request) -> None:
        """Raise 429 when the key is over its limit in the current window."""
        key = client_key(request)
        now = int(time.monotonic())
        start = now - now % self.window
        with self._lock:
            w, n = self._hits.get(key, (start, 0))
            if w != start:
                w, n = start, 0
            n += 1
            self._hits[key] = (w, n)
            self._hits.move_to_end(key)
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
        if n > self.limit:
            retry = self.window - (now - start)
            raise HTTPException(
                429,
                f"rate limit exceeded ({self.spec})",
                headers={"Retry-After": str(max(1, retry))},
            )
