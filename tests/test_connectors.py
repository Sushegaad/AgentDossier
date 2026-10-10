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


# --- seed enrichment: GitHub repository URLs in the workbook -----------------------------


def test_seed_enrich_repo_of_accepts_repositories_only():
    from agentdossier.connectors.seed_enrich import repo_of

    assert repo_of("https://github.com/Aider-AI/aider") == "Aider-AI/aider"
    assert repo_of("https://github.com/microsoft/autogen/tree/main/python") == "microsoft/autogen"
    assert repo_of("https://github.com/crewAIInc/crewAI.git") == "crewAIInc/crewAI"
    assert repo_of("https://github.com/features/copilot") is None
    assert repo_of("https://github.com/openai") is None
    assert repo_of("https://example.com/a/b") is None and repo_of(None) is None


def test_seed_enrich_apply_repo_fills_identity_domain_and_signals():
    from agentdossier.connectors.seed_enrich import apply_repo

    res = {
        "name": "CrewAI",
        "vendor": "CrewAI",
        "url": "https://github.com/crewAIInc/crewAI",
        "publisher_domain": "github.com",
    }
    repo = {
        "full_name": "crewAIInc/crewAI",
        "homepage": "crewai.com",
        "description": "Framework for orchestrating role-playing, autonomous AI agents.",
        "topics": ["agents", "mcp", "llms"],
        "license": {"spdx_id": "MIT", "key": "mit"},
        "stargazers_count": 30000,
        "pushed_at": "2026-10-01T00:00:00Z",
        "archived": False,
    }
    changed = apply_repo(res, repo)
    assert res["external_ids"]["github"] == "crewAIInc/crewAI"
    assert res["publisher_domain"] == "crewai.com" and res["homepage"] == "https://crewai.com"
    assert "mcp" in res["tags"] and res["license"] == "MIT"
    assert res["signals"]["github_stars"] == 30000
    assert res["enrichment"]["github"]["changed"] == changed and "publisher_domain" in changed
    # a GitHub Pages or code-host homepage does not become the publisher domain
    res2 = {
        "name": "AutoGen",
        "vendor": "Microsoft",
        "url": "https://github.com/microsoft/autogen",
        "publisher_domain": "github.com",
    }
    apply_repo(res2, {"full_name": "microsoft/autogen", "homepage": "https://microsoft.github.io/autogen/"})
    assert res2["publisher_domain"] == "github.com" and res2["external_ids"]["github"] == "microsoft/autogen"
    assert apply_repo(res2, {"full_name": "microsoft/autogen"}) == []  # idempotent


def test_seed_enrich_run_only_touches_seed_rows(monkeypatch):
    from agentdossier.connectors import seed_enrich

    calls = []

    def fake_get_json(store, source, key, url, **kw):
        calls.append(url)
        return {"full_name": key, "homepage": "https://x.example"}, None, None

    monkeypatch.setattr(seed_enrich, "get_json", fake_get_json)
    seed = {"name": "A", "url": "https://github.com/o/a", "sources": [{"system": "seed_xlsx"}]}
    discovered = {"name": "B", "url": "https://github.com/o/b", "sources": [{"system": "github"}]}
    rep = seed_enrich.run([seed, discovered], token=None)
    assert calls == ["https://api.github.com/repos/o/a"]
    assert rep.fetched == 1 and rep.produced == 1
    assert seed["publisher_domain"] == "x.example" and "publisher_domain" not in discovered
