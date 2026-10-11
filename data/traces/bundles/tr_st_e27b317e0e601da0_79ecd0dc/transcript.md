# Probe transcript — LobeChat

Agent `res_e27b317e0e601da0` · publisher domain `lobehub.com` · 2026-10-11 · harness probe-1.0

## Agent2Agent (A2A)

- requested `https://lobehub.com/.well-known/agent-card.json`
- result: **invalid**
- declared version:  (card 1.0.0)
- signed: no
- validation error: missing service endpoint ('url' or 'supportedInterfaces')
- validation error: skills[0] missing id/name
- validation error: skills[1] missing id/name
- validation error: skills[2] missing id/name

---
Observation only: the registry fetched public well-known paths and validated the documents against the protocol specifications. No credentials, no message exchange beyond discovery, nothing written.
