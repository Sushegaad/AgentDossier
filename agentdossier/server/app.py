"""Self-hosted AgentDossier server: one process serving the ARD REST API, policy
qualification, scan control and the web UI (BRD §4.3–4.4).

    uvicorn --factory agentdossier.server.app:create_app --host 0.0.0.0 --port 8080

Routes
------
ARD REST (public read, subject to auth mode)
  GET  /.well-known/ard.json        registry self-description + entries
  POST /search                      {query, limit, filters} -> ranked, explained results
  POST /explore                     {domain?, type?} -> counts by domain / type / evidence tier
  GET  /agents                      paged listing (pageSize, pageToken)
  GET  /agents/{id}                 full resource (id or slug)
  POST /qualify                     {policy | policyId, resourceIds?} -> verdict per resource (FR-38)
  GET  /policies                    policy templates shipped with the instance
Operations (admin)
  POST /api/scan                    start an authorized scan now (background)
  GET  /api/scans, /api/scans/{id}  scan history and reports
  GET  /api/audit                   audit trail
  POST /api/reload                  reload the catalog from disk
  GET  /api/deliveries              notification deliveries (email, webhook)
  POST /api/notify/test             send a test notification to every channel
  GET  /api/evidence/expiring       compliance records expiring or due for recheck
  POST /api/jobs/evidence-expiry    run the daily expiry job now
Decision workflow (FR-28, FR-34, FR-35; members read and open, reviewers sign and move)
  GET/POST /api/decisions           list / open a decision for a resource (runs the policy if given)
  GET  /api/decisions/export.csv    every decision with its sign-off state
  GET  /api/decisions/{id}          decision with events, approvals, comments, tasks, feedback
  POST /api/decisions/{id}/stage    {stage, note}            reviewer
  POST /api/decisions/{id}/sign     {role, verdict, note}    reviewer
  POST /api/decisions/{id}/comments {body, parentId}
  POST /api/decisions/{id}/tasks    {title, assignee, due}
  GET  /api/decisions/{id}/export   ?format=json|csv — the decision packet with a trust snapshot
  POST /api/tasks/{id}              {status, note}
  GET  /api/tasks                   open review tasks (?assignee=)
  GET/POST /api/feedback            feedback on a resource (?resourceId=, ?status=)
  POST /api/feedback/{id}           {status}                 reviewer
Integrations (server/integrations.py): Slack, Teams, Jira, ServiceNow, GRC webhook are extra
  notification channels configured by environment; GET /api/status lists the active ones.
Federation (server/federation.py): POST /search {federation: none|referrals|auto} answers with
  `referrals` to peer registries or, in auto mode, their hits marked source_registry.
SCIM 2.0 (server/scim.py, on when SCIM_TOKEN is set)
  GET  /scim/v2/ServiceProviderConfig · GET/POST /scim/v2/Users · GET/PUT/PATCH/DELETE /scim/v2/Users/{id}
  GET  /scim/v2/Groups              a deprovisioned user is refused at sign-in
Hardening: security headers on every response, request bodies capped (AGENTDOSSIER_MAX_BODY_BYTES),
  per-client rate limit on /search, /explore and /qualify (AGENTDOSSIER_RATE_LIMIT).
  GET  /healthz, /api/status        liveness and instance info
Static
  /catalog/*                        the catalog files (index.json, agents/…)
  /*                                the web UI when web/dist is present (built with SITE_BASE=/)
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..util import now_iso
from .auth import Auth
from .catalog import Catalog
from .federation import HOP_HEADER, Federation, peers_from_env
from .integrations import build_integrations
from .notify import Notifier, catalog_diff, evidence_expiring, expiry_text, scan_text
from .scim import LIST_SCHEMA, Scim, scim_error
from .settings import Settings
from .workflow import Actor, Workflow, WorkflowError

log = logging.getLogger("agentdossier.server")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    problems = settings.validate()
    if problems:
        raise RuntimeError("; ".join(problems))
    from ..storage.db import Store  # noqa: PLC0415

    app = FastAPI(
        title="AgentDossier", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    catalog = Catalog(settings.catalog_dir)
    store = Store(settings.db_path)
    auth = Auth(settings)
    state: dict[str, Any] = {"scan_lock": threading.Lock(), "scheduler": None, "config": None}
    notifier = Notifier(settings.notify, store, site=settings.site, tenant=None)
    flow = Workflow(store.db, store.lock)
    settings.integrations.packet_for = lambda did: flow.packet(
        did,
        resource=catalog.resource(flow.decision(did)["resource_id"]),
        instance={**catalog.meta, "site": settings.site},
    )
    notifier.integrations = build_integrations(settings.integrations)
    federation = Federation(
        peers_from_env(
            settings.federation_peers, token=settings.federation_token, timeout=settings.federation_timeout
        ),
        settings.federation_mode,
    )
    scim = Scim(store.db, store.lock, settings.scim_token, site=settings.site)
    auth.allowed = scim.allowed

    # --- hardening: headers, body cap, rate limit ------------------------------------------
    @app.middleware("http")
    async def _harden(request: Request, call_next):  # noqa: ANN001
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Cache-Control",
            "no-store"
            if request.url.path.startswith(("/api/", "/scim/", "/auth/"))
            else "public, max-age=300",
        )
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
        if settings.behind_tls_proxy or settings.site.startswith("https://"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    limiter: Any = None
    if settings.rate_limit:
        try:
            from slowapi import Limiter  # noqa: PLC0415
            from slowapi.errors import RateLimitExceeded  # noqa: PLC0415
            from slowapi.util import get_remote_address  # noqa: PLC0415

            limiter = Limiter(key_func=get_remote_address, default_limits=[])
            app.state.limiter = limiter

            @app.exception_handler(RateLimitExceeded)
            async def _rl(request: Request, exc: RateLimitExceeded):  # noqa: ANN001
                return JSONResponse(
                    {"error": "rate limit exceeded", "detail": str(exc.detail)},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
        except ImportError:  # pragma: no cover
            log.warning("slowapi not installed; rate limiting off")

    def limited(fn):  # noqa: ANN001
        return limiter.limit(settings.rate_limit)(fn) if limiter else fn

    if settings.auth_mode == "oidc":
        from starlette.middleware.sessions import SessionMiddleware  # noqa: PLC0415

        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.session_secret or "",
            https_only=settings.behind_tls_proxy or settings.site.startswith("https://"),
            same_site="lax",
        )

    # --- enterprise config and scheduler ----------------------------------------------
    if settings.enterprise_config:
        from ..enterprise.config import load  # noqa: PLC0415

        state["config"] = load(settings.enterprise_config)
        notifier.tenant = state["config"].tenant

    def run_scan(trigger: str, user: str = "system") -> dict[str, Any]:
        cfg = state["config"]
        if cfg is None:
            raise HTTPException(400, "no enterprise configuration (set AGENTDOSSIER_ENTERPRISE_CONFIG)")
        if not state["scan_lock"].acquire(blocking=False):
            raise HTTPException(409, "a scan is already running")
        scan_id = store.start_scan(trigger)
        store.audit(user, "scan.start", f"trigger={trigger} tenant={cfg.tenant} ticket={cfg.ticket}")

        def work() -> None:
            from ..enterprise import preflight, scanner  # noqa: PLC0415

            try:
                pf = preflight.run(cfg)
                if not pf.ok:
                    store.finish_scan(scan_id, "preflight_failed", pf.as_dict())
                    failed = [c for c in pf.as_dict().get("checks", []) if c.get("status") == "fail"]
                    notifier.send(
                        "scan.failed",
                        f"scan #{scan_id} stopped at preflight",
                        "Preflight failed:\n"
                        + "\n".join(f"  {c.get('id')}: {c.get('message')}" for c in failed),
                        {"scanId": scan_id, "preflight": pf.as_dict()},
                    )
                    return
                before = list(catalog.records)
                report = scanner.scan(cfg)
                catalog.path = Path(report["catalog"])
                n = catalog.reload()
                store.finish_scan(scan_id, "done", report, resources=n)
                store.audit(user, "scan.done", f"resources={n}")
                diff = catalog_diff(before, catalog.records)
                summary = {
                    k: v
                    for k, v in report.items()
                    if k in ("tenant", "ticket", "resources", "errors", "finished")
                }
                notifier.send(
                    "scan.done",
                    f"scan #{scan_id} done: {n} resources",
                    scan_text(report, diff, settings.site),
                    {"scanId": scan_id, "report": summary, "diff": diff},
                )
                if diff["added"] or diff["removed"] or diff["changed"]:
                    notifier.send(
                        "catalog.changed",
                        f"catalog changed: +{len(diff['added'])} -{len(diff['removed'])} ~{len(diff['changed'])}",
                        scan_text(report, diff, settings.site),
                        {"scanId": scan_id, "diff": diff},
                    )
            except Exception as exc:  # noqa: BLE001
                log.exception("scan failed")
                store.finish_scan(scan_id, "error", {"error": f"{type(exc).__name__}: {exc}"})
                notifier.send(
                    "scan.failed",
                    f"scan #{scan_id} failed",
                    f"{type(exc).__name__}: {exc}",
                    {"scanId": scan_id},
                )
            finally:
                state["scan_lock"].release()

        threading.Thread(target=work, daemon=True, name=f"scan-{scan_id}").start()
        return {"scanId": scan_id, "status": "running"}

    def run_expiry(trigger: str = "schedule") -> dict[str, Any]:
        """Daily job: warn about compliance evidence that expires or is due for a recheck."""
        full = [catalog.resource(r["id"]) or r for r in catalog.records]
        items = evidence_expiring(full, days=settings.notify.expiry_warning_days)
        store.audit("system", "evidence.expiry", f"trigger={trigger} items={len(items)}")
        deliveries: list[dict[str, Any]] = []
        if items:
            deliveries = notifier.send(
                "evidence.expiring",
                f"{len(items)} compliance record(s) expiring or due for recheck",
                expiry_text(items, settings.site),
                {"items": items},
            )
        return {"items": items, "deliveries": deliveries}

    cfg = state["config"]
    jobs: list[tuple[str, str, Any]] = []
    if cfg is not None and cfg.schedule:
        jobs.append(("scan", cfg.schedule, lambda: run_scan("schedule")))
    if settings.expiry_cron and notifier.channels:
        jobs.append(("evidence_expiry", settings.expiry_cron, lambda: run_expiry("schedule")))
    if jobs and settings.start_scheduler:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415
            from apscheduler.triggers.cron import CronTrigger  # noqa: PLC0415

            sched = BackgroundScheduler(timezone="UTC")
            for job_id, cron, fn in jobs:
                sched.add_job(fn, CronTrigger.from_crontab(cron), id=job_id, replace_existing=True)
            sched.start()
            state["scheduler"] = sched
        except ImportError:
            log.warning("apscheduler not installed; schedule ignored")
    state["jobs"] = [{"id": j, "cron": c} for j, c, _ in jobs]

    @app.middleware("http")
    async def _scan_on_first_request(request: Request, call_next):  # noqa: ANN001
        if settings.scan_on_start and state["config"] is not None and not state.get("started"):
            state["started"] = True
            try:
                run_scan("startup")
            except HTTPException:
                pass
        return await call_next(request)

    # --- helpers ----------------------------------------------------------------------
    def user(request: Request, admin: bool = False, reviewer: bool = False):
        return auth.require(request, admin=admin, reviewer=reviewer)

    def to_result(hit) -> dict[str, Any]:  # noqa: ANN001
        r = hit.record
        return {
            "identifier": f"urn:air:{catalog.index.get('tenant') or 'agentdossier'}:catalog:{r['slug']}",
            "resourceId": r["id"],
            "displayName": r["name"],
            "vendor": r.get("vendor"),
            "type": r.get("resource_type"),
            "url": f"{settings.site.rstrip('/')}/agents/{r['slug']}/",
            "description": r.get("description"),
            "score": hit.score,
            "explanation": hit.explanation,
            "trust": r.get("trust"),
            "protocols": r.get("protocols"),
            "compliance": r.get("compliance_summary", []),
            "domains": r.get("domains", {}),
        }

    # --- ARD REST ----------------------------------------------------------------------
    @app.get("/.well-known/ard.json")
    def ard_manifest(request: Request):
        p = catalog.path / "ard.json"
        if p.exists():
            return FileResponse(p, media_type="application/ai-registry+json")
        return {"entries": []}

    @app.post("/search")
    @limited
    def search(request: Request, body: dict[str, Any] = Body(default={})):
        user(request)
        q = str(body.get("query") or "")
        limit = min(int(body.get("limit") or 20), 100)
        f = body.get("filters") or {}
        hits = catalog.search(
            q,
            limit=limit,
            domain=f.get("domain"),
            resource_type=f.get("type"),
            framework=f.get("framework"),
            max_tier=f.get("maxTier"),
            protocol=f.get("protocol"),
        )
        out: dict[str, Any] = {
            "query": q,
            "count": len(hits),
            "results": [to_result(h) for h in hits],
            "catalog": catalog.meta,
        }
        mode = federation.effective_mode(body.get("federation"), request.headers.get(HOP_HEADER))
        if mode == "referrals":
            out["federation"] = {"mode": mode, "referrals": federation.referrals(q)}
        elif mode == "auto":
            peers = federation.query(body)
            merged = []
            for p in peers:
                for r in p["results"]:
                    merged.append({**r, "source_registry": p["registry"]})
            out["federation"] = {
                "mode": mode,
                "peers": [{k: v for k, v in p.items() if k != "results"} for p in peers],
            }
            out["results"] += merged
            out["count"] = len(out["results"])
        return out

    @app.post("/explore")
    @limited
    def explore(request: Request, body: dict[str, Any] = Body(default={})):
        user(request)
        domain, rtype = body.get("domain"), body.get("type")
        recs = [
            r
            for r in catalog.records
            if (not domain or domain in r.get("domains", {}))
            and (not rtype or r.get("resource_type") == rtype)
        ]
        by_domain: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        by_protocol: dict[str, int] = {}
        for r in recs:
            for d in r.get("domains", {}):
                by_domain[d] = by_domain.get(d, 0) + 1
            by_type[r.get("resource_type", "?")] = by_type.get(r.get("resource_type", "?"), 0) + 1
            t = f"T{r.get('trust', {}).get('compliance', 5)}"
            by_tier[t] = by_tier.get(t, 0) + 1
            for p, s in (r.get("protocols") or {}).items():
                if s in ("verified", "claimed"):
                    by_protocol[p] = by_protocol.get(p, 0) + 1
        return {
            "total": len(recs),
            "byDomain": by_domain,
            "byType": by_type,
            "byEvidenceTier": dict(sorted(by_tier.items())),
            "byProtocol": by_protocol,
        }

    @app.get("/agents")
    def agents(request: Request, pageSize: int = Query(100, ge=1, le=500), pageToken: str | None = None):  # noqa: N803 - ARD REST names
        user(request)
        recs = sorted(catalog.records, key=lambda r: r["name"].lower())
        start = int(pageToken) if pageToken and pageToken.isdigit() else 0
        page = recs[start : start + pageSize]
        nxt = str(start + pageSize) if start + pageSize < len(recs) else None
        return {
            "agents": [
                {
                    "identifier": f"urn:air:{catalog.index.get('tenant') or 'agentdossier'}:catalog:{r['slug']}",
                    "displayName": r["name"],
                    "type": r.get("resource_type"),
                    "url": f"{settings.site.rstrip('/')}/agents/{r['slug']}/",
                    "resourceId": r["id"],
                }
                for r in page
            ],
            "total": len(recs),
            "pageSize": pageSize,
            "nextPageToken": nxt,
        }

    @app.get("/agents/{ident}")
    def agent(request: Request, ident: str):
        user(request)
        res = catalog.resource(ident)
        if not res:
            raise HTTPException(404, "unknown resource")
        return res

    @app.get("/policies")
    def policies(request: Request):
        user(request)
        return {
            "policies": [
                {
                    "id": k,
                    "name": v.get("name"),
                    "version": v.get("version"),
                    "jurisdictions": v.get("jurisdictions"),
                    "rules": len(v.get("rules", [])),
                }
                for k, v in catalog.policies.items()
            ]
        }

    @app.post("/qualify")
    @limited
    def qualify(request: Request, body: dict[str, Any] = Body(...)):
        u = user(request)
        policy = body.get("policy") or body.get("policyId")
        if not policy:
            raise HTTPException(400, "policy (inline) or policyId is required")
        if isinstance(policy, str) and policy not in catalog.policies:
            raise HTTPException(404, f"unknown policyId {policy}")
        ids = body.get("resourceIds")
        results = catalog.qualify(policy, ids)
        not_found = [i for i in ids or [] if catalog.resource(str(i)) is None]
        for r in results:  # echo the slug so callers that asked by slug can match the answer
            rec = catalog.by_id.get(r["resourceId"])
            if rec:
                r["slug"] = rec.get("slug")
        store.audit(
            u.subject,
            "qualify",
            f"policy={policy if isinstance(policy, str) else policy.get('id', 'inline')} n={len(results)}",
        )
        return {
            "policyId": policy if isinstance(policy, str) else policy.get("id", "inline"),
            "count": len(results),
            "results": results,
            "notFound": not_found,
        }

    # --- operations -------------------------------------------------------------------
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__, "resources": len(catalog.records), "at": now_iso()}

    @app.get("/api/status")
    def status(request: Request):
        user(request)
        c = state["config"]
        return {
            "version": __version__,
            "catalog": {**catalog.meta, "resources": len(catalog.records), "path": str(catalog.path)},
            "auth_mode": settings.auth_mode,
            "enterprise": {
                "tenant": c.tenant,
                "ticket": c.ticket,
                "schedule": c.schedule,
                "targets": len(c.target_hosts) + len(c.target_cidrs) + len(c.dns_domains),
            }
            if c
            else None,
            "scans": store.scans(5),
            "notify": {"channels": notifier.channels, "events": sorted(settings.notify.events)},
            "jobs": state.get("jobs", []),
            "federation": {"mode": settings.federation_mode, "peers": [p.base for p in federation.peers]},
            "scim": scim.enabled,
        }

    @app.post("/api/scan")
    def scan_now(request: Request):
        u = user(request, admin=True)
        return run_scan("manual", u.subject)

    @app.get("/api/scans")
    def scans(request: Request):
        user(request)
        return {"scans": store.scans(50)}

    @app.get("/api/scans/{scan_id}")
    def scan_report(request: Request, scan_id: int):
        user(request)
        rep = store.scan_report(scan_id)
        if rep is None:
            raise HTTPException(404, "no report")
        return rep

    @app.get("/api/audit")
    def audit(request: Request):
        user(request, admin=True)
        return {"events": store.audit_log()}

    @app.post("/api/reload")
    def reload(request: Request):
        u = user(request, admin=True)
        n = catalog.reload()
        store.audit(u.subject, "catalog.reload", f"resources={n}")
        return {"resources": n}

    @app.get("/api/deliveries")
    def deliveries(request: Request):
        user(request, admin=True)
        return {"channels": notifier.channels, "deliveries": store.deliveries(100)}

    @app.post("/api/notify/test")
    def notify_test(request: Request):
        u = user(request, admin=True)
        if not notifier.channels:
            raise HTTPException(
                400, "no notification channel configured (SMTP_* or AGENTDOSSIER_WEBHOOK_URL)"
            )
        out = notifier.send(
            "test", "test notification", f"Sent by {u.subject} from {settings.site}", {"by": u.subject}
        )
        store.audit(u.subject, "notify.test", ", ".join(f"{d['channel']}={d['status']}" for d in out))
        return {"deliveries": out}

    @app.get("/api/evidence/expiring")
    def expiring(request: Request, days: int = Query(30, ge=0, le=730)):
        user(request)
        full = [catalog.resource(r["id"]) or r for r in catalog.records]
        return {"days": days, "items": evidence_expiring(full, days=days)}

    @app.post("/api/jobs/evidence-expiry")
    def expiry_now(request: Request):
        u = user(request, admin=True)
        return run_expiry(f"manual:{u.subject}")

    # --- decision workflow ------------------------------------------------------------------
    def actor(request: Request, *, reviewer: bool = False) -> Actor:
        u = user(request, reviewer=reviewer)
        return Actor(u.subject, u.name, set(u.roles))

    def _flow(fn):  # noqa: ANN001 - translate workflow errors into HTTP
        try:
            return fn()
        except WorkflowError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    def _decision_event(d: dict[str, Any], what: str, who: str) -> None:
        store.audit(who, f"decision.{what}", f"id={d['id']} resource={d['resource_id']} stage={d['stage']}")
        notifier.send(
            "decision.changed",
            f"decision #{d['id']} {what}: {d['title']} → {d['stage']}",
            f"{who} — {what}\nDecision #{d['id']}: {d['title']}\nStage: {d['stage']}\n"
            f"Sign-offs: approved {', '.join(d['signoff']['approved']) or '-'}; missing {', '.join(d['signoff']['missing']) or '-'}\n"
            f"{settings.site.rstrip('/')}/api/decisions/{d['id']}",
            {"decisionId": d["id"], "stage": d["stage"], "signoff": d["signoff"], "by": who, "what": what},
        )

    @app.get("/api/decisions")
    def list_decisions(request: Request, stage: str | None = None, resourceId: str | None = None):  # noqa: N803
        user(request)
        return {"decisions": flow.decisions(stage=stage, resource_id=resourceId)}

    @app.get("/api/decisions/export.csv")
    def decisions_csv(request: Request):
        user(request)
        return PlainTextResponse(flow.decisions_csv(), media_type="text/csv")

    @app.post("/api/decisions", status_code=201)
    def open_decision(request: Request, body: dict[str, Any] = Body(...)):
        a = actor(request)
        rid = body.get("resourceId")
        if not rid:
            raise HTTPException(400, "resourceId is required")
        res = catalog.resource(str(rid))
        if not res:
            raise HTTPException(404, "unknown resource")
        verdict = None
        pid = body.get("policyId")
        if pid:
            if pid not in catalog.policies:
                raise HTTPException(404, f"unknown policyId {pid}")
            results = catalog.qualify(pid, [res["id"]])
            verdict = results[0]["verdict"] if results else None
        d = _flow(
            lambda: flow.create_decision(
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
        )
        _decision_event(d, "opened", a.subject)
        return d

    @app.get("/api/decisions/{did}")
    def get_decision(request: Request, did: int):
        user(request)
        return _flow(lambda: flow.decision(did))

    @app.post("/api/decisions/{did}/stage")
    def set_stage(request: Request, did: int, body: dict[str, Any] = Body(...)):
        a = actor(request, reviewer=True)
        stage = str(body.get("stage") or "")
        verdict = None
        d0 = _flow(lambda: flow.decision(did))
        if stage == "approved" and d0.get("policy_id"):
            results = catalog.qualify(d0["policy_id"], [d0["resource_id"]])
            verdict = results[0]["verdict"] if results else None
        d = _flow(lambda: flow.transition(a, did, stage, note=body.get("note"), verdict=verdict))
        _decision_event(d, f"moved to {stage}", a.subject)
        return d

    @app.post("/api/decisions/{did}/sign")
    def sign_decision(request: Request, did: int, body: dict[str, Any] = Body(...)):
        a = actor(request, reviewer=True)
        d = _flow(
            lambda: flow.sign(
                a, did, str(body.get("role") or ""), str(body.get("verdict") or ""), body.get("note")
            )
        )
        _decision_event(d, f"{body.get('role')} {body.get('verdict')}", a.subject)
        return d

    @app.post("/api/decisions/{did}/comments", status_code=201)
    def add_comment(request: Request, did: int, body: dict[str, Any] = Body(...)):
        a = actor(request)
        c = _flow(lambda: flow.comment(a, did, str(body.get("body") or ""), body.get("parentId")))
        store.audit(a.subject, "decision.comment", f"id={did} comment={c['id']}")
        return c

    @app.post("/api/decisions/{did}/tasks", status_code=201)
    def add_task(request: Request, did: int, body: dict[str, Any] = Body(...)):
        a = actor(request)
        t = _flow(
            lambda: flow.add_task(
                a, did, str(body.get("title") or ""), assignee=body.get("assignee"), due=body.get("due")
            )
        )
        store.audit(a.subject, "decision.task", f"id={did} task={t['id']}")
        return t

    @app.get("/api/decisions/{did}/export")
    def export_decision(request: Request, did: int, format: str = Query("json", pattern="^(json|csv)$")):  # noqa: A002
        u = user(request)
        d = _flow(lambda: flow.decision(did))
        res = catalog.resource(d["resource_id"])
        packet = flow.packet(
            did, resource=res, instance={**catalog.meta, "site": settings.site, "exported_by": u.subject}
        )
        store.audit(u.subject, "decision.export", f"id={did} format={format}")
        if format == "csv":
            return PlainTextResponse(
                flow.packet_csv(packet),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="decision-{did}.csv"'},
            )
        return JSONResponse(
            packet, headers={"Content-Disposition": f'attachment; filename="decision-{did}.json"'}
        )

    @app.get("/api/tasks")
    def tasks(request: Request, assignee: str | None = None):
        user(request)
        return {"tasks": flow.open_tasks(assignee)}

    @app.post("/api/tasks/{tid}")
    def set_task(request: Request, tid: int, body: dict[str, Any] = Body(...)):
        a = actor(request)
        t = _flow(lambda: flow.set_task(a, tid, str(body.get("status") or ""), body.get("note")))
        store.audit(a.subject, "task.status", f"task={tid} status={t['status']}")
        return t

    @app.get("/api/feedback")
    def list_feedback(request: Request, resourceId: str | None = None, status: str | None = None):  # noqa: N803
        user(request)
        out: dict[str, Any] = {"feedback": flow.feedback_for(resourceId, status)}
        if resourceId:
            out["summary"] = flow.feedback_summary(resourceId)
        return out

    @app.post("/api/feedback", status_code=201)
    def add_feedback(request: Request, body: dict[str, Any] = Body(...)):
        a = actor(request)
        rid = body.get("resourceId")
        res = catalog.resource(str(rid or ""))
        if not res:
            raise HTTPException(404, "unknown resource")
        f = _flow(
            lambda: flow.add_feedback(
                a,
                resource_id=res["id"],
                kind=str(body.get("kind") or "note"),
                body=body.get("body"),
                rating=body.get("rating"),
                decision_id=body.get("decisionId"),
            )
        )
        store.audit(a.subject, "feedback.add", f"resource={res['id']} kind={f['kind']} id={f['id']}")
        return f

    @app.post("/api/feedback/{fid}")
    def triage_feedback(request: Request, fid: int, body: dict[str, Any] = Body(...)):
        a = actor(request, reviewer=True)
        f = _flow(lambda: flow.set_feedback(a, fid, str(body.get("status") or "")))
        store.audit(a.subject, "feedback.status", f"id={fid} status={f['status']}")
        return f

    # --- SCIM 2.0 ------------------------------------------------------------------------------
    if scim.enabled:
        scim_mt = "application/scim+json"

        @app.get("/scim/v2/ServiceProviderConfig")
        def scim_spc(request: Request):
            scim.require(request)
            return JSONResponse(scim.service_provider_config(), media_type=scim_mt)

        @app.get("/scim/v2/Users")
        def scim_users(request: Request, filter: str | None = None, startIndex: int = 1, count: int = 100):  # noqa: A002, N803
            scim.require(request)
            try:
                return JSONResponse(scim.list(filter, startIndex, min(count, 200)), media_type=scim_mt)
            except HTTPException as exc:
                return scim_error(exc.status_code, str(exc.detail))

        @app.post("/scim/v2/Users", status_code=201)
        def scim_create(request: Request, body: dict[str, Any] = Body(...)):
            scim.require(request)
            try:
                u = scim.create(body)
            except HTTPException as exc:
                return scim_error(exc.status_code, str(exc.detail))
            store.audit("scim", "scim.user.create", f"{u['userName']} id={u['id']}")
            return JSONResponse(u, status_code=201, media_type=scim_mt)

        @app.get("/scim/v2/Users/{uid}")
        def scim_get(request: Request, uid: str):
            scim.require(request)
            try:
                return JSONResponse(scim.get(uid), media_type=scim_mt)
            except HTTPException as exc:
                return scim_error(exc.status_code, str(exc.detail))

        @app.put("/scim/v2/Users/{uid}")
        def scim_put(request: Request, uid: str, body: dict[str, Any] = Body(...)):
            scim.require(request)
            try:
                u = scim.replace(uid, body)
            except HTTPException as exc:
                return scim_error(exc.status_code, str(exc.detail))
            store.audit("scim", "scim.user.replace", f"{u['userName']} active={u['active']}")
            return JSONResponse(u, media_type=scim_mt)

        @app.patch("/scim/v2/Users/{uid}")
        def scim_patch(request: Request, uid: str, body: dict[str, Any] = Body(...)):
            scim.require(request)
            try:
                u = scim.patch(uid, body)
            except HTTPException as exc:
                return scim_error(exc.status_code, str(exc.detail))
            store.audit("scim", "scim.user.patch", f"{u['userName']} active={u['active']}")
            return JSONResponse(u, media_type=scim_mt)

        @app.delete("/scim/v2/Users/{uid}", status_code=204)
        def scim_delete(request: Request, uid: str):
            scim.require(request)
            try:
                scim.delete(uid)
            except HTTPException as exc:
                return scim_error(exc.status_code, str(exc.detail))
            store.audit("scim", "scim.user.delete", uid)
            return JSONResponse(None, status_code=204)

        @app.get("/scim/v2/Groups")
        def scim_groups(request: Request):
            scim.require(request)
            return JSONResponse(
                {
                    "schemas": [LIST_SCHEMA],
                    "totalResults": 0,
                    "startIndex": 1,
                    "itemsPerPage": 0,
                    "Resources": [],
                },
                media_type=scim_mt,
            )

    # --- OIDC login flow --------------------------------------------------------------------
    if settings.auth_mode == "oidc":

        @app.get("/auth/login")
        async def login(request: Request):
            redirect = str(request.url_for("auth_callback"))
            return await auth.oauth.idp.authorize_redirect(request, redirect)

        @app.get("/auth/callback", name="auth_callback")
        async def auth_callback(request: Request):
            token = await auth.oauth.idp.authorize_access_token(request)
            info = token.get("userinfo") or await auth.oauth.idp.userinfo(token=token)
            request.session["user"] = {
                "sub": info.get("sub"),
                "name": info.get("name"),
                "email": info.get("email"),
                "groups": info.get("groups") or [],
            }
            store.audit(str(info.get("sub")), "login", str(info.get("email") or ""))
            return RedirectResponse("/")

        @app.get("/auth/logout")
        async def logout(request: Request):
            request.session.clear()
            return RedirectResponse("/")

        @app.get("/auth/me")
        def me(request: Request):
            u = auth.current(request)
            return {"user": u.__dict__ if u else None}

    # --- static: catalog files and the web UI ----------------------------------------------
    @app.get("/catalog/{path:path}")
    def catalog_file(request: Request, path: str):
        user(request)
        base = catalog.path.resolve()
        target = (base / path).resolve()
        if base not in target.parents and target != base:
            raise HTTPException(404)
        if not target.is_file():
            raise HTTPException(404)
        return FileResponse(target)

    dist = settings.web_dist
    if dist and (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")
    else:

        @app.get("/")
        def root():
            return JSONResponse(
                {
                    "name": "AgentDossier",
                    "version": __version__,
                    "docs": "/api/docs",
                    "ard": "/.well-known/ard.json",
                }
            )

    app.state.catalog = catalog
    app.state.store = store
    app.state.settings = settings
    return app


# No module-level instance: run with `uvicorn --factory agentdossier.server.app:create_app` (or
# `agentdossier serve`). A misconfigured instance then fails at startup instead of serving errors.
