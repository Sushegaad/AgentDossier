# AgentDossier

**An evidence dossier for every AI agent.**

AgentDossier is a vendor-neutral registry of AI agents that leads with
evidence instead of marketing. For each agent it shows what compliance and
trust evidence exists — HIPAA, SOC 2, FedRAMP, GDPR, ISO/IEC 42001, the EU AI
Act and more — who issued it, what it covers, whether it is still current and
what you still have to verify yourself. Agents are discovered through the open
standards they publish (Agentic Resource Discovery, Agent2Agent, Model Context
Protocol) as well as public registries and marketplaces, and the same engine
can scan an enterprise's own network for the agents already running there.

- **Public demo:** https://sushegaad.github.io/AgentDossier/ — static, no accounts, cookieless analytics unless you opt in
- **Self-hosted edition:** the same MIT codebase as one container with an authorized private-network scanner, ARD REST API, policy qualification, decision workflow and integrations
- **Docs:** [`docs/methodology.md`](docs/methodology.md) (how evidence is graded), [`docs/enterprise-runbook.md`](docs/enterprise-runbook.md) (run your own), [`docs/architecture.md`](docs/architecture.md), [`docs/brd-traceability.md`](docs/brd-traceability.md), [`CHANGELOG.md`](CHANGELOG.md)

### How it grades evidence

Every claim carries a tier and a date. The tier says *how* we know, not how
good the agent is:

| Tier | Meaning | Example |
|---|---|---|
| T1 | Registry-matched | found in the FedRAMP Marketplace or the CSA STAR registry on the stated date |
| T2 | Marketplace-listed | listed on a cloud marketplace that performs its own vetting |
| T3 | Document-evidenced | a certificate or report reviewed by a named maintainer |
| T4 | Vendor-claimed | stated on the vendor's trust page, not yet verified |
| T5 | No evidence found | shown as unknown — never as non-compliant |

Protocol support (MCP · A2A · ARD) is reported the same way: ✔ verified at
the publisher's endpoint, ○ documented by the vendor or named by the agent
itself, – probed and not found, ? never probed. Claims never outrank probes,
and evidence only counts toward an agent's score once the publisher's identity
is established. The full rules, with version numbers, are in
`docs/methodology.md`.

## Example use case

An insurer's platform team is asked to pick a claims-intake agent and prove
to risk and legal that the choice was defensible.

1. **Search by intent.** On the demo, type *HIPAA-compliant claims intake agent*.
   The query becomes chips (compliance: HIPAA · domain: insurance · capability:
   claims intake) that you can edit, and every result shows its trust profile
   next to its relevance.
2. **Read the dossier.** Open the top result. The evidence ledger lists each
   framework with its issuer, scope, as-of date and a link to the source; the
   gaps line says what is still unverified; the protocol row says whether the
   agent can be wired in over MCP or A2A.
3. **Shortlist and compare.** Add three candidates to the shortlist, compare
   their score breakdowns side by side, and export CSV or JSON with the
   sources attached for the risk review.
4. **Qualify against policy (self-hosted).** The team's instance runs
   `POST /qualify` with the insurer's policy template; the verdict
   (eligible / needs review / disallowed) and the failing rules go into a
   decision record that security and legal sign off per role. The signed
   packet is exported to the GRC system, and the repository's
   `agents.lock.json` is checked on every pull request by the GitHub Action,
   so a later loss of evidence blocks the build instead of surprising an
   auditor.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 22 (for the site).

```bash
git clone https://github.com/Sushegaad/AgentDossier && cd AgentDossier
uv sync --extra dev
uv run pytest -q                                   # ~150 tests, all offline

# build a catalog from the seed workbook only (no network)
uv run agentdossier build --sources seed --offline --out /tmp/catalog

# live build: registries, vendor trust pages and news for a small slice
uv run agentdossier build --sources seed,marketplaces --claim-domains 12 --news-limit 12 \
  --out /tmp/catalog --cache /tmp/cache

# run the site against it
cd web && npm ci && CATALOG_DIR=/tmp/catalog npm run dev
```

`--no-compliance` and `--no-news` skip those stages; `GITHUB_TOKEN` enables
the GitHub connector and release feeds and `NVD_API_KEY` lifts the NVD rate
limit. Hand-verified evidence, publisher-domain checks and documented
protocol support live in `data/curated/`. The public catalog is rebuilt every
Monday by `.github/workflows/refresh.yml` and published through GitHub Pages.

## Self-hosted edition

The enterprise edition finds the agents your teams already run — by reading
the ARD manifests, A2A agent cards and MCP server cards they publish — and
puts a governance surface around them. Nothing leaves your network.

```bash
uv sync --extra connectors --extra server --extra mcp
agentdossier enterprise selftest                                  # loopback end-to-end check
agentdossier enterprise preflight examples/enterprise/enterprise.json
agentdossier enterprise plan examples/enterprise/enterprise.json  # dry run for the change ticket
agentdossier enterprise scan examples/enterprise/enterprise.json
```

Run it as one container (`deploy/docker-compose.yml`, or the Helm chart in
`deploy/helm/agentdossier`); the image on GHCR is signed with cosign and
ships an SBOM. The instance serves:

- the web UI and the **ARD REST API** (`/.well-known/ard.json`, `POST /search` with federation to peer registries, `GET /agents`)
- **`POST /qualify`** — the machine constraint contract: a verdict per agent against a policy template or an inline policy
- the **decision workflow**: lifecycle with per-role sign-offs, comments, review tasks, feedback, and a decision packet export (JSON/CSV)
- **notifications and integrations**: email, signed webhooks, Slack, Teams, Jira, ServiceNow, a GRC webhook, and a GitHub Action that qualifies a repository's `agents.lock.json` on every pull request
- **identity**: OIDC with member/reviewer/admin roles, SCIM 2.0 provisioning, static tokens for service accounts; an MCP wrapper so internal agents can query the registry

The scanner refuses to run without an authorization record and only reaches
the CIDRs and hosts you list; every probe is written to a hash-chained audit
log. The operator guide is [`docs/enterprise-runbook.md`](docs/enterprise-runbook.md).

## Author

Hemant Naik — [LinkedIn](https://www.linkedin.com/in/tanaji-naik/) · [hemant.naik@gmail.com](mailto:hemant.naik@gmail.com)

Built October 2026 as a reference implementation. Issues and pull requests
are welcome; see `CONTRIBUTING.md` and `SECURITY.md` for reporting a
vulnerability.

## License and disclaimer

Code is released under the MIT License (see `LICENSE`). The compiled catalog
data is CC BY 4.0 with per-record source attribution. Third-party files keep
their own licenses; see `THIRD_PARTY_NOTICES.md`.

AgentDossier compiles information from public sources as of the date shown
on each record. It is **not** an assessment, certification, legal opinion or
recommendation, and no vendor or issuing body has endorsed it. Evidence can
expire or be withdrawn after it was collected; absence of evidence means only
that none was found in the sources checked. Confirm current status with the
vendor and the issuing body before relying on it.
