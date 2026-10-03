# Changelog

All notable changes to AgentDossier. The format follows Keep a Changelog; versions
follow SemVer. Catalog data versions (`sar-score`, `frameworks`, `identity`) are
listed in `docs/methodology.md`.

## [1.0.0] — 2026-10-03

First general-availability release of both editions.

### Public demo
- Astro site with intent-based search (chips, facets, auto-relax), domain Top 100
  lists, trust-profile dossiers, compare, shortlist, private-catalog viewer and the
  editorial design system; gates: precision@10 ≥ 0.80 on 50 hand-labelled queries,
  intent accuracy 100 % on 52 cases, axe 0 serious/critical, Lighthouse ≥ 80/95/90/90.
- Catalog pipeline: seed workbook, GitHub, Hugging Face, MCP Registry, ARD web and
  marketplace connectors; dedup with review file; compliance evidence (FedRAMP, CSA
  STAR, DPF, vendor trust centers) with evidence tiers T1–T5, identity-first
  crediting and the trust changelog; news (Hacker News, GDELT, GitHub releases,
  vendor feeds) and NVD; weekly refresh with a wall-clock budget.
- Protocol status with a claimed layer (curated vendor documentation and
  self-description) and an honest "not probed" state; compound vendor matching.
- Google Analytics in consent mode (cookieless until opted in) on the demo only.

### Enterprise edition
- Authorized scanner (preflight, plan, scan, self-test), ARD REST API,
  `POST /qualify`, policy templates, OIDC / token auth with member, reviewer and
  admin roles, in-process scheduler, MCP wrapper.
- Notifications: email and signed webhooks for scan results, catalog changes,
  expiring evidence and decisions; Slack, Teams, Jira, ServiceNow and a GRC
  webhook as additional channels; delivery log.
- Decision workflow: lifecycle with per-role sign-offs, comments, review tasks,
  internal feedback, decision packet export (JSON/CSV).
- GitHub Action policy check over `agents.lock.json`.
- ARD federation (`referrals` and `auto`), SCIM 2.0 user provisioning with
  deprovisioning enforced at sign-in.
- Hardening: security headers and CSP, HSTS behind TLS, request-body cap,
  per-client rate limits; signed container image with SBOM and provenance.
- Deployment: Dockerfile, docker-compose, Helm chart; operator runbook.

### Frameworks
- `frameworks-1.1`: the 15-framework launch set plus Phase-2 GovRAMP, BSI C5,
  IRAP and DORA (HITRUST and PCI DSS were already present).

## [0.1.0] — 2026-09-27

Phases P0–P2 as merged on `main`: design, connectors, evidence, site, launch gates,
enterprise container.
