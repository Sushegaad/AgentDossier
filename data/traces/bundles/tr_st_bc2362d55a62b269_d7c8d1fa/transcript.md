# Probe transcript — Infisical vs. Azure Key Vault

Agent `res_bc2362d55a62b269` · publisher domain `infisical.com` · 2026-11-16 · harness probe-1.0

## Agentic Resource Discovery (ARD)

- requested `https://infisical.com/.well-known/ard.json`
- result: **verified**

---
Observation only: the registry fetched public well-known paths and validated the documents against the protocol specifications. No credentials, no message exchange beyond discovery, nothing written.
