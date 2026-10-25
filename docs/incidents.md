# The incident registry

> "We urgently need more public traces of AI agents attacking and defending systems. Defenders
> can't learn from what they can't see."

The incident registry at `/traces/` is the record: one row per real, public event where an AI agent
attacked or defended a system. It sits alongside the per-agent trace evidence (see
[`docs/traces.md`](traces.md)) and gives a defender an incident-first view — tactics, timeline,
what to take from it, and sources.

## Record

`schema/incident_record.schema.json`, data in `data/curated/incidents.yaml`.

| Field | Meaning |
| --- | --- |
| `id` | `TR-YYYY-###` registry id |
| `ai_role` | what the AI agent did: `attacker` (ran the attack), `defender`, or `target` (was exploited) |
| `category` | `red_team` (researcher disclosure) or `incident` (happened in the wild) |
| `attacker` / `defender` | who, in words, with any models named |
| `tactics` | MITRE ATT&CK tactic ids the maintainer mapped from the reports |
| `timeline` | dated lines, each with an evidence tier and a source index |
| `lessons` | what a defender can take from it (the maintainer's reading) |
| `related_agents` | catalog slugs; the registry and the dossier cross-link both ways |
| `sources` | at least one public https source with a date |
| `reviewer` / `checked_on` | null until a person has checked the entry |
| `specimen` | true if an illustrative composite, shown labelled as such |

## Honesty rules

- Every row is a real event with public sources. `summary`, `timeline` and `scale` are **as
  reported**; a claim or an allegation is labelled.
- MITRE tactics are an analytic mapping, **not an attribution or a finding of fault**.
- No fabricated incidents, and none about a private individual. Corrections go through the
  per-incident "Request a correction" link; changes are recorded in the trace changelog.

## Export

Each incident is downloadable as raw JSON (`/traces/<id>.json`) and as a **STIX 2.1** bundle
(`/traces/<id>/stix.json`) — an `incident` object, an `attack-pattern` per tactic, and the
attacker/defender identities, so the registry is usable in threat-intel tooling. The whole
registry is at `/traces/export.json`.

## Where new entries come from

- Curated from public reports — **13 published** (ForcedLeak, EchoLeak, CamoLeak, the Gemini CLI
  and Amazon Q cases, AgentFlayer, the Claude Code espionage report, s1ngularity, the Replit
  database deletion, ShadowLeak, CurXecute/MCPoison, the GitHub MCP toxic agent flow, and the
  Gemini "Promptware" smart-home hijack) and **14 placeholders** drafted from the scout's first
  run (TR-2026-014 → 027: the Hugging Face intrusion OpenAI attributed to its own models,
  JADEPUFFER / Storm-3168, Unit 42's under-ten-hour agent-run breach, rogue OpenAI agents on
  Wikimedia, Anthropic's evaluation incidents, the ARTEX campaign against South Korean banks, and
  eight sourced disclosures) that a person still has to complete and publish. These counts are
  checked against `incidents.yaml` by `scripts/check_docs_drift.py`.
- **The weekly scout.** The refresh workflow runs `agentdossier incidents scout`, which reads the
  feeds in `config/trace_sources.json` (press, researcher labs, vendor advisories; RSS and Atom,
  parsed with the standard library) and keeps any item whose title or summary names both an
  *agent* and an *attack* — two keyword axes, so "AI agent" alone or "vulnerability" alone is not
  enough. Items already cited by an incident are dropped. What survives is written to
  `data/curated/incident_candidates.yaml` as a **candidate**: title, link, date, outlet, snippet and
  the terms that matched — what the source said, nothing more. The refresh PR lists the new ones.
- Promoted from an agent-level trace when it rises to a named incident.
- A harness `injection_eval` run can seed an entry for an agent that fails under benchmark attack.

### Reviewing candidates

A candidate is a lead for the maintainer, never an incident; the site shows only how many are
waiting. For each one:

- `agentdossier incidents draft <cand-id>` appends a `status: placeholder` record to
  `incidents.yaml` with the title, link, date and outlet filled in and `TODO` where a person must
  write (summary, attacker, defender, tactics, timeline, lessons). Complete it from the sources,
  then set `status: published`. Placeholders validate against the schema but are never rendered.
- `agentdossier incidents dismiss <cand-id> --note "why"` marks it dismissed; it will not come back.
- Candidates nobody touches age out after 180 days; promoted and dismissed rows are kept for a
  year so the same item does not resurface.

### Sources re-checked weekly

Every row stands on its linked sources, so the refresh also runs `agentdossier incidents recheck`:
it re-fetches each published incident's source URLs (HEAD, then a capped GET when a site refuses
HEAD) and writes `data/curated/incident_source_check.json` — per link, `ok`, `moved` (answered from
another site), `gone` (404/410), `unverified` (a 401/403/429 or a bot-protection challenge page;
not evidence it is gone) or `error` (no answer). A same-site redirect (a CDN, a trailing slash) is
still `ok`, with the final URL recorded. The PR body lists links that moved or vanished; `/traces/`
shows the re-check date and flags those rows; each incident page notes the status beside the link.
The re-check never edits an incident and never sets `checked_on` — that field means a *person*
checked the entry against its sources. The first run found one dead link (a truncated Okta URL on
TR-2026-008), which was corrected.

Adding or removing a feed, or tuning the keyword axes, is a reviewed pull request to
`config/trace_sources.json`. A feed that fails is reported in the run and the PR body, never fatal.
`agentdossier incidents scout --offline <dir>` runs against saved `<source_id>.xml` files (tests,
dry runs) with no network.
