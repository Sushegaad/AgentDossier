"""Operations: health, status, scans, audit, reload, deliveries, notifications, evidence expiry."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ... import __version__
from ..deps import deps
from ..jobs import run_expiry, run_scan
from ..notify import evidence_expiring

router = APIRouter()


# --- operations -------------------------------------------------------------------
@router.get("/healthz")
def healthz():
    return {"ok": True}  # liveness only; version and counts are on /api/status (authenticated)


@router.get("/api/status")
def status(request: Request):
    d = deps(request)
    d.user(request)
    c = d.state["config"]
    return {
        "version": __version__,
        "catalog": {**d.catalog.meta, "resources": len(d.catalog.records), "path": str(d.catalog.path)},
        "auth_mode": d.settings.auth_mode,
        "enterprise": {
            "tenant": c.tenant,
            "ticket": c.ticket,
            "schedule": c.schedule,
            "targets": len(c.target_hosts) + len(c.target_cidrs) + len(c.dns_domains),
        }
        if c
        else None,
        "scans": d.store.scans(5),
        "notify": {"channels": d.notifier.channels, "events": sorted(d.settings.notify.events)},
        "jobs": d.state.get("jobs", []),
        "federation": {"mode": d.settings.federation_mode, "peers": [p.base for p in d.federation.peers]},
        "scim": d.scim.enabled,
    }


@router.post("/api/scan")
def scan_now(request: Request):
    d = deps(request)
    u = d.user(request, admin=True)
    return run_scan(d, "manual", u.subject)


@router.get("/api/scans")
def scans(request: Request):
    d = deps(request)
    d.user(request)
    return {"scans": d.store.scans(50)}


@router.get("/api/scans/{scan_id}")
def scan_report(request: Request, scan_id: int):
    d = deps(request)
    d.user(request)
    rep = d.store.scan_report(scan_id)
    if rep is None:
        raise HTTPException(404, "no report")
    return rep


@router.get("/api/audit")
def audit(request: Request):
    d = deps(request)
    d.user(request, admin=True)
    return {"events": d.store.audit_log()}


@router.post("/api/reload")
def reload(request: Request):
    d = deps(request)
    u = d.user(request, admin=True)
    n = d.catalog.reload()
    d.store.audit(u.subject, "catalog.reload", f"resources={n}")
    return {"resources": n}


@router.get("/api/deliveries")
def deliveries(request: Request):
    d = deps(request)
    d.user(request, admin=True)
    return {"channels": d.notifier.channels, "deliveries": d.store.deliveries(100)}


@router.post("/api/notify/test")
def notify_test(request: Request):
    d = deps(request)
    u = d.user(request, admin=True)
    if not d.notifier.channels:
        raise HTTPException(400, "no notification channel configured (SMTP_* or AGENTDOSSIER_WEBHOOK_URL)")
    out = d.notifier.send(
        "test", "test notification", f"Sent by {u.subject} from {d.settings.site}", {"by": u.subject}
    )
    d.store.audit(u.subject, "notify.test", ", ".join(f"{d['channel']}={d['status']}" for d in out))
    return {"deliveries": out}


@router.get("/api/evidence/expiring")
def expiring(request: Request, days: int = Query(30, ge=0, le=730)):
    d = deps(request)
    d.user(request)
    full = [d.catalog.resource(r["id"]) or r for r in d.catalog.records]
    return {"days": days, "items": evidence_expiring(full, days=days)}


@router.post("/api/jobs/evidence-expiry")
def expiry_now(request: Request):
    d = deps(request)
    u = d.user(request, admin=True)
    return run_expiry(d, f"manual:{u.subject}")
