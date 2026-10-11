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

- Curated from public reports (the current seven: ForcedLeak, EchoLeak, CamoLeak, the Gemini CLI
  and Amazon Q cases, AgentFlayer, and the Claude Code espionage report).
- Promoted from an agent-level trace when it rises to a named incident.
- A harness `injection_eval` run can seed an entry for an agent that fails under benchmark attack.
