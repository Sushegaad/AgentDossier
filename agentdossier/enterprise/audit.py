"""Hash-chained audit log for authorized scans.

Every scan writes ``audit.jsonl`` next to its report: one JSON object per line, each
carrying the SHA-256 of the previous line's hash plus its own canonical content. The
first line is the run header (who authorized the scan, the change ticket, the hash of
the configuration that was used, the scanner version). An auditor can show that the
log was neither truncated nor edited after the fact with
``agentdossier enterprise audit-verify audit.jsonl``.

Kinds: ``run`` (header), ``blocked`` (a target the scope refused — recorded, never
contacted), ``probe`` (an origin that was contacted, with each probe's status),
``found`` (resources produced from one origin), ``registry``, ``error``, ``done``.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from .. import __version__
from ..util import now_iso

GENESIS = "0" * 64


def _digest(prev_hash: str, entry: dict[str, Any]) -> str:
    body = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only writer. Entries are hashed over their content *and* the previous hash."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._prev = GENESIS
        self._seq = 0
        if self.path.exists() and self.path.stat().st_size:
            raise ValueError(f"{self.path} already exists; a scan's audit log is written once")

    def append(self, kind: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            entry: dict[str, Any] = {
                "seq": self._seq,
                "at": now_iso(),
                "kind": kind,
                **fields,
                "prev_hash": self._prev,
            }
            entry["hash"] = _digest(self._prev, entry)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str) + "\n")
            self._prev = entry["hash"]
            self._seq += 1
            return entry

    def header(
        self, *, tenant: str, authorized_by: str, ticket: str, config_hash: str, targets: int
    ) -> dict[str, Any]:
        return self.append(
            "run",
            tenant=tenant,
            authorized_by=authorized_by,
            ticket=ticket,
            config_hash=config_hash,
            scanner_version=__version__,
            targets=targets,
        )

    @property
    def last_hash(self) -> str:
        return self._prev


def verify(path: str | Path) -> tuple[bool, list[dict[str, Any]], str | None]:
    """Re-walk the chain. Returns (ok, entries, first problem)."""
    entries: list[dict[str, Any]] = []
    prev = GENESIS
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            return False, entries, f"line {n}: not JSON"
        claimed = entry.get("hash")
        if entry.get("prev_hash") != prev:
            return (
                False,
                entries,
                f"line {n}: prev_hash does not match the previous entry (chain broken or truncated)",
            )
        body = {k: v for k, v in entry.items() if k != "hash"}
        if _digest(prev, body) != claimed:
            return False, entries, f"line {n}: content does not match its hash (edited after the fact)"
        if entry.get("seq") != len(entries):
            return False, entries, f"line {n}: sequence gap"
        entries.append(entry)
        prev = claimed
    if not entries:
        return False, entries, "empty log"
    if entries[0].get("kind") != "run":
        return False, entries, "first entry is not the run header"
    if entries[-1].get("kind") != "done":
        return (
            False,
            entries,
            "log ends without a done entry (the scan did not finish, or lines were removed)",
        )
    return True, entries, None
