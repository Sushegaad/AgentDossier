"""Decision workflow for the self-hosted server (FR-28 lifecycle, FR-34 collaboration and
procurement, FR-35 internal feedback).

A *decision* is the record an organisation keeps about one agent: whether it may be
used, under which policy, who signed off and why. Its stage history is append-only
(``decision_events``), sign-offs are per role (``approvals``), and discussion,
follow-ups and feedback hang off it (``comments``, ``review_tasks``, ``feedback``).
Everything is exportable as one packet (JSON or CSV) so the record can live in a
GRC tool, a ticket or an archive after the instance is gone.

Stages::

    candidate ──► under_review ──► approved ──► retired
                      │                ▲
                      ├──► rejected    │
                      └──► deferred ───┘ (back to under_review)

``approved`` is only reachable when every required role has an ``approve`` and no
role has a ``reject``; a reject moves the decision to ``rejected``. Roles come
from the signed-in user (OIDC groups or token kind): ``member`` may open
decisions, comment, add tasks and feedback; ``reviewer`` and ``admin`` may sign
off and change stages.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any

from ..storage.db import ensure_schema
from ..util import now_iso

STAGES = ("candidate", "under_review", "approved", "rejected", "deferred", "retired")
TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"under_review", "rejected"},
    "under_review": {"approved", "rejected", "deferred"},
    "deferred": {"under_review", "rejected"},
    "approved": {"retired", "under_review"},
    "rejected": {"under_review"},
    "retired": set(),
}
DEFAULT_ROLES = ("security", "business")
APPROVAL_ROLES = ("security", "legal", "procurement", "business", "privacy", "architecture")
TASK_STATUS = ("open", "done", "cancelled")
FEEDBACK_KINDS = ("correction", "rating", "note", "incident")
FEEDBACK_STATUS = ("open", "acknowledged", "resolved")


class WorkflowError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Actor:
    subject: str
    name: str
    roles: set[str] = field(default_factory=lambda: {"member"})

    @property
    def can_sign(self) -> bool:
        return bool(self.roles & {"reviewer", "admin"})


def _row(cur: sqlite3.Cursor, r: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return dict(zip([c[0] for c in cur.description], r, strict=True))


def _rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


class Workflow:
    def __init__(self, db: sqlite3.Connection, lock: threading.RLock | None = None):
        self.db = db
        self.lock = lock or threading.RLock()
        ensure_schema(self.db, self.lock)

    # --- decisions --------------------------------------------------------------------

    def create_decision(
        self,
        actor: Actor,
        *,
        resource_id: str,
        resource_name: str | None,
        title: str | None = None,
        policy_id: str | None = None,
        required_roles: list[str] | None = None,
        owner: str | None = None,
        notes: str | None = None,
        verdict: str | None = None,
    ) -> dict[str, Any]:
        roles = [r for r in (required_roles or list(DEFAULT_ROLES)) if r in APPROVAL_ROLES]
        if not roles:
            raise WorkflowError(400, f"required_roles must be from {', '.join(APPROVAL_ROLES)}")
        now = now_iso()
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO decisions (resource_id, resource_name, title, stage, policy_id, required_roles, "
                "requested_by, owner, created, updated, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    resource_id,
                    resource_name,
                    title or f"Use of {resource_name or resource_id}",
                    "candidate",
                    policy_id,
                    json.dumps(roles),
                    actor.subject,
                    owner or actor.subject,
                    now,
                    now,
                    notes,
                ),
            )
            did = int(cur.lastrowid or 0)
            self.db.execute(
                "INSERT INTO decision_events (decision_id, at, user, from_stage, to_stage, note, verdict) "
                "VALUES (?,?,?,?,?,?,?)",
                (did, now, actor.subject, None, "candidate", "opened", verdict),
            )
            self.db.commit()
        return self.decision(did)

    def decision(self, did: int) -> dict[str, Any]:
        with self.lock:
            cur = self.db.execute("SELECT * FROM decisions WHERE id=?", (did,))
            d = _row(cur, cur.fetchone())
            if not d:
                raise WorkflowError(404, f"no decision {did}")
            d["required_roles"] = json.loads(d["required_roles"])
            d["events"] = _rows(
                self.db.execute("SELECT * FROM decision_events WHERE decision_id=? ORDER BY id", (did,))
            )
            d["approvals"] = _rows(
                self.db.execute("SELECT * FROM approvals WHERE decision_id=? ORDER BY id", (did,))
            )
            d["comments"] = _rows(
                self.db.execute("SELECT * FROM comments WHERE decision_id=? ORDER BY id", (did,))
            )
            d["tasks"] = _rows(
                self.db.execute("SELECT * FROM review_tasks WHERE decision_id=? ORDER BY id", (did,))
            )
            d["feedback"] = _rows(
                self.db.execute("SELECT * FROM feedback WHERE decision_id=? ORDER BY id", (did,))
            )
        d["signoff"] = self.signoff_state(d)
        return d

    def decisions(
        self, *, stage: str | None = None, resource_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM decisions", []  # type: str, list[Any]
        conds = []
        if stage:
            conds.append("stage=?")
            args.append(stage)
        if resource_id:
            conds.append("resource_id=?")
            args.append(resource_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY updated DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = _rows(self.db.execute(q, args))
        for r in rows:
            r["required_roles"] = json.loads(r["required_roles"])
        return rows

    @staticmethod
    def signoff_state(d: dict[str, Any]) -> dict[str, Any]:
        """Latest verdict per role, and whether the required set is complete."""
        latest: dict[str, dict[str, Any]] = {}
        for a in d.get("approvals", []):
            latest[a["role"]] = a
        required = d["required_roles"]
        approved = [r for r in required if latest.get(r, {}).get("verdict") == "approve"]
        rejected = [r for r, a in latest.items() if a.get("verdict") == "reject"]
        missing = [r for r in required if r not in approved]
        return {
            "required": required,
            "approved": approved,
            "rejected": rejected,
            "missing": missing,
            "complete": not missing and not rejected,
        }

    def transition(
        self, actor: Actor, did: int, to_stage: str, *, note: str | None = None, verdict: str | None = None
    ) -> dict[str, Any]:
        if to_stage not in STAGES:
            raise WorkflowError(400, f"unknown stage {to_stage}")
        if not actor.can_sign:
            raise WorkflowError(403, "stage changes need the reviewer or admin role")
        d = self.decision(did)
        if to_stage not in TRANSITIONS[d["stage"]]:
            raise WorkflowError(409, f"cannot move from {d['stage']} to {to_stage}")
        if to_stage == "approved" and not d["signoff"]["complete"]:
            s = d["signoff"]
            raise WorkflowError(
                409,
                f"sign-offs incomplete: missing {', '.join(s['missing']) or '-'}; rejected {', '.join(s['rejected']) or '-'}",
            )
        now = now_iso()
        with self.lock:
            self.db.execute("UPDATE decisions SET stage=?, updated=? WHERE id=?", (to_stage, now, did))
            self.db.execute(
                "INSERT INTO decision_events (decision_id, at, user, from_stage, to_stage, note, verdict) VALUES (?,?,?,?,?,?,?)",
                (did, now, actor.subject, d["stage"], to_stage, note, verdict),
            )
            self.db.commit()
        return self.decision(did)

    def sign(
        self, actor: Actor, did: int, role: str, verdict: str, note: str | None = None
    ) -> dict[str, Any]:
        if role not in APPROVAL_ROLES:
            raise WorkflowError(400, f"role must be one of {', '.join(APPROVAL_ROLES)}")
        if verdict not in ("approve", "reject"):
            raise WorkflowError(400, "verdict must be approve or reject")
        if not actor.can_sign:
            raise WorkflowError(403, "sign-offs need the reviewer or admin role")
        d = self.decision(did)
        if d["stage"] not in ("under_review", "candidate"):
            raise WorkflowError(409, f"decision is {d['stage']}; sign-offs are recorded under review")
        now = now_iso()
        with self.lock:
            self.db.execute(
                "INSERT INTO approvals (decision_id, at, user, role, verdict, note) VALUES (?,?,?,?,?,?)",
                (did, now, actor.subject, role, verdict, note),
            )
            if d["stage"] == "candidate":
                self.db.execute("UPDATE decisions SET stage='under_review', updated=? WHERE id=?", (now, did))
                self.db.execute(
                    "INSERT INTO decision_events (decision_id, at, user, from_stage, to_stage, note) VALUES (?,?,?,?,?,?)",
                    (did, now, actor.subject, "candidate", "under_review", f"first sign-off ({role})"),
                )
            else:
                self.db.execute("UPDATE decisions SET updated=? WHERE id=?", (now, did))
            self.db.commit()
        if verdict == "reject":
            return self.transition(
                actor, did, "rejected", note=f"{role} rejected" + (f": {note}" if note else "")
            )
        return self.decision(did)

    # --- comments, tasks, feedback ----------------------------------------------------

    def comment(self, actor: Actor, did: int, body: str, parent_id: int | None = None) -> dict[str, Any]:
        if not body.strip():
            raise WorkflowError(400, "empty comment")
        self.decision(did)
        now = now_iso()
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO comments (decision_id, parent_id, at, user, body) VALUES (?,?,?,?,?)",
                (did, parent_id, now, actor.subject, body.strip()[:5000]),
            )
            self.db.execute("UPDATE decisions SET updated=? WHERE id=?", (now, did))
            self.db.commit()
            cid = int(cur.lastrowid or 0)
            c = self.db.execute("SELECT * FROM comments WHERE id=?", (cid,))
            return _row(c, c.fetchone()) or {}

    def add_task(
        self, actor: Actor, did: int, title: str, *, assignee: str | None = None, due: str | None = None
    ) -> dict[str, Any]:
        if not title.strip():
            raise WorkflowError(400, "task needs a title")
        self.decision(did)
        now = now_iso()
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO review_tasks (decision_id, title, assignee, due, status, created_by, created) VALUES (?,?,?,?,?,?,?)",
                (did, title.strip()[:500], assignee, due, "open", actor.subject, now),
            )
            self.db.execute("UPDATE decisions SET updated=? WHERE id=?", (now, did))
            self.db.commit()
            tid = int(cur.lastrowid or 0)
            c = self.db.execute("SELECT * FROM review_tasks WHERE id=?", (tid,))
            return _row(c, c.fetchone()) or {}

    def set_task(self, actor: Actor, tid: int, status: str, note: str | None = None) -> dict[str, Any]:
        if status not in TASK_STATUS:
            raise WorkflowError(400, f"status must be one of {', '.join(TASK_STATUS)}")
        now = now_iso()
        with self.lock:
            c = self.db.execute("SELECT * FROM review_tasks WHERE id=?", (tid,))
            t = _row(c, c.fetchone())
            if not t:
                raise WorkflowError(404, f"no task {tid}")
            self.db.execute(
                "UPDATE review_tasks SET status=?, completed=?, note=? WHERE id=?",
                (status, now if status != "open" else None, note, tid),
            )
            self.db.execute("UPDATE decisions SET updated=? WHERE id=?", (now, t["decision_id"]))
            self.db.commit()
            c = self.db.execute("SELECT * FROM review_tasks WHERE id=?", (tid,))
            return _row(c, c.fetchone()) or {}

    def open_tasks(self, assignee: str | None = None) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM review_tasks WHERE status='open'", []  # type: str, list[Any]
        if assignee:
            q += " AND assignee=?"
            args.append(assignee)
        with self.lock:
            return _rows(self.db.execute(q + " ORDER BY due IS NULL, due, id", args))

    def add_feedback(
        self,
        actor: Actor,
        *,
        resource_id: str,
        kind: str,
        body: str | None = None,
        rating: int | None = None,
        decision_id: int | None = None,
    ) -> dict[str, Any]:
        if kind not in FEEDBACK_KINDS:
            raise WorkflowError(400, f"kind must be one of {', '.join(FEEDBACK_KINDS)}")
        if rating is not None and not 1 <= int(rating) <= 5:
            raise WorkflowError(400, "rating is 1–5")
        if not (body and body.strip()) and rating is None:
            raise WorkflowError(400, "feedback needs a body or a rating")
        if decision_id is not None:
            self.decision(decision_id)
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO feedback (resource_id, decision_id, at, user, kind, body, rating, status) VALUES (?,?,?,?,?,?,?,?)",
                (
                    resource_id,
                    decision_id,
                    now_iso(),
                    actor.subject,
                    kind,
                    (body or "").strip()[:5000] or None,
                    rating,
                    "open",
                ),
            )
            self.db.commit()
            fid = int(cur.lastrowid or 0)
            c = self.db.execute("SELECT * FROM feedback WHERE id=?", (fid,))
            return _row(c, c.fetchone()) or {}

    def set_feedback(self, actor: Actor, fid: int, status: str) -> dict[str, Any]:
        if status not in FEEDBACK_STATUS:
            raise WorkflowError(400, f"status must be one of {', '.join(FEEDBACK_STATUS)}")
        if not actor.can_sign:
            raise WorkflowError(403, "feedback triage needs the reviewer or admin role")
        with self.lock:
            c = self.db.execute("SELECT id FROM feedback WHERE id=?", (fid,))
            if not c.fetchone():
                raise WorkflowError(404, f"no feedback {fid}")
            self.db.execute(
                "UPDATE feedback SET status=?, resolved_by=?, resolved=? WHERE id=?",
                (
                    status,
                    actor.subject if status == "resolved" else None,
                    now_iso() if status == "resolved" else None,
                    fid,
                ),
            )
            self.db.commit()
            c = self.db.execute("SELECT * FROM feedback WHERE id=?", (fid,))
            return _row(c, c.fetchone()) or {}

    def feedback_for(
        self, resource_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        q, args = "SELECT * FROM feedback", []  # type: str, list[Any]
        conds = []
        if resource_id:
            conds.append("resource_id=?")
            args.append(resource_id)
        if status:
            conds.append("status=?")
            args.append(status)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        with self.lock:
            return _rows(self.db.execute(q + " ORDER BY id DESC LIMIT ?", [*args, limit]))

    def feedback_summary(self, resource_id: str) -> dict[str, Any]:
        items = self.feedback_for(resource_id, limit=1000)
        ratings = [int(i["rating"]) for i in items if i.get("rating")]
        return {
            "count": len(items),
            "open": sum(1 for i in items if i["status"] == "open"),
            "rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "ratings": len(ratings),
            "by_kind": {
                k: sum(1 for i in items if i["kind"] == k)
                for k in FEEDBACK_KINDS
                if any(i["kind"] == k for i in items)
            },
        }

    # --- export -------------------------------------------------------------------------

    def packet(
        self, did: int, *, resource: dict[str, Any] | None = None, instance: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """One self-contained record of the decision: lifecycle, sign-offs, discussion, and the
        resource's trust profile as it was when the packet was exported."""
        d = self.decision(did)
        snapshot = None
        if resource:
            snapshot = {
                "id": resource.get("id"),
                "name": resource.get("name"),
                "vendor": resource.get("vendor"),
                "url": resource.get("url"),
                "identity": resource.get("identity"),
                "trust": resource.get("trust"),
                "protocols": resource.get("protocols"),
                "compliance": [
                    {
                        k: c.get(k)
                        for k in (
                            "framework",
                            "variant",
                            "tier",
                            "status",
                            "issuer",
                            "valid_until",
                            "evidence_url",
                            "source",
                        )
                    }
                    for c in resource.get("compliance") or []
                ],
                "security": resource.get("security"),
                "issues": resource.get("issues"),
            }
        return {
            "format": "agentdossier-decision-packet/1",
            "exported_at": now_iso(),
            "instance": instance or {},
            "decision": {
                k: v
                for k, v in d.items()
                if k not in ("events", "approvals", "comments", "tasks", "feedback", "signoff")
            },
            "signoff": d["signoff"],
            "events": d["events"],
            "approvals": d["approvals"],
            "comments": d["comments"],
            "tasks": d["tasks"],
            "feedback": d["feedback"],
            "resource_snapshot": snapshot,
        }

    @staticmethod
    def packet_csv(p: dict[str, Any]) -> str:
        """The packet flattened: one row per event, approval, comment, task and feedback item."""
        out = io.StringIO()
        w = csv.writer(out)
        d = p["decision"]
        w.writerow(
            [
                "decision_id",
                "resource_id",
                "resource_name",
                "title",
                "stage",
                "policy_id",
                "required_roles",
                "owner",
                "created",
                "updated",
            ]
        )
        w.writerow(
            [
                d["id"],
                d["resource_id"],
                d["resource_name"],
                d["title"],
                d["stage"],
                d["policy_id"],
                " ".join(d["required_roles"]),
                d["owner"],
                d["created"],
                d["updated"],
            ]
        )
        w.writerow([])
        w.writerow(["kind", "at", "user", "field1", "field2", "text"])
        for e in p["events"]:
            w.writerow(
                ["event", e["at"], e["user"], e.get("from_stage") or "", e["to_stage"], e.get("note") or ""]
            )
        for a in p["approvals"]:
            w.writerow(["approval", a["at"], a["user"], a["role"], a["verdict"], a.get("note") or ""])
        for c in p["comments"]:
            w.writerow(["comment", c["at"], c["user"], c.get("parent_id") or "", "", c["body"]])
        for t in p["tasks"]:
            w.writerow(
                ["task", t["created"], t["created_by"], t.get("assignee") or "", t["status"], t["title"]]
            )
        for f in p["feedback"]:
            w.writerow(
                ["feedback", f["at"], f["user"], f["kind"], f.get("rating") or "", f.get("body") or ""]
            )
        return out.getvalue()

    def decisions_csv(self) -> str:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(
            [
                "id",
                "resource_id",
                "resource_name",
                "title",
                "stage",
                "policy_id",
                "required_roles",
                "approved_roles",
                "rejected_roles",
                "requested_by",
                "owner",
                "created",
                "updated",
            ]
        )
        for d in self.decisions(limit=10000):
            full = self.decision(d["id"])
            s = full["signoff"]
            w.writerow(
                [
                    d["id"],
                    d["resource_id"],
                    d["resource_name"],
                    d["title"],
                    d["stage"],
                    d["policy_id"],
                    " ".join(d["required_roles"]),
                    " ".join(s["approved"]),
                    " ".join(s["rejected"]),
                    d["requested_by"],
                    d["owner"],
                    d["created"],
                    d["updated"],
                ]
            )
        return out.getvalue()
