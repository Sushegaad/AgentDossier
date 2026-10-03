"""Wk 13–14: decision lifecycle with sign-offs (FR-28, FR-34), comments, review tasks,
internal feedback (FR-35) and the decision packet export."""

from __future__ import annotations

import csv
import io
import sqlite3

import pytest

from agentdossier.server.workflow import Actor, Workflow, WorkflowError

MEMBER = Actor("alice", "Alice", {"member"})
REVIEWER = Actor("bob", "Bob", {"member", "reviewer"})
ADMIN = Actor("root", "Root", {"member", "reviewer", "admin"})


@pytest.fixture
def flow():
    return Workflow(sqlite3.connect(":memory:", check_same_thread=False))


def test_lifecycle_requires_every_role_to_sign(flow):
    d = flow.create_decision(
        MEMBER, resource_id="r1", resource_name="Claims Agent", policy_id="pol_x", verdict="needs_review"
    )
    assert d["stage"] == "candidate" and d["required_roles"] == ["security", "business"]
    assert d["events"][0]["to_stage"] == "candidate" and d["events"][0]["verdict"] == "needs_review"
    with pytest.raises(WorkflowError) as e:
        flow.transition(MEMBER, d["id"], "under_review")
    assert e.value.status == 403
    with pytest.raises(WorkflowError) as e:
        flow.sign(MEMBER, d["id"], "security", "approve")
    assert e.value.status == 403
    d = flow.sign(REVIEWER, d["id"], "security", "approve", "pen test clean")
    assert d["stage"] == "under_review" and d["signoff"] == {
        "required": ["security", "business"],
        "approved": ["security"],
        "rejected": [],
        "missing": ["business"],
        "complete": False,
    }
    with pytest.raises(WorkflowError) as e:
        flow.transition(REVIEWER, d["id"], "approved")
    assert e.value.status == 409 and "business" in str(e.value)
    d = flow.sign(ADMIN, d["id"], "business", "approve")
    assert d["signoff"]["complete"]
    d = flow.transition(REVIEWER, d["id"], "approved", note="go", verdict="eligible")
    assert d["stage"] == "approved" and d["events"][-1]["verdict"] == "eligible"
    assert [e["to_stage"] for e in d["events"]] == ["candidate", "under_review", "approved"]
    with pytest.raises(WorkflowError):
        flow.sign(REVIEWER, d["id"], "legal", "approve")  # already approved
    d = flow.transition(ADMIN, d["id"], "retired")
    with pytest.raises(WorkflowError) as e:
        flow.transition(ADMIN, d["id"], "under_review")
    assert e.value.status == 409


def test_reject_moves_to_rejected_and_can_be_reopened(flow):
    d = flow.create_decision(MEMBER, resource_id="r2", resource_name="X", required_roles=["legal"])
    d = flow.sign(REVIEWER, d["id"], "legal", "reject", "no DPA")
    assert d["stage"] == "rejected" and d["signoff"]["rejected"] == ["legal"]
    d = flow.transition(REVIEWER, d["id"], "under_review", note="DPA now signed")
    d = flow.sign(REVIEWER, d["id"], "legal", "approve")
    assert d["signoff"]["complete"]  # the later verdict per role wins
    d = flow.transition(REVIEWER, d["id"], "approved")
    assert d["stage"] == "approved"


def test_validation(flow):
    with pytest.raises(WorkflowError):
        flow.create_decision(MEMBER, resource_id="r", resource_name="R", required_roles=["nope"])
    d = flow.create_decision(MEMBER, resource_id="r", resource_name="R")
    for bad in [("security", "maybe"), ("ceo", "approve")]:
        with pytest.raises(WorkflowError) as e:
            flow.sign(REVIEWER, d["id"], *bad)
        assert e.value.status == 400
    with pytest.raises(WorkflowError) as e:
        flow.decision(999)
    assert e.value.status == 404


def test_comments_tasks_and_feedback(flow):
    d = flow.create_decision(MEMBER, resource_id="r3", resource_name="Agent")
    c = flow.comment(MEMBER, d["id"], "Does it support SSO?")
    r = flow.comment(REVIEWER, d["id"], "Yes, OIDC.", parent_id=c["id"])
    assert r["parent_id"] == c["id"]
    t = flow.add_task(REVIEWER, d["id"], "Collect SOC 2 report", assignee="alice", due="2026-10-15")
    assert flow.open_tasks("alice")[0]["id"] == t["id"] and flow.open_tasks("bob") == []
    t = flow.set_task(MEMBER, t["id"], "done", note="attached")
    assert t["status"] == "done" and t["completed"] and flow.open_tasks() == []
    f = flow.add_feedback(MEMBER, resource_id="r3", kind="rating", rating=4, decision_id=d["id"])
    g = flow.add_feedback(MEMBER, resource_id="r3", kind="correction", body="vendor renamed")
    with pytest.raises(WorkflowError):
        flow.add_feedback(MEMBER, resource_id="r3", kind="rating", rating=9)
    with pytest.raises(WorkflowError):
        flow.set_feedback(MEMBER, g["id"], "resolved")
    g = flow.set_feedback(REVIEWER, g["id"], "resolved")
    assert g["resolved_by"] == "bob"
    s = flow.feedback_summary("r3")
    assert s == {
        "count": 2,
        "open": 1,
        "rating": 4.0,
        "ratings": 1,
        "by_kind": {"correction": 1, "rating": 1},
    }
    full = flow.decision(d["id"])
    assert (
        len(full["comments"]) == 2
        and len(full["tasks"]) == 1
        and [x["id"] for x in full["feedback"]] == [f["id"]]
    )


