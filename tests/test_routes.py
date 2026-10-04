"""The route table is the server's public contract: PR 4 split app.py into routers and this
test pins every (method, path) so a refactor cannot drop or rename an endpoint unnoticed."""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from agentdossier.build import BuildOptions, build  # noqa: E402
from agentdossier.server.app import create_app  # noqa: E402
from agentdossier.server.settings import Settings  # noqa: E402

EXPECTED = {
    ("GET", "/.well-known/ard.json"),
    ("POST", "/search"),
    ("POST", "/explore"),
    ("GET", "/agents"),
    ("GET", "/agents/{ident}"),
    ("GET", "/policies"),
    ("POST", "/qualify"),
    ("GET", "/healthz"),
    ("GET", "/api/status"),
    ("POST", "/api/scan"),
    ("GET", "/api/scans"),
    ("GET", "/api/scans/{scan_id}"),
    ("GET", "/api/audit"),
    ("POST", "/api/reload"),
    ("GET", "/api/deliveries"),
    ("POST", "/api/notify/test"),
    ("GET", "/api/evidence/expiring"),
    ("POST", "/api/jobs/evidence-expiry"),
    ("GET", "/api/decisions"),
    ("GET", "/api/decisions/export.csv"),
    ("POST", "/api/decisions"),
    ("GET", "/api/decisions/{did}"),
    ("POST", "/api/decisions/{did}/stage"),
    ("POST", "/api/decisions/{did}/sign"),
    ("POST", "/api/decisions/{did}/comments"),
    ("POST", "/api/decisions/{did}/tasks"),
    ("GET", "/api/decisions/{did}/export"),
    ("GET", "/api/tasks"),
    ("POST", "/api/tasks/{tid}"),
    ("GET", "/api/feedback"),
    ("POST", "/api/feedback"),
    ("POST", "/api/feedback/{fid}"),
    ("GET", "/catalog/{path:path}"),
    ("GET", "/scim/v2/ServiceProviderConfig"),
    ("GET", "/scim/v2/Users"),
    ("POST", "/scim/v2/Users"),
    ("GET", "/scim/v2/Users/{uid}"),
    ("PUT", "/scim/v2/Users/{uid}"),
    ("PATCH", "/scim/v2/Users/{uid}"),
    ("DELETE", "/scim/v2/Users/{uid}"),
    ("GET", "/scim/v2/Groups"),
    ("GET", "/auth/login"),
    ("GET", "/auth/callback"),
    ("GET", "/auth/logout"),
    ("GET", "/auth/me"),
}


def _routes(app) -> set[tuple[str, str]]:
    out = set()

    def walk(routes):
        for r in routes:
            inner = getattr(r, "routes", None) or getattr(getattr(r, "original_router", None), "routes", None)
            if inner is not None:  # included routers nest their routes (FastAPI wraps them)
                walk(inner)
                continue
            methods = getattr(r, "methods", None)
            if not methods:
                continue
            for m in methods - {"HEAD", "OPTIONS"}:
                out.add((m, r.path))

    walk(app.routes)
    return out


def test_route_table_is_stable(tmp_path: Path):
    out = tmp_path / "catalog"
    build(
        BuildOptions(
            out_dir=out,
            cache_dir=out / "cache",
            offline=True,
            write_review=False,
            compliance=False,
            news=False,
        )
    )
    app = create_app(
        Settings(
            catalog_dir=out,
            db_path=tmp_path / "r.db",
            web_dist=None,
            auth_mode="oidc",
            oidc_issuer="https://idp.example",
            oidc_client_id="c",
            oidc_client_secret="s",
            session_secret="x" * 32,
            scim_token="scim",
            enterprise_config=None,
            start_scheduler=False,
        )
    )
    got = {
        (m, p)
        for m, p in _routes(app)
        if not p.startswith("/api/docs")
        and p not in ("/api/openapi.json", "/docs/oauth2-redirect", "/", "/redoc")
    }
    missing, extra = EXPECTED - got, got - EXPECTED
    assert not missing and not extra, f"missing={sorted(missing)} extra={sorted(extra)}"
