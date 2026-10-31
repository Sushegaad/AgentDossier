# Changelog

All notable changes to AgentDossier. The format follows Keep a Changelog; versions
follow SemVer. Catalog data versions (`sar-score`, `frameworks`, `identity`) are
listed in `docs/methodology.md`.

## [Unreleased]

### Changed — analytics on the public demo now reports
- Google Analytics ran with `analytics_storage` denied and no way to grant it, so every hit was a
  cookieless ping that GA4 never surfaces in reports: months of collection, nothing to read.
  Analytics storage is now granted on the demo build (first-party `_ga` cookie, anonymised IP);
  advertising storage, ad data and personalisation stay denied. Footer, `/about/`, README and
  `docs/architecture.md` say so instead of "cookieless". Self-hosted builds still have no tag.

### Changed — traces listed newest first
- The incident registry loads sorted by date, newest first (ties by id), so `/traces/`, the
  dossier's incident list and the JSON export lead with the latest event; `/cves/` already did.

### Fixed — documentation drift after the machine review shipped
- The review stamps the registry's `collected_on` on every publish, so `/traces/` "as of" moves
  with the data (it showed 2026-10-11 under rows published 2026-10-25). CONTRIBUTING, README's
  technical design, `docs/traces.md`, `docs/architecture.md` (now describes both registries and the
  self-merging refresh), `docs/cves.md` and `/methodology/#cves` no longer describe a person
  promoting candidates or an "unreviewed" CVE list.

### Changed — the incident registry publishes by default (machine review, no human in the loop)
- `agentdossier incidents review` runs in the weekly refresh after the scout: it fetches each new
  candidate's article (and any placeholder's sources), asks a model (`ANTHROPIC_API_KEY`;
  `claude-sonnet-5-5` by default) one structured question against that text only, validates the
  JSON reply field by field, and **publishes** the record when it is a specific, real event with
  confidence ≥ 0.8 from a non-aggregator source — `reviewer: "model: … (automated review)"`,
  `checked_on` the run date — or **dismisses** the candidate with the reason on file. Placeholders
  that fail are removed in place; unreadable pages wait a week. The model is told never to invent,
  never to reproduce prompts or payloads, never to name a private individual.
- The refresh PR now **merges itself** once the gates pass (drift check, trace chain, the incident,
  review and CVE tests run in the job) and dispatches the Pages deploy, since a PR opened with
  `GITHUB_TOKEN` triggers neither `ci` nor `pages`. The PR body lists every decision.
- `/traces/` no longer shows "candidates awaiting review"; its header reads feeds scouted ·
  machine-reviewed date · rows published by the weekly review, rows are marked *machine-reviewed*,
  and the re-check becomes a footnote. The incident page says when the review published a row.
  `/methodology/#traces`, `/about/`, README and `docs/incidents.md` describe the bar; the docs no
  longer quote a fixed incident count (the drift check now forbids one).
- `tests/test_incident_review.py` (5): verdict parsing and the bar, article stripping, an offline
  end-to-end run (publish, dismiss, placeholder rewrite and removal, idempotence), dry run, and the
  API call shape.

### Added — CVE cross-links (PR 3 of 3)
- Every dossier's **Security** row now says what the CVE registry links to the agent ("36 CVEs
  linked · 27 critical/high · newest 2026-09-17", or "No CVE linked … none linked in the products
  checked, not a finding"), and a **CVEs — on the official record** band after Traces lists the
  newest eight with severity, surface and fix status, linking to the filtered registry. The NVD
  keyword count is retired from the dossier (the Issues row points to Security); no score changes.
- Search results carry the same line (`/cves/agents.json`); an incident page lists the **CVEs on
  record** (the new `cves:` field in `schema/incident_record.schema.json`, set on TR-2026-002,
  TR-2026-011 and the TR-2026-027 placeholder, plus any registry record naming the incident);
  a CVE page lists the dossiers and incidents that name it. `/methodology/` says how the links
  are made and read. README dossier screenshots re-shot.

