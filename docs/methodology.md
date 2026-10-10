# Methodology

## Scores (`sar-score-1.0`)

Seven components are normalized to 0-100 (adoption /30, trust /25, health
/20, ecosystem /15, domain fit /100, governance /100, docs /10) and weighted
by the domain's profile in `config/scoring.json`:

| Dimension | General | Technology | Regulated | Security | Commercial | Data | Operations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Adoption | 25 | 30 | 15 | 20 | 25 | 25 | 20 |
| Trust & security | 20 | 20 | 25 | 25 | 20 | 20 | 20 |
| Health | 15 | 20 | 10 | 15 | 15 | 20 | 15 |
| Ecosystem | 10 | 15 | 10 | 10 | 15 | 15 | 15 |
| Domain fit | 10 | 10 | 20 | 15 | 15 | 15 | 20 |
| Governance | 5 | 0 | 15 | 10 | 5 | 0 | 5 |
| Docs | 5 | 5 | 5 | 5 | 5 | 5 | 5 |

Weights are normalized by their sum. An unknown component contributes 0 and
is flagged; it is never imputed. These profiles reproduce all 1,200 scores in
the 25 Sep 2026 seed workbook within 0.1. Scores are comparative discovery
signals, not certification.

## Evidence tiers

1 Registry-matched (credit 1.0) · 2 Marketplace-listed (0.8) · 3
Document-evidenced (0.7) · 4 Vendor-claimed (0.3) · 5 Unknown (0). Expired,
stale, revoked, in-process and inherited items earn zero and are shown with
their dates. Wording per framework lives in `config/frameworks/*.json`.

### Where evidence comes from (P1b)

| Source | Tier | How it is matched | Cadence |
| --- | --- | --- | --- |
| FedRAMP Marketplace `data.json` | 1 | vendor ↔ CSP (legal entity) **and** product ↔ CSO (offering); accept needs confidence ≥ 0.9 with entity ≥ 0.85 and offering ≥ 0.8, else the pair goes to `data/review/matches.yaml` | weekly |
| CSA STAR Registry index | 1 | vendor ↔ organization card; the card's filter terms give STAR Level 1/2, STAR for AI, AIUC-1 and ISO/IEC 42001. Entry pages are not crawled | weekly |
| Maintainer-curated (`data/curated/compliance.yaml`) | 1–4 by what was checked | DPF list, IAF CertSearch, HITRUST letters and any document reviewed by hand; every record carries an evidence URL, a date and who checked | on edit |
| Marketplace listings (`data/curated/marketplaces.json`) | 2 | listing metadata (e.g. AWS "HIPAA eligible") | weekly |
| Vendor trust/security pages | 4 | robots-aware crawl of at most five pages per publisher domain; a framework named on the page becomes a *claim* with that page as evidence | weekly, stale after 3 months |
| Curated trust pages (`data/curated/trust_pages.yaml`) | 4 | the certifications page of a large vendor (AWS, Google Cloud, Microsoft, …) that the five-page walk never reaches; read first, then the normal walk. Rows hosted on a shared host (a GitHub repository, an AWS Marketplace listing) are crawled under their vendor's own domain when `vendors:` names it, never under the host's | weekly, stale after 3 months |

Rules that never bend: "HIPAA certified" is never rendered (HIPAA has no
certification; the badge reads *BAA available*); "GDPR certified" appears
only for a verified Art. 42 seal; a registry match that is only strong on the
vendor name is a review item, not a badge (Oracle SCM Agents is not Oracle
Service Cloud). Records are deduplicated per (framework, variant) keeping the
best tier, then freshness is applied from the framework's `expiry_rule`
(`fixed_date`, `period_end_plus_months`, `recheck_months`, `mirror_registry`)
and a `next_check` date is set from the source cadence.

### Evidence-based governance (`sar-score-1.1`)

For each domain a preset of frameworks applies (healthcare: HIPAA, HITRUST,
SOC 2; government: FedRAMP, CSA STAR, ISO 27001; …) plus ISO 42001 and CSA
STAR for every domain. The component is the mean over that preset of the best
*credited, active* record's tier credit, scaled to 0–100. It is published as
`governance_evidence` next to the workbook's `sar-score-1.0` governance value
and is not blended into the rank yet; the two are meant to be compared.

### Trust changelog

Every build diffs each resource's compliance summary against the last
published index and appends `badge_added`, `badge_changed` and
`badge_removed` events to `data/changelog/trust-changelog.jsonl` (FR-53).

## Changes

Any change to scoring weights, the taxonomy, a framework file or an evidence
rule goes through a reviewed pull request, bumps the relevant version string
and is recorded in `data/changelog/trust-changelog.jsonl`.

