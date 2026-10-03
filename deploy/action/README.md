# AgentDossier policy check (GitHub Action)

Blocks a pull request when an agent the repository depends on no longer passes
your policy. The check calls `POST /qualify` on your self-hosted AgentDossier;
nothing about the repository leaves your network except the agent identifiers.

```yaml
# .github/workflows/agents.yml
on: [pull_request]
jobs:
  agents:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Sushegaad/AgentDossier/deploy/action@main
        with:
          registry: https://agents.corp.example.com
          token: ${{ secrets.AGENTDOSSIER_TOKEN }}
          policy: pol_insurer_default      # or set policyId in the manifest
          fail-on: disallowed              # or needs_review / unknown
```

`agents.lock.json` (validated by `schema/agents_lock.schema.json`):

```json
{
  "registry": "https://agents.corp.example.com",
  "policyId": "pol_insurer_default",
  "agents": [
    { "id": "res_7f3a…", "use": "claims intake" },
    { "slug": "acme-claims-intake-agent", "use": "document triage" }
  ]
}
```

The step prints a table, writes it to the job summary, and emits one
`::error` annotation per blocking agent. An agent the registry does not know
is `unknown`, which blocks at `fail-on: unknown` or stricter. The same script
runs anywhere: `python3 deploy/action/policy_check.py agents.lock.json --registry … --token …`.
