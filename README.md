# AgentDossier

**An evidence dossier for every AI agent.** A standards-aware agent registry
(Agentic Resource Discovery, Agent2Agent, Model Context Protocol) that shows
what evidence exists for an agent, who issued it, what it covers and whether
it is current, and lets enterprises find the agents already running on their
own networks.

Reference implementation by Hemant Naik. Sample data compiled from public
sources as of a stated date. It is not an assessment, certification or
recommendation. Confirm current status with the vendor and the issuing body.

- **Public demo:** https://sushegaad.github.io/AgentDossier/ (static, no accounts, no analytics)
- **Enterprise edition:** the same MIT codebase as one self-hosted container with a private-network scanner (Phase 2)
- **Docs:** `docs/` (architecture, methodology, operator guide, BRD traceability)

## Status

Phase 0 (design): schemas, configuration, seed import and CI. See
`docs/brd-traceability.md` for what each requirement maps to.

## Quick start

```bash
uv sync --extra dev
uv run pytest
uv run agentdossier seed-check data/seed/top_100_ai_agents_by_domain_2026-09-25.xlsx
```

The core package uses only the Python standard library; `openpyxl` is needed
to read the seed workbook (`--extra connectors` or `--extra dev`).

## License

Code: MIT (see `LICENSE`). Compiled catalog data: CC BY 4.0 with per-record
source attribution. Third-party files keep their own licenses; see
`THIRD_PARTY_NOTICES.md`.
