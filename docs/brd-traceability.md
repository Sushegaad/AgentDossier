# BRD traceability (v3.2 → code)

Maps every functional requirement to the modules and tests that implement it.
`scripts/check_traceability.py` fails CI if a referenced path is missing.
Status: **P0** = delivered in Phase 0, **P1**–**P3** = planned phase.

| FR | Requirement | Modules | Tests / evidence | Status |
| --- | --- | --- | --- | --- |
| FR-01 | Multi-source ingestion | `agentdossier/connectors/seed_xlsx.py`, `agentdossier/connectors/github.py`, `agentdossier/connectors/huggingface.py`, `agentdossier/connectors/mcp_registry.py`, `agentdossier/connectors/ard_web.py`, `agentdossier/connectors/marketplaces.py`, `agentdossier/connectors/base.py` | `tests/test_seed_import.py`, `tests/test_connectors.py` | P1a |
| FR-02 | ARD discovery v0.91 | `agentdossier/standards/ard.py`, `agentdossier/connectors/ard_web.py` | `tests/test_standards.py`, `tests/fixtures/ard/` | P1a (DNS SVCB in P1b) |
| FR-03 | A2A inspection | `agentdossier/standards/a2a.py` | `tests/test_standards.py`, `tests/fixtures/a2a/` | P0 |
| FR-04 | MCP inspection | `agentdossier/standards/mcp.py` | `tests/test_mcp.py`, `tests/fixtures/mcp/` | P1a |
| FR-05 | Normalization | `agentdossier/models.py`, `schema/resource.schema.json` | `tests/test_seed_import.py` (schema validation) | P0 |
| FR-06 | Identity / dedup | `agentdossier/dedup.py`, `data/review/` | `tests/test_dedup_build.py` | P1a |
| FR-07 | Classification | `agentdossier/classify.py`, `config/taxonomy.json` | `tests/test_config.py` | P0 (keyword), P2 (model) |
| FR-08 | Scoring | `agentdossier/score.py`, `config/scoring.json` | `tests/test_score.py` | P0 |
| FR-09 | Search / API | `web/src/lib/search.ts` (site), `agentdossier/server/catalog.py` + `agentdossier/server/app.py` (`POST /search`, `/explore`, `GET /agents`) | `web/tests/search.test.ts`, `tests/test_server.py` | P1d (site), P2 (API) |
| FR-10 | Governance / provenance | `agentdossier/models.py`, `agentdossier/connectors/base.py` (snapshot store, hashes), `agentdossier/build.py` | `tests/test_dedup_build.py` | P1a (changelog in P1b) |
| FR-11 | Public demo site | `web/src/pages/`, `web/astro.config.mjs`, `.github/workflows/pages.yml` (Astro build; offline seed catalog until the first refresh) | `.github/workflows/ci.yml` web job, `web/scripts/audit.mjs` (axe + Lighthouse gates) | P1d |
| FR-12 | Open-source repository | `README.md`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md`, `.github/workflows/ci.yml`, `.github/workflows/pages.yml`, `.github/workflows/refresh.yml`, `scripts/validate_catalog.py`, `scripts/catalog_summary.py` | CI; weekly refresh PR | P1a |
| FR-13 | Enterprise private discovery | `agentdossier/enterprise/scanner.py`, `agentdossier/enterprise/targets.py` (hosts, CIDRs, DNS SVCB, registries), `agentdossier/enterprise/config.py` | `tests/test_enterprise.py` (loopback self-test) | P2 |
| FR-14 | Private data handling | `schema/resource.schema.json` (scope, tenant), `agentdossier/build.py` (scope/tenant/site options), `web/src/components/PrivateCatalogApp.tsx` | `tests/test_enterprise.py` (scope=private, tenant) | P2 |
| FR-15 | ARD registry API | `agentdossier/server/app.py` (`/.well-known/ard.json`, `POST /search`, `POST /explore`, `GET /agents`, `GET /agents/{id}`) | `tests/test_server.py` | P2 |
| FR-16 | Seed import with score reproduction | `agentdossier/connectors/seed_xlsx.py` | `tests/test_seed_import.py`, CI step "Seed fidelity" | P0 |
| FR-17 | Registry self-description | `web/public/.well-known/ard.json` | validated by `agentdossier/standards/ard.py` | P0 |
| FR-18 | Corrections via GitHub | `CONTRIBUTING.md`, `data/review/` | maintainer process | P0 (process), P1 (changelog) |
| FR-19 | Compliance evidence model | `schema/compliance_record.schema.json` | `tests/test_config.py` | P0 |
| FR-20 | Authoritative registry connectors | `agentdossier/compliance/fedramp.py`, `agentdossier/compliance/csa_star.py`, `agentdossier/compliance/matching.py`, `agentdossier/compliance/curated.py` (DPF, IAF, HITRUST by hand), `config/sources.json` | `tests/test_compliance.py`, `tests/fixtures/compliance/` | P1b (FedRAMP, CSA STAR automatic; DPF curated) |
| FR-21 | Claim extraction | `agentdossier/compliance/claims.py` (robots-aware, ≤5 pages/domain) | `tests/test_compliance.py` | P1b |
| FR-22 | Verification and tiering | `agentdossier/compliance/engine.py` (finalize, render_display), `config/frameworks/` (credit, wording) | `tests/test_compliance.py`, `tests/test_config.py` | P1b |
| FR-23 | Freshness and expiry | `agentdossier/compliance/engine.py` (apply_freshness), `config/frameworks/` (expiry_rule) | `tests/test_compliance.py` | P1b |
| FR-24 | Compliance search and display | `web/src/components/SearchApp.tsx` (evidence-level filter, must-have chips), `web/src/pages/agents/[slug].astro` (evidence list with tier, status, source, link, next check) | `web/tests/search.test.ts` | P1c |
| FR-25 | Evidence-based governance score | `agentdossier/compliance/engine.py` (governance_from_evidence, sar-score-1.1), `agentdossier/build.py` (governance_evidence per domain) | `tests/test_compliance.py` | P1b (shown beside sar-score-1.0; not yet blended) |
| FR-26 | Evidence corrections | `CONTRIBUTING.md`, `data/curated/` (compliance.yaml, identity.yaml) | `tests/test_compliance.py` (curated) | P1b |
| FR-27 | Intent-based onboarding | `config/intent_rules.json`, `web/src/lib/intent.ts`, `web/src/components/SearchApp.tsx` (chips, filters) | `web/tests/intent.test.ts` (52 cases in `eval/intent_cases.yaml`, ≥ 95 % gate) | P1d |
| FR-28 | Decision lifecycle | `agentdossier/server/workflow.py` (stages candidate → under_review → approved/rejected/deferred → retired, append-only `decision_events`, per-role `approvals`, policy verdict recorded at open and approval), `agentdossier/server/app.py` (`/api/decisions…`), `agentdossier/server/auth.py` (member / reviewer / admin roles) | `tests/test_workflow.py` | Wk 13–14 |
| FR-29 | Identity and accounts | `agentdossier/server/auth.py` (none / static token / OIDC via Authlib; member / reviewer / admin roles from groups), `agentdossier/server/scim.py` (SCIM 2.0 Users with filter, patch, delete; a deprovisioned person is refused at sign-in), `agentdossier/server/settings.py` | `tests/test_server.py`, `tests/test_federation_scim.py` | P2 (OIDC), Wk 16 (SCIM) |
| FR-30 | Workspaces, saved searches, shortlists | `web/src/lib/shortlist.ts`, `web/src/components/ShortlistApp.tsx` (browser-local, JSON export); shareable search and compare URLs | manual | P1c (local), P2 (server) |
| FR-31 | Watchlists and alerts | `agentdossier/server/notify.py` (email + signed webhook; scan.done, catalog.changed with the diff, scan.failed, evidence.expiring), `agentdossier/server/app.py` (scheduled scans, daily expiry job, `/api/deliveries`, `/api/notify/test`, `/api/evidence/expiring`), `agentdossier/storage/db.py` (deliveries) | `tests/test_notify.py` (incl. reference deployment end to end) | P2 (schedule), Wk 12 (alerts); per-user watchlists P3 |
| FR-32 | Policy profiles | `agentdossier/policy/engine.py`, `schema/policy.schema.json`, `config/policy_templates/` | `tests/test_policy_engine.py`, `eval/policy_cases.yaml` | P0 (engine, templates), P1 (UI) |
| FR-33 | Recommendation explanations | `web/src/lib/search.ts` (template explanation per hit: rank, matched terms, capability, evidence tier, protocol, deployment, gaps), `config/search_synonyms.json` | `web/tests/search.test.ts` (precision@10 ≥ 0.80 on `eval/queries.yaml`) | P1d |
| FR-34a | Integrations | `agentdossier/server/integrations.py` (Slack, Teams, Jira, ServiceNow as notification channels; GRC webhook with the signed decision packet), `deploy/action/` (GitHub Action policy check over `agents.lock.json`, `schema/agents_lock.schema.json`) | `tests/test_integrations.py` (payload shapes against a local sink; the action against a live instance) | Wk 15 |
| FR-34 | Collaboration and procurement workflow | `agentdossier/server/workflow.py` (comments with threads, review tasks with assignee and due date, decision packet export JSON/CSV with trust snapshot), `decision.changed` notifications | `tests/test_workflow.py` (API end to end: approval with two sign-offs, export) | Wk 13–14 (API; UI pending) |
| FR-35 | Internal feedback | `agentdossier/server/workflow.py` (feedback: rating 1–5, correction, incident, note; triage open → acknowledged → resolved; per-resource summary), `/api/feedback` | `tests/test_workflow.py` | Wk 13–14 |
| FR-36 | Publisher guidance | `CONTRIBUTING.md`, docs (P1) | process | P0/P1 |
| FR-37 | Integrations | see FR-34a (Slack, Teams, Jira, ServiceNow, GRC webhook, GitHub Action) | `tests/test_integrations.py` | Wk 15 |
| FR-38 | Machine constraint contract | `agentdossier/policy/engine.py`, `agentdossier/server/app.py` (`POST /qualify`, `GET /policies`), `agentdossier/server/mcp_server.py` (`qualify_agent`) | `tests/test_policy_engine.py`, `tests/test_server.py` | P2 |
| FR-39 | Contributions via GitHub | `CONTRIBUTING.md`, `.github/CODEOWNERS` | process | P0 |
| FR-40 | Instance analytics (optional) | server (P3) | P3 | P3 |
| FR-41 | Dry run and self-test | `agentdossier/enterprise/selftest.py` (loopback publisher), `agentdossier/enterprise/scanner.py` (dry_run), CLI `enterprise selftest` / `plan` | `tests/test_enterprise.py` | P2 |
| FR-42 | Preflight and operator kit | `agentdossier/enterprise/preflight.py`, `examples/enterprise/enterprise.json`, `deploy/Dockerfile`, `deploy/docker-compose.yml`, `docs/enterprise-runbook.md` | `tests/test_enterprise.py`, `tests/test_config.py` (schema) | P2 |
| FR-43 | News sources | `agentdossier/news/sources.py` (Hacker News, GDELT with circuit breaker, GitHub releases, vendor RSS/Atom, NVD) | `tests/test_news.py` | P1b |
| FR-44 | Entity linking | `agentdossier/news/linking.py` (link_confidence ≥ 0.85, distinctive names) | `tests/test_news.py` | P1b |
| FR-45 | Ranking and diversity | `agentdossier/news/linking.py` (cluster, rank) | `tests/test_news.py` | P1b |
| FR-46 | News panel | `web/src/pages/agents/[slug].astro` (top-10 items with tag, outlet, date, link confidence) | build smoke test in `.github/workflows/ci.yml` | P1c |
| FR-47 | Headline, link and short description only | `agentdossier/news/sources.py` (item: 240-char summaries, no article bodies) | `tests/test_news.py` | P1b |
| FR-48 | Trust profile | `web/src/pages/agents/[slug].astro`, `web/src/components/TrustStrip.tsx`, `web/src/components/CompareApp.tsx`, `schema/catalog_index.schema.json` (trust summary) | `web/tests/search.test.ts`, CI build | P1c |
| FR-49 | Identity-first crediting | `agentdossier/build.py` (identity-1.0 rules incl. publisher-domain and curated), `agentdossier/compliance/engine.py` (credited flag), `data/curated/identity.yaml` | `tests/test_dedup_build.py`, `tests/test_compliance.py` | P1b |
| FR-50 | Framework catalog as configuration | `config/frameworks/` (19 files: 15-framework launch set plus Phase-2 GovRAMP, BSI C5, IRAP, DORA, HITRUST, PCI DSS; `frameworks-1.1`) | `tests/test_config.py`, `agentdossier/cli.py` config-check | P0 |
| FR-51 | Jurisdiction applicability | `config/frameworks/` (jurisdictions), `schema/policy.schema.json` | P1 | P0 (config), P1 |
| FR-52 | Negative evidence and checklist | `agentdossier/news/run.py` (issues from tagged news + NVD CVEs), `schema/resource.schema.json` (issues, security) | `tests/test_news.py` | P1b, P1c (issues shown on the profile and in compare) |
| FR-53 | Registry accountability | `agentdossier/compliance/engine.py` (changelog_events, append_changelog), `data/changelog/`, `web/src/pages/changelog.astro`, `web/src/pages/methodology.astro` | `tests/test_compliance.py` | P1b/P1c |

Security controls (plan section 9): SSRF guard and scanner scope in
`agentdossier/util.py`, tested by `tests/test_netpolicy.py` (P0).
| ARD §6 | Registry federation | `agentdossier/server/federation.py` (`referrals` and `auto` modes, REST peers and static-manifest peers, hop header against loops), `POST /search {federation}` | `tests/test_federation_scim.py` (live REST peer, static manifest peer, dead peer) | Wk 16 |
| NFR | Hardening | `agentdossier/server/app.py` (security headers, CSP, HSTS, body cap, per-client rate limit on search/explore/qualify), `SECURITY.md`, `.github/workflows/release.yml` (signed image, SBOM) | `tests/test_federation_scim.py` | Wk 16 |
