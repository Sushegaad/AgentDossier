"""MCP wrapper (BRD §4.3): lets an internal agent query the registry over MCP.

    agentdossier mcp --catalog ./build/enterprise/acme/catalog      # stdio transport

Tools: ``search_agents``, ``get_agent``, ``qualify_agent``, ``list_policies``. Reads
the catalog directory directly, so it runs next to the server or on its own.
Needs the ``mcp`` extra.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import Catalog


def build_server(catalog_dir: str | Path) -> Any:
    import importlib  # noqa: PLC0415

    try:  # mcp >= 2 renamed FastMCP to MCPServer
        server_cls: Any = importlib.import_module("mcp.server.mcpserver").MCPServer
    except (ImportError, AttributeError):  # mcp 1.x
        server_cls = importlib.import_module("mcp.server.fastmcp").FastMCP

    catalog = Catalog(catalog_dir)
    server = server_cls(
        "agentdossier", instructions="Search a standards-aware AI agent registry with evidence tiers."
    )

    @server.tool()
    def search_agents(
        query: str,
        limit: int = 10,
        domain: str | None = None,
        framework: str | None = None,
        max_tier: int | None = None,
    ) -> str:
        """Search the registry. Returns ranked agents with a one-line explanation and trust tiers."""
        hits = catalog.search(query, limit=limit, domain=domain, framework=framework, max_tier=max_tier)
        return json.dumps(
            [
                {
                    "id": h.record["id"],
                    "name": h.record["name"],
                    "vendor": h.record.get("vendor"),
                    "type": h.record.get("resource_type"),
                    "score": h.score,
                    "why": h.explanation,
                    "trust": h.record.get("trust"),
                    "compliance": h.record.get("compliance_summary", []),
                }
                for h in hits
            ],
            indent=1,
        )

    @server.tool()
    def get_agent(id_or_slug: str) -> str:
        """Full dossier for one agent: identity, compliance evidence, protocols, issues, provenance."""
        res = catalog.resource(id_or_slug)
        return json.dumps(res, indent=1, default=str) if res else json.dumps({"error": "unknown resource"})

    @server.tool()
    def qualify_agent(id_or_slug: str, policy_id: str) -> str:
        """Evaluate one agent against a policy template (eligible / needs_review / disallowed / unknown)."""
        res = catalog.resource(id_or_slug)
        if not res:
            return json.dumps({"error": "unknown resource"})
        if policy_id not in catalog.policies:
            return json.dumps({"error": f"unknown policy {policy_id}", "policies": list(catalog.policies)})
        return json.dumps(catalog.qualify(policy_id, [res["id"]])[0], indent=1)

    @server.tool()
    def list_policies() -> str:
        """Policy templates available on this instance."""
        return json.dumps(
            [
                {"id": k, "name": v.get("name"), "rules": len(v.get("rules", []))}
                for k, v in catalog.policies.items()
            ],
            indent=1,
        )

    return server


def main(catalog_dir: str | Path) -> None:
    build_server(catalog_dir).run(transport="stdio")
