"""FR-32/FR-38: policy DSL evaluator parity with eval/policy_cases.yaml."""

import json

import pytest

from agentdossier.policy.engine import evaluate
from tests.conftest import ROOT

yaml = pytest.importorskip("yaml")


def _templates():
    return {p.stem: json.loads(p.read_text()) for p in (ROOT / "config" / "policy_templates").glob("*.json")}


def test_policy_cases_parity():
    cases = yaml.safe_load((ROOT / "eval" / "policy_cases.yaml").read_text())["cases"]
    templates = _templates()
    assert len(cases) == 100
    for case in cases:
        ev = evaluate(templates[case["template"]], case["resource"])
        assert ev.verdict == case["expected"]["verdict"], case["id"]
        assert [{"id": r.id, "result": r.result} for r in ev.rules] == case["expected"]["rules"], case["id"]


def test_verdict_ladder():
    policy = {
        "id": "pol_t",
        "version": 1,
        "rules": [
            {"id": "m", "kind": "must", "field": "identity.tier", "op": "lte", "value": 2},
            {
                "id": "p",
                "kind": "preferred",
                "field": "protocols.mcp.status",
                "op": "eq",
                "value": "verified",
            },
        ],
    }
    assert (
        evaluate(policy, {"identity": {"tier": 1}, "protocols": {"mcp": {"status": "verified"}}}).verdict
        == "eligible"
    )
    assert (
        evaluate(policy, {"identity": {"tier": 1}, "protocols": {"mcp": {"status": "claimed"}}}).verdict
        == "needs_review"
    )
    assert (
        evaluate(policy, {"identity": {"tier": 4}, "protocols": {"mcp": {"status": "verified"}}}).verdict
        == "disallowed"
    )
    assert evaluate(policy, {"protocols": {"mcp": {"status": "verified"}}}).verdict == "unknown"


def test_must_not_inverts_and_unknown_stays_unknown():
    policy = {
        "id": "pol_t",
        "version": 1,
        "rules": [
            {
                "id": "n",
                "kind": "must_not",
                "field": "data_handling.trains_on_customer_data",
                "op": "eq",
                "value": True,
            }
        ],
    }
    assert evaluate(policy, {"data_handling": {"trains_on_customer_data": True}}).verdict == "disallowed"
    assert evaluate(policy, {"data_handling": {"trains_on_customer_data": False}}).verdict == "eligible"
    assert evaluate(policy, {}).verdict == "unknown"
