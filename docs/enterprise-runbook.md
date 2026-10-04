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
| Scheduler | in-process (APScheduler) | runs the scan on the `schedule.cron` in `enterprise.json` and the daily evidence-expiry job |
| Notifications | `GET /api/deliveries`, `POST /api/notify/test`, `GET /api/evidence/expiring`, `POST /api/jobs/evidence-expiry` | email (SMTP) and signed webhooks for scan results, catalog changes and expiring evidence |
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
| `none` | everyone | everyone | local development only: `agentdossier serve --dev` (needs `AGENTDOSSIER_DEV=1` and a loopback bind; refused otherwise) |
| `token` | `Authorization: Bearer $AGENTDOSSIER_API_TOKEN` | `$AGENTDOSSIER_ADMIN_TOKEN` | service accounts, CI, agents |
| `oidc` | anyone who signs in at `/auth/login` through your IdP | members of `OIDC_ADMIN_GROUP` (from the `groups` claim); tokens still work for APIs | people using the web UI |

There is no default. An instance started without `AGENTDOSSIER_AUTH_MODE` refuses to start
(`uvicorn --factory agentdossier.server.app:create_app` exits; the container does not come up),
so a missing environment variable can never produce an open administrator API.

Behind a TLS-terminating proxy set `AGENTDOSSIER_TRUSTED_PROXIES` to the proxy's address(es)
(for example `10.0.0.0/8` or `172.17.0.1`): client addresses, the `https` scheme for the OIDC
callback and the session cookie's `Secure` flag then come from `X-Forwarded-*` headers only
when a trusted proxy sent them. Without it, forwarded headers are ignored.

Roles: every signed-in user is a **member** (read, open decisions, comment, add tasks and feedback); members of `OIDC_REVIEWER_GROUP` — and the admin token — are **reviewers** (sign off, move stages, triage feedback); admins also operate the instance.

OIDC uses standard discovery (`<issuer>/.well-known/openid-configuration`); the
callback is `/auth/callback`. Put the container behind your TLS-terminating
proxy and set `AGENTDOSSIER_SITE` to the public URL.

### Notifications

The instance can tell you when something happened, by email (any SMTP relay,
through the standard library) and/or a signed webhook. Both are off until
configured; see `deploy/.env.example`.

| Event | When |
| --- | --- |
| `scan.done` | a scan finished and the catalog was reloaded; the message carries what changed (added, removed, trust-tier changes) |
| `catalog.changed` | sent alongside `scan.done` only when something did change — subscribe to this one for a quiet channel |
| `scan.failed` | preflight refused the scan, or the scanner raised |
| `evidence.expiring` | the daily job (`AGENTDOSSIER_EXPIRY_CRON`, default 07:00 UTC) found compliance records that expire within `AGENTDOSSIER_EXPIRY_WARNING_DAYS`, are expired but still active, or whose `next_check` has passed |
| `test` | `POST /api/notify/test` |

Webhook bodies are JSON (`event`, `at`, `tenant`, `subject`, `text`, `data`)
with `X-AgentDossier-Event` and, when `AGENTDOSSIER_WEBHOOK_SECRET` is set,
`X-AgentDossier-Signature: sha256=<HMAC of the raw body>`; verify it with
`agentdossier.server.notify.verify_signature`. Each attempt (three, with
backoff) is recorded and visible at `GET /api/deliveries`; `GET
/api/evidence/expiring?days=30` shows what the next expiry run would report
and `POST /api/jobs/evidence-expiry` runs it now. Restrict events with
`AGENTDOSSIER_NOTIFY_EVENTS=catalog.changed,scan.failed,evidence.expiring`.

### Integrations

Each integration is one more notification channel: same events, same delivery
log (`GET /api/deliveries`), configured by environment (`deploy/.env.example`).

