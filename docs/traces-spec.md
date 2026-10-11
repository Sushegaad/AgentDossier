# Publishing your own agent traces (vendor spec)

AgentDossier shows every public trace of an agent under attack or in defence, and says "none
found" when there are none. If you publish an agent, you can fill that gap for your own product:
run an attack/defense evaluation, publish the trace bundle, and point to it from your
[ARD](https://github.com/agentic-resource-discovery) manifest. The registry fetches it, checks
the hash, and shows it on your dossier as a **vendor-published** trace.

## 1. Produce a bundle

A bundle is a small JSON document describing one evaluation run. Minimum shape:

```json
{
  "schema": "agentdossier.trace/1",
  "kind": "injection_eval",
  "agent": "your-agent-name",
  "agent_version": "2.4.0",
  "date": "2026-10-11",
  "harness": "your-eval-harness 1.0 (or a named public benchmark)",
  "scenario": "N tasks where tool output carried attacker instructions",
  "observed": {
    "pairs": 120,
    "injections_succeeded": 3,
    "attack_success_rate": 0.025,
    "egress": false,
    "notes": "3 failures were in the travel suite; fixed in 2.4.1"
  }
}
```

Publish behaviour, not weapons: the tasks attempted, what the agent did, the outcome. Do not
publish working payloads against third-party systems. Redact secrets.

## 2. Reference it from your ARD manifest

Add a `traces` array to the manifest entry for the agent. Each item names a bundle:

```json
{
  "entries": [
    {
      "identifier": "urn:air:acme:agent:support-bot",
      "displayName": "Acme Support Bot",
      "type": "agent",
      "url": "https://acme.example/agents/support-bot",
      "traces": [
        {
          "url": "https://acme.example/.well-known/traces/support-bot-2.4.0.json",
          "format": "bundle",
          "sha256": "sha256:<hex digest of the bundle bytes>"
        }
      ]
    }
  ]
}
```

- `url` must be `https://` and stable.
- `format` is one of `bundle`, `spans` (OpenTelemetry GenAI), `transcript`, `report`.
- `sha256` is optional but recommended: the registry refuses to show a bundle whose bytes do not
  match the digest you stated, so the hash is your guarantee the trace was not altered in transit.

## 3. What the registry does

On each refresh it fetches each declared bundle (size-capped, no redirects), and records a
`vendor_published` trace on your dossier:

- **tier 1** when the bundle is fetched and its hash matches (or no hash was given but the body is
  valid JSON) — shown as a reproducible, vendor-published trace;
- **tier 4** when the bundle is unreachable, oversized, not valid JSON, or does not match the hash
  — shown as *claimed*, so a broken link never looks like evidence.

A vendor-published trace is still evidence of behaviour, not a certification, and the registry
does not endorse your numbers — it shows them with their source and date, and anyone can fetch the
same bundle and check the hash. To correct or withdraw one, change your manifest; the next refresh
reflects it, and the change is recorded in the trace changelog.
