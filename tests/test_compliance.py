"""FR-19..FR-26, FR-49, FR-53: registry matching, evidence tiers, freshness, wording, credit, changelog."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentdossier.compliance import claims, csa_star, curated, engine, fedramp
from agentdossier.compliance.matching import match, normalize_entity, normalize_product

FIX = Path(__file__).parent / "fixtures" / "compliance"


# --- matching -------------------------------------------------------------------


def test_normalization_strips_legal_suffixes_and_product_noise():
    assert normalize_entity("Everlaw, Inc.") == "everlaw"
    assert normalize_entity("Oracle Corporation") == "oracle"
    assert normalize_product("Zendesk AI Agents") == "zendesk"


@pytest.mark.parametrize(
    ("vendor", "product", "entity", "offering", "decision"),
    [
        ("Workiva", "Workiva", "Workiva Inc.", "Workiva Platform", "accept"),
        ("Everlaw", "Everlaw AI", "Everlaw, Inc.", "Everlaw Platform", "accept"),
        ("Zendesk", "Zendesk AI Agents", "Zendesk", "Zendesk Suite", "accept"),
        # same vendor, different product: strong entity, weak offering -> review, never accept
        ("Oracle", "Oracle SCM AI Agents", "Oracle", "Oracle Service Cloud (OSvC)", "review"),
        ("Salesforce", "Agentforce", "Salesforce", "Government Cloud Plus", "drop"),
        ("Microsoft", "Copilot Studio", "Microsoft", "Azure Government", "drop"),
    ],
)
def test_match_decisions(vendor, product, entity, offering, decision):
    m = match(vendor, product, entity, offering)
    assert m.decision == decision, m


def test_entity_only_match_when_registry_has_no_offering():
    m = match("Workiva", "Workiva", "Workiva Inc.")
    assert m.product_score is None and m.decision == "accept"


# --- FedRAMP --------------------------------------------------------------------


def _fedramp_products():
    return json.loads((FIX / "fedramp_products.json").read_text())["data"]["Products"]


def test_fedramp_find_matches_and_record():
    products = _fedramp_products()
    matches = fedramp.find_matches("Everlaw", "Everlaw AI", products)
    assert matches and matches[0][0]["csp"].startswith("Everlaw") and matches[0][1].decision == "accept"
    rec = fedramp.to_record(matches[0][0], matches[0][1], "sha256:x")
    assert rec["tier"] == 1 and rec["framework"] == "fedramp" and rec["source"] == "fedramp"
    assert rec["evidence_url"].startswith("https://marketplace.fedramp.gov/products/")
    assert rec["payload_hash"] == "sha256:x"


def test_fedramp_oracle_scm_is_not_accepted_as_service_cloud():
    products = _fedramp_products()
    accepted = [
        p["cso"]
        for p, m in fedramp.find_matches("Oracle", "Oracle SCM AI Agents", products)
        if m.decision == "accept"
    ]
    assert accepted == []


# --- CSA STAR -------------------------------------------------------------------


def test_csa_star_index_parsing_and_levels():
    index = csa_star.parse_index((FIX / "csa_star_index.html").read_text())
    assert set(index) >= {"zendesk", "box", "workiva"}
    z = index["zendesk"]
    assert z.name == "Zendesk" and z.listed_since == "2014-03-25"
    found = csa_star.find_match("Zendesk, Inc.", index)
    assert found is not None
    lst, m = found
    assert lst.slug == "zendesk" and m.confidence >= 0.9
    recs = csa_star.to_records(lst, m, "sha256:idx")
    variants = {(r["framework"], r["variant"]) for r in recs}
    assert ("csa_star", "STAR_FOR_AI") in variants and ("iso42001", "ISO42001") in variants
    assert ("csa_star", "STAR_LEVEL_1") in variants and all(r["tier"] == 1 for r in recs)
    box = csa_star.to_records(index["box"], m, None)
    assert [(r["framework"], r["variant"]) for r in box] == [("csa_star", "STAR_LEVEL_1")]


def test_csa_star_level_2_supersedes_level_1():
    lst = csa_star.Listing("acme", "Acme", ("star_level_1", "star_level_2"), "2020-01-01")
    m = match("Acme", None, "Acme")
    variants = [r["variant"] for r in csa_star.to_records(lst, m, None)]
    assert variants == ["STAR_LEVEL_2"]


def test_csa_star_no_match_for_unknown_vendor():
    index = csa_star.parse_index((FIX / "csa_star_index.html").read_text())
    assert csa_star.find_match("Completely Unrelated Vendor", index) is None


# --- vendor claims ----------------------------------------------------------------


def test_claim_patterns_prefer_specific_variants():
    text = "We are SOC 2 Type II audited, ISO/IEC 27001 certified, HIPAA compliant and sign BAAs. GDPR DPA available."
    found = claims.find_claims(text)
    assert ("soc2", "SOC2_TYPE_II") in found and ("soc2", None) not in found
    assert ("iso27001", "ISO27001") in found
    assert ("hipaa", "BAA_AVAILABLE") in found and ("hipaa", None) not in found
    assert ("gdpr", "DPA_AVAILABLE") in found


def test_robots_rules_are_honored():
    assert claims.allowed("/trust", ["/admin", "/private/*"])
    assert not claims.allowed("/private/trust", ["/admin", "/private/*"])


def test_claims_to_records_are_tier4():
    crawl = {
        "domain": "example.com",
        "pages": ["https://example.com/"],
        "claims": [{"framework": "soc2", "variant": "SOC2_TYPE_II", "url": "https://example.com/trust"}],
        "hashes": {"https://example.com/trust": "sha256:t"},
        "checked_at": "2026-09-27T00:00:00Z",
    }
    recs = claims.to_records(crawl)
    assert (
        recs[0]["tier"] == 4 and recs[0]["source"] == claims.SOURCE and recs[0]["payload_hash"] == "sha256:t"
    )


# --- curated ----------------------------------------------------------------------


def test_curated_records_apply_by_vendor_and_set_tier_from_kind(tmp_path):
    yaml = pytest.importorskip("yaml")
    path = tmp_path / "compliance.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "records": [
                    {
                        "vendor": "Acme",
                        "framework": "gdpr",
                        "variant": "DPF_ACTIVE",
                        "checked": "registry",
                        "evidence_url": "https://www.dataprivacyframework.gov/list",
                        "checked_on": "2026-09-01",
                        "checked_by": "hemant.naik",
                    }
                ]
            }
        )
    )
    entries = curated.load(path)
    recs = curated.records_for({"id": "x", "slug": "acme-agent", "vendor": "acme"}, entries)
    assert len(recs) == 1 and recs[0]["tier"] == 1 and recs[0]["reviewer"] == "hemant.naik"
    assert recs[0]["retrieved_at"] == "2026-09-01T00:00:00Z"
    assert curated.records_for({"id": "y", "slug": "other", "vendor": "Other"}, entries) == []


# --- engine: freshness, wording, credit --------------------------------------------


def _rec(framework, variant=None, tier=1, status="active", source="fedramp", **kw):
    base = {
        "framework": framework,
        "variant": variant,
        "status": status,
        "tier": tier,
        "scope": "entity",
        "covers_resource": "unknown",
        "evidence_url": "https://example.com/e",
        "source": source,
        "retrieved_at": "2026-09-27T00:00:00Z",
    }
    base.update(kw)
    return base


NOW = datetime(2026, 9, 27, tzinfo=UTC)


def test_freshness_fixed_date_expires():
    rec = engine.apply_freshness(_rec("iso27001", "ISO27001", tier=3, valid_until="2026-01-01"), NOW)
    assert rec["status"] == "expired"


def test_freshness_period_end_plus_months_goes_stale():
    rec = engine.apply_freshness(_rec("soc2", "SOC2_TYPE_II", tier=3, period_end="2025-01-31"), NOW)
    assert rec["status"] == "stale" and rec["stale_since"]


def test_freshness_recheck_months_on_vendor_claims():
    old = _rec("gdpr", None, tier=4, source="vendor_trust_centers", retrieved_at="2026-01-01T00:00:00Z")
    assert engine.apply_freshness(old, NOW)["status"] == "stale"
    fresh = _rec("gdpr", None, tier=4, source="vendor_trust_centers")
    assert engine.apply_freshness(fresh, NOW)["status"] == "active"


def test_next_check_follows_source_cadence():
    rec = engine.apply_freshness(_rec("fedramp", "FEDRAMP_MODERATE"), NOW)
    assert rec["next_check"] == "2026-10-04"  # weekly registry


@pytest.mark.parametrize(
    ("rec", "expected"),
    [
        (
            _rec(
                "fedramp",
                "FEDRAMP_MODERATE",
                detail={"impact_level": "Moderate", "fedramp_status": "Authorized"},
            ),
            "FedRAMP Moderate: Authorized (FedRAMP Marketplace, 2026-09-27)",
        ),
        (
            _rec("csa_star", "STAR_FOR_AI", source="csa_star"),
            "STAR for AI: found in CSA STAR Registry on 2026-09-27",
        ),
        (_rec("csa_star", "AIUC_1", source="csa_star"), "AIUC-1: found in CSA STAR Registry on 2026-09-27"),
        (
            _rec("hipaa", "BAA_AVAILABLE", tier=4, source="vendor_trust_centers"),
            "HIPAA: BAA available (vendor-claimed, 2026-09-27)",
        ),
        (
            _rec("soc2", "SOC2_TYPE_II", tier=4, source="vendor_trust_centers"),
            "SOC 2 Type II: Vendor-claimed (vendor page, 2026-09-27)",
        ),
    ],
)
def test_wording(rec, expected):
    rec = {**rec, "credited": True}
    assert engine.render_display(rec) == expected


def test_hipaa_is_never_worded_as_certified():
    for tier in (1, 2, 3, 4):
        text = engine.render_display({**_rec("hipaa", "BAA_AVAILABLE", tier=tier), "credited": True})
        assert "certified" not in text.lower()


def test_finalize_dedupes_credits_and_flags_pending():
    raw = [
        _rec("soc2", "SOC2_TYPE_II", tier=4, source="vendor_trust_centers"),
        _rec("soc2", "SOC2_TYPE_II", tier=2, source="aws_marketplace"),
        _rec(
            "fedramp", "FEDRAMP_MODERATE", detail={"impact_level": "Moderate", "fedramp_status": "Authorized"}
        ),
    ]
    out = engine.finalize(raw, identity_tier=2, now=NOW)
    assert [(r["framework"], r["tier"]) for r in out] == [("fedramp", 1), ("soc2", 2)]
    assert all(r["credited"] for r in out)
    pending = engine.finalize(raw, identity_tier=4, now=NOW)
    assert not any(r["credited"] for r in pending)
    assert not any(
        "pending publisher verification" in r["display"] for r in pending
    )  # said once per dossier, not per row


def test_governance_from_evidence_uses_domain_preset_and_credit_weights():
    recs = engine.finalize(
        [
            _rec("fedramp", "FEDRAMP_MODERATE", scope="product", covers_resource="yes"),
            _rec("iso27001", "ISO27001", tier=3, scope="product", covers_resource="yes"),
        ],
        2,
        NOW,
    )
    value, detail = engine.governance_from_evidence(recs, "government")
    # preset fedramp, csa_star, iso27001 + extras iso42001, csa_star: fedramp 1.0 + iso27001 0.7 over 5 slots
    assert value == pytest.approx(100 * (1.0 + 0.7) / 5, abs=0.1)
    assert detail["credited"] == {"fedramp": 1.0, "iso27001": 0.7}
    assert engine.governance_from_evidence([], "finance") == (
        None,
        {
            "preset": engine.DOMAIN_PRESETS["finance"] + engine.ALL_DOMAINS_EXTRA,
            "credited": {},
            "version": engine.GOVERNANCE_VERSION,
        },
    )


def test_uncredited_records_do_not_score():
    recs = engine.finalize([_rec("fedramp", "FEDRAMP_MODERATE")], identity_tier=4, now=NOW)
    value, _ = engine.governance_from_evidence(recs, "government")
    assert value == 0.0


# --- changelog ----------------------------------------------------------------------


def test_changelog_events_added_changed_removed(tmp_path):
    previous = {
        "records": [
            {
                "id": "r1",
                "compliance_summary": [
                    {"framework": "soc2", "variant": "SOC2_TYPE_II", "tier": 4, "status": "active"},
                    {"framework": "gdpr", "variant": None, "tier": 4, "status": "active"},
                ],
            }
        ]
    }
    current = [
        {
            "id": "r1",
            "name": "Agent One",
            "compliance": [
                {
                    "framework": "soc2",
                    "variant": "SOC2_TYPE_II",
                    "tier": 2,
                    "status": "active",
                    "source": "aws",
                },
                {
                    "framework": "fedramp",
                    "variant": "FEDRAMP_MODERATE",
                    "tier": 1,
                    "status": "active",
                    "source": "fedramp",
                },
            ],
        }
    ]
    events = engine.changelog_events(previous, current, "2026-09-27T00:00:00Z")
    kinds = sorted(e["event"] for e in events)
    assert kinds == ["badge_added", "badge_changed", "badge_removed"]
    path = tmp_path / "log.jsonl"
    assert engine.append_changelog(events, path) == 3
    assert len(path.read_text().splitlines()) == 3
    assert engine.append_changelog([], path) == 0


def test_compound_vendor_matches_each_part():
    """ "GitHub / Microsoft" must find Microsoft's registry rows (FR-20)."""
    from agentdossier.compliance.matching import match, vendor_variants

    assert vendor_variants("GitHub / Microsoft")[:3] == ["GitHub / Microsoft", "GitHub", "Microsoft"]
    assert vendor_variants("OpenAI (Microsoft)")[1:3] == ["OpenAI", "Microsoft"]
    assert vendor_variants(None) == []
    whole = match("GitHub / Microsoft", None, "Microsoft Corporation")
    assert whole.entity_score >= 0.85 and whole.decision == "accept"
    assert match("GitHub / Microsoft", "Copilot", "Microsoft", "Copilot").decision == "accept"


