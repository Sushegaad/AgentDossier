"""FR-02, FR-03: ARD and A2A adapters against spec fixtures (no network)."""

from agentdossier.standards import a2a, ard
from tests.conftest import load_fixture


def test_ard_valid_manifest():
    report = ard.validate_manifest(load_fixture("ard", "manifest_valid.json"))
    assert report["errors"] == []
    assert report["warnings"] == []


def test_ard_invalid_manifest_reports_urn_and_binding_errors():
    report = ard.validate_manifest(load_fixture("ard", "manifest_invalid.json"))
    msgs = " ".join(report["errors"])
    assert "not a urn:air" in msgs
    assert "exactly one of 'url' or 'data'" in msgs
    assert "publisher authority binding failed" in msgs


def test_ard_representative_queries_is_a_warning_not_error():
    entry = {
        "identifier": "urn:air:x.com:a:b",
        "displayName": "b",
        "type": "application/a2a-agent-card+json",
        "url": "https://x.com/c",
    }
    errors, warnings = ard.validate_entry(entry)
    assert errors == [] and len(warnings) == 1


def test_ard_link_rel_and_agentmap_and_jsonld():
    html = '<html><head><link rel="ard" href="/catalog/ard.json"><script type="application/ld+json">{"identifier":"urn:air:x.com:a:b","displayName":"B","type":"application/ai-skill+md","url":"https://x.com/b"}</script></head></html>'
    assert ard.find_link_rel(html, "https://x.com/") == ["https://x.com/catalog/ard.json"]
    assert ard.find_inpage_entries(html)[0]["identifier"] == "urn:air:x.com:a:b"
    assert ard.find_agentmap("User-agent: *\nAgentmap: https://x.com/entries.json\n", "https://x.com/") == [
        "https://x.com/entries.json"
    ]


def test_ard_entry_to_resource_marks_protocols():
    entry = load_fixture("ard", "manifest_valid.json")["entries"][0]
    res = ard.entry_to_resource(entry, "https://acme.com/.well-known/ard.json")
    assert res["resource_type"] == "mcp_server"
    assert res["protocols"]["ard"]["status"] == "verified"
    assert res["protocols"]["mcp"]["status"] == "claimed"
    assert res["publisher_domain"] == "acme.com"


def test_a2a_v1_card_validates_and_summarizes():
    card = load_fixture("a2a", "card_v1.json")
    errors, warnings = a2a.validate_card(card)
    assert errors == []
    s = a2a.summarize(card)
    assert s["protocol_version"] == "1.0" and s["signed"] is True
    assert s["interfaces"][0]["binding"] == "JSONRPC"
    assert s["skills"][0]["id"] == "route-optimizer-traffic"


def test_a2a_v03_card_uses_url_and_preferred_transport():
    card = load_fixture("a2a", "card_v03.json")
    errors, _ = a2a.validate_card(card)
    assert errors == []
    s = a2a.summarize(card)
    assert s["interfaces"][0]["url"] == "https://legacy.example.com/a2a"
    assert s["protocol_version"] == "0.3.0" and s["signed"] is False


def test_a2a_card_missing_endpoint_is_an_error():
    errors, _ = a2a.validate_card({"name": "x", "description": "y", "version": "1"})
    assert any("endpoint" in e for e in errors)
