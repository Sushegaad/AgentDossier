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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import __version__
from .auth import Auth
from .catalog import Catalog
from .deps import Deps
from .federation import Federation, peers_from_env
from .hardening import BodyCapMiddleware, security_headers
from .integrations import build_integrations
from .jobs import run_scan, start_scheduler
from .notify import Notifier
from .ratelimit import RateLimiter
from .routers import ard, ops, static
from .routers import auth as auth_routes
from .routers import scim as scim_routes
from .routers import workflow as workflow_routes
from .scim import Scim, scim_error
from .settings import Settings
from .workflow import Workflow, WorkflowError

log = logging.getLogger("agentdossier.server")


def build_deps(settings: Settings) -> Deps:
    """Everything the routers share, wired once."""
    from ..storage.db import Store  # noqa: PLC0415

    catalog = Catalog(settings.catalog_dir)
    store = Store(settings.db_path)
    egress = settings.egress_policy()
    notifier = Notifier(settings.notify, store, site=settings.site, tenant=None, policy=egress)
    flow = Workflow(store.db, store.lock)
    settings.integrations.packet_for = lambda did: flow.packet(
        did,
        resource=catalog.resource(flow.decision(did)["resource_id"]),
        instance={**catalog.meta, "site": settings.site},
    )
    settings.integrations.policy = egress
    notifier.integrations = build_integrations(settings.integrations)
    federation = Federation(
        peers_from_env(
            settings.federation_peers,
            token=settings.federation_token,
            timeout=settings.federation_timeout,
            policy=egress,
        ),
        settings.federation_mode,
    )
    scim = Scim(store.db, store.lock, settings.scim_token, site=settings.site)
    auth = Auth(settings)
    auth.allowed = scim.allowed
    d = Deps(
        settings=settings,
        catalog=catalog,
        store=store,
        auth=auth,
        notifier=notifier,
        flow=flow,
        scim=scim,
        federation=federation,
        limiter=RateLimiter(settings.rate_limit) if settings.rate_limit else None,
    )
    if settings.enterprise_config:
        from ..enterprise.config import load  # noqa: PLC0415

        d.state["config"] = load(settings.enterprise_config)
        notifier.tenant = d.state["config"].tenant
    return d


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    problems = settings.validate()
    if problems:
        raise RuntimeError("; ".join(problems))
    d = build_deps(settings)

    app = FastAPI(
        title="AgentDossier", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.deps = d
    app.state.catalog, app.state.store, app.state.settings = d.catalog, d.store, settings  # back-compat

    # --- errors: one place each ------------------------------------------------------------
    @app.exception_handler(WorkflowError)
    async def _workflow_error(request: Request, exc: WorkflowError):  # noqa: ANN001
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):  # noqa: ANN001
        if request.url.path.startswith("/scim/"):
            return scim_error(exc.status_code, str(exc.detail))  # RFC 7644 error shape
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    # --- middleware (outermost last) ----------------------------------------------------------
    app.add_middleware(BodyCapMiddleware, limit=settings.max_body_bytes)
    app.middleware("http")(
        security_headers(
            max_body_bytes=settings.max_body_bytes,
            hsts=settings.behind_tls_proxy or settings.site.startswith("https://"),
        )
    )
    if settings.auth_mode == "oidc":
        from starlette.middleware.sessions import SessionMiddleware  # noqa: PLC0415

        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.session_secret or "",
            https_only=settings.behind_tls_proxy or settings.site.startswith("https://"),
            same_site="lax",
        )

    @app.middleware("http")
    async def _scan_on_first_request(request: Request, call_next):  # noqa: ANN001
        if settings.scan_on_start and d.state["config"] is not None and not d.state.get("started"):
            d.state["started"] = True
            try:
                run_scan(d, "startup")
            except HTTPException:
                pass
        return await call_next(request)

    # --- routes -------------------------------------------------------------------------------
    start_scheduler(d)
    app.include_router(ard.router)
    app.include_router(ops.router)
    app.include_router(workflow_routes.router)
    if d.scim.enabled:
        app.include_router(scim_routes.router)
    if settings.auth_mode == "oidc":
        app.include_router(auth_routes.router)
    static.mount(app, d)  # catalog files and the web UI; must be last (catch-all)
    return app


# No module-level instance: run with `uvicorn --factory agentdossier.server.app:create_app` (or
# `agentdossier serve`). A misconfigured instance then fails at startup instead of serving errors.
