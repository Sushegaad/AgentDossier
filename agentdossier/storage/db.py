"""Small SQLite store for the self-hosted server: scan runs and an audit trail.

SQLite (stdlib) keeps the container to one process and no external service.
The schema is deliberately tiny; Postgres support is a Phase 3 item and would
replace this module behind the same three functions.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..util import now_iso


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT, "
                "status TEXT, trigger TEXT, resources INTEGER, report TEXT)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, user TEXT, action TEXT, detail TEXT)"
            )
            self.db.commit()

    def start_scan(self, trigger: str) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO scans (started, status, trigger) VALUES (?, 'running', ?)", (now_iso(), trigger)
            )
            self.db.commit()
            return int(cur.lastrowid or 0)

    def finish_scan(
        self, scan_id: int, status: str, report: dict[str, Any] | None, resources: int | None = None
    ) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE scans SET finished=?, status=?, resources=?, report=? WHERE id=?",
                (now_iso(), status, resources, json.dumps(report, default=str) if report else None, scan_id),
            )
            self.db.commit()

    def scans(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT id, started, finished, status, trigger, resources FROM scans ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            dict(zip(("id", "started", "finished", "status", "trigger", "resources"), r, strict=True))
            for r in rows
        ]

    def scan_report(self, scan_id: int) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT report FROM scans WHERE id=?", (scan_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def audit(self, user: str, action: str, detail: str = "") -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO audit (at, user, action, detail) VALUES (?, ?, ?, ?)",
                (now_iso(), user, action, detail[:2000]),
            )
            self.db.commit()

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                "SELECT at, user, action, detail FROM audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(zip(("at", "user", "action", "detail"), r, strict=True)) for r in rows]
