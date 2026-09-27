"""FR-05/FR-06/FR-08: dedup rules, signal-derived components and the offline build."""

import json

import pytest

from agentdossier.build import BuildOptions, build
from agentdossier.dedup import dedup, identity_keys
from agentdossier.models import new_resource
from agentdossier.score import components_from_signals, score_for_domain
from tests.conftest import ROOT


def _res(name, url, system="github", vendor="acme", **ext):
    r = new_resource(
        name=name, source_system=system, vendor=vendor, url=url, external_ids=ext, key=f"{system}:{name}"
    )
    return r


def test_identity_keys_prefer_stable_ids():
    r = _res("Agent", "https://github.com/acme/agent", github="acme/agent")
    assert "github:acme/agent" in identity_keys(r)


def test_marketplace_listing_merges_into_seed_record():
    seed = _res(
        "Agentforce Insurance",
        "https://aws.amazon.com/marketplace/pp/prodview-1",
        system="seed_xlsx",
        vendor="Salesforce",
    )
    listing = _res(
        "Agentforce Insurance (AWS listing)",
        "https://aws.amazon.com/marketplace/pp/prodview-1",
        system="aws_marketplace",
        vendor="Salesforce",
        aws_marketplace="https://aws.amazon.com/marketplace/pp/prodview-1",
    )
    result = dedup([listing, seed], fuzzy=False)
    assert len(result.resources) == 1 and result.merged == 1
    keep = result.resources[0]
    assert keep["name"] == "Agentforce Insurance"  # seed wins on name
    assert keep["external_ids"]["aws_marketplace"] and {s["system"] for s in keep["sources"]} == {
        "seed_xlsx",
        "aws_marketplace",
    }


def test_two_seed_products_sharing_a_url_stay_separate():
    a = _res("Vercel AI SDK", "https://github.com/vercel/ai", system="seed_xlsx", vendor="Vercel")
    b = _res("AI SDK Agents", "https://github.com/vercel/ai", system="seed_xlsx", vendor="Vercel")
    result = dedup([a, b], fuzzy=False)
    assert len(result.resources) == 2 and result.merged == 0
    assert result.candidates and result.candidates[0].reason.startswith("shared identity key")


def test_fuzzy_names_become_review_candidates_not_merges():
    a = _res("Acme Claims Agent", "https://acme.com/claims", vendor="Acme")
    b = _res("Acme Claims Agents", "https://acme.example/claims-agents", vendor="Acme")
    result = dedup([a, b])
    assert len(result.resources) == 2
    assert any(c.similarity >= 0.92 for c in result.candidates)
    merged = dedup([a, b], decisions={(a["id"], b["id"]): "merge"})
    assert len(merged.resources) == 1


def test_components_from_signals_flags_unknowns():
    r = {
        "signals": {"github_stars": 1000, "github_pushed_at": "2026-09-01T00:00:00Z"},
        "protocols": {
            "a2a": {"status": "unknown"},
            "mcp": {"status": "claimed"},
            "ard": {"status": "unknown"},
        },
        "tags": ["a"],
        "description": "d",
        "url": "https://x",
    }
    c = components_from_signals(r, 0.56)
    assert c["governance"] is None and 0 < c["adoption"] < 30 and c["health"] == 20.0
    s = score_for_domain(c, "finance")
    assert "governance" in s.unknown and s.evidence_coverage < 1.0


def test_offline_build_writes_valid_outputs(tmp_path):
    jsonschema = pytest.importorskip("jsonschema")
    result = build(
        BuildOptions(out_dir=tmp_path, cache_dir=tmp_path / "cache", offline=True, write_review=False)
    )
    assert result.summary["resources"] == 158
    assert result.summary["by_source"]["aws_marketplace"] == 7
    index = json.loads((tmp_path / "index.json").read_text())
    schema = json.loads((ROOT / "schema" / "catalog_index.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(index)
    assert len(index["records"]) == 158 and index["disclaimer"].startswith("Reference implementation")
    ins = json.loads((tmp_path / "domains" / "insurance.json").read_text())
    assert [r["rank"] for r in ins["ranked"]] == list(range(1, 101)) and ins["ranked"][0][
        "name"
    ] == "Agentforce Financial Services"
    assert (tmp_path / "ard.json").exists() and (tmp_path / "agents-list" / "page-1.json").exists()
    agent = json.loads(next((tmp_path / "agents").glob("*.json")).read_text())
    assert "raw" not in agent and agent["identity"]["tier"] in (2, 3, 4)


def test_identity_rules_domain_match_and_curated():
    from agentdossier.build import _domain_matches_vendor, _identity

    assert _domain_matches_vendor("www.everlaw.com", "Everlaw, Inc.")
    assert _domain_matches_vendor("salesforce.com", "Salesforce")
    assert not _domain_matches_vendor("github.com", "Acme AI Labs")
    assert not _domain_matches_vendor("example.com", "The AI Inc")  # only stop-words / short tokens
    base = {"protocols": {}, "vendor": "Everlaw", "url": "https://www.everlaw.com/ai", "external_ids": {}}
    assert _identity(base)["tier"] == 3 and _identity(base)["evidence"] == ["publisher_domain_matches_vendor"]
    curated = {"everlaw.com": {"vendor": "Everlaw", "checked_by": "hemant.naik", "checked_on": "2026-09-27"}}
    ident = _identity(base, curated)
    assert ident["tier"] == 2 and ident["verified_by"] == "hemant.naik"
    assert (
        _identity({"protocols": {}, "vendor": "Acme", "url": "https://other.io", "external_ids": {}})["tier"]
        == 4
    )


def test_offline_build_skips_evidence_and_news_but_keeps_fields(tmp_path):
    result = build(
        BuildOptions(
            out_dir=tmp_path,
            cache_dir=tmp_path / "cache",
            offline=True,
            write_review=False,
            compliance=False,
            news=False,
        )
    )
    agent = json.loads(next((tmp_path / "agents").glob("*.json")).read_text())
    assert agent["compliance"] == [] and agent["news"] == [] and not agent.get("news_checked")
    assert "compliance_summary" in result.summary or "identity_tiers" in result.summary
