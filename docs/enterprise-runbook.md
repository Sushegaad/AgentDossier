# Self-hosted edition: operator runbook

The enterprise edition is the same code as the public demo, run by you, inside
your network, with one addition: an **authorized scanner** that finds the agents
your teams already run by reading the standards they publish (ARD manifests, A2A
agent cards, MCP server cards). Nothing leaves your network; the public demo and
this instance never talk to each other.

## What you get

One container (`deploy/Dockerfile`) that serves:

| Piece | Where | Notes |
| --- | --- | --- |
| Web UI | `/` | the same search, trust profile, compare and private-catalog pages as the demo, built for the root path |
| ARD REST API | `POST /search`, `POST /explore`, `GET /agents`, `GET /agents/{id}`, `GET /.well-known/ard.json` | other registries and agents can federate or query you |
| Policy qualification | `POST /qualify`, `GET /policies` | the machine constraint contract (FR-38): verdict per agent against a policy template or an inline policy |
| Scan control | `POST /api/scan`, `GET /api/scans`, `GET /api/scans/{id}`, `GET /api/status`, `GET /api/audit`, `POST /api/reload` | admin-only |
| Scheduler | in-process (APScheduler) | runs the scan on the `schedule.cron` in `enterprise.json` |
| MCP wrapper | `agentdossier mcp --catalog /data/catalog` | lets an internal agent search the registry over MCP (stdio) |
| Catalog files | `/catalog/*` | the same JSON the public site uses; the private-catalog viewer can open it |

State lives in one volume (`/data`): the SQLite database (scan history, audit
trail), the catalog, raw probe snapshots and the trust changelog.

## Before the first scan

1. **Authorization.** `enterprise.json` must name who authorized the scan and
   the change ticket. Preflight refuses to run without both. Keep the file in
   your configuration repository; it contains no secrets.
2. **Scope.** `scope.allow_cidrs` / `allow_hosts` is the only address space the
   scanner can reach. There is no allow-public switch: a manifest that points at
   the internet is recorded as refused, never followed. Keep the scope to the
   subnets where agents run.
3. **Targets.** Hosts, CIDRs (at most 4,096 addresses per run), DNS domains
   (ARD Service Binding records `_entries._agents.<domain>` and
   `_search._agents.<domain>`) and internal ARD registries.
4. **Credentials.** Headers the scanner should send come from environment
   variables named in `auth.headers_from_env`; the values are never in the file.
5. **TLS.** Point `tls.ca_bundle` at your internal root CA when agents use
   private certificates.
6. **Probes.** ARD, A2A and MCP server cards are metadata reads. The MCP
   handshake (`initialize` + `tools/list`) is off by default and never calls a
   tool.

Then:

```bash
agentdossier enterprise selftest                      # proves the scanner works on this host (loopback fixtures)
agentdossier enterprise preflight enterprise.json     # pass / warn / fail per check
agentdossier enterprise plan enterprise.json          # dry run: every origin that would be probed, nothing fetched
agentdossier enterprise scan enterprise.json          # the real thing; writes <output_dir>/catalog and scan-report.json
```

`plan` output is what you attach to the change ticket.

## Running the container

```bash
cd deploy
cp .env.example .env            # tokens, OIDC settings, scanner credentials
cp ../examples/enterprise/enterprise.json .   # then edit tenant, scope, targets
docker compose up -d
curl -s -H "Authorization: Bearer $AGENTDOSSIER_API_TOKEN" localhost:8080/api/status
```

With `AGENTDOSSIER_SCAN_ON_START=1` the first request triggers a scan; afterwards
the schedule runs it (`0 6 * * 1` = Mondays 06:00 UTC in the example) and an
admin can start one any time with `POST /api/scan`.

### Authentication

| `AGENTDOSSIER_AUTH_MODE` | Who can read | Who can scan | Use |
| --- | --- | --- | --- |
| `none` | everyone | everyone | local development only |
| `token` | `Authorization: Bearer $AGENTDOSSIER_API_TOKEN` | `$AGENTDOSSIER_ADMIN_TOKEN` | service accounts, CI, agents |
| `oidc` | anyone who signs in at `/auth/login` through your IdP | members of `OIDC_ADMIN_GROUP` (from the `groups` claim); tokens still work for APIs | people using the web UI |

OIDC uses standard discovery (`<issuer>/.well-known/openid-configuration`); the
callback is `/auth/callback`. Put the container behind your TLS-terminating
proxy and set `AGENTDOSSIER_SITE` to the public URL.

### Backups and upgrades

Back up the `/data` volume. Upgrading is pulling a new image; the SQLite schema
is created on start and the catalog is rebuilt by the next scan. Raw snapshots
(`/data/snapshots`, `/data/raw`) are evidence for audits and safe to prune.

## Querying from an agent

```bash
# ARD REST
curl -s -X POST localhost:8080/search -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"query":"claims intake agent","limit":5,"filters":{"framework":"soc2","maxTier":2}}'

# machine constraint contract
curl -s -X POST localhost:8080/qualify -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"policyId":"pol_insurer_default","resourceIds":["res_…"]}'
```

MCP: register `agentdossier mcp --catalog /data/catalog` as a stdio server;
tools are `search_agents`, `get_agent`, `qualify_agent`, `list_policies`.

## What the scan does not do

It does not execute agents, call tools, submit forms, or read anything beyond
the standards' well-known documents and pages linked from them. It respects
`robots.txt` for optional page reads, spaces requests per host
(`limits.requests_per_host_per_sec`) and stops at `limits.concurrency` parallel
hosts. Everything it fetched is listed in `scan-report.json` with the outcome
per origin, so the report is reviewable by whoever signed the ticket.
