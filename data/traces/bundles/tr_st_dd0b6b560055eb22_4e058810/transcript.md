# Probe transcript — Agent Blueprint

Agent `res_dd0b6b560055eb22` · publisher domain `agentblueprint.ai` · 2026-11-09 · harness probe-1.0

## Agent2Agent (A2A)

- requested `https://agentblueprint.ai/.well-known/agent.json`
- result: **invalid**
- signed: no
- validation error: missing 'version'

## Agentic Resource Discovery (ARD)

- requested `https://agentblueprint.ai/.well-known/ai-catalog.json`
- result: **invalid**
- manifest entries: 1
- validation error: entries[0]: missing required term 'displayName'

---
Observation only: the registry fetched public well-known paths and validated the documents against the protocol specifications. No credentials, no message exchange beyond discovery, nothing written.
