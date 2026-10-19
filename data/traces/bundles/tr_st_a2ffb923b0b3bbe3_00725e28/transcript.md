# Probe transcript — ARC (arcreport.ai): can an agent reach checkout?

Agent `res_a2ffb923b0b3bbe3` · publisher domain `arcreport.ai` · 2026-10-19 · harness probe-1.0

## Agent2Agent (A2A)

- requested `https://www.arcreport.ai/.well-known/agent-card.json`
- result: **verified**
- declared version: 1.0 (card 1.1.0)
- signed: no
- skills advertised: precheck, find_agent_ready_stores, can_agent_checkout, ask_arc, agent_commerce_adoption, product_data_check, google_checkout_readiness, get_agent_facts, list_category_agent_facts, dataset_info, protocol_matrix, agent_leaderboard, submit_leaderboard_run, submit_store, store_card, validate_ucp_profile

## Agentic Resource Discovery (ARD)

- requested `https://www.arcreport.ai/.well-known/ai-catalog.json`
- result: **invalid**
- manifest entries: 2
- validation error: entries[0]: missing required term 'displayName'
- validation error: entries[1]: missing required term 'displayName'

---
Observation only: the registry fetched public well-known paths and validated the documents against the protocol specifications. No credentials, no message exchange beyond discovery, nothing written.
