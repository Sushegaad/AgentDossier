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

# incident candidates from the scout, and what the machine review did with them
cands = Path("data/curated/incident_candidates.yaml")
review = Path("build/incident_review.json")
if cands.exists():
    try:
        import yaml  # noqa: PLC0415

        cdoc = yaml.safe_load(cands.read_text()) or {}
    except ImportError:  # pragma: no cover
        cdoc = {}
    new = [c for c in cdoc.get("candidates") or [] if c.get("status") == "new"]
    fresh = [c for c in (cdoc.get("candidates") or []) if c.get("first_seen") == cdoc.get("scouted_on")]
    print(
        f"\n### Incident scout\n\n{len(fresh)} candidate(s) found this run from "
        f"{cdoc.get('sources_checked', 0)} feeds"
        + (f" (failed: {', '.join(cdoc['sources_failed'])})" if cdoc.get("sources_failed") else "")
        + f"; {len(new)} left unread (page could not be fetched; retried next week).\n"
    )
    for c in fresh[:15]:
        print(
            f"- `{c['id']}` [{c['title']}]({c['url']}) — {c.get('outlet', '')}, {c.get('date') or 'undated'}: **{c.get('status')}**"
        )
    if len(fresh) > 15:
        print(f"- … and {len(fresh) - 15} more in `data/curated/incident_candidates.yaml`")
if review.exists():
    rdoc = json.loads(review.read_text())
    print(
        f"\n### Machine review ({rdoc.get('model')}, {rdoc.get('reviewed_on')})\n\n"
        f"{rdoc.get('candidates_reviewed', 0)} candidates and {rdoc.get('placeholders_reviewed', 0)} placeholders read → "
        f"**{len(rdoc.get('published') or [])} published**, {len(rdoc.get('dismissed') or [])} dismissed, "
        f"{len(rdoc.get('unreadable') or [])} unreadable, {len(rdoc.get('errors') or [])} errors. "
        "Published rows carry `reviewer: model: … (automated review)`; retract one with "
        "`agentdossier incidents dismiss <cand-id> --note` and delete the row.\n"
    )
    for r in rdoc.get("published") or []:
        print(f"- published **{r['id']}** {r['title']} — {r['why']}")
    for r in (rdoc.get("dismissed") or [])[:20]:
        print(f"- dismissed `{r['id']}` {r['title']} — {r['why']}")
    for r in rdoc.get("unreadable") or []:
        print(f"- unreadable `{r['id']}` — {r['why']}")
    for e in rdoc.get("errors") or []:
        print(f"- error: {e}")

# source re-check: which incident links still answer
check = Path("data/curated/incident_source_check.json")
if check.exists():
    rdoc = json.loads(check.read_text())
    sm = rdoc.get("summary", {})
    print(
        f"\n### Incident sources re-checked ({rdoc.get('checked_on')})\n\n"
        f"{rdoc.get('sources_checked', 0)} links across {rdoc.get('incidents_checked', 0)} incidents — "
        f"ok {sm.get('ok', 0)}, moved {sm.get('moved', 0)}, gone {sm.get('gone', 0)}, "
        f"unverified (bot wall) {sm.get('unverified', 0)}, error {sm.get('error', 0)}."
    )
    for iid in rdoc.get("needs_attention") or []:
        for line in rdoc["incidents"].get(iid, []):
            if line["status"] in ("gone", "moved", "error"):
                where = f" → {line['final_url']}" if line.get("final_url") else ""
                print(f"- [ ] {iid}: **{line['status']}** (HTTP {line['http']}) {line['url']}{where}")
    if not rdoc.get("needs_attention"):
        print("\nNothing needs attention.")

# the CVE registry: what changed this week, and a sample to spot-check for precision
cve_index = Path("data/cves/index.json")
if cve_index.exists():
    cdoc = json.loads(cve_index.read_text())
    recs = cdoc.get("records") or []
    cc = cdoc.get("counts") or {}
    built = cdoc.get("built_at")
    fresh = [r for r in recs if r.get("retrieved_on") == built and r.get("status") == "candidate"]
    kev = [r for r in recs if r.get("kev")]
    print(
        f"\n### CVE registry\n\n{cc.get('total', 0)} CVEs listed ({cc.get('included', 0)} included, "
        f"{cc.get('candidate', 0)} candidates, {cc.get('kev', 0)} in CISA KEV, {cc.get('unscored', 0)} unscored) "
        f"across {len(cdoc.get('products_matched') or [])} listed products, as of {built}. "
        "Decide with `agentdossier cves include|exclude <id> --note`.\n"
    )
    for r in sorted(fresh, key=lambda r: r.get("published") or "", reverse=True)[:15]:
        sev = f"{r['cvss']['severity']} {r['cvss']['score']}" if r.get("cvss") else "unscored"
        prod = ", ".join(
            sorted({p.get("product_id") or p["product"] for p in r.get("products") or []})
        ) or r.get("category")
        print(f"- `{r['id']}` {sev} · {prod} · {', '.join(r['match']['tests'])}: {r['description'][:110]}")
    if len(fresh) > 15:
        print(f"- … and {len(fresh) - 15} more candidates in `data/cves/index.json`")
    pool = [r for r in recs if r.get("status") != "excluded"]
    if pool:
        random.seed(str(built))
        print(
            "\n#### CVE spot-check (tick when the CVE is genuinely about an agent product, framework, protocol or infrastructure)\n"
        )
        for r in random.sample(pool, min(50, len(pool))):
            print(f"- [ ] {r['id']} · {r['category']} · {', '.join(r['match']['tests'])}")
