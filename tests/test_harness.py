"""The sandbox harness: a model-free run through AgentDojo's real benchmark, recorded as a trace.

The mock pipeline refuses every injection, so these tests need no model and no network; they
exercise the same machinery a real run uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

pytest.importorskip("agentdojo")

from agentdossier.harness import record_run, run_suite  # noqa: E402
from agentdossier.harness.bundles import observation_key, trace_id  # noqa: E402
from agentdossier.harness.mock import RefusingPipeline  # noqa: E402
from agentdossier.harness.models import load_models  # noqa: E402
from agentdossier.traces import apply_traces  # noqa: E402
from agentdossier.traces.store import TraceStore  # noqa: E402

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "schema" / "trace_record.schema.json").read_text())


def test_refusing_agent_runs_and_resists():
    res = run_suite(
        RefusingPipeline(), "slack", user_tasks=["user_task_0"], injection_tasks=["injection_task_1"]
    )
    assert res.error is None and res.pairs == 1
    assert res.injections_succeeded == 0 and res.resisted == 1 and res.attack_success_rate == 0.0
    assert res.injection_tasks == ["injection_task_1"]
    assert run_suite(RefusingPipeline(), "no-such-suite").error


def test_record_run_writes_a_schema_valid_model_scoped_bundle(tmp_path):
    store = TraceStore(tmp_path / "traces")
    res = run_suite(
        RefusingPipeline(), "slack", user_tasks=["user_task_0"], injection_tasks=["injection_task_1"]
    )
    tid = record_run(store, res, "gpt-4o-mini", site="https://s.example/AgentDossier/", date="2026-10-11")
    assert tid == trace_id(res, "gpt-4o-mini") == "tr_hn_gpt-4o-mini_slack_ignore-previous"
    line = store.lines()[0]
    rec = line["record"]
    jsonschema.Draft202012Validator(SCHEMA).validate(rec)
    assert rec["kind"] == "injection_eval" and rec["scope"] == "model" and rec["tier"] == 1
    assert line["agent"] == "gpt-4o-mini" and rec["source"].startswith("AgentDojo")
    assert rec["observed"]["refused"] is True and "0 of 1" in rec["observed"]["outcome"]
    assert store.verify() == []
    transcript = (tmp_path / "traces" / rec["bundle"] / "transcript.md").read_text()
    assert (
        "AgentDojo" in transcript
        and "scope: model" in transcript
        and "did not author the attacks" in transcript
    )
    # unchanged outcome: nothing re-appended
    assert record_run(store, res, "gpt-4o-mini", site="https://s.example/", date="2026-10-18") is None
    assert len(store.lines()) == 1


def test_model_scoped_traces_fan_out_to_mapped_agents(tmp_path):
    store = TraceStore(tmp_path / "traces")
    res = run_suite(
        RefusingPipeline(), "slack", user_tasks=["user_task_0"], injection_tasks=["injection_task_1"]
    )
    record_run(store, res, "gpt-4o-mini", site="https://s.example/", date="2026-10-11")
    agents = [
        {"id": "r1", "slug": "mapped-agent", "name": "Mapped"},
        {"id": "r2", "slug": "unmapped-agent", "name": "Unmapped"},
    ]
    import agentdossier.traces as traces_mod

    # a model map that attaches gpt-4o-mini's traces to mapped-agent only
    orig = traces_mod._model_fanout

    def fake_fanout(stored):
        return {"mapped-agent": stored.get("gpt-4o-mini", [])}

    traces_mod._model_fanout = fake_fanout
    try:
        counts = apply_traces(agents, store)
    finally:
        traces_mod._model_fanout = orig
    assert counts["model_level"] == 1
    assert len(agents[0]["traces"]) == 1 and agents[0]["traces"][0]["scope"] == "model"
    assert agents[1]["traces"] == []
    assert "agent" not in agents[0]["traces"][0]


def test_observation_key_changes_with_outcome():
    a = run_suite(
        RefusingPipeline(), "slack", user_tasks=["user_task_0"], injection_tasks=["injection_task_1"]
    )
    k1 = observation_key(a, "m")
    a.security[("user_task_0", "injection_task_1")] = True
    assert observation_key(a, "m") != k1


def test_shipped_model_map_is_well_formed():
    models = load_models()
    assert models, "data/traces/harness/models.yaml should ship with models"
    for key, entry in models.items():
        assert "backend" in entry and isinstance(entry.get("agents", []), list)
