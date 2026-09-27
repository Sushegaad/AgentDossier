"""FR-01: connectors map source payloads onto the canonical record (offline fixtures)."""

from agentdossier.connectors import github, huggingface, marketplaces, mcp_registry
from tests.conftest import load_fixture


def test_github_repo_to_resource():
    item = load_fixture("github", "search_repositories.json")["items"][0]
    res = github.repo_to_resource(item, topic="ai-agents", payload_hash="sha256:x")
    assert res["external_ids"]["github"] == "example-org/example-agent"
    assert res["license"] == "Apache-2.0" and res["commercial"] is False
    assert res["resource_type"] == "mcp_server"  # topic mcp-server wins
    assert res["signals"]["github_stars"] == 12345 and res["publisher_domain"] == "example-agent.dev"
    assert res["sources"][0]["payload_hash"] == "sha256:x"


def test_huggingface_space_to_resource():
    space = load_fixture("huggingface", "spaces.json")[0]
    res = huggingface.space_to_resource(space)
    assert res["external_ids"]["huggingface_space"] == space["id"]
    assert res["vendor"] == space["author"] and res["signals"]["hf_likes"] == space["likes"]
    assert "region:us" not in res["tags"]


def test_mcp_registry_record_to_resource():
    page = load_fixture("mcp_registry", "servers_page.json")
    res = mcp_registry.record_to_resource(page["servers"][0])
    assert res["resource_type"] == "mcp_server"
    assert res["protocols"]["mcp"]["status"] == "claimed"
    assert res["external_ids"]["mcp_registry"] == page["servers"][0]["server"]["name"]
    assert res["signals"]["mcp_registry_status"] == "active"


def test_mcp_registry_skips_inactive():
    rec = {
        "server": {"name": "x.example/y", "description": "d", "version": "1"},
        "_meta": {"io.modelcontextprotocol.registry/official": {"status": "deprecated"}},
    }
    assert mcp_registry.record_to_resource(rec) is None


def test_curated_marketplace_listings_load():
    resources, report = marketplaces.run()
    assert report.produced == 7
    assert all(r["signals"]["marketplace"] == "aws_marketplace" for r in resources)
    assert all(
        r["external_ids"]["aws_marketplace"].startswith("https://aws.amazon.com/marketplace/")
        for r in resources
    )
    assert (
        marketplaces.marketplace_for("https://aws.amazon.com/marketplace/pp/prodview-x") == "aws_marketplace"
    )
    assert marketplaces.marketplace_for("https://example.com/") is None
