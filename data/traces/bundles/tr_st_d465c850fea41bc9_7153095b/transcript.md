# Probe transcript — Admux

Agent `res_d465c850fea41bc9` · publisher domain `admux.ai` · 2026-11-16 · harness probe-1.0

## Agentic Resource Discovery (ARD)

- requested `https://admux.ai/.well-known/ai-catalog.json`
- result: **invalid**
- manifest entries: 1
- validation error: entries[0]: missing required term 'displayName'

---
Observation only: the registry fetched public well-known paths and validated the documents against the protocol specifications. No credentials, no message exchange beyond discovery, nothing written.
