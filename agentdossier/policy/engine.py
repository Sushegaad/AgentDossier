"""Policy DSL evaluator (FR-32, FR-38) - Python twin of ``web/src/lib/policy.ts``.

The DSL is deliberately tiny: rules are ``must`` / ``must_not`` / ``preferred``
over a whitelist of field paths with operators ``eq``, ``in``, ``lte``,
``gte``, ``has`` and ``exists``. Both evaluators must produce identical
verdicts and per-rule results on ``eval/policy_cases.yaml``.

Verdict rules (BRD §8.3):

* any ``must`` (or ``must_not``) rule fails      -> ``disallowed``
* else any ``must`` / ``must_not`` is unknown     -> ``unknown``
* else any ``preferred`` rule is not a pass      -> ``needs_review``
* else                                            -> ``eligible``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VERDICTS = ("eligible", "needs_review", "disallowed", "unknown")
RESULTS = ("pass", "fail", "unknown")
ACTIVE_STATUSES = {"active"}


@dataclass(frozen=True)
class RuleResult:
    id: str
    kind: str
    result: str
    evidence: str | None = None


@dataclass(frozen=True)
class Evaluation:
    verdict: str
    rules: tuple[RuleResult, ...]
    policy_id: str
    policy_version: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "rules": [
                {"id": r.id, "kind": r.kind, "result": r.result, "evidence": r.evidence} for r in self.rules
            ],
        }


def _get(resource: dict[str, Any], path: str) -> Any:
    cur: Any = resource
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _has_compliance(records: Any, want: dict[str, Any]) -> tuple[str, str | None]:
    """``has`` over compliance records: pass if an active record for the framework
    (and variant, when given) exists at or better than ``minTier``.
    No compliance list at all -> unknown; a list without a match -> fail."""
    if records is None:
        return "unknown", None
    best: tuple[str, str | None] = ("fail", None)
    for rec in records:
        if not isinstance(rec, dict) or rec.get("framework") != want.get("framework"):
            continue
        if want.get("variant") and rec.get("variant") != want["variant"]:
            continue
        if rec.get("status") not in ACTIVE_STATUSES:
            continue
        tier = int(rec.get("tier", 5))
        if tier <= int(want.get("minTier", 5)):
            return "pass", f"{rec.get('framework')}/{rec.get('variant')} tier {tier}"
        best = ("fail", f"{rec.get('framework')} only at tier {tier}")
    return best


def evaluate_rule(rule: dict[str, Any], resource: dict[str, Any]) -> RuleResult:
    field, op, value = rule["field"], rule["op"], rule.get("value")
    evidence: str | None = None
    if op == "has":
        result, evidence = _has_compliance(resource.get("compliance"), value or {})
    else:
        actual = _get(resource, field)
        if actual is None:
            result = "unknown"
        elif op == "eq":
            result = "pass" if actual == value else "fail"
        elif op == "in":
            result = "pass" if actual in (value or []) else "fail"
        elif op == "lte":
            result = "pass" if actual <= value else "fail"
        elif op == "gte":
            result = "pass" if actual >= value else "fail"
        elif op == "exists":
            result = "pass"
        else:
            raise ValueError(f"unknown operator {op!r}")
        evidence = f"{field}={actual!r}" if actual is not None else None
    if rule["kind"] == "must_not" and result in ("pass", "fail"):
        result = "fail" if result == "pass" else "pass"
    return RuleResult(id=rule["id"], kind=rule["kind"], result=result, evidence=evidence)


def evaluate(policy: dict[str, Any], resource: dict[str, Any]) -> Evaluation:
    results = tuple(evaluate_rule(r, resource) for r in policy["rules"])
    verdict = "eligible"
    for r in results:
        if r.kind in ("must", "must_not"):
            if r.result == "fail":
                verdict = "disallowed"
            elif r.result == "unknown" and verdict != "disallowed":
                verdict = "unknown"
        elif r.kind == "preferred" and r.result != "pass" and verdict == "eligible":
            verdict = "needs_review"
    return Evaluation(
        verdict=verdict,
        rules=results,
        policy_id=str(policy.get("id", "")),
        policy_version=int(policy.get("version", 1)),
    )
