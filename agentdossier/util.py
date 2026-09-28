"""Shared helpers: config loading, safe HTTP fetching, hashing, timestamps."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
USER_AGENT = (
    f"AgentDossier/{__version__} (+https://github.com/Sushegaad/AgentDossier; metadata-only discovery)"
)
MAX_BYTES = 2_000_000  # never pull more than 2 MB from a single discovery URL


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def load_json(path: str | Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_config(name: str):
    return load_json(CONFIG_DIR / name)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def domain_of(url: str | None) -> str | None:
    if not url or not isinstance(url, str) or "://" not in url:
        return None
    host = urllib.parse.urlparse(url).hostname or ""
    host = host.lower()
    return host[4:] if host.startswith("www.") else host or None


def canonical_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str) or "://" not in url:
        return None
    p = urllib.parse.urlparse(url.strip())
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/")
    return f"{host}{path}".lower()


# ---------------------------------------------------------------------------
# Safe HTTP
# ---------------------------------------------------------------------------


class FetchBlockedError(Exception):
    """Raised when a URL is refused by the network policy (SSRF guard)."""


@dataclass
class NetPolicy:
    """Egress policy.

    Public mode (default) refuses private, loopback and link-local targets so a
    malicious manifest cannot pivot the crawler into an internal network (SSRF).
    Enterprise mode inverts this: only explicitly allow-listed CIDRs/hosts are
    reachable, and only after the operator asserted authorization.
    """

    mode: str = "public"  # "public" | "enterprise"
    allow_cidrs: list = field(default_factory=list)
    allow_hosts: list = field(default_factory=list)
    allow_public: bool = False  # enterprise mode: may it also reach public IPs?

    def check(self, url: str) -> None:
        p = urllib.parse.urlparse(url)
        if p.scheme not in ("http", "https"):
            raise FetchBlockedError(f"scheme not allowed: {p.scheme}")
        host = p.hostname or ""
        try:
            infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80))
            addrs = {ipaddress.ip_address(i[4][0]) for i in infos}
        except socket.gaierror as exc:
            raise FetchBlockedError(f"cannot resolve {host}: {exc}") from exc
        for addr in addrs:
            internal = addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
            if self.mode == "public":
                if internal:
                    raise FetchBlockedError(f"{host} resolves to non-public address {addr}")
            else:
                if host.lower() in {h.lower() for h in self.allow_hosts}:
                    continue
                if any(addr in ipaddress.ip_network(c, strict=False) for c in self.allow_cidrs):
                    continue
                if self.allow_public and not internal:
                    continue
                raise FetchBlockedError(f"{host} ({addr}) is outside the authorized scan scope")


class RateLimiter:
    """Simple per-host minimum interval limiter (thread safe)."""

    def __init__(self, min_interval: float = 0.25):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            last = self._last.get(host, 0.0)
            delay = self.min_interval - (time.monotonic() - last)
            self._last[host] = time.monotonic() + max(delay, 0)
        if delay > 0:
            time.sleep(delay)


@dataclass
class FetchResult:
    url: str
    status: int
    headers: dict
    body: bytes
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300

    def json(self):
        return json.loads(self.body.decode("utf-8", errors="replace"))

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


_DEFAULT_LIMITER = RateLimiter()


def fetch(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: float = 10.0,
    policy: NetPolicy | None = None,
    limiter: RateLimiter | None = None,
    retries: int = 1,
    verify_tls: bool = True,
    follow_redirects: bool = True,
    max_bytes: int = MAX_BYTES,
) -> FetchResult:
    """Fetch with SSRF guard, size cap, rate limit and retry/backoff. Never raises for HTTP errors."""
    policy = policy or NetPolicy()
    limiter = limiter or _DEFAULT_LIMITER
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.8, */*;q=0.5"}
    hdrs.update(headers or {})
    try:
        policy.check(url)
    except FetchBlockedError as exc:
        return FetchResult(url, 0, {}, b"", error=f"blocked: {exc}")

    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    active_policy = policy

    class _Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs_, newurl):
            if not follow_redirects:
                return None
            active_policy.check(newurl)  # re-check every hop (SSRF via redirect)
            return super().redirect_request(req, fp, code, msg, hdrs_, newurl)

    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), _Redirect())
    attempt = 0
    while True:
        attempt += 1
        limiter.wait(urllib.parse.urlparse(url).hostname or "")
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with opener.open(req, timeout=timeout) as resp:
                body = resp.read(max_bytes + 1)
                if len(body) > max_bytes:
                    return FetchResult(url, resp.status, dict(resp.headers), b"", error="response too large")
                return FetchResult(resp.geturl(), resp.status, dict(resp.headers), body)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503, 504) and attempt <= retries:
                time.sleep(min(2**attempt, 8))
                continue
            try:
                body = exc.read(MAX_BYTES)
            except Exception:  # noqa: BLE001
                body = b""
            return FetchResult(url, exc.code, dict(exc.headers or {}), body, error=f"HTTP {exc.code}")
        except FetchBlockedError as exc:
            return FetchResult(url, 0, {}, b"", error=f"blocked: {exc}")
        except Exception as exc:  # noqa: BLE001 - network errors are data, not crashes
            if attempt <= retries:
                time.sleep(min(2**attempt, 8))
                continue
            return FetchResult(url, 0, {}, b"", error=f"{type(exc).__name__}: {exc}")


def fetch_json(url: str, **kw):
    r = fetch(url, **kw)
    if not r.ok:
        return None, r
    try:
        return r.json(), r
    except ValueError:
        return None, FetchResult(r.url, r.status, r.headers, r.body, error="invalid JSON")


class Deadline:
    """Wall-clock budget shared by the build stages (the weekly job must finish inside its runner limit)."""

    def __init__(self, minutes: float | None):
        self.started = time.monotonic()
        self.seconds = None if minutes is None else float(minutes) * 60.0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining(self) -> float | None:
        return None if self.seconds is None else max(0.0, self.seconds - self.elapsed)

    def expired(self) -> bool:
        return self.seconds is not None and self.elapsed >= self.seconds

    def log(self, stage: str, msg: str = "") -> None:
        left = "" if self.remaining is None else f", {self.remaining / 60:.0f} min left"
        print(
            f"[build] {self.elapsed / 60:.1f} min{left} · {stage}{(': ' + msg) if msg else ''}",
            file=sys.stderr,
            flush=True,
        )
