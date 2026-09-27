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
from its homepage, and NVD for CVE counts. Only resources with a
*distinctive* name are searched (two words, or one non-generic word of six or
more letters; "Muse" alone is not searched).

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