### Added — CVE registry on the site (PR 2 of 3)
- A **CVEs** tab (`/cves/`) between Traces and Trust methodology: every listed CVE in one
  filterable table — KEV, reviewed, severity, attack surface, category, product, year, fix status;
  word search; sort by published / last modified / CVSS / id; CSV export of the visible rows;
  every filtered view is a link (`/cves/?surface=prompt_injection&kev=1`) — over a slim
  `/cves/list.json`, with `/cves/export.json` for the whole registry.
- A page and JSON per CVE (`/cves/<id>/`): the official record (description, CVSS with vector and
  scorer, CWE, NVD status, CNA), affected products with fixed-in versions, KEV details, references
  (deduplicated, never exploit-tagged), links to dossiers and traces, and *why it is listed here*
  (the tests and terms, the reviewer or "not yet checked by a person"). Buttons to CVE.org, NVD,
  JSON and "Report a wrong listing".
- `/methodology/#cves` states the two tests and what is and is not the registry's; `/about/`
  names the source; README gains a screenshot of the tab; the axe/Lighthouse audit covers
  `/traces/`, `/cves/` and one CVE page. Unlisted products are shown by their tidied CPE name.
- `web/tests/cves.test.ts` pins the filter model, URL round-trip, CSV, the loader and cross-links.

### Added — CVE registry (data stage, PR 1 of 3)
- **`agentdossier cves update`** runs in the weekly refresh: reads official records from NVD API
  2.0 (the CVE.org record plus CVSS, CWE, CPE) and the CISA KEV catalog, keeps a CVE when a listed
  agent product/framework/protocol/infrastructure is affected (Test A: CPE or exact name, 41
  products in `config/cve_products.json`) or the weakness is agent-specific (Test B: CWE-1427 or
  the vocabulary), assigns a category and attack-surface tags, links catalog agents and incidents,
  applies the maintainer's `data/curated/cve_overrides.yaml` (include/exclude/notes/signatures,
  retired products), and writes `data/cves/index.json` validated against
  `schema/cve_record.schema.json`. Deterministic; `--offline <dir>` replays saved responses;
  `cves plan|show|include|exclude|spot-check`. First backfill (2023 onward, 35 targeted queries):
  2,149 fetched → 1,738 listed across 29 products, 10 in KEV. A product's display name is never matched (only its specific `names`), so "Continue" and "Cursor" do not list every record using those words; a record about a third-party MCP or A2A implementation is categorised `protocol` without a product link. Exploit-tagged references are never
  stored; nothing here enters a score. The scout now hands bare advisory URLs to this registry
  instead of filing them as incident candidates. The refresh PR body lists new CVEs, KEV additions
  and a 50-row precision spot-check. `docs/cves.md`; the site tab follows in PR 2.

### Fixed — documentation drift, and a guard against it
- Eleven PRs had shipped without updating the documents that describe them. Corrected: README
  (the incident registry, weekly scout and re-check in the Traces feature; the harness described
  honestly as producing tier-1 traces only once a provider key is set; test count; analytics
  wording; docs index now lists `traces.md`, `traces-spec.md`, `incidents.md`; screenshots
  re-shot from the current build), `/methodology/#traces` (how traces and the registry are
  collected — the target of the `/traces/` "how it is collected" link, which previously pointed at
  a page that said nothing about traces), `/about/` (a registry row, the weekly scout and re-check),
  `/enterprise/` (the decision workflow and trace gate are built, not "the next phase"), the hero
  copy ("the public traces … on record" rather than "every public trace"), `docs/incidents.md`
  (13 published + 14 placeholders), `docs/enterprise-runbook.md` (the trace gate), and
  `CONTRIBUTING.md` (the candidate workflow and the docs rule).
- `deploy/Dockerfile` back to `python:3.13-slim` / `node:22-alpine` — the versions CI tests;
  Dependabot had moved it to Python 3.14 / Node 26, which nothing tests. Dependabot may now bump
  image digests and patch releases only.
- **`scripts/check_docs_drift.py`**, run by CI (lint job) and by `pytest`
  (`tests/test_docs_drift.py`): the README test count, Python and Node versions across README, CI
  matrix, Dockerfile and `pyproject`, the README docs index, and the incident counts in
  `docs/incidents.md` are verified against the repository on every change. A PR template carries
  the documentation checklist. Two `[Unreleased]` headings merged into one.

