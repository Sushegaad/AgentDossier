"""The incident registry (data/curated/incidents.yaml) — schema and integrity."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "schema" / "incident_record.schema.json").read_text())


def _load():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((ROOT / "data" / "curated" / "incidents.yaml").read_text())
    return doc["incidents"]


def test_every_incident_validates_and_is_sourced():
    incidents = _load()
    assert incidents, "incidents.yaml should ship with records"
    validator = jsonschema.Draft202012Validator(SCHEMA)
    ids = set()
    for inc in incidents:
        inc = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in inc.items()}
        # dates inside nested lists (sources/timeline) are plain strings in YAML here
        validator.validate(inc)
        assert inc["id"] not in ids, f"duplicate {inc['id']}"
        ids.add(inc["id"])
        assert inc["sources"] and all(s["url"].startswith("https://") for s in inc["sources"])
        # timeline source references point at a real source index
        for t in inc.get("timeline") or []:
            if t.get("source") and str(t["source"]).isdigit():
                assert 1 <= int(t["source"]) <= len(inc["sources"])


def test_tactics_are_known_mitre_ids():
    known = {
        "TA0043", "TA0001", "TA0002", "TA0003", "TA0004", "TA0005", "TA0006",
        "TA0007", "TA0008", "TA0009", "TA0010", "TA0011", "TA0040", "TA0042",
    }
    for inc in _load():
        for t in inc.get("tactics") or []:
            assert t in known, f"{inc['id']}: unknown MITRE tactic {t}"


def test_related_agents_exist_in_the_catalog():
    import glob

    slugs = set()
    for f in glob.glob(str(ROOT / "data" / "catalog" / "agents" / "*.json")):
        slugs.add(json.load(open(f)).get("slug"))
    if not slugs:
        pytest.skip("no built catalog to check against")
    for inc in _load():
        for a in inc.get("related_agents") or []:
            assert a in slugs, f"{inc['id']}: related agent {a} not in catalog"
