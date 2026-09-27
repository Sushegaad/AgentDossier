"""Self-hosted AgentDossier server: one process serving the ARD REST API, policy
qualification, scan control and the web UI (BRD §4.3–4.4).

    uvicorn agentdossier.server.app:app --host 0.0.0.0 --port 8080

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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..util import now_iso
from .auth import Auth
from .catalog import Catalog
from .settings import Settings

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

    if settings.auth_mode == "oidc":
        from starlette.middleware.sessions import SessionMiddleware  # noqa: PLC0415

        app.add_middleware(
            SessionMiddleware, secret_key=settings.session_secret or "", https_only=False, same_site="lax"
        )

    # --- enterprise config and scheduler ----------------------------------------------
    if settings.enterprise_config:
        from ..enterprise.config import load  # noqa: PLC0415

        state["config"] = load(settings.enterprise_config)

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
                    return
                report = scanner.scan(cfg)
                catalog.path = Path(report["catalog"])
                n = catalog.reload()
                store.finish_scan(scan_id, "done", report, resources=n)
                store.audit(user, "scan.done", f"resources={n}")
            except Exception as exc:  # noqa: BLE001
                log.exception("scan failed")
                store.finish_scan(scan_id, "error", {"error": f"{type(exc).__name__}: {exc}"})
            finally:
                state["scan_lock"].release()

        threading.Thread(target=work, daemon=True, name=f"scan-{scan_id}").start()
        return {"scanId": scan_id, "status": "running"}

    cfg = state["config"]
    if cfg is not None and cfg.schedule:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415
            from apscheduler.triggers.cron import CronTrigger  # noqa: PLC0415

            sched = BackgroundScheduler(timezone="UTC")
            sched.add_job(
                lambda: run_scan("schedule"),
                CronTrigger.from_crontab(cfg.schedule),
                id="scan",
                replace_existing=True,
            )
            sched.start()
            state["scheduler"] = sched
        except ImportError:
            log.warning("apscheduler not installed; schedule ignored")

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
    def user(request: Request, admin: bool = False):
        return auth.require(request, admin=admin)

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
        return {
            "query": q,
            "count": len(hits),
            "results": [to_result(h) for h in hits],
            "catalog": catalog.meta,
        }

    @app.post("/explore")
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
    def qualify(request: Request, body: dict[str, Any] = Body(...)):
        u = user(request)
        policy = body.get("policy") or body.get("policyId")
        if not policy:
            raise HTTPException(400, "policy (inline) or policyId is required")
        if isinstance(policy, str) and policy not in catalog.policies:
            raise HTTPException(404, f"unknown policyId {policy}")
        ids = body.get("resourceIds")
        results = catalog.qualify(policy, ids)
        store.audit(
            u.subject,
            "qualify",
            f"policy={policy if isinstance(policy, str) else policy.get('id', 'inline')} n={len(results)}",
        )
        return {
            "policyId": policy if isinstance(policy, str) else policy.get("id", "inline"),
            "count": len(results),
            "results": results,
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


try:  # module-level app for `uvicorn agentdossier.server.app:app`
    app = create_app()
except Exception as _exc:  # noqa: BLE001 - surfaced on first request instead of import time
    _err = str(_exc)
    app = FastAPI(title="AgentDossier (misconfigured)")

    @app.get("/{path:path}")
    def _misconfigured(path: str):
        return JSONResponse({"error": _err}, status_code=500)