def test_csa_star_find_match_handles_compound_vendor():
    from agentdossier.compliance import csa_star

    idx = {
        "microsoft": csa_star.Listing(
            slug="microsoft", name="Microsoft", terms=("STAR Level 1",), listed_since=None
        )
    }
    found = csa_star.find_match("GitHub / Microsoft", idx)
    assert found is not None and found[0].slug == "microsoft" and found[1].confidence >= 0.9


# --- vendor-level (inherited) FedRAMP rows ------------------------------------------


def test_fedramp_vendor_authorization_is_inherited_when_no_offering_matches():
    products = _fedramp_products()
    best = fedramp.best_vendor_authorization("Oracle", products)
    assert best is not None
    product, m = best
    assert product["impact_level"] == "High"  # the highest authorized level the vendor holds
    rec = fedramp.inherited_record(product, m, "sha256:x")
    assert rec["tier"] == 1 and rec["status"] == "active"
    assert rec["scope"] == "entity" and rec["covers_resource"] == "inherited"
    assert "Oracle Cloud Infrastructure" in rec["review_reason"]
    assert fedramp.best_vendor_authorization("Ironclad", products) is None  # Ready is not Authorized
    assert fedramp.best_vendor_authorization("Nobody Inc", products) is None
    assert fedramp.best_vendor_authorization(None, products) is None