| Channel | Setting | Receives |
| --- | --- | --- |
| Slack | `SLACK_WEBHOOK_URL` (incoming webhook) | every enabled event, as a Block Kit message |
| Microsoft Teams | `TEAMS_WEBHOOK_URL` (incoming webhook) | every enabled event, as an Adaptive Card |
| Jira | `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, `JIRA_ISSUE_TYPE` | one issue for `scan.failed`, `evidence.expiring`, and a decision opened for review (labels `agentdossier`, `<event>`) |
| ServiceNow | `SERVICENOW_INSTANCE_URL`, `SERVICENOW_USER`, `SERVICENOW_PASSWORD`, `SERVICENOW_TABLE` | the same actionable events as records in the table (default `incident`) |
| GRC webhook | `GRC_WEBHOOK_URL`, `GRC_WEBHOOK_SECRET` | the full decision packet, signed, when a decision is approved, rejected or retired |

### CI policy check (GitHub Action)

`deploy/action` is a composite action that reads a repository's
`agents.lock.json` (the agents it depends on; schema in
`schema/agents_lock.schema.json`), calls `POST /qualify` on your instance and
fails the job when any verdict is `disallowed` (or `needs_review` / `unknown`
with `fail-on`). It prints a table into the job summary and one error
annotation per blocking agent. The script is standard-library Python and runs
anywhere: `python3 deploy/action/policy_check.py agents.lock.json --registry … --token …`.
See `deploy/action/README.md` and `examples/agents.lock.json`.

### Federation

Other registries can be peers (`AGENTDOSSIER_FEDERATION_PEERS`, comma-separated
base URLs; `AGENTDOSSIER_FEDERATION_TOKEN` if they need one). The widest mode
this instance allows is `AGENTDOSSIER_FEDERATION_MODE`:

| Mode | `POST /search` adds |
| --- | --- |
| `none` | nothing |
| `referrals` (default) | `federation.referrals`: each peer's `/search` and `/.well-known/ard.json`, for the client to query itself |
| `auto` | the peers' hits, queried in parallel through the guarded egress client (no redirects, `AGENTDOSSIER_EGRESS_ALLOW` applies) with `AGENTDOSSIER_FEDERATION_TIMEOUT` seconds each and marked `source_registry`; `federation.peers` reports count, route (`rest` or `manifest`) and errors per peer |

A request may narrow the mode (`"federation": "none"`) but never widen it. A
peer that has no REST API — the public demo, or any publisher's static manifest
— is matched locally on its `ard.json`. Federated queries carry
`X-AgentDossier-Federation-Hop: 1` and are never federated again, so two
instances that list each other cannot loop.

A private registry's `/.well-known/ard.json` requires authentication (peers send
`AGENTDOSSIER_FEDERATION_TOKEN`); a public-scope catalog's manifest stays open.

### SCIM provisioning

Set `SCIM_TOKEN` and point the IdP's SCIM connector at `/scim/v2` (Okta,
Entra ID and others): `ServiceProviderConfig`, `Users` (list with `filter`,
create, read, replace, patch `active`, delete) and an empty `Groups`. The
stub exists for **deprovisioning**: a person whose SCIM record is inactive or
deleted is refused at sign-in even while the IdP session is still valid.
Unknown people are still admitted — SCIM may not cover every group and the
IdP already authenticated them.

### Hardening

**Egress.** Everything the server itself calls — webhooks, Slack/Teams, Jira,
ServiceNow, the GRC hook, federation peers — goes through the same guarded HTTP
client as discovery: scheme allow-list, address checked and *pinned* at connect
time (a second DNS answer cannot redirect the connection), no redirects
followed, 2 MB response cap. By default only public addresses are reachable;
list the private CIDRs or hosts an instance may call in
`AGENTDOSSIER_EGRESS_ALLOW` (for example an on-prem Jira or an internal peer
registry). Loopback is admitted only in `--dev`.

Every response carries `X-Content-Type-Options`, `X-Frame-Options: DENY`, a
`Referrer-Policy`, a `Permissions-Policy` and a Content-Security-Policy; API,
SCIM and auth responses are `no-store`; `Strict-Transport-Security` is sent
when `AGENTDOSSIER_SITE` is https or `AGENTDOSSIER_BEHIND_TLS_PROXY=1`.
Request bodies above `AGENTDOSSIER_MAX_BODY_BYTES` (1 MiB) get 413.
`/search`, `/explore` and `/qualify` are rate-limited per client — by bearer token
when one is sent, otherwise by the (proxy-resolved) address — with
`AGENTDOSSIER_RATE_LIMIT` (default `120/minute`; empty disables). `/healthz`
returns only `{"ok": true}`; version and counts are on the authenticated
`/api/status`.

Releases publish a container image signed with cosign (keyless) with a
CycloneDX SBOM attestation and build provenance; verify before deploying:

```bash
cosign verify --certificate-identity-regexp github.com/Sushegaad/AgentDossier \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/sushegaad/agentdossier:1.0.0
```

### Kubernetes (Helm)

`deploy/helm/agentdossier` deploys the same container: one replica (the scanner
and the SQLite store are single-writer; the Deployment uses `Recreate`), a
PersistentVolumeClaim for `/data`, `enterprise.json` from a ConfigMap, secrets
from a Secret you render or one you already manage (`existingSecret`), optional
Ingress and an optional internal root CA mount.

```bash
helm upgrade --install agentdossier deploy/helm/agentdossier \
  --namespace agent-governance --create-namespace \
  --set-file enterpriseConfig=enterprise.json \
  --set env.AGENTDOSSIER_SITE=https://agents.corp.example.com/ \
  --set existingSecret=agentdossier-secrets \
  --set ingress.enabled=true --set ingress.hosts[0].host=agents.corp.example.com
