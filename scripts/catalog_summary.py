"""Render the refresh PR body from summary.json, with a 50-badge spot-check list."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/catalog")
s = json.loads((out / "summary.json").read_text())
index = json.loads((out / "index.json").read_text())
print(
    f"## Weekly catalog refresh\n\nBuilt {s['built_at']} with `{s['generator']}` (score {s['score_version']}, snapshot {s['snapshot_date']}).\n"
)
print(f"- Resources: **{s['resources']}**")
print("- By source: " + ", ".join(f"{k} {v}" for k, v in s["by_source"].items()))
print("- By type: " + ", ".join(f"{k} {v}" for k, v in s["by_type"].items()))
for p, counts in s["protocols"].items():
    print(f"- {p.upper()}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
print("- Identity tiers: " + ", ".join(f"{k} {v}" for k, v in s["identity_tiers"].items()))
print("\n### Connector reports\n")
print("| Source | Fetched | Produced | Skipped | Errors |\n| --- | --- | --- | --- | --- |")
for name, rep in s["reports"].items():
    print(
        f"| {name} | {rep.get('fetched', '')} | {rep.get('produced', rep.get('output', ''))} | {rep.get('skipped', '')} | {rep.get('errors', '')} |"
    )
badges = [(r["name"], c) for r in index["records"] for c in r.get("compliance_summary", [])]
if badges:
    random.seed(s["built_at"])
    sample = random.sample(badges, min(50, len(badges)))
    print("\n### Badge spot-check (tick after checking the source link)\n")
    for name, c in sample:
        print(f"- [ ] {name}: {c['framework']} {c.get('variant') or ''} T{c['tier']} {c['status']}")
else:
    print("\nNo compliance badges yet (Phase 1b).")
print("\nReview `data/review/matches.yaml` for new near-duplicate candidates before merging.")

# incident candidates from the scout (leads for the maintainer, never incidents)
cands = Path("data/curated/incident_candidates.yaml")
if cands.exists():
    try:
        import yaml  # noqa: PLC0415

        cdoc = yaml.safe_load(cands.read_text()) or {}
    except ImportError:  # pragma: no cover
        cdoc = {}
    new = [c for c in cdoc.get("candidates") or [] if c.get("status") == "new"]
    fresh = [c for c in new if c.get("first_seen") == cdoc.get("scouted_on")]
    print(
        f"\n### Incident candidates (scout)\n\n{len(new)} awaiting review, {len(fresh)} found this run, "
        f"{cdoc.get('sources_checked', 0)} feeds checked"
        + (f", failed: {', '.join(cdoc['sources_failed'])}" if cdoc.get("sources_failed") else "")
        + ". Promote with `agentdossier incidents draft <id>`, or set `status: dismissed`.\n"
    )
    for c in fresh[:15]:
        print(
            f"- `{c['id']}` [{c['title']}]({c['url']}) — {c.get('outlet', '')}, {c.get('date') or 'undated'}"
        )
    if len(fresh) > 15:
        print(f"- … and {len(fresh) - 15} more in `data/curated/incident_candidates.yaml`")