## Discovered resources (`components-from-signals-1.0`)

Resources found by the live connectors have no workbook components, so the
seven components are derived from observable signals. Every rule is
heuristic and versioned; a component with no supporting signal is unknown
(scored 0 and flagged), never imputed.

| Component | Derived from |
| --- | --- |
| Adoption /30 | log10 of GitHub stars (or Hugging Face likes ×10, downloads /100) against a ceiling of 150,000 |
| Trust /25 | identity tier base (T1 20, T2 18, T3 15, T4 10, T5 6) + 2 per verified protocol, 1 per claimed, +1 signed Agent Card, +1 declared license |
| Health /20 | days since last push or update: <30 → 20, <90 → 16, <180 → 12, <365 → 8, else 4; archived → 2 |
| Ecosystem /15 | MCP verified 6 / claimed 3.6, A2A 5 / 3, ARD 4 / 2.4, +0.3 per topic (max 3), +1 per MCP transport |
| Domain fit /100 | classifier confidence × 100 |
| Governance /100 | tier-weighted credit of active compliance records (Phase 1b); unknown until evidence exists |
| Docs /10 | description 4, homepage 3, representative queries 2, capabilities 1 |

Discovered resources appear in domain lists as **unranked** entries sorted
by score. The seed workbook remains the ranked Top 100 per domain (frozen
baseline) until the maintainer re-scores.

## What one evidence row says

Every material claim on a dossier is shown as a compact block with the same six fields, so a
reader can tell at a glance what is independently supported, what is self-reported and what is
unknown:

| Field | Where it comes from | What the reader sees |
|---|---|---|
| Claim | `framework` + `variant` | the precise assertion ("SOC 2 Type II", "FedRAMP Moderate"), never "secure" or "compliant" |
| Subject and scope | `scope` (`entity` / `product`) + `covers_resource` | whether the evidence is about this agent or about its vendor; vendor-level rows are shown in a separate, muted group and **never count toward the agent's evidence tier** |
| Evidence type | `tier` | T1 registry match, T2 marketplace listing, T3 reviewed document, T4 vendor assertion, T5 nothing found |
| Provenance | `issuer`, `source`, `evidence_url` | who issued it and the page or registry entry it was read from — every row links |
| Timing | `issued`, `retrieved_at`, `valid_until` / `period_end` / `next_check` | the as-of date, the expiry where one exists, and when it is re-checked |
| Limitations | the framework's wording template | what the row does not establish ("covers platform, not this agent", "pending publisher verification", "a DPA is a contract you still have to sign") |

Agent-level versus vendor-level: a CSA STAR entry for "Microsoft" is real evidence that the
organisation was assessed and says nothing about whether one product is inside that scope. The
site groups such rows under "About the vendor — inherited" and the trust strip, the compare view
and the homepage specimen count only agent-scoped rows (`agentScoped()` in `web/src/lib/dossier.ts`).

FedRAMP has the same split. When no marketplace offering matches the agent but the vendor
holds a FedRAMP authorization for something else, the build adds one vendor-level row for the
vendor's highest authorized impact level with `covers_resource: inherited` (tier 1, scope
`entity`). "Amazon Bedrock Agents" is not on the marketplace; AWS's authorizations are, and the
dossier shows them in the vendor group, never in the agent-scoped strip.

## Before you deploy (`deploy-rules-1.0`)

Every dossier ends with three lists derived from data, never written per agent:

* **Evidence supporting this use** — active rows from the ledger (vendor-level ones labelled) and,
  for agents in the reference set, the deployment questions answered "yes" or "configurable".
* **Unknowns to check** — frameworks from the domain preset with nothing found, expired or stale
  rows, questions the vendor documentation does not answer, and the buyer checklist.
* **Suggested restrictions for a pilot** — rules in `config/deploy_rules.json`, each keyed to a
  condition (an answer value, a missing framework, an identity tier, a protocol state). They are
  advice for a bounded pilot, not a verdict.

### The reference set (`reference-set-1.0`)

`data/curated/reference_set.yaml` holds a small group of agents (two use cases: coding agents in a
private repository; claims-intake agents touching personal data) whose dossiers answer five
deployment questions each from the vendor's own documentation, with the page quoted and linked.
Values are `yes`, `no`, `configurable` or `unknown`; `unknown` means the pages checked do not say
and is a question for the vendor, not a mark against the agent. The file records who collected the
answers and, once a maintainer has re-checked every source, `reviewed_by`; until then the pages say
"maintainer review pending". The worked comparisons at `/compare/<use-case>/` are rendered from it
and close with one honest sentence per agent, including when the evidence is not sufficient to
scope a pilot. Corrections: the "Dispute or correct this dossier" link on every dossier opens a
pre-filled GitHub issue.

