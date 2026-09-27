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
| FR-09 | Search / API | web (P1), server (P2) | `eval/queries.yaml` | P1 |
| FR-10 | Governance / provenance | `agentdossier/models.py`, `agentdossier/connectors/base.py` (snapshot store, hashes), `agentdossier/build.py` | `tests/test_dedup_build.py` | P1a (changelog in P1b) |
| FR-11 | Public demo site | `web/public/index.html` (placeholder), Astro site in P1 | Lighthouse and axe in P1 | P0 (placeholder), P1 |
| FR-12 | Open-source repository | `README.md`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md`, `.github/workflows/ci.yml`, `.github/workflows/pages.yml`, `.github/workflows/refresh.yml`, `scripts/validate_catalog.py`, `scripts/catalog_summary.py` | CI; weekly refresh PR | P1a |
| FR-13 | Enterprise private discovery | `agentdossier/enterprise/` (scanner in P2) | self-test in P2 | P2 |
| FR-14 | Private data handling | `schema/resource.schema.json` (scope, tenant), `schema/catalog_index.schema.json` | P1 viewer | P0 (schema), P1 |
| FR-15 | ARD registry API | `agentdossier/server/` (P2) | conformance CLI in P2 | P2 |
| FR-16 | Seed import with score reproduction | `agentdossier/connectors/seed_xlsx.py` | `tests/test_seed_import.py`, CI step "Seed fidelity" | P0 |
| FR-17 | Registry self-description | `web/public/.well-known/ard.json` | validated by `agentdossier/standards/ard.py` | P0 |
| FR-18 | Corrections via GitHub | `CONTRIBUTING.md`, `data/review/` | maintainer process | P0 (process), P1 (changelog) |
| FR-19 | Compliance evidence model | `schema/compliance_record.schema.json` | `tests/test_config.py` | P0 |
| FR-20 | Authoritative registry connectors | `agentdossier/compliance/` (P1), `config/sources.json` | P1 | P1 |
| FR-21 | Claim extraction | `agentdossier/compliance/` (P1) | P1 | P1 |
| FR-22 | Verification and tiering | `config/frameworks/` (credit, wording) | `tests/test_config.py` | P0 (config), P1 (engine) |
| FR-23 | Freshness and expiry | `config/frameworks/` (expiry_rule) | P1 | P0 (config), P1 |
| FR-24 | Compliance search and display | web (P1) | P1 | P1 |
| FR-25 | Evidence-based governance score | `agentdossier/score.py` (sar-score-1.1 in P2) | P2 | P2 |
| FR-26 | Evidence corrections | `CONTRIBUTING.md` | process | P0 |
| FR-27 | Intent-based onboarding | `config/intent_rules.json`; `web/` intent.ts (P1) | `eval/intent_cases.yaml` | P0 (rules), P1 |
| FR-28 | Decision lifecycle | server (P3) | P3 | P3 |
| FR-29 | Identity and accounts | server (P2) | P2 | P2 |
| FR-30 | Workspaces, saved searches, shortlists | web local (P1), server (P2) | P1 | P1/P2 |
| FR-31 | Watchlists and alerts | server jobs (P2) | P2 | P2 |
| FR-32 | Policy profiles | `agentdossier/policy/engine.py`, `schema/policy.schema.json`, `config/policy_templates/` | `tests/test_policy_engine.py`, `eval/policy_cases.yaml` | P0 (engine, templates), P1 (UI) |
| FR-33 | Recommendation explanations | web explain.ts (P1) | P1 | P1 |
| FR-34 | Collaboration and procurement workflow | server (P3) | P3 | P3 |
| FR-35 | Internal feedback | server (P3) | P3 | P3 |
| FR-36 | Publisher guidance | `CONTRIBUTING.md`, docs (P1) | process | P0/P1 |
| FR-37 | Integrations | server (P3) | P3 | P3 |
| FR-38 | Machine constraint contract | `agentdossier/policy/engine.py`; `POST /qualify` (P2) | `tests/test_policy_engine.py` | P0 (engine), P2 (API) |
| FR-39 | Contributions via GitHub | `CONTRIBUTING.md`, `.github/CODEOWNERS` | process | P0 |
| FR-40 | Instance analytics (optional) | server (P3) | P3 | P3 |
| FR-41 | Dry run and self-test | `agentdossier/enterprise/` (P2) | P2 | P2 |
| FR-42 | Preflight and operator kit | `agentdossier/enterprise/` (P2), `examples/enterprise/enterprise.json` | `tests/test_config.py` (config schema) | P0 (schema, example), P2 |
| FR-43–47 | News and chatter | `agentdossier/news/` (P1) | P1 | P1 |
| FR-48 | Trust profile | web (P1), `schema/catalog_index.schema.json` (trust summary) | P1 | P0 (schema), P1 |
| FR-49 | Identity-first crediting | `agentdossier/build.py` (identity-1.0 rules), `config/frameworks/` credit | `tests/test_dedup_build.py` | P1a (crediting rule applied in P1b) |
| FR-50 | Framework catalog as configuration | `config/frameworks/` (15 files) | `tests/test_config.py`, `agentdossier/cli.py` config-check | P0 |
| FR-51 | Jurisdiction applicability | `config/frameworks/` (jurisdictions), `schema/policy.schema.json` | P1 | P0 (config), P1 |
| FR-52 | Negative evidence and checklist | `schema/resource.schema.json` (issues) | P1 | P0 (schema), P1 |
| FR-53 | Registry accountability | `docs/` methodology (P1), `data/changelog/` | P1 | P1 |

Security controls (plan section 9): SSRF guard and scanner scope in
`agentdossier/util.py`, tested by `tests/test_netpolicy.py` (P0).
