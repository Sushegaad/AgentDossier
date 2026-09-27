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
| 2 | Marketplace listing, or ARD/A2A metadata served at the publisher's own domain |
| 3 | Repository or Hub account ownership (GitHub, Hugging Face) |
| 4 | Vendor name only |
| 5 | Unknown |

Certifications earn governance credit only once identity is tier 2 or better
(FR-49); until then they show as "pending publisher verification".

## Duplicate handling

Deterministic keys (ARD URN, GitHub `owner/repo`, Hugging Face id, MCP
Registry name, A2A card URL, canonical URL) merge automatically, with the
seed record winning on descriptive fields. Two workbook products that share
a key stay separate. Name similarity ≥ 0.92 only creates a candidate in
`data/review/matches.yaml`; nothing merges without a recorded decision.
