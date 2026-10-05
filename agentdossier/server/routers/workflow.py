"""Decision workflow (FR-28, FR-34, FR-35): decisions, sign-offs, comments, tasks, feedback, export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from ..deps import Deps, deps

router = APIRouter()


def _decision_event(d: Deps, dec: dict[str, Any], what: str, who: str) -> None:
    d.store.audit(
        who, f"decision.{what}", f"id={dec['id']} resource={dec['resource_id']} stage={dec['stage']}"
    )
    d.notifier.send(
        "decision.changed",
        f"decision #{dec['id']} {what}: {dec['title']} → {dec['stage']}",
        f"{who} — {what}\nDecision #{dec['id']}: {dec['title']}\nStage: {dec['stage']}\n"
        f"Sign-offs: approved {', '.join(dec['signoff']['approved']) or '-'}; missing {', '.join(dec['signoff']['missing']) or '-'}\n"
        f"{d.settings.site.rstrip('/')}/api/decisions/{dec['id']}",
        {"decisionId": dec["id"], "stage": dec["stage"], "signoff": dec["signoff"], "by": who, "what": what},
    )


@router.get("/api/decisions")
def list_decisions(request: Request, stage: str | None = None, resourceId: str | None = None):  # noqa: N803
    d = deps(request)
    d.user(request)
    return {"decisions": d.flow.decisions(stage=stage, resource_id=resourceId)}


@router.get("/api/decisions/export.csv")
def decisions_csv(request: Request):
    d = deps(request)
    d.user(request)
    return PlainTextResponse(d.flow.decisions_csv(), media_type="text/csv")


@router.post("/api/decisions", status_code=201)
def open_decision(request: Request, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request)
    rid = body.get("resourceId")
    if not rid:
        raise HTTPException(400, "resourceId is required")
    res = d.catalog.resource(str(rid))
    if not res:
        raise HTTPException(404, "unknown resource")
    verdict = None
    pid = body.get("policyId")
    if pid:
        if pid not in d.catalog.policies:
            raise HTTPException(404, f"unknown policyId {pid}")
        results = d.catalog.qualify(pid, [res["id"]])
        verdict = results[0]["verdict"] if results else None
    dec = d.flow.create_decision(
        a,
        resource_id=res["id"],
        resource_name=res.get("name"),
        title=body.get("title"),
        policy_id=pid,
        required_roles=body.get("requiredRoles"),
        owner=body.get("owner"),
        notes=body.get("notes"),
        verdict=verdict,
    )
    _decision_event(d, dec, "opened", a.subject)
    return dec


@router.get("/api/decisions/{did}")
def get_decision(request: Request, did: int):
    d = deps(request)
    d.user(request)
    return d.flow.decision(did)


@router.post("/api/decisions/{did}/stage")
def set_stage(request: Request, did: int, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request, reviewer=True)
    stage = str(body.get("stage") or "")
    verdict = None
    dec0 = d.flow.decision(did)
    if stage == "approved" and dec0.get("policy_id"):
        results = d.catalog.qualify(dec0["policy_id"], [dec0["resource_id"]])
        verdict = results[0]["verdict"] if results else None
    dec = d.flow.transition(a, did, stage, note=body.get("note"), verdict=verdict)
    _decision_event(d, dec, f"moved to {stage}", a.subject)
    return dec


@router.post("/api/decisions/{did}/sign")
def sign_decision(request: Request, did: int, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request, reviewer=True)
    dec = d.flow.sign(a, did, str(body.get("role") or ""), str(body.get("verdict") or ""), body.get("note"))
    _decision_event(d, dec, f"{body.get('role')} {body.get('verdict')}", a.subject)
    return dec


@router.post("/api/decisions/{did}/comments", status_code=201)
def add_comment(request: Request, did: int, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request)
    c = d.flow.comment(a, did, str(body.get("body") or ""), body.get("parentId"))
    d.store.audit(a.subject, "decision.comment", f"id={did} comment={c['id']}")
    return c


@router.post("/api/decisions/{did}/tasks", status_code=201)
def add_task(request: Request, did: int, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request)
    t = d.flow.add_task(
        a, did, str(body.get("title") or ""), assignee=body.get("assignee"), due=body.get("due")
    )
    d.store.audit(a.subject, "decision.task", f"id={did} task={t['id']}")
    return t


@router.get("/api/decisions/{did}/export")
def export_decision(request: Request, did: int, format: str = Query("json", pattern="^(json|csv)$")):  # noqa: A002
    d = deps(request)
    u = d.user(request)
    dec = d.flow.decision(did)
    res = d.catalog.resource(dec["resource_id"])
    packet = d.flow.packet(
        did, resource=res, instance={**d.catalog.meta, "site": d.settings.site, "exported_by": u.subject}
    )
    d.store.audit(u.subject, "decision.export", f"id={did} format={format}")
    if format == "csv":
        return PlainTextResponse(
            d.flow.packet_csv(packet),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="decision-{did}.csv"'},
        )
    return JSONResponse(
        packet, headers={"Content-Disposition": f'attachment; filename="decision-{did}.json"'}
    )


@router.get("/api/tasks")
def tasks(request: Request, assignee: str | None = None):
    d = deps(request)
    d.user(request)
    return {"tasks": d.flow.open_tasks(assignee)}


@router.post("/api/tasks/{tid}")
def set_task(request: Request, tid: int, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request)
    t = d.flow.set_task(a, tid, str(body.get("status") or ""), body.get("note"))
    d.store.audit(a.subject, "task.status", f"task={tid} status={t['status']}")
    return t


@router.get("/api/feedback")
def list_feedback(request: Request, resourceId: str | None = None, status: str | None = None):  # noqa: N803
    d = deps(request)
    d.user(request)
    out: dict[str, Any] = {"feedback": d.flow.feedback_for(resourceId, status)}
    if resourceId:
        out["summary"] = d.flow.feedback_summary(resourceId)
    return out


@router.post("/api/feedback", status_code=201)
def add_feedback(request: Request, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request)
    rid = body.get("resourceId")
    res = d.catalog.resource(str(rid or ""))
    if not res:
        raise HTTPException(404, "unknown resource")
    f = d.flow.add_feedback(
        a,
        resource_id=res["id"],
        kind=str(body.get("kind") or "note"),
        body=body.get("body"),
        rating=body.get("rating"),
        decision_id=body.get("decisionId"),
    )
    d.store.audit(a.subject, "feedback.add", f"resource={res['id']} kind={f['kind']} id={f['id']}")
    return f


@router.post("/api/feedback/{fid}")
def triage_feedback(request: Request, fid: int, body: dict[str, Any] = Body(...)):
    d = deps(request)
    a = d.actor(request, reviewer=True)
    f = d.flow.set_feedback(a, fid, str(body.get("status") or ""))
    d.store.audit(a.subject, "feedback.status", f"id={fid} status={f['status']}")
    return f
