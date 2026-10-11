"""The trace store: ``data/traces/`` — append-only, hash-chained, in this repository.

``index.jsonl`` holds one line per trace. Each line carries ``prev`` (the ``hash`` of the
line before it) and ``hash`` (SHA-256 of the line's canonical JSON without ``hash``), so
a trace cannot be edited or removed without breaking every later line; CI verifies the
chain on every pull request. Bundles live in ``bundles/<id>/`` as small text files
(manifest.json, transcript.md, verdict.json, optional spans.jsonl, scenario.yaml); the
index line records the SHA-256 of the whole bundle. ``git clone`` is the mirror.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..util import ROOT

STORE_ROOT = ROOT / "data" / "traces"
GENESIS = "sha256:" + "0" * 64
BUNDLE_MAX_BYTES = 2_000_000
BUNDLE_FILES = ("manifest.json", "transcript.md", "verdict.json", "spans.jsonl", "scenario.yaml")


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def line_hash(line: dict[str, Any]) -> str:
    return _sha(_canonical({k: v for k, v in line.items() if k != "hash"}))


def bundle_hash(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode())
        h.update(b"\0")
        h.update(hashlib.sha256(files[name]).digest())
    return "sha256:" + h.hexdigest()


class TraceStore:
    def __init__(self, root: Path = STORE_ROOT):
        self.root = Path(root)
        self.index_path = self.root / "index.jsonl"
        self.bundles = self.root / "bundles"

    # --- reading --------------------------------------------------------------------

    def lines(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        out = []
        for raw in self.index_path.read_text().splitlines():
            raw = raw.strip()
            if raw:
                out.append(json.loads(raw))
        return out

    def verify(self) -> list[str]:
        """Problems with the chain and the bundles on disk; empty when everything checks out."""
        problems: list[str] = []
        prev = GENESIS
        seen: set[str] = set()
        for n, line in enumerate(self.lines(), 1):
            if line.get("prev") != prev:
                problems.append(f"line {n} ({line.get('id')}): prev {line.get('prev')} != {prev}")
            if line.get("hash") != line_hash(line):
                problems.append(f"line {n} ({line.get('id')}): hash does not match content")
            if line.get("id") in seen:
                problems.append(f"line {n}: duplicate id {line.get('id')}")
            seen.add(str(line.get("id")))
            bundle = line.get("record", {}).get("bundle")
            if bundle:
                files = self.read_bundle(bundle)
                if files is None:
                    problems.append(f"line {n} ({line.get('id')}): bundle {bundle} missing")
                elif bundle_hash(files) != line["record"].get("sha256"):
                    problems.append(f"line {n} ({line.get('id')}): bundle {bundle} hash mismatch")
            prev = line_hash(line)  # recomputed, so an edited line also breaks every line after it
        return problems

    def read_bundle(self, bundle: str) -> dict[str, bytes] | None:
        d = self.root / bundle
        if not d.is_dir():
            return None
        return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.name in BUNDLE_FILES}

    def keys(self) -> set[str]:
        return {str(line.get("key")) for line in self.lines() if line.get("key")}

    def records_by_agent(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for line in self.lines():
            rec = dict(line.get("record") or {})
            if rec:
                out.setdefault(str(line.get("agent")), []).append(rec)
        return out

    # --- writing --------------------------------------------------------------------

    def append(
        self,
        record: dict[str, Any],
        *,
        agent: str,
        key: str | None = None,
        files: dict[str, bytes] | None = None,
    ) -> dict[str, Any]:
        """Write the bundle (if any) and append one chained line. Never rewrites earlier lines."""
        record = dict(record)
        if files:
            unknown = set(files) - set(BUNDLE_FILES)
            if unknown:
                raise ValueError(f"bundle files not allowed: {sorted(unknown)}")
            size = sum(len(b) for b in files.values())
            if size > BUNDLE_MAX_BYTES:
                raise ValueError(f"bundle {record['id']} is {size} bytes; limit {BUNDLE_MAX_BYTES}")
            d = self.bundles / record["id"]
            d.mkdir(parents=True, exist_ok=True)
            for name, data in files.items():
                (d / name).write_bytes(data)
            record["bundle"] = f"bundles/{record['id']}"
            record["sha256"] = bundle_hash(files)
        lines = self.lines()
        prev = lines[-1]["hash"] if lines else GENESIS
        line: dict[str, Any] = {
            "id": record["id"],
            "agent": agent,
            "key": key,
            "prev": prev,
            "record": record,
        }
        line["hash"] = line_hash(line)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n")
        return line
