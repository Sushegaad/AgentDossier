# Architecture (summary)

One Python engine plus one TypeScript front end, built twice:

- **Public demo:** GitHub Actions runs `agentdossier build` weekly and opens a
  pull request with the catalog; merging deploys a static Astro site to GitHub
  Pages. No server, no accounts, no analytics.
- **Enterprise edition:** the `agentdossier[server]` extra in one self-hosted
  container: private-network scanner, ARD registry API, application service
  (workspaces, policy profiles, approvals, alerts), SQLite or PostgreSQL.

The core package is standard-library only so the scanner installs with zero
dependencies on air-gapped hosts. Standards adapters (`standards/ard.py`,
`a2a.py`, `mcp.py`) separate fetch from parse and stamp every record with a
parser version; raw payload hashes are kept for forward migration.

Full design: the AgentDossier Technical Implementation Plan (26 Sep 2026)
and BRD v3.2. Requirement mapping: `brd-traceability.md`.
