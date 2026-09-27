"""FR-16: the seed workbook imports and every domain score reproduces."""

import collections


def test_all_1200_scores_reproduce(seed_import):
    assert seed_import.ok, seed_import.errors[:10]
    assert len(seed_import.rows) == 1200
    assert seed_import.max_score_error <= 0.1


def test_unique_products_and_domains(seed_import):
    assert len(seed_import.resources) == 158
    domains = collections.Counter(row.domain for row in seed_import.rows)
    assert len(domains) == 12 and all(n == 100 for n in domains.values())
    assert seed_import.snapshot_date == "2026-09-25"
    assert len(seed_import.source_catalog) == 185


def test_every_resource_has_provenance_and_profile(seed_import):
    for res in seed_import.resources.values():
        assert res["sources"] and res["sources"][0]["system"] == "seed_xlsx"
        for domain, d in res["domains"].items():
            assert d["profile"] in {
                "general",
                "technology",
                "regulated",
                "security",
                "commercial",
                "data",
                "operations",
            }
            assert d["score_version"] == "sar-score-1.0"
            assert d["confidence"] == 1.0


def test_resources_validate_against_schema(seed_import):
    jsonschema = __import__("pytest").importorskip("jsonschema")
    import json

    from referencing import Registry, Resource

    from tests.conftest import ROOT

    names = ["resource", "compliance_record", "policy", "enterprise_config", "catalog_index"]
    schemas = {n: json.loads((ROOT / "schema" / f"{n}.schema.json").read_text()) for n in names}
    registry = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    validator = jsonschema.Draft202012Validator(schemas["resource"], registry=registry)
    for res in seed_import.resources.values():
        errors = list(validator.iter_errors(res))
        assert not errors, (res["name"], [e.message for e in errors[:3]])
