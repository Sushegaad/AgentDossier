# Changelog

All notable changes to AgentDossier. The format follows Keep a Changelog; versions
follow SemVer. Catalog data versions (`sar-score`, `frameworks`, `identity`) are
listed in `docs/methodology.md`.

## [Unreleased]

### Security
- Authentication is fail-closed: `AGENTDOSSIER_AUTH_MODE` has no inferred default and
  `none` needs `AGENTDOSSIER_DEV=1` on a loopback bind; the app is started through a
  uvicorn factory so a misconfigured container exits instead of serving an open admin API.
- One guarded egress client for everything the server calls (webhooks, Slack, Teams,
  Jira, ServiceNow, GRC, federation peers): address vetted and pinned at connect time
  (DNS rebinding), no redirects, size cap, `AGENTDOSSIER_EGRESS_ALLOW` for private targets.
- Private-scope `/.well-known/ard.json` requires auth; `/healthz` is liveness only;
  chunked request bodies are capped; rate limits keyed per bearer token; session cookie
  `Secure` behind TLS; `AGENTDOSSIER_TRUSTED_PROXIES` governs forwarded headers.
- Container image built from `uv.lock` with digest-pinned bases; every GitHub Action
  pinned to a commit SHA; release permissions scoped per job; Dependabot.
- Hash-chained scan audit log (`audit.jsonl`, `agentdossier enterprise audit-verify`).

### Changed
- Homepage leads with search and a live specimen result; the detailed trust model moved
  to Methodology. Intent parser understands "HIPAA-compliant" / "FedRAMP-authorized".
- Server trimmed: `sqlalchemy`, `alembic`, `psycopg`, `cryptography` (direct) and
  `slowapi` dropped; in-house fixed-window limiter; settings via pydantic-settings; one
  `storage/schema.sql`; app-level exception handlers. `itsdangerous` declared (OIDC).
- Curated protocol claims require a named reviewer; enterprise CA bundle rides on the
  scan's network policy instead of the process environment.

## [Unreleased]

### Evidence-first dossiers
- The promise is narrowed to what the data supports: "Discover AI agents. Inspect the evidence.
  Decide what fits your risk requirements." (homepage, meta description, README).
- Every dossier opens with "Evidence available — not a safety certification" and splits the
  ledger into evidence about the agent and vendor-level (inherited) rows; the trust strip, the
  compare view and the homepage specimen count agent-scoped rows only.
- "Before you deploy" on every dossier: evidence supporting this use, unknowns to check, and
  rule-driven pilot restrictions (`config/deploy_rules.json`). Compare puts unresolved questions
  first and marks vendor-level rows.
- Reference set (`data/curated/reference_set.yaml`): eleven agents across two use cases answer
  five deployment questions each from vendor documentation, with sources; worked comparisons at
  `/compare/coding-agents-private-repo/` and `/compare/claims-intake-pii/` close with one honest
  sentence per agent. "Dispute or correct this dossier" opens a pre-filled GitHub issue.

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
