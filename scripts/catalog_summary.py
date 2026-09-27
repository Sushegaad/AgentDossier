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
