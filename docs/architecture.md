# Architecture (summary)

One Python engine plus one TypeScript front end, built twice:

- **Public demo:** GitHub Actions runs `agentdossier build` weekly, opens a
  pull request with the catalog, merges it once the gates pass, and deploys a
  static Astro site to GitHub Pages. No server, no accounts; Google Analytics on the public demo only (page counts; ad storage denied, IP anonymised).
- **Enterprise edition:** the `agentdossier[server]` extra in one self-hosted
  container: private-network scanner, ARD registry API, application service
  (workspaces, policy profiles, approvals, alerts), SQLite or PostgreSQL.

The core package is standard-library only so the scanner installs with zero
dependencies on air-gapped hosts. Standards adapters (`standards/ard.py`,
`a2a.py`, `mcp.py`) separate fetch from parse and stamp every record with a
parser version; raw payload hashes are kept for forward migration.

Two registries ride on the same weekly run and the same static site:

- **Incident registry** (`agentdossier/incidents/`, `data/curated/incidents.yaml`, `/traces/`):
  a scout reads public feeds into candidates; a machine review fetches each candidate's source,
  asks a model one structured question against that text, and publishes or dismisses it with the
  reason on file; a re-check records whether every source link still answers. The refresh PR
  merges itself and redeploys. `docs/incidents.md`.
- **CVE registry** (`agentdossier/cves/`, `data/cves/index.json`, `/cves/`): every official CVE
  (NVD API 2.0, CISA KEV) that names a listed agent product or is about agents by its own record,
  classified and cross-linked to dossiers and incidents; a person's overrides live in one file.
  `docs/cves.md`.

Full design: the AgentDossier Technical Implementation Plan (26 Sep 2026)
and BRD v3.2. Requirement mapping: `brd-traceability.md`.