## Protocol status (MCP · A2A · ARD)

Each resource carries one status per protocol:

| Status | Meaning | Site glyph |
|---|---|---|
| `verified` | the build fetched and parsed the artefact on the publisher's own domain: `/.well-known/ard.json`, the A2A agent card, the MCP server card (or completed an MCP handshake) | ✔ |
| `claimed` | the vendor documents support (`data/curated/protocols.yaml`, with a reviewer, a date and the documentation URL) or the resource names the protocol in its own tags, description or deployment text; `source` says which | ○ |
| `invalid` | an artefact was found but did not validate | – |
| `not_found` | the publisher domain was probed and nothing was there. A web page served where the JSON artefact should be (the site's soft 404) counts as nothing there, not as an invalid artefact | – |
| `unknown` | never probed; `not_checked` says why (`code_host`: the URL is on github.com, huggingface.co, pypi.org or npmjs.com, which never carry a publisher's well-known files; `no_publisher_domain`) | ? |

Seed rows whose URL is a GitHub repository are looked up once (`GET /repos/{owner}/{repo}`,
`agentdossier/connectors/seed_enrich.py`) before any probe runs. The repository becomes
`external_ids.github` (identity tier 3, repository ownership), its homepage becomes the
`publisher_domain` the probes and the trust-page crawler use (a GitHub Pages or code-host
homepage does not), and its topics join the self-described protocol claims. Without that
step a workbook row such as `github.com/crewAIInc/crewAI` is "vendor name only" and `unknown`
on every protocol, however much the project publishes on crewai.com.

A claim never outranks an observation. When a curated claim sits next to a `not_found` probe the probe result is kept under `probe`, so the dossier can say "documented by the vendor; no endpoint at the well-known paths". Protocol trust tier is 1 with any `verified`, 3 with any `claimed`, else 5.

Vendor strings that name more than one entity ("GitHub / Microsoft", "OpenAI (Microsoft)") are matched against registries part by part and the best part wins, so a product sold under a subsidiary's name still finds the parent's FedRAMP and CSA STAR rows.

## Identity tiers (`identity-1.0`)

| Tier | Evidence |
| --- | --- |
| 1 | ARD manifest with a `trustManifest.identity` that binds to the publisher domain |
| 2 | Marketplace listing, ARD/A2A metadata served at the publisher's own domain, or a publisher domain the maintainer confirmed in `data/curated/identity.yaml` |
| 3 | Repository or Hub account ownership (GitHub, Hugging Face), or a resource URL on a domain that carries the vendor's name |
| 4 | Vendor name only |
| 5 | Unknown |

Certifications earn governance credit only once identity is tier 2 or better
(FR-49); until then they show as "pending publisher verification". Most seed
entries sit at tier 3 or 4 today, so their registry badges are visible but
uncredited until the vendor publishes an ARD manifest or A2A card, or the
maintainer records the domain check.

## News and chatter (FR-43–FR-47)

Sources: Hacker News (Algolia, stories with ≥ 5 points), GDELT DOC 2.0 (90
days, English; skipped for the rest of a run after two rate-limit failures),
GitHub releases (with a token), the vendor's own RSS/Atom feed discovered
from its homepage, and NVD for CVE counts. Every resource gets its own
repository's releases and its vendor's feed; only resources with a
*distinctive* name go to the name-search sources (two words, or one
non-generic word of six or more letters; "Muse" or "Dify" alone is not
searched). A release published by the agent's own repository links at
confidence 1.0 whatever its title; everything else must name the agent in
the headline plus one more signal (vendor named, vendor domain, vendor feed).

An item links to a resource only when the resource name appears in the
headline **and** a second signal agrees (vendor name in the text, publisher
domain in the URL, the vendor's own feed, or a distinctive multi-word name),
giving confidence ≥ 0.85. Near-identical headlines within 48 hours are
clustered. Ranking is link confidence × source authority (news/security 1.0,
community 0.8, vendor 0.7) × recency (half-life 14 days; 3 for community,
30 for security) × engagement × coverage breadth, with at most three items
per outlet, at most two vendor items and at least two community items when
available. Items tagged `security_incident`, `outage` or `legal_regulatory`
and NVD CVEs feed the resource's `issues` block. Only the headline, link,
outlet, date, tag and a 240-character summary are stored (FR-47).

## Duplicate handling

Deterministic keys (ARD URN, GitHub `owner/repo`, Hugging Face id, MCP
Registry name, A2A card URL, canonical URL) merge automatically, with the
seed record winning on descriptive fields. Two workbook products that share
a key stay separate. Name similarity ≥ 0.92 only creates a candidate in
`data/review/matches.yaml`; nothing merges without a recorded decision.
