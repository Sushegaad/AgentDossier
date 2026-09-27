"""FR-41, FR-42: enterprise configuration, preflight, target planning and the loopback self-test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentdossier.enterprise import preflight, scanner, selftest, targets
from agentdossier.enterprise.config import ConfigError, load
from agentdossier.util import ROOT, FetchBlockedError

EXAMPLE = ROOT / "examples" / "enterprise" / "enterprise.json"


def _write(tmp_path: Path, **overrides) -> Path:
    doc = json.loads(EXAMPLE.read_text())
    doc.update(overrides)
    p = tmp_path / "enterprise.json"
    p.write_text(json.dumps(doc))
    return p


def test_example_config_loads_and_builds_an_enterprise_policy(tmp_path):
    cfg = load(_write(tmp_path, output_dir=str(tmp_path / "out")))
    assert cfg.tenant == "acme-corp" and cfg.ticket == "CHG-10432"
    pol = cfg.policy
    assert pol.mode == "enterprise" and "10.20.0.0/16" in pol.allow_cidrs
    # public internet is refused in enterprise mode, even when it resolves
    with pytest.raises(FetchBlockedError):
        pol.check("https://example.com/.well-known/ard.json")
    assert cfg.probes["mcp_handshake"] is False and cfg.limits["concurrency"] == 16
    assert cfg.missing_env() == ["AGENTREG_INTERNAL_TOKEN"]


def test_config_rejects_unknown_keys_and_bad_cidrs(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")  # noqa: F841 - schema validation path
    with pytest.raises(ConfigError):
        load(_write(tmp_path, allow_public=True))
    with pytest.raises(ConfigError):
        load(_write(tmp_path, scope={"allow_cidrs": ["10.0.0.0/99"]}))
    with pytest.raises(ConfigError):
        load(_write(tmp_path, ticket=""))


def test_schedule_is_read_when_present(tmp_path):
    cfg = load(_write(tmp_path, schedule={"cron": "0 6 * * 1"}, output_dir=str(tmp_path)))
    assert cfg.schedule == "0 6 * * 1"


def test_preflight_flags_out_of_scope_targets_and_missing_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTREG_INTERNAL_TOKEN", raising=False)
    cfg = load(_write(tmp_path, output_dir=str(tmp_path / "out"), targets={"cidrs": ["192.168.1.0/24"]}))
    pf = preflight.run(cfg, resolve_dns=False)
    ids = {c.id: c.status for c in pf.checks}
    assert ids["targets_in_scope"] == "fail"
    assert ids["auth_env"] == "fail"
    assert ids["tls"] == "fail"  # /etc/ssl/corp-root-ca.pem does not exist here
    assert not pf.ok


def test_preflight_passes_for_a_consistent_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTREG_INTERNAL_TOKEN", "x")
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    cfg = load(
        _write(
            tmp_path,
            output_dir=str(tmp_path / "out"),
            tls={"ca_bundle": str(ca)},
            targets={"cidrs": ["10.20.4.0/24"], "hosts": []},
        )
    )
    pf = preflight.run(cfg, resolve_dns=False)
    assert pf.ok, [c for c in pf.checks if c.status == "fail"]
    assert cfg.headers() == {"Authorization": "x"}


def test_plan_expands_cidrs_caps_and_refuses_out_of_scope(tmp_path):
    cfg = load(
        _write(
            tmp_path,
            output_dir=str(tmp_path),
            scope={"allow_cidrs": ["10.20.4.0/30"]},
            targets={"cidrs": ["10.20.4.0/30"], "hosts": ["10.99.0.1"]},
            ports=[443, 8080],
        )
    )
    p = targets.plan(cfg, use_dns=False)
    origins = [t["origin"] for t in p["targets"]]
    assert "https://10.20.4.1" in origins and "http://10.20.4.2:8080" in origins
    assert any(r["origin"].startswith("https://10.99.0.1") for r in p["refused"])
    hosts, warnings = targets.expand_cidrs(["10.0.0.0/8"], cap=10)
    assert len(hosts) == 10 and warnings


def test_dry_run_scan_fetches_nothing(tmp_path):
    cfg = load(_write(tmp_path, output_dir=str(tmp_path / "out"), targets={"cidrs": ["10.20.4.0/30"]}))
    rep = scanner.scan(cfg, dry_run=True, use_dns=False)
    assert rep["dry_run"] and rep["probed"] == [] and len(rep["plan"]["targets"]) > 0
    assert not (tmp_path / "out" / "catalog").exists()


def test_selftest_finds_ard_a2a_and_mcp_on_loopback(tmp_path):
    result = selftest.run(tmp_path / "selftest")
    assert result["ok"], result
    scan = next(s for s in result["steps"] if s["step"] == "scan")
    assert scan["probed"][0]["ard"] == "verified" and scan["probed"][0]["a2a"] == "verified"
    assert scan["probed"][0]["mcp"] == "claimed"
    index = json.loads((Path(result["catalog"]) / "index.json").read_text())
    assert index["scope"] == "private" and index["tenant"] == "selftest"
    assert all(r["scope"] == "private" for r in index["records"])
    report = json.loads((tmp_path / "selftest" / "scan-report.json").read_text())
    assert report["ticket"] == "SELFTEST" and report["resources"] == len(index["records"])
