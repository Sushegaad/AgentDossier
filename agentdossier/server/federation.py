"""ARD federation for ``POST /search`` (Wk 16).

A registry may know other registries. Two modes, chosen per instance
(``AGENTDOSSIER_FEDERATION_MODE``) and narrowed per request (``federation`` in the
search body):

* ``referrals`` — the response lists peer registries the client may query itself
  (``referrals: [{registry, search, manifest, reason}]``). Nothing leaves this
  instance; the client decides.
* ``auto`` — this instance queries every peer in parallel, with a short timeout,
  and appends their hits marked ``source_registry``. A peer that serves the ARD
  REST API answers ``POST /search``; a static registry (the public demo, or any
  publisher's ``/.well-known/ard.json``) is matched locally on its manifest.

Loops are cut by the ``X-AgentDossier-Federation-Hop`` header: a federated query
is never federated again. Peer failures are reported, never raised.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

MODES = ("none", "referrals", "auto")
HOP_HEADER = "X-AgentDossier-Federation-Hop"
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if len(t) > 2}


class Peer:
    def __init__(
        self, base: str, *, token: str | None = None, timeout: float = 5.0, cache_ttl: float = 600.0
    ):
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._manifest: dict[str, Any] | None = None
        self._manifest_at = 0.0
        self._lock = threading.Lock()

    @property
    def search_url(self) -> str:
        return f"{self.base}/search"

    @property
    def manifest_url(self) -> str:
        return f"{self.base}/.well-known/ard.json"

    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": "AgentDossier-federation/1", HOP_HEADER: "1", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def manifest(self) -> dict[str, Any]:
        with self._lock:
            if self._manifest is not None and time.monotonic() - self._manifest_at < self.cache_ttl:
                return self._manifest
        req = urllib.request.Request(self.manifest_url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - operator-configured peer
            doc = json.loads(resp.read())
        with self._lock:
            self._manifest, self._manifest_at = doc, time.monotonic()
        return doc

    def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Hits from the peer: its REST API when it has one, else a manifest match."""
        payload = {k: v for k, v in body.items() if k != "federation"}
        payload["federation"] = "none"
        raw = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.search_url,
            data=raw,
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                data = json.loads(resp.read())
                return {"via": "rest", "results": data.get("results", []), "catalog": data.get("catalog")}
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 405, 501):
                raise RuntimeError(f"HTTP {exc.code}") from exc
        # static registry: match the manifest locally
        doc = self.manifest()
        q = _tokens(str(body.get("query") or ""))
        limit = int(body.get("limit") or 20)
        hits = []
        for e in doc.get("entries", []):
            if e.get("type") == "application/ai-registry+json":
                continue
            text = " ".join(
                str(x)
                for x in [
                    e.get("displayName"),
                    e.get("description"),
                    " ".join(e.get("tags") or []),
                    " ".join(e.get("representativeQueries") or []),
                ]
            )
            toks = _tokens(text)
            overlap = len(q & toks)
            if q and not overlap:
                continue
            hits.append(
                {
                    "identifier": e.get("identifier"),
                    "displayName": e.get("displayName"),
                    "type": e.get("type"),
                    "url": e.get("url"),
                    "description": e.get("description"),
                    "score": round(overlap / max(len(q), 1), 3) if q else 0.0,
                    "explanation": f"manifest match on {overlap} term(s)"
                    if q
                    else "listed in the peer manifest",
                }
            )
        hits.sort(key=lambda h: -h["score"])
        return {"via": "manifest", "results": hits[:limit], "catalog": None}


class Federation:
    def __init__(self, peers: list[Peer], mode: str = "referrals", *, max_workers: int = 4):
        if mode not in MODES:
            raise ValueError(f"federation mode must be one of {', '.join(MODES)}")
        self.peers = peers
        self.mode = mode
        self.max_workers = max_workers

    @property
    def enabled(self) -> bool:
        return bool(self.peers) and self.mode != "none"

    def effective_mode(self, requested: str | None, hop: str | None) -> str:
        """The request may narrow the instance mode, never widen it; a hop ends federation."""
        if hop or not self.enabled:
            return "none"
        req = (requested or self.mode).lower()
        if req not in MODES:
            req = self.mode
        order = {m: i for i, m in enumerate(MODES)}
        return req if order[req] <= order[self.mode] else self.mode

    def referrals(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "registry": p.base,
                "search": p.search_url,
                "manifest": p.manifest_url,
                "reason": f"peer registry configured on this instance; repeat the query there for '{query}'"
                if query
                else "peer registry configured on this instance",
            }
            for p in self.peers
        ]

    def query(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        def one(p: Peer) -> dict[str, Any]:
            started = time.monotonic()
            try:
                out = p.search(body)
                return {
                    "registry": p.base,
                    "via": out["via"],
                    "count": len(out["results"]),
                    "results": out["results"],
                    "ms": int((time.monotonic() - started) * 1000),
                }
            except Exception as exc:  # noqa: BLE001 - a dead peer must not fail the local answer
                return {
                    "registry": p.base,
                    "error": f"{type(exc).__name__}: {exc}",
                    "count": 0,
                    "results": [],
                    "ms": int((time.monotonic() - started) * 1000),
                }

        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(self.peers)))) as pool:
            return list(pool.map(one, self.peers))


def peers_from_env(value: str | None, *, token: str | None = None, timeout: float = 5.0) -> list[Peer]:
    return [Peer(u.strip(), token=token, timeout=timeout) for u in (value or "").split(",") if u.strip()]
