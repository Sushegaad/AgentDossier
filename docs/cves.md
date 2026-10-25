# The CVE registry

`/cves/` lists every **official CVE** related to AI agents — agent products, the frameworks agents
are built with, implementations of the agent protocols (MCP, A2A) and the infrastructure agents
call through — as one filterable list, refreshed every Monday with the catalog. It is a lookup
surface: not a scanner, never a claim about any specific deployment, and never a score.

## What counts

A CVE is listed when either test passes:

- **Test A — the affected product is on the list.** `config/cve_products.json` names
  **41 products**, each with a category (`product` · `framework` · `protocol` ·
  `infrastructure`), its CPE `vendor:product` keys, the exact names it is known by, and the catalog
  agents it maps to. A CPE match or one of its listed `names` (whole-word, in the official description) counts; the display name itself is never matched, since it can be an ordinary word ("Continue", "Cursor"), and a name must be specific to the product ("MCP Inspector", not "MCP server").
- **Test B — the weakness is agent-specific.** The record cites **CWE-1427** (*Improper
  Neutralization of Input Used for LLM Prompting*) or its description matches the vocabulary: one
  *strong* phrase (prompt injection, MCP server, tool call, AI agent…) or two distinct *weak* ones
  (LLM, chatbot, language model…). Short terms match whole words only.

Products deliberately **not** listed: general-purpose platforms with an AI feature (n8n, say) —
listing a product lists every CVE it has, and Test B still catches the agent-specific ones. A
retired product (`exclude_products`, in the config or the overrides file) never lists again, whatever
the description says.

Every record keeps *why it is listed* (`match.tests`, `match.terms`) so a reviewer reads the reason
first.

## Where the data comes from

