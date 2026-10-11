# Trace store

Append-only, hash-chained store of trace bundles. See docs/traces.md. `index.jsonl` is the ledger; `bundles/<id>/` holds each bundle's text files. Never edit a line or a bundle: append a new one.
