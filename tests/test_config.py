"""Configuration and schema integrity (FR-50, plan section 8)."""

import json

import pytest

from agentdossier.classify import Classifier
from agentdossier.cli import main
from tests.conftest import ROOT


def test_config_check_passes(capsys):
    assert main(["config-check"]) == 0


def test_frameworks_launch_set_is_15():
    fws = [json.loads(p.read_text()) for p in (ROOT / "config" / "frameworks").glob("*.json")]
    launch = [f for f in fws if f["priority"] == "launch"]
    assert (
        len(launch) == 13 and len(fws) == 15
    )  # 13 files cover the 15-framework launch set (ISO 27001 family and NIST pair share files)
    for f in fws:
        assert f["group"] in {"certification", "law", "voluntary"}
        assert set(f["credit"]) == {"1", "2", "3", "4", "5"}
        assert all(s["terms_note"] for s in f["sources"])


def test_voluntary_frameworks_never_verified():
    nist = json.loads((ROOT / "config" / "frameworks" / "nist_ai_rmf.json").read_text())
    assert nist["group"] == "voluntary"
    assert all(s["kind"] == "vendor" for s in nist["sources"])


def test_schemas_are_valid_draft_2020_12():
    jsonschema = pytest.importorskip("jsonschema")
    for p in (ROOT / "schema").glob("*.json"):
        jsonschema.Draft202012Validator.check_schema(json.loads(p.read_text()))


def test_enterprise_example_validates_and_has_no_allow_public():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schema" / "enterprise_config.schema.json").read_text())
    cfg = json.loads((ROOT / "examples" / "enterprise" / "enterprise.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(cfg)
    assert "allow_public" not in cfg["scope"]
    with pytest.raises(jsonschema.ValidationError):
        bad = json.loads(json.dumps(cfg))
        bad["scope"]["allow_public"] = True
        jsonschema.Draft202012Validator(schema).validate(bad)


def test_classifier_brd_examples():
    c = Classifier()
    assert "insurance" in c.classify("an agent for insurance claims that can handle PHI").domains
    assert "technology" in c.classify("coding agents we can deploy inside our VPC").domains
    r = c.classify("Clinical documentation assistant for hospitals", category="Clinical documentation agent")
    assert "healthcare" in r.domains and r.domains["healthcare"] >= 0.5
    assert c.classify("lorem ipsum").domains == {}
