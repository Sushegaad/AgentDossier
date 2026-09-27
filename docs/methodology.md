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
