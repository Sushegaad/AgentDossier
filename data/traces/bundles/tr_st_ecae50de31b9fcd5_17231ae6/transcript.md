# Probe transcript — ai.augmentev/paseo

Agent `res_ecae50de31b9fcd5` · publisher domain `augmentev.com` · 2026-10-11 · harness probe-1.0

## Agent2Agent (A2A)

- requested `https://augmentev.com/.well-known/agent-card.json`
- result: **verified**
- declared version: 0.3.0 (card 2026-10-08)
- auth schemes: creditKey
- signed: no
- skills advertised: Append a signed agent record, Append 100-1000 signed records, Get an offline-verifiable proof, Audit pack, Top up prepaid credit

## Agentic Resource Discovery (ARD)

- requested `https://augmentev.com/.well-known/ai-catalog.json`
- result: **invalid**
- manifest entries: 3
- validation error: entries[0]: identifier is not a urn:air:<publisher>:<namespace>:<name> URN: urn:ai:augmentev.com:paseo:khanoor
- validation error: entries[1]: identifier is not a urn:air:<publisher>:<namespace>:<name> URN: urn:ai:augmentev.com:paseo:resolve
- validation error: entries[2]: identifier is not a urn:air:<publisher>:<namespace>:<name> URN: urn:ai:augmentev.com:paseo:docflow

---
Observation only: the registry fetched public well-known paths and validated the documents against the protocol specifications. No credentials, no message exchange beyond discovery, nothing written.
