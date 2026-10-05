"""Hash-chained scan audit log (plan §Scanner): tamper-evident, truncation-evident, verifiable."""

from __future__ import annotations

import json

import pytest

from agentdossier.enterprise.audit import GENESIS, AuditLog, verify


def test_chain_verifies_and_detects_edits_truncation_and_gaps(tmp_path):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    head = log.header(tenant="acme", authorized_by="J. Smith", ticket="CHG-1", config_hash="abc", targets=2)
    assert head["prev_hash"] == GENESIS and head["seq"] == 0
    log.append("blocked", origin="https://10.9.9.9", reason="outside scope")
    log.append("probe", origin="https://a.corp", ard="verified")
    log.append("found", origin="https://a.corp", resources=["Claims Agent"])
    log.append("done", resources=1, errors=0, catalog="/x")
    ok, entries, problem = verify(p)
    assert ok and problem is None and len(entries) == 5 and entries[-1]["hash"] == log.last_hash

    lines = p.read_text().splitlines()
    # edit a line's content
    tampered = tmp_path / "t1.jsonl"
    bad = json.loads(lines[2])
    bad["origin"] = "https://b.corp"
    tampered.write_text("\n".join([*lines[:2], json.dumps(bad, sort_keys=True), *lines[3:]]) + "\n")
    ok, _, problem = verify(tampered)
    assert not ok and "edited" in problem
    # drop a line from the middle
    cut = tmp_path / "t2.jsonl"
    cut.write_text("\n".join([*lines[:2], *lines[3:]]) + "\n")
    ok, _, problem = verify(cut)
    assert not ok and "chain broken" in problem
    # drop the tail
    trunc = tmp_path / "t3.jsonl"
    trunc.write_text("\n".join(lines[:-1]) + "\n")
    ok, _, problem = verify(trunc)
    assert not ok and "done" in problem
    with pytest.raises(ValueError):
        AuditLog(p)  # written once per scan


def test_scan_writes_a_verifiable_chain(tmp_path):
    from agentdossier.enterprise import scanner
    from agentdossier.enterprise.selftest import FixturePublisher, config_for

    with FixturePublisher() as pub:
        cfg = config_for(pub.port, tmp_path / "out")
        report = scanner.scan(cfg, out_dir=tmp_path / "out")
    ok, entries, problem = verify(report["audit"])
    assert ok, problem
    kinds = [e["kind"] for e in entries]
    assert kinds[0] == "run" and kinds[-1] == "done" and "probe" in kinds and "found" in kinds
    assert entries[0]["ticket"] == cfg.ticket and entries[0]["scanner_version"]
    assert report["audit_hash"] == entries[-1]["hash"]


def test_cli_audit_verify(tmp_path, capsys):
    from agentdossier.cli import main

    p = tmp_path / "audit.jsonl"
    log = AuditLog(p)
    log.header(tenant="t", authorized_by="a", ticket="T-1", config_hash="h", targets=0)
    log.append("done", resources=0, errors=0, catalog="/c")
    assert main(["enterprise", "audit-verify", str(p)]) == 0
    assert "ok: 2 entries" in capsys.readouterr().out
    p.write_text(p.read_text().replace('"ticket": "T-1"', '"ticket": "T-2"'))
    assert main(["enterprise", "audit-verify", str(p)]) == 1


def test_ca_bundle_rides_on_the_policy(tmp_path):
    from agentdossier.enterprise.selftest import config_for

    cfg = config_for(1, tmp_path)
    cfg.ca_bundle = str(tmp_path / "corp.pem")
    assert cfg.policy.ca_bundle == cfg.ca_bundle


def test_curated_protocol_claims_need_a_named_reviewer(tmp_path):
    from agentdossier.protocol_claims import load_curated_protocols

    cur = tmp_path / "p.yaml"
    cur.write_text(
        "claims:\n"
        "  - name: A\n    checked_by: maintainer\n    checked_on: 2026-10-02\n    mcp: https://a\n"
        "  - name: B\n    checked_by: hemant.naik\n    checked_on: 2026-10-02\n    mcp: https://b\n"
    )
    assert [e["name"] for e in load_curated_protocols(cur)] == ["B"]
    assert all(e["checked_by"] != "maintainer" for e in load_curated_protocols())  # the shipped file
