"""Traces: curated public observations, the hash-chained store, and self_test bundles."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from agentdossier.traces import apply_traces, trace_tier
from agentdossier.traces.curated import load_curated
from agentdossier.traces.selftest import record_probes
from agentdossier.traces.store import GENESIS, TraceStore, bundle_hash, line_hash

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "schema" / "trace_record.schema.json").read_text())


def _validate(rec: dict) -> None:
    jsonschema.Draft202012Validator(SCHEMA).validate({k: v for k, v in rec.items() if k != "agent"})


def test_curated_traces_validate_and_expand_to_siblings():
    recs = load_curated()
    assert recs, "data/curated/traces.yaml should ship with records"
    for r in recs:
        _validate(r)
        assert r["url"].startswith("https://") and r["date"] >= "2025-01-01"
    forced = [r for r in recs if r["id"] == "tr_forcedleak_agentforce_2025"]
    assert len(forced) == 4
    assert (
        forced[0]["agent"] == "salesforce-salesforce-agentforce"
        and forced[0]["scope"] == "product"
        and forced[0]["tier"] == 2
    )
    assert all(r["scope"] == "platform" and r["tier"] == 3 for r in forced[1:])  # siblings one tier lower
    echo = next(r for r in recs if r["id"] == "tr_echoleak_m365_copilot_2025")
    assert echo["scope"] == "platform" and echo["tier"] == 3


def test_apply_traces_sets_list_and_tier():
    agentforce = {"id": "r1", "slug": "salesforce-salesforce-agentforce", "name": "Agentforce"}
    nobody = {"id": "r2", "slug": "nobody-agent", "name": "Nobody"}
    counts = apply_traces([agentforce, nobody])
    assert counts["agents_with_traces"] == 1 and counts["curated"] >= 1
    assert trace_tier(agentforce) == 2 and trace_tier(nobody) == 5 and nobody["traces"] == []
    assert "agent" not in agentforce["traces"][0]


def test_store_chain_appends_verifies_and_detects_tampering(tmp_path):
    store = TraceStore(tmp_path / "traces")
    assert store.verify() == [] and store.lines() == []
    rec = {
        "id": "tr_test_one",
        "kind": "self_test",
        "tier": 1,
        "title": "t",
        "source": "s",
        "url": "https://x.example/t",
        "date": "2026-10-11",
        "format": "bundle",
        "observed": {"outcome": "ok"},
    }
    files = {"manifest.json": b"{}", "transcript.md": b"# t\n", "verdict.json": b"{}"}
    line = store.append(rec, agent="res_a", key="k1", files=files)
    assert line["prev"] == GENESIS and line["hash"] == line_hash(line)
    assert (
        line["record"]["sha256"] == bundle_hash(files)
        and (tmp_path / "traces" / "bundles" / "tr_test_one" / "transcript.md").exists()
    )
    store.append({**rec, "id": "tr_test_two"}, agent="res_b", key="k2")
    assert store.verify() == [] and store.keys() == {"k1", "k2"}
    assert set(store.records_by_agent()) == {"res_a", "res_b"}
    # edit the bundle: the chain notices
    (tmp_path / "traces" / "bundles" / "tr_test_one" / "transcript.md").write_text("tampered")
    assert any("hash mismatch" in p for p in store.verify())
    # edit a line: every later line's prev breaks
    lines = store.index_path.read_text().splitlines()
    lines[0] = lines[0].replace('"k1"', '"kX"')
    store.index_path.write_text("\n".join(lines) + "\n")
    problems = store.verify()
    assert any("does not match" in p for p in problems) and any("prev" in p for p in problems)
    with pytest.raises(ValueError):
        store.append({**rec, "id": "tr_test_three"}, agent="r", files={"evil.sh": b"x"})


def test_shipped_store_chain_is_intact():
    assert TraceStore().verify() == []


def test_self_test_bundles_only_for_found_probes_and_only_when_changed(tmp_path):
    store = TraceStore(tmp_path / "traces")
    found = {
        "id": "res_abc123",
        "slug": "x-agent",
        "name": "X Agent",
        "publisher_domain": "x.example",
        "protocols": {
            "a2a": {
                "status": "verified",
                "card_url": "https://x.example/.well-known/agent-card.json",
                "auth_schemes": [],
                "signed": False,
                "skills": ["search"],
                "protocol_version": "0.3.0",
            },
            "mcp": {
                "status": "claimed",
                "source": "curated_claim",
                "probe": {
                    "status": "invalid",
                    "card_url": "https://x.example/.well-known/mcp.json",
                    "errors": ["not valid JSON"],
                },
            },
            "ard": {"status": "not_found"},
        },
    }
    nothing = {
        "id": "res_def456",
        "slug": "y",
        "name": "Y",
        "protocols": {
            "a2a": {"status": "not_found"},
            "mcp": {"status": "unknown"},
            "ard": {"status": "not_found"},
        },
    }
    counts = record_probes(
        [found, nothing], store, site="https://site.example/AgentDossier/", date="2026-10-11"
    )
    assert counts == {"candidates": 1, "appended": 1, "unchanged": 0}
    line = store.lines()[0]
    rec = line["record"]
    _validate(rec)
    assert (
        rec["kind"] == "self_test"
        and rec["tier"] == 1
        and rec["url"].startswith("https://site.example/AgentDossier/traces/tr_st_abc123_")
    )
    assert (
        "A2A verified (auth none; unsigned)" in rec["observed"]["outcome"]
        and "MCP invalid (1 validation error)" in rec["observed"]["outcome"]
    )
    transcript = (tmp_path / "traces" / rec["bundle"] / "transcript.md").read_text()
    assert (
        "requested `https://x.example/.well-known/agent-card.json`" in transcript
        and "not valid JSON" in transcript
    )
    # same observation next week: nothing appended
    counts = record_probes([found, nothing], store, site="https://site.example/", date="2026-10-18")
    assert counts == {"candidates": 1, "appended": 0, "unchanged": 1}
    # the card changes: a new bundle, the old one untouched
    found["protocols"]["a2a"]["signed"] = True
    counts = record_probes([found], store, site="https://site.example/", date="2026-10-25")
    assert counts["appended"] == 1 and len(store.lines()) == 2 and store.verify() == []
    apply_traces([found], store)
    assert len(found["traces"]) == 2 and trace_tier(found) == 1