def test_compliance_run_adds_inherited_row_only_without_product_match(monkeypatch):
    from agentdossier.compliance import run as comp_run

    products = _fedramp_products()
    monkeypatch.setattr(
        fedramp,
        "load_products",
        lambda store, policy: (products, "sha256:f", fedramp.ConnectorReport("fedramp")),
    )
    monkeypatch.setattr(
        csa_star, "load_index", lambda store, policy: ({}, None, fedramp.ConnectorReport("csa_star"))
    )
    monkeypatch.setattr(curated, "load", lambda: [])
    agent = {"id": "r1", "name": "Oracle Agent Studio", "vendor": "Oracle", "identity": {"tier": 3}}
    matched = {"id": "r2", "name": "Everlaw Platform", "vendor": "Everlaw", "identity": {"tier": 3}}
    reports, _ = comp_run.run([agent, matched], store=None, crawl_claims=False)
    inherited = [c for c in agent["compliance"] if c["covers_resource"] == "inherited"]
    assert len(inherited) == 1 and inherited[0]["framework"] == "fedramp"
    assert not [c for c in matched["compliance"] if c["covers_resource"] == "inherited"]
    assert reports["fedramp"]["inherited"] == 1


# --- curated trust pages ------------------------------------------------------------


def test_trust_pages_loader_and_vendor_aliases(tmp_path):
    path = tmp_path / "trust_pages.yaml"
    path.write_text(
        "domains:\n  aws.amazon.com:\n    pages: [https://aws.amazon.com/compliance/programs/]\n"
        "  ibm.com:\n    pages: ['http://insecure.example/']\n"
        "vendors:\n  aws: aws.amazon.com\n  ibm: ibm.com\n  ghost: nowhere.example\n"
    )
    tp = claims.load_trust_pages(path)
    assert tp.pages_for("www.aws.amazon.com") == ["https://aws.amazon.com/compliance/programs/"]
    assert tp.pages_for("ibm.com") == [] and "ibm" not in tp.vendors  # http pages are ignored
    assert tp.domain_for_vendor("AWS") == "aws.amazon.com"
    assert tp.domain_for_vendor("Amazon / AWS") == "aws.amazon.com"
    assert tp.domain_for_vendor("Searce (AWS Partner)") is None  # a partner is not the vendor
    assert tp.domain_for_vendor("ghost") is None and tp.domain_for_vendor(None) is None
    assert claims.load_trust_pages(tmp_path / "missing.yaml").domains == {}


