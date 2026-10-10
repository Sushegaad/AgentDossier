"""The reference set (data/curated/reference_set.yaml) is reviewable data: every agent exists in the
catalog, every answer has a value from the fixed set and an http(s) source, and the reviewer field
is a person or null — never a placeholder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
VALUES = {"yes", "no", "configurable", "unknown"}
PLACEHOLDERS = {"", "maintainer", "todo", "tbd", "pending", "n/a", "none"}


def test_reference_set_is_well_formed():
    doc = yaml.safe_load((ROOT / "data" / "curated" / "reference_set.yaml").read_text())
    assert doc["version"].startswith("reference-set-")
    assert doc["reviewed_by"] is None or str(doc["reviewed_by"]).strip().lower() not in PLACEHOLDERS
    cases = {u["id"]: u for u in doc["use_cases"]}
    assert len(cases) == 2
    for a in doc["agents"]:
        uc = cases[a["use_case"]]
        for q in uc["questions"]:
            ans = a["answers"][q["id"]]
            assert ans["value"] in VALUES, (a["slug"], q["id"])
            assert ans["note"] and ans["source"].startswith(("http://", "https://")), (a["slug"], q["id"])
        assert set(a["answers"]) == {q["id"] for q in uc["questions"]}, a["slug"]


def test_reference_agents_exist_in_the_catalog():
    idx = ROOT / "data" / "catalog" / "index.json"
    if not idx.exists():
        pytest.skip("no committed catalog")
    slugs = {r["slug"] for r in json.loads(idx.read_text())["records"]}
    doc = yaml.safe_load((ROOT / "data" / "curated" / "reference_set.yaml").read_text())
    missing = [a["slug"] for a in doc["agents"] if a["slug"] not in slugs]
    assert not missing, f"reference set names agents not in data/catalog: {missing}"


def test_deploy_rules_are_well_formed():
    rules = json.loads((ROOT / "config" / "deploy_rules.json").read_text())["rules"]
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids))
    for r in rules:
        assert set(r["when"]) <= {"answer", "evidence_missing", "identity_tier_min", "protocol"}, r["id"]
        assert len(r["restriction"]) > 20
        for values in (r["when"].get("answer") or {}).values():
            assert set(values) <= VALUES