### Added — incident scout (the registry grows weekly)
- **`agentdossier incidents scout`** runs in the weekly refresh: reads twelve public feeds
  (`config/trace_sources.json` — The Hacker News, BleepingComputer, Dark Reading, SecurityWeek,
  Simon Willison's prompt-injection tag, Embrace The Red, Wiz, Unit 42, Trail of Bits, MSRC's
  update guide, Google Security Blog, OpenAI news; RSS/Atom via the standard library, no new
  dependency), keeps items that name both an *agent* and an *attack* (two keyword axes, whole-word
  matching for short terms), drops anything already cited by an incident, and merges the rest into
  `data/curated/incident_candidates.yaml` with stable ids and statuses (new / promoted / dismissed).
  Candidates are leads for the maintainer, never incidents: `incidents draft <id>` scaffolds a
  schema-valid `status: placeholder` record in `incidents.yaml` (appended, the hand-written file is
  not rewritten) and `incidents dismiss <id>` retires one. The refresh PR body lists the week's
  finds; `/traces/` shows the count awaiting review. First run over today's feeds: 6,643 items →
  60 candidates. Feed failures are reported, never fatal; `--offline <dir>` runs on saved feeds.

### Added — weekly source re-check
- **`agentdossier incidents recheck`** runs in the weekly refresh: re-fetches every published
  incident's source links (HEAD, then a capped GET) and records `ok` / `moved` / `gone` /
  `unverified` / `error` per link in `data/curated/incident_source_check.json`. Same-site redirects
  (CDNs) stay `ok`; a 200 from a bot-protection challenge page counts as `unverified`, not `ok`;
  only a cross-site redirect is `moved`. The refresh PR lists links needing attention, `/traces/`
  shows the re-check date and flags affected rows, and each incident page notes the status beside
  the link. Never edits an incident; never sets `checked_on`. First run: 18 links, 15 answer, 3
  bot-walled, 0 gone — after it caught a truncated Okta URL on TR-2026-008, now fixed.

### Added — incident registry
- **`/traces/` is now an incident registry** — one row per real, public event where an AI agent
  attacked or defended a system (`data/curated/incidents.yaml`, `schema/incident_record.schema.json`).
  Columns: ID, incident, AI role (attacker/defender/target), attacker, defender, **MITRE ATT&CK
  tactics**, sources. Each incident has a detail page with a timeline (per-line evidence tier and
  source), "what defenders can take from it," an "at a glance · as reported" panel, and **STIX 2.1
  + JSON export**. Seeded with thirteen sourced incidents (ForcedLeak, EchoLeak, CamoLeak, Gemini
  CLI, Amazon Q, AgentFlayer, the Claude Code espionage report, s1ngularity, the Replit database
  deletion, ShadowLeak, CurXecute/MCPoison, the GitHub MCP toxic agent flow, and the Gemini
  "Promptware" smart-home hijack). Dossiers cross-link to incidents that
  name the agent; "Traces" is promoted in the nav and the hero now leads with trust and under-attack
  behaviour. Everything stays "as reported," unreviewed until signed, with a correction link.
  (Per-agent trace bundles moved to `/traces/bundle/<id>/`.)

### Added — traces
- **Enterprise trace gate (PR 5).** A self-hosted tenant runs the harness against private agents
  and stores the results in its own database (`traces` table, never in the public store). A
  decision can set `require_trace_tier`, and approval is blocked until a trace of that tier or
  better exists for the agent (`agentdossier enterprise trace-selftest` exercises it with the
  mock). Optional publish-back to the public store.
- **Vendor-published traces (PR 4).** A vendor can serve a trace bundle and name it in its ARD
  manifest entry (`traces: [{url, format, sha256}]`); the build fetches it, checks the stated
  hash, and shows it on the dossier as `vendor_published` (tier 1 verified, tier 4 when only
  claimed). Spec and example bundle in `docs/traces-spec.md`.
