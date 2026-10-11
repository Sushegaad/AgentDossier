"""PR 5: instance-local traces for private agents, and the decision gate that can require one."""

from __future__ import annotations

import sqlite3

import pytest

from agentdossier.enterprise import traces as et
from agentdossier.server.workflow import Actor, Workflow, WorkflowError
from agentdossier.storage.db import ensure_schema

REVIEWER = Actor("bob", "Bob", {"member", "reviewer"})
ADMIN = Actor("root", "Root", {"member", "reviewer", "admin"})


def _rec(tid: str, tier: int) -> dict:
    return {
        "id": tid,
        "kind": "injection_eval",
        "tier": tier,
        "title": "t",
        "scenario": "s",
        "source": "AgentDojo",
        "observed": {"outcome": "ok"},
    }


def test_record_and_best_tier():
    db = sqlite3.connect(":memory:")
    ensure_schema(db)
    et.record_trace(
        db,
        "r1",
        _rec("t_a", 3),
        extra={"model": "m", "suite": "slack", "pairs": 10, "injections_succeeded": 2},
    )
    et.record_trace(db, "r1", _rec("t_b", 1))
    assert et.best_tier(db, "r1") == 1
    assert et.best_tier(db, "other") is None
    assert len(et.traces_for(db, "r1")) == 2


def test_decision_gate_blocks_approval_until_a_qualifying_trace_exists():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    flow = Workflow(db)
    d = flow.create_decision(
        REVIEWER,
        resource_id="r1",
        resource_name="Claims Agent",
        required_roles=["security"],
        require_trace_tier=2,
    )
    did = d["id"]
    assert d["trace_gate"] == {"required_tier": 2, "best_tier": None, "met": False}
    flow.sign(ADMIN, did, "security", "approve")  # auto-advances to under_review
    # sign-offs complete but no trace: approval blocked
    with pytest.raises(WorkflowError) as e:
        flow.transition(ADMIN, did, "approved")
    assert "trace of tier 2" in str(e.value) and "none on file" in str(e.value)
    # a tier-3 trace is not good enough
    et.record_trace(db, "r1", _rec("t_weak", 3))
    with pytest.raises(WorkflowError):
        flow.transition(ADMIN, did, "approved")
    # a tier-1 trace clears the gate
    et.record_trace(db, "r1", _rec("t_strong", 1))
    assert flow.decision(did)["trace_gate"]["met"] is True
    out = flow.transition(ADMIN, did, "approved")
    assert out["stage"] == "approved"


def test_no_gate_when_unset():
    flow = Workflow(sqlite3.connect(":memory:", check_same_thread=False))
    d = flow.create_decision(REVIEWER, resource_id="r2", resource_name="X", required_roles=["security"])
    assert d["trace_gate"]["required_tier"] is None and d["trace_gate"]["met"] is True
    with pytest.raises(WorkflowError):
        flow.create_decision(REVIEWER, resource_id="r3", resource_name="Y", require_trace_tier=9)


def test_run_and_store_with_mock_pipeline():
    pytest.importorskip("agentdojo")
    from agentdossier.harness.mock import RefusingPipeline

    db = sqlite3.connect(":memory:")
    ensure_schema(db)
    tid = et.run_and_store(db, RefusingPipeline(), "slack", "r9", "mock-refusing", attack="ignore_previous")
    assert tid and et.best_tier(db, "r9") == 1
    row = et.traces_for(db, "r9")[0]
    assert row["kind"] == "injection_eval" and row["observed"]["refused"] is True
