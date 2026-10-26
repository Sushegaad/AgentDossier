# Traces

> "We urgently need more public traces of AI agents attacking and defending systems. Defenders
> can't learn from what they can't see."

A **trace** is one observed run of an agent under adversarial or evaluative conditions: what
reached it, what it did, what came out. Every dossier carries a `traces` list and a trace tier in
its trust summary, lists every public trace the registry can find, and says "none found" out loud
when nothing exists. The absence is the point: it is the number this project exists to move.

## Record

`schema/trace_record.schema.json`. The fields a defender needs first:

| Field | Meaning |
| --- | --- |
| `kind` | `red_team` (attacked by a researcher) · `injection_eval` (tested under adversarial input) · `ctf` (cyber-range run) · `incident` (real-world event with a post-mortem) · `self_test` (this registry's own probe) · `vendor_published` (a bundle the vendor serves at a well-known path) |
| `tier` | 1 reproducible run with public artifacts · 2 third-party report with a transcript or proof of concept · 3 vendor-published report or evaluation with results only · 4 vendor claim ("we red-teamed it") · 5 nothing found |
| `scope` | `product` (this agent) · `platform` (a sibling product on the same platform; tiered one step lower) · `model` (the underlying model, not the agent) |
| `observed` | `entry` (how the adversarial input reached the agent), `actions`, `egress`, `approval`, `secrets_touched`, `refused`, `outcome` |
| `source`, `url`, `date`, `format` | who published it, where, when, as what |
| `reviewer`, `checked_on` | who checked the row against its source and when — a person, or `model: … (automated review)` for a row the weekly machine review published; the site shows "unreviewed" while both are null |

## Sources, in order of effort

1. **Curated public sources** — `data/curated/traces.yaml`: researcher write-ups, incident
   post-mortems, vendor reports. One row may apply to several catalog entries; siblings on the
   same platform get `scope: platform` and one tier lower.
2. **This registry's own probes** — every refresh fetches each publisher's ARD manifest, A2A
   agent card and MCP server card and validates them. When the probes found something (a card or
   manifest, valid or not) and the observation differs from the last bundle for that agent, a
   `self_test` bundle is appended to the store (`agentdossier/traces/selftest.py`). A "not found"
   everywhere is recorded in the dossier's protocol block, not as a trace.
3. **Vendor-published bundles** — a vendor serves a trace bundle and names it in its ARD manifest
   entry (`traces: [{url, format, sha256}]`); the build fetches it, checks the hash, and shows it
   as `vendor_published` (tier 1 when fetched and the hash matches, tier 4 when only claimed). The
   vendor spec and an example bundle are in [docs/traces-spec.md](traces-spec.md).
4. **The sandbox harness** (`agentdossier/harness/`, PR 3a) — the part that *produces* new
   attack-and-defense traces. It does not author attacks: it runs an agent against
   [AgentDojo](https://github.com/ethz-spylab/agentdojo) (MIT), a peer-reviewed set of
   prompt-injection tasks and attacks, and records, per task, whether the injection succeeded,
   with the tool trace. AgentDojo measures a *model's* susceptibility inside a generic tool-use
   agent, so a harness trace is `scope: model` — inherited, model-level evidence for every agent
   built on that model (`data/traces/harness/models.yaml` maps model → agents), never a claim
   about one product. `agentdossier harness run --model mock` runs the whole pipeline with no
   model or network (used by the tests); real runs use a model backend and happen in the
   `harness` workflow, which opens a `traces/harness` PR. Tier 1: reproducible, public artifacts.

## The store: `data/traces/`

```
data/traces/
  index.jsonl          one line per trace: id, agent, key, prev, record, hash
  bundles/<id>/        manifest.json, transcript.md, verdict.json [, spans.jsonl, scenario.yaml]
```

* **Append-only and hash-chained.** Each line carries `prev`, the hash of the line before it,
  and `hash`, the SHA-256 of its own canonical JSON. `verify()` recomputes every hash, so an
  edited or removed line breaks every line after it. `scripts/verify_traces.py` runs in CI.
* **Bundles are text**, at most 2 MB, hashed as a whole (`record.sha256`); anything larger goes to
  a GitHub Release on this repository, referenced by hash.
* **Deduplicated by observation.** `key` is a hash of what was observed; the weekly refresh appends
  a new `self_test` bundle only when the observation changed.
* **The site publishes every bundle** at `/traces/<id>/` with a JSON download, and `/traces/` is the
  running count. `git clone` is the mirror.

## Publication policy

* Behaviour, not weapons: scenario inputs, the agent's actions and the outcome. No payloads
  against third-party systems are reproduced; where an author published one, the row links to it.
* Honeytokens and egress sinks used by the harness are ours and rotated per run; secrets are
  redacted from spans before a bundle is written.
* A trace describes one agent version on one date; both are on the record. Disputes go through the
  dossier's correction link; re-runs and corrections are appended, never overwritten.
* A trace is evidence of behaviour, never a certification, and "none found" is never a finding
  against the agent.

## What the dossier does with it

* Trust profile row **Traces**: count, best tier, and whether any trace saw data leave.
* Section **Traces — under attack, in defence, in incidents**: every record with its scenario,
  what was observed, the vendor's response, source and date.
* Before you deploy: `no-public-trace` (run your own sandbox trace before the pilot and keep the
  transcript) and `trace-shows-exfiltration` (confirm the fix is in the deployed version; egress
  allowlist during the pilot).
* Top 100 tables carry a Traces column; the homepage counts agents with a public trace.

## Enterprise edition (private agents)

A self-hosted tenant runs the same harness against agents the public registry never sees and
keeps the results in its own database (`traces` table), not in `data/traces/`. Nothing leaves the
tenant unless it chooses to publish a bundle back to the public store. A decision can carry a
**trace gate**: set `require_trace_tier` (1–5) on the decision and approval is blocked until a
trace of that tier or better exists for the agent — so "we approved it without ever watching it
under attack" cannot happen by accident. `agentdossier enterprise trace-selftest` runs the gate
and the harness end to end with the mock pipeline (no model, no network).