def test_shipped_trust_pages_are_https_and_vendor_aliases_resolve():
    tp = claims.load_trust_pages()
    assert tp.pages_for("aws.amazon.com")
    assert all(u.startswith("https://") for pages in tp.domains.values() for u in pages)
    assert all(d in tp.domains for d in tp.vendors.values())


def test_claim_domain_uses_vendor_pages_for_shared_hosts():
    from agentdossier.compliance.run import claim_domain

    tp = claims.TrustPages(
        {"aws.amazon.com": ["https://aws.amazon.com/compliance/programs/"]}, {"aws": "aws.amazon.com"}
    )
    assert claim_domain({"url": "https://github.com/awslabs/x", "vendor": "AWS"}, tp) == "aws.amazon.com"
    assert claim_domain({"url": "https://github.com/someone/x", "vendor": "Someone"}, tp) is None
    assert claim_domain({"url": "https://aws.amazon.com/marketplace/pp/1", "vendor": "Zensar"}, tp) is None
    assert claim_domain({"publisher_domain": "www.crewai.com", "vendor": "CrewAI"}, tp) == "crewai.com"


def test_crawl_domain_reads_curated_pages_first(monkeypatch):
    from agentdossier.util import FetchResult

    seen: list[str] = []

    def fake_fetch(url, **kw):
        seen.append(url)
        if url.endswith("robots.txt"):
            return FetchResult(url, 404, {}, b"")
        if url == "https://aws.amazon.com/compliance/programs/":
            return FetchResult(
                url, 200, {"Content-Type": "text/html"}, b"<html>SOC 2 Type II, FedRAMP and HIPAA</html>"
            )
        return FetchResult(url, 200, {"Content-Type": "text/html"}, b"<html><a href='/x'>x</a></html>")

    monkeypatch.setattr(claims, "fetch", fake_fetch)
    crawl = claims.crawl_domain("aws.amazon.com", pages=["https://aws.amazon.com/compliance/programs/"])
    assert seen[1] == "https://aws.amazon.com/compliance/programs/"  # after robots.txt
    found = {(c["framework"], c["variant"]) for c in crawl["claims"]}
    assert ("soc2", "SOC2_TYPE_II") in found and ("fedramp", None) in found and ("hipaa", None) in found
    assert len(crawl["pages"]) <= claims.MAX_PAGES + 1


