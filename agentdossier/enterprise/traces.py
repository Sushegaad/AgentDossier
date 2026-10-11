"""Instance-local traces for private and internal agents (PR 5).

A self-hosted tenant runs the same harness against agents the public registry never sees and keeps
the results in its own database. The rows gate approvals (``require_trace_tier`` on a decision) and
can be published back to the public store when the tenant chooses. Nothing here leaves the tenant
on its own.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..util import now_iso


def record_trace(
    db: sqlite3.Connection, resource_id: str, record: dict[str, Any], *, extra: dict[str, Any] | None = None
) -> str:
    """Store one trace record for a resource. ``record`` is a trace_record dict; returns its id."""
    e = extra or {}
    db.execute(
        "INSERT OR REPLACE INTO traces (id, resource_id, kind, tier, title, scenario, source, model, suite, "
        "attack, injections_succeeded, pairs, record, created, published) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["id"],
            resource_id,
            record["kind"],
            int(record["tier"]),
            record.get("title"),
            record.get("scenario"),
            record.get("source"),
            e.get("model"),
            e.get("suite"),
            e.get("attack"),
            e.get("injections_succeeded"),
            e.get("pairs"),
            json.dumps(record, sort_keys=True),
            now_iso(),
            None,
        ),
    )
    db.commit()
    return str(record["id"])


def traces_for(db: sqlite3.Connection, resource_id: str) -> list[dict[str, Any]]:
    cur = db.execute("SELECT record FROM traces WHERE resource_id=? ORDER BY tier, created", (resource_id,))
    return [json.loads(r[0]) for r in cur.fetchall()]


def best_tier(db: sqlite3.Connection, resource_id: str) -> int | None:
    cur = db.execute("SELECT MIN(tier) FROM traces WHERE resource_id=?", (resource_id,))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def run_and_store(
    db: sqlite3.Connection,
    pipeline: Any,
    suite: str,
    resource_id: str,
    model_key: str,
    *,
    attack: str = "ignore_previous",
) -> str | None:
    """Run the harness against ``pipeline`` and store the result as an instance-local trace."""
    from ..harness import run_suite
    from ..harness.bundles import _manifest, _verdict, trace_id  # internal helpers reused

    result = run_suite(pipeline, suite, attack_name=attack)
    if result.error or not result.pairs:
        return None
    tid = trace_id(result, model_key) + f"_{resource_id}"
    record = {
        "id": tid,
        "kind": "injection_eval",
        "tier": 1,
        "scope": "model",
        "title": f"{model_key}: AgentDojo {result.suite} under {result.attack} (private)",
        "scenario": f"{result.pairs} tasks; injection succeeded in {result.injections_succeeded}",
        "source": f"AgentDojo {result.agentdojo_version}",
        "url": None,
        "date": now_iso()[:10],
        "format": "bundle",
        "observed": _verdict(result),
        "manifest": _manifest(result, model_key, tid),
    }
    return record_trace(
        db,
        resource_id,
        record,
        extra={
            "model": model_key,
            "suite": result.suite,
            "attack": result.attack,
            "injections_succeeded": result.injections_succeeded,
            "pairs": result.pairs,
        },
    )
