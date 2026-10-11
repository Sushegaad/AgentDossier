"""Traces: public observations of an agent under attack, in defence or in an incident.

"We urgently need more public traces of AI agents attacking and defending systems.
Defenders can't learn from what they can't see." A dossier therefore carries a
``traces`` list and a trace tier in its trust summary, and says "none found" out
loud when nothing exists. Records come from two places:

* ``data/curated/traces.yaml`` — public write-ups, incident reports and evaluations a
  person checked (:mod:`.curated`);
* ``data/traces/`` — the registry's own hash-chained store of trace bundles, starting
  with the ``self_test`` transcripts of every protocol probe (:mod:`.store`).
"""

from __future__ import annotations

from typing import Any

from .curated import load_curated
from .store import TraceStore

TIER_WORD = {
    1: "reproducible run",
    2: "third-party report",
    3: "vendor report",
    4: "vendor claim",
    5: "none found",
}
KIND_WORD = {
    "red_team": "attacked by a researcher",
    "injection_eval": "tested under adversarial input",
    "ctf": "cyber-range run",
    "incident": "real-world incident",
    "self_test": "registry probe",
    "vendor_published": "published by the vendor",
}


def apply_traces(resources: list[dict[str, Any]], store: TraceStore | None = None) -> dict[str, int]:
    """Attach curated and stored trace records to every resource; returns counts for the report."""
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for rec in load_curated():
        by_slug.setdefault(rec["agent"], []).append(rec)
    stored = store.records_by_agent() if store else {}
    counts = {"curated": 0, "stored": 0, "agents_with_traces": 0}
    for res in resources:
        recs = [dict(r) for r in by_slug.get(res["slug"], [])]
        counts["curated"] += len(recs)
        own = stored.get(res["id"], []) + stored.get(res["slug"], [])
        counts["stored"] += len(own)
        recs += own
        for r in recs:
            r.pop("agent", None)
        recs.sort(key=lambda r: (int(r["tier"]), r.get("date") or ""), reverse=False)
        res["traces"] = recs
        if recs:
            counts["agents_with_traces"] += 1
    return counts


def trace_tier(res: dict[str, Any]) -> int:
    recs = res.get("traces") or []
    return min((int(r["tier"]) for r in recs), default=5)
