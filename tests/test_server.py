"""Self-hosted server: ARD REST API, /qualify (FR-38), auth modes, scan control (needs the server extra)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentdossier.build import BuildOptions, build  # noqa: E402
from agentdossier.enterprise.selftest import FixturePublisher  # noqa: E402
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
    base = {
        "catalog_dir": catalog_dir,
        "db_path": tmp_path / "srv.db",
        "web_dist": None,
        "auth_mode": "none",
        "api_token": None,
        "admin_token": None,
        "enterprise_config": None,
    }
    base.update(kw)
    return Settings(**base)


def test_ard_rest_search_agents_and_qualify(catalog_dir, tmp_path):
    c = TestClient(create_app(_settings(catalog_dir, tmp_path)))
    assert c.get("/healthz").json()["resources"] == 158
    r = c.post("/search", json={"query": "insurance claims agent", "limit": 5}).json()
    assert r["count"] == 5 and all("insurance" in x["domains"] for x in r["results"])
    assert r["results"][0]["explanation"] and r["results"][0]["identifier"].startswith("urn:air:")
    r = c.post("/search", json={"query": "coding agent", "filters": {"type": "framework"}}).json()
    assert all(x["type"] == "framework" for x in r["results"])
    page = c.get("/agents?pageSize=50").json()
    assert page["total"] == 158 and page["nextPageToken"] == "50" and len(page["agents"]) == 50
    page2 = c.get("/agents?pageSize=50&pageToken=150").json()
    assert len(page2["agents"]) == 8 and page2["nextPageToken"] is None
    ident = page["agents"][0]["resourceId"]
    full = c.get(f"/agents/{ident}").json()
    assert full["id"] == ident and "identity" in full and "compliance" in full
    ex = c.post("/explore", json={"domain": "insurance"}).json()
    assert ex["total"] == 100 and "T5" in ex["byEvidenceTier"]
    pols = c.get("/policies").json()["policies"]
    assert any(p["id"] == "pol_healthcare_default" for p in pols)
    q = c.post("/qualify", json={"policyId": "pol_healthcare_default", "resourceIds": [ident]}).json()
    assert q["count"] == 1 and q["results"][0]["verdict"] in (
        "disallowed",
        "unknown",
        "needs_review",
        "eligible",
    )
    inline = {
        "id": "p_inline",
        "version": 1,
        "rules": [{"id": "r1", "kind": "must", "field": "identity.tier", "op": "lte", "value": 5}],
    }
    q = c.post("/qualify", json={"policy": inline, "resourceIds": [ident]}).json()
    assert q["results"][0]["verdict"] == "eligible"
    assert c.post("/qualify", json={"policyId": "nope"}).status_code == 404
    assert c.get("/.well-known/ard.json").status_code == 200
    assert c.get("/catalog/index.json").status_code == 200
    assert c.get("/catalog/../pyproject.toml").status_code == 404


def test_token_auth_separates_readers_and_admins(catalog_dir, tmp_path):
    app = create_app(
        _settings(catalog_dir, tmp_path, auth_mode="token", api_token="reader", admin_token="boss")
    )
    c = TestClient(app)
    assert c.post("/search", json={"query": "x"}).status_code == 401
    assert (
        c.post("/search", json={"query": "x"}, headers={"Authorization": "Bearer reader"}).status_code == 200
    )
    assert c.post("/api/reload", headers={"Authorization": "Bearer reader"}).status_code == 403
    assert c.post("/api/reload", headers={"Authorization": "Bearer boss"}).status_code == 200
    audit = c.get("/api/audit", headers={"Authorization": "Bearer boss"}).json()["events"]
    assert audit and audit[0]["action"] == "catalog.reload"


def test_settings_validation_rejects_incomplete_oidc(catalog_dir, tmp_path):
    with pytest.raises(RuntimeError):
        create_app(_settings(catalog_dir, tmp_path, auth_mode="oidc"))


def test_scan_endpoint_runs_the_scanner_and_reloads_the_catalog(tmp_path):
    with FixturePublisher() as pub:
        cfg = {
            "tenant": "acme-test",
            "authorized_by": "Test Suite",
            "ticket": "T-1",
            "scope": {"allow_cidrs": ["127.0.0.0/8"]},
            "targets": {"hosts": ["127.0.0.1"]},
            "ports": [pub.port],
            "limits": {"requests_per_host_per_sec": 20, "concurrency": 2, "timeout_sec": 5},
            "output_dir": str(tmp_path / "scan"),
        }
        cfg_path = tmp_path / "enterprise.json"
        cfg_path.write_text(json.dumps(cfg))
        empty = tmp_path / "empty-catalog"
        empty.mkdir()
        app = create_app(_settings(empty, tmp_path, enterprise_config=cfg_path))
        c = TestClient(app)
        assert c.get("/healthz").json()["resources"] == 0
        started = c.post("/api/scan").json()
        assert started["status"] == "running"
        for _ in range(100):
            scans = c.get("/api/scans").json()["scans"]
            if scans and scans[0]["status"] != "running":
                break
            time.sleep(0.2)
        assert scans[0]["status"] == "done", scans
        assert c.get("/healthz").json()["resources"] >= 2
        rep = c.get(f"/api/scans/{scans[0]['id']}").json()
        assert rep["tenant"] == "acme-test" and rep["probed"][0]["ard"] == "verified"
        r = c.post("/search", json={"query": "claims intake"}).json()
        assert r["results"] and r["results"][0]["displayName"] == "Self-test Claims Intake Agent"
        st = c.get("/api/status").json()
        assert st["catalog"]["scope"] == "private" and st["enterprise"]["tenant"] == "acme-test"
