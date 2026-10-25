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
| `cves` | official CVE ids the sources name (`CVE-YYYY-NNNN`); the incident page links each to its registry page (or the official record when it is not listed there), and the CVE registry links back (`related_incidents`) |
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

- Curated from public reports — the first thirteen (ForcedLeak, EchoLeak, CamoLeak, the Gemini CLI
  and Amazon Q cases, AgentFlayer, the Claude Code espionage report, s1ngularity, the Replit
  database deletion, ShadowLeak, CurXecute/MCPoison, the GitHub MCP toxic agent flow, and the
  Gemini "Promptware" smart-home hijack) were written by hand; everything after them is published
  by the weekly machine review below. The live counts are on `/traces/`.
- **The weekly scout.** The refresh workflow runs `agentdossier incidents scout`, which reads the
  feeds in `config/trace_sources.json` (press, researcher labs, vendor advisories; RSS and Atom,
  parsed with the standard library) and keeps any item whose title or summary names both an
  *agent* and an *attack* — two keyword axes, so "AI agent" alone or "vulnerability" alone is not
  enough. Items already cited by an incident are dropped. What survives is written to
  `data/curated/incident_candidates.yaml` as a **candidate**: title, link, date, outlet, snippet and
  the terms that matched — what the source said, nothing more. The refresh PR lists the new ones.
- Promoted from an agent-level trace when it rises to a named incident.
- A harness `injection_eval` run can seed an entry for an agent that fails under benchmark attack.

### Machine review — publish by default

Nobody reads candidates by hand. The refresh runs `agentdossier incidents review` after the
scout: for every `status: new` candidate (and any `status: placeholder` record still waiting) it
fetches the article through the guarded client, strips it to text, and asks a model
(`ANTHROPIC_API_KEY`; `claude-sonnet-5-5` by default, `INCIDENT_REVIEW_MODEL` to change) one
structured question against that text only: is this a specific, real event in which an AI agent
attacked, defended or was the target? The reply is JSON — date, AI role, category, an "as
reported" summary, attacker and defender as the source describes them, scale and impact as
stated, MITRE ATT&CK tactics, models and agents named, a timeline — validated field by field in
`agentdossier/incidents/review.py`; a field the article does not state stays null.

- **The bar.** Published when the verdict is an incident, confidence ≥ 0.8, the source is not an
  aggregator, and the record's required fields are all stated. The record is appended to
  `incidents.yaml` as `status: published` with `reviewer: "model: <name> (automated review)"` and
  `checked_on` set to the run date, so every row says who reviewed it; the site marks these rows
  *machine-reviewed*. Agents named are cross-linked only by exact catalog name.
- **Everything else is dismissed** with the model's reason kept on the candidate (`note:`), so the
  same item does not come back and the decision is on record. A placeholder that fails the bar is
  removed from `incidents.yaml` in place. A page that cannot be read (bot wall, dead link) is left
  `new` for next week.
- **Rules the model is given:** answer only from the article; never invent a fact; summarise,
  never reproduce prompts, payloads, commands or exploit details; name organisations, products
  and models, never private individuals; describe each side as the article does, without
  attribution or blame. Opinion pieces, announcements, surveys and benchmark papers without a
  concrete run are not incidents.
- **Retraction.** `agentdossier incidents dismiss <cand-id> --note "why"` on the candidate, and
  delete the row; or edit the row — the file is yours. `incidents draft <cand-id>` still scaffolds
  a placeholder for a record you would rather write by hand.
- The refresh PR body lists every decision (published, dismissed with reason, unreadable), the
  PR merges itself once the gates pass, and the site redeploys. Candidates nobody can read age out
  after 180 days; promoted and dismissed rows are kept for a year.
- `--offline <dir>` replays saved pages and a `verdicts.json`; `tests/test_incident_review.py`
  covers parsing, the bar, in-place placeholder rewrites, dismissals and the API call shape.

### Sources re-checked weekly

Every row stands on its linked sources, so the refresh also runs `agentdossier incidents recheck`:
it re-fetches each published incident's source URLs (HEAD, then a capped GET when a site refuses
HEAD) and writes `data/curated/incident_source_check.json` — per link, `ok`, `moved` (answered from
another site), `gone` (404/410), `unverified` (a 401/403/429 or a bot-protection challenge page;
not evidence it is gone) or `error` (no answer). A same-site redirect (a CDN, a trailing slash) is
still `ok`, with the final URL recorded. The PR body lists links that moved or vanished; `/traces/`
shows the re-check date and flags those rows; each incident page notes the status beside the link.
The re-check never edits an incident and never sets `checked_on` — that field is set by whoever
reviewed the entry against its sources, a person or the model. The first run found one dead link (a truncated Okta URL on
TR-2026-008), which was corrected.

Adding or removing a feed, or tuning the keyword axes, is a reviewed pull request to
`config/trace_sources.json`. A feed that fails is reported in the run and the PR body, never fatal.
`agentdossier incidents scout --offline <dir>` runs against saved `<source_id>.xml` files (tests,
dry runs) with no network.