```

`helm lint` and `helm template` run in CI. The pod runs as uid 10001 with a
read-only root filesystem; `/data` and `/tmp` are the only writable mounts. The
scanner's egress to the agent subnets is yours to allow in NetworkPolicy.

### Reference deployment (the enterprise-beta gate)

The end-to-end path — scan mock agents, rebuild the catalog, answer `/search`
and `/qualify`, deliver `scan.done` to a webhook, run the expiry job — is
exercised in `tests/test_notify.py::test_reference_deployment_scan_notifies_and_expiry_job_runs`
on every CI run, against the loopback fixtures `agentdossier enterprise selftest`
uses. To reproduce it on a real host:

```bash
docker compose -f deploy/docker-compose.yml up -d
curl -s -X POST -H "Authorization: Bearer $AGENTDOSSIER_ADMIN_TOKEN" localhost:8080/api/notify/test
curl -s -X POST -H "Authorization: Bearer $AGENTDOSSIER_ADMIN_TOKEN" localhost:8080/api/scan
curl -s -H "Authorization: Bearer $AGENTDOSSIER_ADMIN_TOKEN" localhost:8080/api/deliveries
```

### Decision workflow

`/api/decisions` keeps the organisation's record per agent (FR-28, FR-34, FR-35):

```
candidate ──► under_review ──► approved ──► retired
                  │                ▲
                  ├──► rejected    │
                  └──► deferred ───┘
```

1. A member opens a decision for a resource: `POST /api/decisions {resourceId, policyId?, requiredRoles?}`.
   With a policy the verdict from `/qualify` is recorded on the opening event and
   again on approval, so the packet shows what the policy said at both moments.
   `requiredRoles` defaults to `security` and `business`; any of `security`,
   `legal`, `procurement`, `business`, `privacy`, `architecture`.
2. Reviewers sign per role: `POST /api/decisions/{id}/sign {role, verdict: approve|reject, note}`.
   The first sign-off moves the decision under review; a reject moves it to
   `rejected` (it can be reopened with `stage: under_review` once the blocker is
   gone). The latest verdict per role counts.
3. `POST /api/decisions/{id}/stage {stage: approved}` succeeds only when every
   required role has approved and none has rejected — the enterprise gate
   "end-to-end approval recorded with sign-offs".
4. Discussion and follow-ups live on the decision: `POST …/comments {body, parentId}`,
   `POST …/tasks {title, assignee, due}`, `POST /api/tasks/{id} {status: done|cancelled}`,
   `GET /api/tasks?assignee=`.
5. Feedback on a resource (ratings 1–5, corrections, incidents, notes) is
   `POST /api/feedback {resourceId, kind, body, rating, decisionId?}`; reviewers
   triage it with `POST /api/feedback/{id} {status}`. `GET /api/feedback?resourceId=`
   returns the items and a summary (count, open, average rating).

**Export.** `GET /api/decisions/{id}/export` (`?format=csv` for a flat file)
returns the decision packet: lifecycle events, sign-offs, comments, tasks,
feedback and a snapshot of the agent's trust profile, compliance records,
security and issues at export time, plus who exported it and from which
catalog build. `GET /api/decisions/export.csv` lists every decision with its
sign-off state for a GRC import. Every workflow action is in the audit trail and
`decision.changed` goes out through the notification channels.

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