def test_vendor_aliases_reach_registry_spellings():
    from agentdossier.compliance.matching import canonical_entities, entity_domains, vendor_variants

    assert canonical_entities("AWS") == ["Amazon"] and "Amazon" in vendor_variants("AWS")
    assert canonical_entities("GitHub / Microsoft") == ["Microsoft", "GitHub"]
    assert "aws.amazon.com" in entity_domains("AWS") and entity_domains("Nobody Inc") == []
    assert vendor_variants("Everlaw") == ["Everlaw"]  # unknown vendors are unchanged
    # the alias table itself: every entity has aliases or domains and no alias is shared
    import json
    from pathlib import Path

    doc = json.loads((Path(__file__).parent.parent / "config" / "vendor_aliases.json").read_text())
    seen: dict[str, str] = {}
    for canonical, entry in doc["entities"].items():
        for n in [canonical, *entry.get("aliases", [])]:
            assert n.lower() not in seen, f"{n} listed under {seen[n.lower()]} and {canonical}"
            seen[n.lower()] = canonical


def test_trust_pages_fall_back_to_alias_domains():
    tp = claims.TrustPages({"aws.amazon.com": ["https://aws.amazon.com/compliance/programs/"]}, {})
    assert tp.domain_for_vendor("AWS") == "aws.amazon.com"


def test_claims_crawl_allows_heavy_vendor_pages(monkeypatch):
    from agentdossier.util import FetchResult

    seen = {}

    def fake_fetch(url, **kw):
        seen[url] = kw.get("max_bytes")
        return FetchResult(url, 404, {}, b"")

    monkeypatch.setattr(claims, "fetch", fake_fetch)
    claims.crawl_domain("example.com")
    assert all(v == claims.PAGE_MAX_BYTES for u, v in seen.items() if not u.endswith("robots.txt"))


def test_governance_credits_vendor_level_rows_at_half():
    agent = _rec("soc2", "SOC2_TYPE_II", tier=1, scope="product", covers_resource="yes", credited=True)
    vendor = _rec("soc2", "SOC2_TYPE_II", tier=1, scope="entity", covers_resource="unknown", credited=True)
    full, _ = engine.governance_from_evidence([agent], "technology")
    half, _ = engine.governance_from_evidence([vendor], "technology")
    assert full and half and abs(half - full / 2) < 0.2