- **Sandbox harness (`agentdossier harness`).** Produces new attack-and-defense traces by running
  an agent against the AgentDojo prompt-injection benchmark (MIT) — it does not author attacks —
  and recording, per task, whether the injection succeeded, as a tier-1 `injection_eval` bundle in
  the store. Model-level (`scope: model`), inherited by the catalog agents a model is mapped to in
  `data/traces/harness/models.yaml`. `--model mock` runs the full pipeline with no model or
  network; real runs go through the monthly `harness` workflow. Optional `harness` extra pins
  AgentDojo.
- Every dossier now carries **Traces**: public observations of the agent under attack, in
  defence or in an incident, tiered T1–T5 with "none found" said out loud. Seven curated
  public traces to start (EchoLeak, ForcedLeak, CamoLeak, the Gemini CLI and Amazon Q
  incidents, AgentFlayer, Anthropic's espionage-campaign report), each marked unreviewed
  until the maintainer signs it. New rules: run your own sandbox trace when none is public;
  egress allowlist when a trace shows data leaving. `/traces/` is the running count.
- An append-only, hash-chained trace store in `data/traces/` (verified in CI), and
  `self_test` bundles: every refresh records what each publisher's discovery endpoints
  served, as a reproducible transcript, whenever the observation changes.

### Changed — trust and credibility (one PR)
- **Scores (`sar-score-2.0`).** Trust and governance are recomputed from evidence for every
  row, including the curated Top 100; the workbook's values stay on the record
  (`seed_components`). The second "evidence-based governance" figure is gone; scores are
  integers. The Top 100 keeps the curator's order: the first build sorted by the recomputed
  score and put LangChain first in Sales and Copilot Studio first in Healthcare, because the
  workbook's fit value is 100 for nearly every row. Vendor-level evidence earns half credit in
  governance, and list rows show "agent T1 · vendor T1" instead of one tier.
- **Publisher identity (`identity-1.1`).** A product page on the vendor's own domain confirms
  the publisher (tier 2), so registry evidence for Agentforce, Bedrock and the like is credited.
  `config/vendor_aliases.json` maps workbook names to registry spellings ("AWS" → "Amazon",
  "Google Cloud" → "Google") for FedRAMP, CSA STAR, trust pages and identity. The "confirm the
  publisher" restriction fires only when nothing beyond the name is known.
- **One scale.** Only compliance evidence uses T1–T5. Publisher is confirmed / likely /
  unconfirmed / unknown; protocols are verified / documented / none found; the NVD check is
  shown as the keyword search it is, never as a tier. "Pending publisher verification" is gone;
  a dossier says once, above its ledger, when evidence is shown but not credited and why.
- **Say it once.** Ledger sentences no longer repeat the framework, source and date the row
  already shows; "Before you deploy" items are one line each; the disclaimer appears once; the
  "not non-compliance" note once per ledger.
- **Catalog hygiene.** Demo, sample, deprecated, hackathon and archived projects and
  repositories idle for a year are dropped from discovery (`connectors.hygiene`, counts in the
  build report). Release headlines read "aider v0.86.1", not "langchain langchain==1.4.4".
  Domain tables show the protocols column only when at least one row in ten has something in it.
- **Trust pages.** Vendor compliance pages up to 6 MB are read (Google Cloud's is 2.3 MB and
  was dropped as "too large").
- **About page** (`/about/`): what the site is, who maintains it, what is automated and what is
  reviewed by hand, how often it refreshes, how to report an error. Worked comparisons carry a
  draft banner until the maintainer records a review. The analytics consent prompt is removed;
  the public build sends cookieless aggregate pings only.
- Search: the domain score adds at most 10 points so text relevance decides the order.

### Added
- Refresh fills the gaps that left most ranked agents with an empty trust profile and
  blank protocol column: seed rows on GitHub are looked up once (`seed_enrich`) for
  repository ownership, publisher domain and topics; `data/curated/trust_pages.yaml`
  names the certifications page of large vendors the crawler never reached, and rows on
  shared hosts are crawled under their vendor's domain; a vendor's FedRAMP authorization
  is shown as an inherited vendor-level row when no offering matches the agent; a web
  page served where a protocol card should be is `not_found`, not `invalid`.
- News and chatter: every resource gets its repository's releases and its vendor's feed
  (short names such as "Aider" or "Dify" were skipped entirely); a release from the
  agent's own repository links without its name in the title.

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
