"""Catalog build pipeline (plan section 4): sources -> normalized, deduplicated,
classified, scored resources -> static catalog files.

Stages are idempotent and every derived value is stamped with the version
that produced it. The seed workbook is the frozen ranked baseline (BRD §7.4
default): seed rows keep their workbook ranks in each domain's Top 100, and
discovered resources appear in the same domain lists as *unranked* entries
sorted by score, until the maintainer re-scores.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import SCORE_VERSION, __version__
from .classify import Classifier
from .connectors import ard_web, github, huggingface, marketplaces, mcp_registry
from .connectors.base import SnapshotStore
from .connectors.seed_xlsx import import_seed
from .dedup import dedup, load_decisions, resource_slug, write_review_file
from .score import COMPONENTS_VERSION, ScoringConfig, components_from_signals, score_for_domain
from .util import ROOT, NetPolicy, load_config, now_iso

ALL_SOURCES = ("seed", "marketplaces", "mcp_registry", "huggingface", "github", "ard_web")
DISCLAIMER = (
    "Reference implementation by Hemant Naik. Compliance information is compiled from the sources shown as of the "
    "date shown. It is not an assessment, certification, legal opinion or recommendation. Confirm current status "
    "with the vendor and the issuing body."
)
REGISTRY_URN = "urn:air:sushegaad.github.io:registry:agentdossier"
SITE = "https://sushegaad.github.io/AgentDossier/"


@dataclass
class BuildOptions:
    out_dir: Path = ROOT / "data" / "catalog"
    cache_dir: Path = ROOT / "build" / "snapshots"
    sources: tuple[str, ...] = ALL_SOURCES
    seed_path: Path = ROOT / "data" / "seed" / "top_100_ai_agents_by_domain_2026-09-25.xlsx"
    offline: bool = False
    limit: int | None = None  # cap discovered resources per source (dev runs)
    ard_domain_limit: int | None = None
    mcp_handshake: bool = False
    github_min_stars: int = 25
    policy: NetPolicy = field(default_factory=NetPolicy)
    write_review: bool = True


@dataclass
class BuildResult:
    resources: list[dict[str, Any]]
    reports: dict[str, dict[str, Any]]
    summary: dict[str, Any]


def _identity(res: dict[str, Any]) -> dict[str, Any]:
    """Identity tier before any cryptographic verification (FR-49, v1 rules)."""
    ext = res.get("external_ids") or {}
    evidence: list[str] = []
    tier = 5
    ard_block = res["protocols"].get("ard", {})
    if ard_block.get("status") == "verified" and ard_block.get("trust_manifest") == "present-binding-ok":
        tier, evidence = 1, ["ard_trust_manifest_binding"]
    elif any(k in ext for k in ("aws_marketplace", "microsoft_agent_store", "google_cloud_marketplace")):
        tier, evidence = 2, ["marketplace_listing"]
    elif ard_block.get("status") == "verified" or res["protocols"].get("a2a", {}).get("status") == "verified":
        tier, evidence = 2, ["standards_metadata_at_publisher_domain"]
    elif "github" in ext or "huggingface_space" in ext or "huggingface_model" in ext:
        tier, evidence = 3, ["repository_ownership"]
    elif res.get("vendor"):
        tier, evidence = 4, ["vendor_name_only"]
    return {"tier": tier, "evidence": evidence, "rules_version": "identity-1.0"}


def _trust_summary(res: dict[str, Any]) -> dict[str, int | None]:
    comp = res.get("compliance") or []
    active = [int(c["tier"]) for c in comp if c.get("status") == "active"]
    protos = [p.get("status") for p in res["protocols"].values()]
    return {
        "identity": int(res["identity"]["tier"]),
        "compliance": min(active) if active else 5,
        "security": res.get("security", {}).get("tier") if res.get("security") else None,
        "protocols": 1 if "verified" in protos else 3 if "claimed" in protos else 5,
        "issues": res.get("issues", {}).get("tier") if res.get("issues") else None,
    }


def collect(opts: BuildOptions) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    store = None if opts.offline else SnapshotStore(opts.cache_dir)
    reports: dict[str, dict[str, Any]] = {}
    resources: list[dict[str, Any]] = []

    if "seed" in opts.sources:
        seed = import_seed(opts.seed_path)
        if not seed.ok:
            raise RuntimeError("seed import failed: " + "; ".join(seed.errors[:3]))
        resources.extend(seed.resources.values())
        reports["seed"] = {
            "source": "seed",
            "produced": len(seed.resources),
            "rows": len(seed.rows),
            "snapshot": seed.snapshot_date,
        }
    if "marketplaces" in opts.sources:
        rs, rep = marketplaces.run()
        resources.extend(rs)
        reports["marketplaces"] = rep.as_dict()
    if opts.offline:
        return resources, reports

    if "mcp_registry" in opts.sources:
        rs, rep = mcp_registry.run(store=store, policy=opts.policy, max_pages=(2 if opts.limit else 200))
        resources.extend(rs[: opts.limit] if opts.limit else rs)
        reports["mcp_registry"] = rep.as_dict()
    if "huggingface" in opts.sources:
        rs, rep = huggingface.run(store=store, policy=opts.policy, limit=(opts.limit or 500))
        resources.extend(rs[: opts.limit] if opts.limit else rs)
        reports["huggingface"] = rep.as_dict()
    if "github" in opts.sources:
        if os.environ.get("GITHUB_TOKEN"):
            rs, rep = github.run(
                store=store,
                policy=opts.policy,
                min_stars=opts.github_min_stars,
                max_pages=(1 if opts.limit else 10),
            )
            resources.extend(rs[: opts.limit] if opts.limit else rs)
            reports["github"] = rep.as_dict()
        else:
            reports["github"] = {"source": "github", "skipped": "GITHUB_TOKEN not set"}
    return resources, reports


def enrich(
    resources: list[dict[str, Any]], opts: BuildOptions, reports: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    decisions = load_decisions()
    result = dedup(resources, decisions=decisions)
    reports["dedup"] = {
        "input": len(resources),
        "output": len(result.resources),
        "merged": result.merged,
        "review_candidates": len(result.candidates),
    }
    if opts.write_review and result.candidates:
        reports["dedup"]["review_added"] = write_review_file(result.candidates)
    resources = result.resources

    if "ard_web" in opts.sources and not opts.offline:
        store = SnapshotStore(opts.cache_dir)
        extra = [
            s.get("domain") for s in load_config("sources.json").get("ard_domains", []) if s.get("domain")
        ]
        new, rep = ard_web.run(
            resources,
            extra_domains=extra,
            store=store,
            policy=opts.policy,
            limit=opts.ard_domain_limit,
            mcp_handshake=opts.mcp_handshake,
        )
        reports["ard_web"] = rep.as_dict()
        if new:
            resources = dedup(resources + new, decisions=decisions, fuzzy=False).resources

    cfg = ScoringConfig.load()
    clf = Classifier()
    for res in resources:
        res["identity"] = _identity(res)
        res.setdefault("compliance", [])
        res.setdefault("news", [])
        is_seed = any(s["system"] == "seed_xlsx" for s in res["sources"])
        if not is_seed:
            cls = clf.classify(
                res.get("name"),
                res.get("description"),
                " ".join(res.get("tags") or []),
                " ".join(res.get("capabilities") or []),
                category=res.get("category"),
            )
            curated = (res.get("signals") or {}).get("curated_domains") or []
            domains = dict(cls.domains)
            for d in curated:
                domains[d] = max(domains.get(d, 0.0), 0.9)
            res["classification"] = {"taxonomy_version": cls.taxonomy_version, "matched": cls.matched}
            res["domains"] = {}
            for d, conf in domains.items():
                comps = components_from_signals(res, conf, cfg)
                sr = score_for_domain(comps, d, cfg)
                res["domains"][d] = {
                    "rank": None,
                    "score": sr.score,
                    "profile": sr.profile,
                    "score_version": sr.version,
                    "evidence_coverage": sr.evidence_coverage,
                    "confidence": conf,
                    "source": "classifier",
                    "components": comps,
                    "components_version": COMPONENTS_VERSION,
                    "unknown": list(sr.unknown),
                }
        res["trust"] = _trust_summary(res)
        res["slug"] = resource_slug(res)
    return resources


def write_outputs(
    resources: list[dict[str, Any]], opts: BuildOptions, reports: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    out = opts.out_dir
    for sub in ("domains", "agents", "agents-list"):
        shutil.rmtree(out / sub, ignore_errors=True)
        (out / sub).mkdir(parents=True, exist_ok=True)
    taxonomy = load_config("taxonomy.json")
    snapshot = reports.get("seed", {}).get("snapshot") or now_iso()[:10]
    built = now_iso()
    frameworks_version = "frameworks-1.0"

    index_records = []
    for res in sorted(resources, key=lambda r: r["name"].lower()):
        index_records.append(
            {
                "id": res["id"],
                "slug": res["slug"],
                "name": res["name"],
                "vendor": res.get("vendor"),
                "resource_type": res["resource_type"],
                "category": res.get("category"),
                "license": res.get("license"),
                "deployment": res.get("deployment"),
                "scope": res["scope"],
                "domains": {
                    d: {"rank": v.get("rank"), "score": v["score"]} for d, v in res["domains"].items()
                },
                "trust": res["trust"],
                "protocols": {p: res["protocols"][p]["status"] for p in ("a2a", "mcp", "ard")},
                "compliance_summary": [
                    {
                        "framework": c["framework"],
                        "variant": c.get("variant"),
                        "tier": c["tier"],
                        "status": c["status"],
                    }
                    for c in res.get("compliance", [])
                ],
                "sources": sorted({s["system"] for s in res["sources"]}),
                "description": (res.get("description") or "")[:200] or None,
                "tags": (res.get("tags") or [])[:12],
            }
        )
    index_doc = {
        "snapshot_date": snapshot,
        "built_at": built,
        "score_version": SCORE_VERSION,
        "taxonomy_version": taxonomy["version"],
        "frameworks_version": frameworks_version,
        "scope": "public",
        "tenant": None,
        "disclaimer": DISCLAIMER,
        "generator": f"agentdossier {__version__}",
        "records": index_records,
    }
    (out / "index.json").write_text(json.dumps(index_doc, separators=(",", ":"), ensure_ascii=False))

    by_id = {r["id"]: r for r in resources}
    for res in resources:
        (out / "agents" / f"{res['id']}.json").write_text(
            json.dumps(
                {**{k: v for k, v in res.items() if k != "raw"}, "disclaimer": DISCLAIMER},
                ensure_ascii=False,
                indent=0,
                sort_keys=True,
            )
        )

    domain_counts = {}
    for slug_, spec in taxonomy["domains"].items():
        ranked = sorted(
            [r for r in resources if r["domains"].get(slug_, {}).get("rank")],
            key=lambda r: r["domains"][slug_]["rank"],
        )
        discovered = sorted(
            [r for r in resources if slug_ in r["domains"] and not r["domains"][slug_].get("rank")],
            key=lambda r: -r["domains"][slug_]["score"],
        )

        def row(r: dict[str, Any], slug_: str = slug_) -> dict[str, Any]:
            d = r["domains"][slug_]
            return {
                "id": r["id"],
                "slug": r["slug"],
                "name": r["name"],
                "vendor": r.get("vendor"),
                "category": r.get("category"),
                "resource_type": r["resource_type"],
                "license": r.get("license"),
                "rank": d.get("rank"),
                "score": d["score"],
                "profile": d["profile"],
                "evidence_coverage": d.get("evidence_coverage"),
                "components": r.get("components") if d.get("rank") else d.get("components"),
                "trust": r["trust"],
                "protocols": {p: r["protocols"][p]["status"] for p in ("a2a", "mcp", "ard")},
                "confidence": d.get("confidence"),
            }

        doc = {
            "domain": slug_,
            "label": spec["label"],
            "snapshot_date": snapshot,
            "score_version": SCORE_VERSION,
            "profile": ScoringConfig.load().profile_for_domain(slug_),
            "ranked": [row(r) for r in ranked],
            "discovered": [row(r) for r in discovered],
            "disclaimer": DISCLAIMER,
            "note": "Ranked rows come from the seed workbook (frozen baseline). Discovered rows are scored with signal-derived components and are not ranked.",
        }
        (out / "domains" / f"{slug_}.json").write_text(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        )
        domain_counts[slug_] = {"ranked": len(ranked), "discovered": len(discovered)}

    page = 100
    listing = [
        {
            "identifier": f"urn:air:sushegaad.github.io:catalog:{r['slug']}",
            "displayName": r["name"],
            "type": _ard_type(r),
            "url": f"{SITE}agents/{r['slug']}/",
            "resourceId": r["id"],
        }
        for r in sorted(resources, key=lambda r: r["name"].lower())
    ]
    pages = max(1, (len(listing) + page - 1) // page)
    for n in range(pages):
        chunk = listing[n * page : (n + 1) * page]
        (out / "agents-list" / f"page-{n + 1}.json").write_text(
            json.dumps(
                {
                    "agents": chunk,
                    "page": n + 1,
                    "pages": pages,
                    "pageSize": page,
                    "total": len(listing),
                    "nextPageToken": str(n + 2) if n + 1 < pages else None,
                }
            )
        )

    ard_entries = [
        {
            "@context": "https://agenticresourcediscovery.org/context/v1",
            "identifier": REGISTRY_URN,
            "displayName": "AgentDossier public demo registry",
            "type": "application/ai-registry+json",
            "url": SITE,
            "description": "Reference implementation of a standards-aware AI agent registry. Static demo; the ARD search API is served by the self-hosted edition.",
            "representativeQueries": [
                "find an insurance claims agent with a HIPAA BAA",
                "which coding agents support MCP",
                "FedRAMP authorized agent platforms",
            ],
            "tags": ["registry", "reference-implementation", "ard", "a2a", "mcp"],
            "version": __version__,
        }
    ]
    for r in resources:
        entry = ((r.get("raw") or {}).get("ard_entry")) if isinstance(r.get("raw"), dict) else None
        if entry:
            ard_entries.append(entry)
    (out / "ard.json").write_text(json.dumps({"entries": ard_entries}, ensure_ascii=False, indent=1))

    search_docs = [
        {
            "id": r["id"],
            "slug": r["slug"],
            "name": r["name"],
            "vendor": r.get("vendor") or "",
            "description": r.get("description") or "",
            "tags": " ".join(r.get("tags") or []),
            "capabilities": " ".join(r.get("capabilities") or []),
            "queries": " ".join(r.get("representative_queries") or []),
            "category": r.get("category") or "",
            "domains": " ".join(r["domains"].keys()),
        }
        for r in resources
    ]
    (out / "search-docs.json").write_text(json.dumps(search_docs, ensure_ascii=False, separators=(",", ":")))

    summary = {
        "built_at": built,
        "snapshot_date": snapshot,
        "generator": f"agentdossier {__version__}",
        "score_version": SCORE_VERSION,
        "resources": len(resources),
        "by_source": _count_by_source(resources),
        "by_type": _count(resources, "resource_type"),
        "protocols": {p: _count_status(resources, p) for p in ("a2a", "mcp", "ard")},
        "domains": domain_counts,
        "identity_tiers": _count_identity(resources),
        "reports": reports,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    _ = by_id
    return summary


def _ard_type(r: dict[str, Any]) -> str:
    return {
        "a2a_agent": "application/a2a-agent-card+json",
        "mcp_server": "application/mcp-server-card+json",
        "skill": "application/ai-skill+md",
        "registry": "application/ai-registry+json",
    }.get(r["resource_type"], "application/agentdossier-record+json")


def _count(resources: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in resources:
        out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
    return dict(sorted(out.items()))


def _count_by_source(resources: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in resources:
        for s in {s["system"] for s in r["sources"]}:
            out[s] = out.get(s, 0) + 1
    return dict(sorted(out.items()))


def _count_status(resources: list[dict[str, Any]], proto: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in resources:
        st = r["protocols"][proto]["status"]
        out[st] = out.get(st, 0) + 1
    return out


def _count_identity(resources: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in resources:
        t = f"T{r['identity']['tier']}"
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items()))


def build(opts: BuildOptions | None = None) -> BuildResult:
    opts = opts or BuildOptions()
    resources, reports = collect(opts)
    resources = enrich(resources, opts, reports)
    summary = write_outputs(resources, opts, reports)
    return BuildResult(resources=resources, reports=reports, summary=summary)