| Source | Gives | Terms |
| --- | --- | --- |
| [NVD API 2.0](https://nvd.nist.gov/developers/vulnerabilities) | The CVE.org record (ID, verbatim description, CNA, dates, references, affected products via CPE) plus CVSS and NVD's CWE mapping | US government work, public domain; attributed |
| [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | Known-exploited flag, date added, due date | Public domain |

Descriptions are shown verbatim and attributed; nothing is paraphrased. CVSS prefers v4.0, then
v3.1, v3.0, v2, and NVD's own score before a CNA's; the record says which. A record NVD has not
analysed yet is listed as *unscored*. References tagged `Exploit` by NVD are dropped — the registry
links advisories and records, never exploit write-ups. A rejected CVE disappears from the list.

## The weekly run

`agentdossier cves update` in `refresh.yml`, after the catalog build:

1. **Collect** — the first run backfills with targeted queries (an exact-phrase search per product
   name and vocabulary phrase, plus `cweId=CWE-1427`; `agentdossier cves plan` prints them); later
   runs fetch everything modified since the last cursor (`data/cves/state.json`), in ≤120-day
   windows. The KEV catalog is read every run.
2. **Match** — Tests A and B, category, surface tags (`prompt_injection`, `tool_execution`,
   `code_execution`, `exfiltration`, `credential_access`, `auth_bypass`, `supply_chain`,
   `privilege_escalation`, `ssrf`, `path_traversal`, `dos`) from CWE and description. The category
   is the listed product's; with no product, `protocol` when the description itself names MCP or
   A2A (a third-party MCP server is a protocol implementation), else `unclassified`. Prior records
   are re-classified with today's config, so a config change applies to the whole list.
3. **Overrides** — `data/curated/cve_overrides.yaml`, the human layer: per CVE a `status`
   (`included` · `excluded`), `note`, `reviewer`, `checked_on`, and corrections to category, surface
   or links; plus `exclude_products`. `agentdossier cves include|exclude <id> --note "…" --reviewer
   "Name"` edits it for you. Until a person decides, a record is a `candidate` and shows *unreviewed*.
4. **Link** — `related_agents` from the product list (only slugs that exist in the catalog);
   `related_incidents` from the incident registry (an explicit `cves:` list on the record, else CVE
   ids in its text).
5. **Write** — `data/cves/index.json` (every record, schema-validated against
   `schema/cve_record.schema.json`; the site reads this one file) and `state.json`. Deterministic:
   the same inputs write the same bytes.

The refresh PR body lists the week's new candidates, KEV additions, and a random **50-row
spot-check** to tick when the CVE is genuinely about an agent product, framework, protocol or
infrastructure — the precision measure. `agentdossier cves spot-check` prints the same list.

The scout (`incidents scout`) hands advisory URLs (MSRC update guide, NVD, CVE.org, GitHub
advisories) to this registry instead of filing them as incident candidates.

## Rules

- A row exists only because CVE.org has the ID. No GHSA-only advisories, no researcher findings
  without a CVE — those belong to traces and the incident registry. The list page says so;
  counting the GHSA-only advisories set aside is an open item.
- Never an exploit: no proof-of-concept code, payloads or reproduction steps.
- Never a score: counts and severities do not enter `sar-score`. "No linked CVE" reads "none linked
  in the sources checked", never as a finding.
- Errors in the record go to the CNA or NVD (their dispute process is linked); errors in our
  classification or links are ours (a GitHub issue; corrections are logged in the trust changelog).
- Attribution to CVE.org, NVD and CISA on the list page and in `THIRD_PARTY_NOTICES.md`.

## On the site

- `/cves/` — the list: a React island over `/cves/list.json` (one slim row per CVE, ~0.9 MB
  uncompressed; the full 3.5 MB index is `/cves/export.json`). Facets: KEV, reviewed, severity,
  attack surface, category, product, year, fix status; word search over id, products, CWE and
  description; sort by published, last modified, CVSS score or id; CSV export of the visible rows.
  Filters live in the query string (`/cves/?surface=prompt_injection&kev=1`), so a view is a link.
  Facet counts are computed against the *other* filters, so a count says what choosing it gives.
- `/cves/<id>/` and `/cves/<id>.json` — one record: the official description, CVSS (version,
  score, vector, who scored it), CWE, NVD status, CNA, affected products with fixed-in versions,
  KEV details, deduplicated references, links to dossiers and traces, and *why it is listed here*
  (the tests and terms that matched, the reviewer or "not yet checked by a person", the note).
  Buttons: the CVE.org record, NVD, JSON, "Report a wrong listing" (a GitHub issue).
- Nav tab **CVEs** between Traces and Trust methodology; `/methodology/#cves` has the rules;
  `/about/` names the source. Pages are in the axe/Lighthouse audit (`npm run audit`).
- **Dossiers.** The Security row says what the registry links to the agent — "N CVEs linked ·
  K exploited in the wild (KEV) · M critical/high · newest date", or "No CVE linked … none linked in
  the products checked, not a finding" — and a *CVEs — on the official record* band after Traces
  lists the newest eight with severity, surface tags and fix status, linking to "all N" on `/cves/`
  filtered by the agent's listed products. The old NVD keyword count is no longer shown (the Issues
  row points to Security); the score is untouched, since the keyword check never entered it either.
  Links are by listed product (`config/cve_products.json` → `agents`), so a CVE that names a
  different component of the same platform may be missing — the band says so.
- **Search results** show the same line from `/cves/agents.json` (per-slug counts, ~2 KB).
- **Incident pages** list *CVEs on record*: the incident's own `cves:` field plus any registry
  record that names the incident, each linking to the registry page or the official record.
- Code: `web/src/lib/cve-filter.ts` (browser-safe model, filters, URL sync, CSV — tested in
  `web/tests/cves.test.ts`), `web/src/lib/cves.ts` (build-time loader, rows, cross-links),
  `web/src/components/CveApp.tsx`, `web/src/pages/cves/`.

## Offline and tests

`agentdossier cves update --backfill --offline <dir>` replays saved responses (`kev.json`,
`queries.json` mapping query → file, and the NVD `*.json` files); the first backfill (2026-10-25)
was produced this way from 35 queries fetched out-of-band: 2,149 records fetched, 1,738 listed. The
parser, both tests, overrides, links and determinism are covered by `tests/test_cves.py` with
inline fixtures and no network.