def test_packet_export_json_and_csv(flow):
    d = flow.create_decision(MEMBER, resource_id="r4", resource_name="Agent", required_roles=["security"])
    flow.comment(MEMBER, d["id"], "ok")
    flow.sign(REVIEWER, d["id"], "security", "approve")
    flow.transition(REVIEWER, d["id"], "approved")
    res = {
        "id": "r4",
        "name": "Agent",
        "trust": {"identity": 3},
        "compliance": [{"framework": "soc2", "tier": 4, "status": "active", "extra": 1}],
    }
    p = flow.packet(d["id"], resource=res, instance={"tenant": "acme"})
    assert p["format"] == "agentdossier-decision-packet/1" and p["decision"]["stage"] == "approved"
    assert p["resource_snapshot"]["compliance"] == [
        {
            "framework": "soc2",
            "variant": None,
            "tier": 4,
            "status": "active",
            "issuer": None,
            "valid_until": None,
            "evidence_url": None,
            "source": None,
        }
    ]
    assert p["signoff"]["complete"] and len(p["approvals"]) == 1 and len(p["comments"]) == 1
    rows = list(csv.reader(io.StringIO(Workflow.packet_csv(p))))
    kinds = [r[0] for r in rows[4:]]  # header, decision row, blank, section header
    assert kinds == ["event", "event", "event", "approval", "comment"]
    all_rows = list(csv.reader(io.StringIO(flow.decisions_csv())))
    assert all_rows[0][0] == "id" and all_rows[1][4] == "approved" and all_rows[1][7] == "security"


# --- through the API ---------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")


def test_api_end_to_end_approval_with_signoffs(tmp_path):
    from fastapi.testclient import TestClient

    from agentdossier.build import BuildOptions, build
    from agentdossier.server.app import create_app
    from agentdossier.server.settings import Settings

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
    s = Settings(
        catalog_dir=out,
        db_path=tmp_path / "w.db",
        web_dist=None,
        auth_mode="token",
        api_token="member",
        admin_token="boss",
        enterprise_config=None,
        start_scheduler=False,
    )
    c = TestClient(create_app(s))
    member, boss = {"Authorization": "Bearer member"}, {"Authorization": "Bearer boss"}
    rid = c.get("/agents?pageSize=1", headers=member).json()["agents"][0]["resourceId"]

    r = c.post(
        "/api/decisions",
        json={
            "resourceId": rid,
            "policyId": "pol_healthcare_default",
            "requiredRoles": ["security", "legal"],
        },
        headers=member,
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["stage"] == "candidate" and d["events"][0]["verdict"] in (
        "eligible",
        "needs_review",
        "disallowed",
        "unknown",
    )
    assert c.post("/api/decisions", json={"resourceId": "nope"}, headers=member).status_code == 404
    assert (
        c.post(
            f"/api/decisions/{d['id']}/sign", json={"role": "security", "verdict": "approve"}, headers=member
        ).status_code
        == 403
    )
    assert (
        c.post(
            f"/api/decisions/{d['id']}/comments", json={"body": "Reviewed the DPA"}, headers=member
        ).status_code
        == 201
    )
    t = c.post(
        f"/api/decisions/{d['id']}/tasks",
        json={"title": "Get SOC 2 report", "assignee": "api-token"},
        headers=member,
    ).json()
    assert c.get("/api/tasks?assignee=api-token", headers=member).json()["tasks"][0]["id"] == t["id"]
    assert c.post(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=member).json()["status"] == "done"
    d = c.post(
        f"/api/decisions/{d['id']}/sign",
        json={"role": "security", "verdict": "approve", "note": "ok"},
        headers=boss,
    ).json()
    assert d["stage"] == "under_review"
    r = c.post(f"/api/decisions/{d['id']}/stage", json={"stage": "approved"}, headers=boss)
    assert r.status_code == 409 and "legal" in r.json()["detail"]
    d = c.post(
        f"/api/decisions/{d['id']}/sign", json={"role": "legal", "verdict": "approve"}, headers=boss
    ).json()
    d = c.post(
        f"/api/decisions/{d['id']}/stage",
        json={"stage": "approved", "note": "procurement may proceed"},
        headers=boss,
    ).json()
    assert d["stage"] == "approved" and d["signoff"]["complete"] and d["events"][-1]["verdict"]
    f = c.post(
        "/api/feedback",
        json={"resourceId": rid, "kind": "rating", "rating": 5, "decisionId": d["id"]},
        headers=member,
    )
    assert f.status_code == 201
    fb = c.get(f"/api/feedback?resourceId={rid}", headers=member).json()
    assert fb["summary"]["rating"] == 5.0 and fb["feedback"][0]["status"] == "open"
    assert (
        c.post(f"/api/feedback/{f.json()['id']}", json={"status": "acknowledged"}, headers=boss).json()[
            "status"
        ]
        == "acknowledged"
    )
    lst = c.get("/api/decisions?stage=approved", headers=member).json()["decisions"]
    assert [x["id"] for x in lst] == [d["id"]]
    packet = c.get(f"/api/decisions/{d['id']}/export", headers=member).json()
    assert packet["resource_snapshot"]["id"] == rid and packet["instance"]["exported_by"] == "api-token"
    assert (
        len(packet["approvals"]) == 2
        and len(packet["comments"]) == 1
        and len(packet["tasks"]) == 1
        and len(packet["feedback"]) == 1
    )
    csv_text = c.get(f"/api/decisions/{d['id']}/export?format=csv", headers=member).text
    assert csv_text.startswith("decision_id,") and "approval" in csv_text
    assert c.get("/api/decisions/export.csv", headers=member).text.count("\n") >= 2
    actions = {e["action"] for e in c.get("/api/audit", headers=boss).json()["events"]}
    assert {
        "decision.opened",
        "decision.comment",
        "decision.task",
        "decision.export",
        "feedback.add",
    } <= actions
