"""Connector plumbing: snapshot store and shared fetch helpers.

Every connector saves the raw payload it read (``SnapshotStore.save``) and
records the hash on the resources it produces (FR-10). Snapshots live in a
build cache that is never committed; only hashes travel with the catalog.
The store also remembers ETags so weekly runs can send conditional requests.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..util import FetchResult, NetPolicy, fetch, now_iso, sha256


@dataclass
class Snapshot:
    source: str
    key: str
    payload_hash: str
    fetched_at: str
    path: Path


class SnapshotStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "snapshots.db")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS snapshots (source TEXT, key TEXT, payload_hash TEXT, etag TEXT, "
            "fetched_at TEXT, path TEXT, PRIMARY KEY (source, key))"
        )

    def save(self, source: str, key: str, body: bytes, etag: str | None = None) -> Snapshot:
        h = sha256(body)
        d = self.root / source
        d.mkdir(exist_ok=True)
        path = d / f"{h}.json"
        if not path.exists():
            path.write_bytes(body)
        fetched = now_iso()
        self.db.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?, ?)",
            (source, key, h, etag, fetched, str(path)),
        )
        self.db.commit()
        return Snapshot(source, key, h, fetched, path)

    def etag(self, source: str, key: str) -> str | None:
        row = self.db.execute("SELECT etag FROM snapshots WHERE source=? AND key=?", (source, key)).fetchone()
        return row[0] if row else None

    def load(self, source: str, key: str) -> Any | None:
        row = self.db.execute("SELECT path FROM snapshots WHERE source=? AND key=?", (source, key)).fetchone()
        if not row or not Path(row[0]).exists():
            return None
        return json.loads(Path(row[0]).read_text())

    def count(self, source: str | None = None) -> int:
        if source:
            return int(
                self.db.execute("SELECT COUNT(*) FROM snapshots WHERE source=?", (source,)).fetchone()[0]
            )
        return int(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])


def get_json(
    store: SnapshotStore | None,
    source: str,
    key: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    policy: NetPolicy | None = None,
    timeout: float = 15.0,
) -> tuple[Any | None, FetchResult | None, str | None]:
    """Fetch JSON with ETag reuse. Returns (data, result, payload_hash).

    A 304 answers with the cached snapshot. Any failure returns (None, result, None).
    """
    hdrs = dict(headers or {})
    if store:
        et = store.etag(source, key)
        if et:
            hdrs["If-None-Match"] = et
    r = fetch(url, headers=hdrs, policy=policy, timeout=timeout)
    if r.status == 304 and store:
        cached = store.load(source, key)
        row = store.db.execute(
            "SELECT payload_hash FROM snapshots WHERE source=? AND key=?", (source, key)
        ).fetchone()
        return cached, r, (row[0] if row else None)
    if not r.ok:
        return None, r, None
    try:
        data = r.json()
    except ValueError:
        return None, FetchResult(r.url, r.status, r.headers, r.body, error="invalid JSON"), None
    if store:
        snap = store.save(source, key, r.body, r.headers.get("ETag") or r.headers.get("etag"))
        return data, r, snap.payload_hash
    return data, r, sha256(r.body)


class ConnectorReport:
    """Counts and errors for the run summary (connector health, plan section 4)."""

    def __init__(self, source: str):
        self.source = source
        self.fetched = 0
        self.produced = 0
        self.skipped = 0
        self.errors: list[str] = []
        self.started = now_iso()

    def error(self, msg: str) -> None:
        if len(self.errors) < 50:
            self.errors.append(msg)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fetched": self.fetched,
            "produced": self.produced,
            "skipped": self.skipped,
            "errors": len(self.errors),
            "error_samples": self.errors[:5],
            "started": self.started,
            "finished": now_iso(),
        }
