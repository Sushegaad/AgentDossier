# AgentDossier

**An evidence dossier for every AI agent.** A standards-aware agent registry
(Agentic Resource Discovery, Agent2Agent, Model Context Protocol) that shows
what evidence exists for an agent, who issued it, what it covers and whether
it is current, and lets enterprises find the agents already running on their
own networks.

Reference implementation by Hemant Naik. Sample data compiled from public
sources as of a stated date. It is not an assessment, certification or
recommendation. Confirm current status with the vendor and the issuing body.

- **Public demo:** https://sushegaad.github.io/AgentDossier/ (static, no accounts; Google Analytics in cookieless consent mode)
- **Enterprise edition:** the same MIT codebase as one self-hosted container with a private-network scanner (Phase 2)
- **Docs:** `docs/` (architecture, methodology, operator guide, BRD traceability)

## Status

**v1.0.0** — both editions are feature-complete for the plan's four phases
(see `CHANGELOG.md`). Public demo: connectors (seed workbook, GitHub, Hugging
Face, MCP Registry, ARD publishers, marketplaces), compliance evidence
(FedRAMP, CSA STAR, curated records, vendor claims) with the tier/freshness
engine, protocol status with a claimed layer, news/security feeds, and the
Astro site with intent search, dossiers, compare and the private-catalog
viewer. Enterprise edition (`agentdossier/enterprise/`, `agentdossier/server/`):
authorized scanner, ARD REST API with federation, `/qualify`, decision
workflow with sign-offs, notifications and integrations (email, webhooks,
Slack, Teams, Jira, ServiceNow, GRC), SCIM provisioning, a GitHub Action policy
check, Docker/compose/Helm deployment with a signed image. See
`docs/brd-traceability.md` for what each requirement maps to,
`docs/methodology.md` for how evidence is graded and `docs/enterprise-runbook.md`
to run your own instance.

## Quick start

```bash
uv sync --extra dev
uv run pytest
uv run agentdossier seed-check data/seed/top_100_ai_agents_by_domain_2026-09-25.xlsx

# offline catalog from the seed workbook only (no network)
uv run agentdossier build --sources seed --offline --out /tmp/catalog

# live build: registries, vendor claims and news for a small slice
uv run agentdossier build --sources seed,marketplaces --claim-domains 12 --news-limit 12 \
  --out /tmp/catalog --cache /tmp/cache
```

`--no-compliance` and `--no-news` skip those stages; `GITHUB_TOKEN` enables
the GitHub connector and release feeds, `NVD_API_KEY` lifts the NVD rate
limit. Hand-verified evidence and publisher-domain checks live in
`data/curated/`.

The site: `cd web && npm ci && CATALOG_DIR=/tmp/catalog npm run dev` (see `web/README.md`).

## Self-hosted edition

```bash
uv sync --extra connectors --extra server --extra mcp
agentdossier enterprise selftest                       # loopback end-to-end check
agentdossier enterprise preflight examples/enterprise/enterprise.json
agentdossier enterprise plan examples/enterprise/enterprise.json   # dry run
agentdossier serve --catalog build/enterprise/acme-corp/catalog --enterprise-config enterprise.json
```

One container (`deploy/`) serves the web UI, the ARD REST API, `POST /qualify`,
scheduled authorized scans and an MCP wrapper. See `docs/enterprise-runbook.md`.

The core package uses only the Python standard library; `openpyxl` is needed
to read the seed workbook (`--extra connectors` or `--extra dev`).

## License

Code: MIT (see `LICENSE`). Compiled catalog data: CC BY 4.0 with per-record
source attribution. Third-party files keep their own licenses; see
`THIRD_PARTY_NOTICES.md`.
