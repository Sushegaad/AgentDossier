# Security policy

AgentDossier never executes third-party agents or tools during discovery.
Discovery is HTTP GET plus MCP list methods only, behind an SSRF guard and
response-size limits. The enterprise scanner refuses to run without an
authorization record and contacts only allow-listed targets.

## Reporting a vulnerability

Use GitHub private vulnerability reporting on this repository. Please do not
open a public issue for security problems. You will get an acknowledgement
within 5 business days.

## Scope

- The `agentdossier` Python package and CLI
- The static demo site and its build workflows
- The enterprise container image

Out of scope: the third-party agents, marketplaces and registries the
catalog describes.
