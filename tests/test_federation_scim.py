"""Wk 16: ARD federation (referrals / auto), the SCIM 2.0 stub with deprovisioning, and the
hardening middleware (headers, body cap, rate limit)."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from agentdossier.server.federation import Federation, Peer, peers_from_env

fastapi = pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")
from fastapi.testclient import TestClient  # noqa: E402

from agentdossier.build import BuildOptions, build  # noqa: E402
from agentdossier.server.app import create_app  # noqa: E402
from agentdossier.server.settings import Settings  # noqa: E402


@pytest.fixture(scope="module")
def catalog_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("catalog")
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
    return out


def _settings(catalog_dir: Path, tmp_path: Path, **kw) -> Settings:
    base = dict(
        catalog_dir=catalog_dir,
        db_path=tmp_path / "s.db",
        web_dist=None,
        auth_mode="none",
        api_token=None,
        admin_token=None,
        enterprise_config=None,
        start_scheduler=False,
    )
    base.update(kw)
    return Settings(**base)


def _serve(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, f"http://127.0.0.1:{port}"


def test_mode_narrowing_and_hop_cut():
    f = Federation([Peer("https://peer.example")], "referrals")
    assert f.effective_mode(None, None) == "referrals"
    assert f.effective_mode("auto", None) == "referrals"  # cannot widen
    assert f.effective_mode("none", None) == "none"
    assert f.effective_mode("auto", "1") == "none"  # a federated query is never federated again
    assert Federation([], "auto").effective_mode("auto", None) == "none"
    with pytest.raises(ValueError):
        Federation([], "sideways")
    assert [p.base for p in peers_from_env(" https://a.example/, https://b.example ")] == [
        "https://a.example",
        "https://b.example",
    ]


def test_referrals_then_auto_against_a_live_peer(catalog_dir, tmp_path):
    """Peer = a second AgentDossier instance (REST). Static-manifest peers are covered below."""
    peer_app = create_app(_settings(catalog_dir, tmp_path / "peer", site="https://peer.example/"))
    server, base = _serve(peer_app)
    try:
        local = TestClient(
            create_app(
                _settings(catalog_dir, tmp_path / "local", federation_peers=base, federation_mode="auto")
            )
        )
        st = local.get("/api/status").json()
        assert st["federation"] == {"mode": "auto", "peers": [base]}
        r = local.post("/search", json={"query": "claims", "limit": 3, "federation": "referrals"}).json()
        assert (
            r["federation"]["mode"] == "referrals"
            and r["federation"]["referrals"][0]["search"] == f"{base}/search"
        )
        assert all("source_registry" not in x for x in r["results"])
        r = local.post("/search", json={"query": "claims", "limit": 3, "federation": "auto"}).json()
        assert r["federation"]["mode"] == "auto"
        peers = r["federation"]["peers"]
        assert (
            peers[0]["registry"] == base
            and peers[0]["via"] == "rest"
            and peers[0]["count"] == 3
            and "error" not in peers[0]
        )
        remote = [x for x in r["results"] if x.get("source_registry") == base]
        assert (
            len(remote) == 3
            and remote[0]["url"].startswith("https://peer.example/agents/")
            and r["count"] == 6
        )
        # the peer saw a hop header and did not federate further (no nested federation block)
        r2 = local.post("/search", json={"query": "claims", "limit": 2, "federation": "none"}).json()
        assert "federation" not in r2
    finally:
        server.should_exit = True


def test_static_manifest_peer_and_dead_peer(catalog_dir, tmp_path):
    """A peer without a REST API (the public demo) is matched on its /.well-known/ard.json."""
    import http.server

    manifest = json.loads((catalog_dir / "ard.json").read_text())
    manifest["entries"].append(
        {
            "identifier": "urn:air:peer.example:catalog:claims-triage-bot",
            "displayName": "Claims Triage Bot",
            "type": "application/a2a-agent-card+json",
            "url": "https://peer.example/claims",
            "description": "insurance claims intake and triage",
            "tags": ["insurance", "claims"],
            "representativeQueries": ["claims intake agent"],
        }
    )

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/.well-known/ard.json":
                body = json.dumps(manifest).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/ai-registry+json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):  # noqa: N802
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    static = f"http://127.0.0.1:{srv.server_port}"
    dead = "http://127.0.0.1:9"
    try:
        local = TestClient(
            create_app(
                _settings(
                    catalog_dir,
                    tmp_path,
                    federation_peers=f"{static},{dead}",
                    federation_mode="auto",
                    federation_timeout=1,
                )
            )
        )
        r = local.post("/search", json={"query": "claims triage", "limit": 5, "federation": "auto"}).json()
        by = {p["registry"]: p for p in r["federation"]["peers"]}
        assert by[static]["via"] == "manifest" and by[static]["count"] >= 1
        assert "error" in by[dead] and by[dead]["count"] == 0
        hit = next(x for x in r["results"] if x.get("source_registry") == static)
        assert hit["displayName"] == "Claims Triage Bot" and hit["identifier"].startswith(
            "urn:air:peer.example"
        )
    finally:
        srv.shutdown()


def test_scim_provisioning_and_deprovisioning(catalog_dir, tmp_path):
    app = create_app(_settings(catalog_dir, tmp_path, scim_token="scim-secret"))
    c = TestClient(app)
    h = {"Authorization": "Bearer scim-secret"}
    assert c.get("/scim/v2/Users").status_code == 401
    spc = c.get("/scim/v2/ServiceProviderConfig", headers=h)
    assert (
        spc.status_code == 200
        and spc.headers["content-type"].startswith("application/scim+json")
        and spc.json()["patch"]["supported"]
    )
    u = c.post(
        "/scim/v2/Users",
        headers=h,
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "alice@example.com",
            "externalId": "okta-1",
            "displayName": "Alice",
            "emails": [{"value": "alice@example.com", "primary": True}],
            "active": True,
        },
    )
    assert u.status_code == 201 and u.json()["active"] and u.json()["meta"]["resourceType"] == "User"
    uid = u.json()["id"]
    assert c.post("/scim/v2/Users", headers=h, json={"userName": "alice@example.com"}).status_code == 409
    lst = c.get('/scim/v2/Users?filter=userName eq "alice@example.com"', headers=h).json()
    assert lst["totalResults"] == 1 and lst["Resources"][0]["id"] == uid
    assert c.get("/scim/v2/Users?filter=title pr", headers=h).status_code == 400
    assert c.get("/scim/v2/Users/nope", headers=h).status_code == 404
    assert c.get("/scim/v2/Groups", headers=h).json()["totalResults"] == 0
    scim = app.state.settings  # the Auth hook is what matters:
    assert scim is not None
    from agentdossier.server.scim import Scim

    s = Scim(app.state.store.db, app.state.store.lock, "scim-secret")
    assert s.allowed(subject="okta-1", email="alice@example.com") and s.allowed(
        subject="unknown", email="nobody@example.com"
    )
    p = c.patch(
        f"/scim/v2/Users/{uid}",
        headers=h,
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
    )
    assert p.status_code == 200 and p.json()["active"] is False
    assert not s.allowed(subject="okta-1", email=None) and not s.allowed(
        subject=None, email="alice@example.com"
    )
    p = c.patch(
        f"/scim/v2/Users/{uid}",
        headers=h,
        json={"Operations": [{"op": "replace", "value": {"active": True, "displayName": "Alice L."}}]},
    )
    assert p.json()["active"] and p.json()["displayName"] == "Alice L."
    r = c.put(
        f"/scim/v2/Users/{uid}",
        headers=h,
        json={
            "userName": "alice@example.com",
            "externalId": "okta-1",
            "emails": [{"value": "a.l@example.com", "primary": True}],
            "active": False,
        },
    )
    assert r.json()["emails"][0]["value"] == "a.l@example.com" and not r.json()["active"]
    assert c.delete(f"/scim/v2/Users/{uid}", headers=h).status_code == 204
    assert c.delete(f"/scim/v2/Users/{uid}", headers=h).status_code == 404
    assert s.allowed(subject="okta-1", email=None)  # gone from SCIM: the IdP decides again
    actions = [e["action"] for e in c.get("/api/audit").json()["events"]]
    assert "scim.user.create" in actions and "scim.user.delete" in actions


def test_hardening_headers_body_cap_and_rate_limit(catalog_dir, tmp_path):
    c = TestClient(
        create_app(
            _settings(
                catalog_dir, tmp_path, site="https://reg.example/", max_body_bytes=2000, rate_limit="3/minute"
            )
        )
    )
    r = c.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert (
        r.headers["strict-transport-security"].startswith("max-age=")
        and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    )
    assert c.get("/api/status").headers["cache-control"] == "no-store"
    big = c.post("/search", json={"query": "x" * 5000})
    assert big.status_code == 413
    codes = [c.post("/search", json={"query": "claims"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert c.get("/healthz").status_code == 200  # the limit is per route, not global
