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
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import SCORE_VERSION, __version__
from .classify import Classifier
from .compliance import run as compliance_run
from .compliance.engine import (
    append_changelog,
    changelog_events,
    governance_from_evidence,
)
from .compliance.matching import entity_domains
from .connectors import ard_web, github, huggingface, hygiene, marketplaces, mcp_registry, seed_enrich
from .connectors.base import SnapshotStore
from .connectors.seed_xlsx import import_seed
from .dedup import dedup, load_decisions, resource_slug, write_review_file
from .news import run as news_run
from .protocol_claims import apply_claims, load_curated_protocols
from .score import COMPONENTS_VERSION, ScoringConfig, components_from_signals, score_for_domain
from .util import ROOT, Deadline, NetPolicy, domain_of, load_config, now_iso

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
    # Default caps for a weekly run: the public catalog is curated, not exhaustive. GitHub alone
    # matches 2,000+ repositories above 25 stars; taking the best few hundred keeps the crawl,
    # evidence and news stages inside the runner's time limit. --limit overrides all three.
    github_cap: int = 300
    seed_enrich: bool = True  # look up seed rows whose URL is a GitHub repository
    hygiene: bool = True  # drop demo, deprecated and inactive discovered rows (connectors.hygiene)
    huggingface_cap: int = 150
    mcp_registry_cap: int = 300
    budget_minutes: float | None = 150.0  # wall-clock budget for the whole build (None = unlimited)
    ard_domain_limit: int | None = None
    mcp_handshake: bool = False
    github_min_stars: int = 25
    policy: NetPolicy = field(default_factory=NetPolicy)
    write_review: bool = True
    compliance: bool = True
    news: bool = True
    claim_domain_limit: int | None = None
    news_limit: int | None = None
    changelog_path: Path = ROOT / "data" / "changelog" / "trust-changelog.jsonl"
    # Self-hosted / private catalogs (enterprise edition)
    scope: str = "public"
    tenant: str | None = None
    site: str = SITE
    registry_urn: str = REGISTRY_URN
    registry_name: str = "AgentDossier public demo registry"
    registry_description: str = (
        "Reference implementation of a standards-aware AI agent registry. Static demo; the ARD search API is "
        "served by the self-hosted edition."
    )


@dataclass
class BuildResult:
    resources: list[dict[str, Any]]
    reports: dict[str, dict[str, Any]]
    summary: dict[str, Any]


_VENDOR_STOP = {
    "inc",
    "llc",
    "ltd",
    "corp",
    "labs",
    "the",
    "and",
    "ai",
    "technologies",
    "software",
    "systems",
}


def _domain_matches_vendor(domain: str | None, vendor: str | None) -> bool:
    """everlaw.com <- "Everlaw"; salesforce.com <- "Salesforce, Inc."; needs a 4+ letter vendor token."""
    if not domain or not vendor:
        return False
    d = domain.lower().removeprefix("www.")
    if any(d == own or d.endswith("." + own) for own in entity_domains(vendor)):
        return True  # config/vendor_aliases.json: aws.amazon.com is AWS's own domain
    label = d.split(".")[0].replace("-", "")
    for tok in re.findall(r"[a-z0-9]+", vendor.lower()):
        if len(tok) >= 4 and tok not in _VENDOR_STOP and tok in label:
            return True
    return False


_CODE_HOSTS = {"github.com", "gitlab.com", "huggingface.co", "pypi.org", "npmjs.com", "www.npmjs.com"}


def _vendor_product_page(res: dict[str, Any]) -> bool:
    """The resource's own URL is a page on the vendor's domain (salesforce.com/agentforce for Salesforce).

    A product page the vendor serves from its own domain ties the product to the publisher at
    least as firmly as a marketplace listing does, so it earns the same tier. Only the URL itself
    counts: a publisher_domain inferred from a repository's homepage field stays at tier 3.
    """
    d = domain_of(res.get("url"))
    if not d or d.lower().removeprefix("www.") in _CODE_HOSTS or d.lower().endswith(".github.io"):
        return False
    return _domain_matches_vendor(d, res.get("vendor"))


def _identity(res: dict[str, Any], curated: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Identity tier before any cryptographic verification (FR-49, v1 rules)."""
    ext = res.get("external_ids") or {}
    evidence: list[str] = []
    tier = 5
    ard_block = res["protocols"].get("ard", {})
    domain = res.get("publisher_domain") or domain_of(res.get("url"))
    cur = (curated or {}).get((domain or "").lower().removeprefix("www."))
    if ard_block.get("status") == "verified" and ard_block.get("trust_manifest") == "present-binding-ok":
        tier, evidence = 1, ["ard_trust_manifest_binding"]
    elif any(k in ext for k in ("aws_marketplace", "microsoft_agent_store", "google_cloud_marketplace")):
        tier, evidence = 2, ["marketplace_listing"]
    elif ard_block.get("status") == "verified" or res["protocols"].get("a2a", {}).get("status") == "verified":
        tier, evidence = 2, ["standards_metadata_at_publisher_domain"]
    elif cur and _domain_matches_vendor(domain, cur.get("vendor") or res.get("vendor")):
        tier, evidence = 2, ["maintainer_verified_publisher_domain"]
    elif _vendor_product_page(res):
        tier, evidence = 2, ["vendor_domain_product_page"]
    elif "github" in ext or "huggingface_space" in ext or "huggingface_model" in ext:
        tier, evidence = 3, ["repository_ownership"]
    elif _domain_matches_vendor(domain, res.get("vendor")):
        tier, evidence = 3, ["publisher_domain_matches_vendor"]
    elif res.get("vendor"):
        tier, evidence = 4, ["vendor_name_only"]
    out: dict[str, Any] = {"tier": tier, "evidence": evidence, "rules_version": "identity-1.1"}
    if cur and tier == 2 and evidence == ["maintainer_verified_publisher_domain"]:
        out["verified_by"] = cur.get("checked_by", "maintainer")
        out["verified_on"] = cur.get("checked_on")
    return out


def load_curated_identity(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """``data/curated/identity.yaml``: publisher domains the maintainer confirmed belong to the vendor."""
    path = path or ROOT / "data" / "curated" / "identity.yaml"
    if not path.exists():
        return {}
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return {
        str(e["publisher_domain"]).lower().removeprefix("www."): e
        for e in doc.get("domains", [])
        if e.get("publisher_domain") and e.get("checked_on")
    }


def _score_domains(res: dict[str, Any], cfg: ScoringConfig, *, is_seed: bool) -> None:
    """Score every domain entry of a resource (sar-score-2.0).

    Workbook rows keep the workbook's adoption, health, ecosystem, domain-fit and docs values
    (nothing better is known for them); ``trust`` and ``governance`` are recomputed from evidence
    for every row, so the Top 100 tables and the dossier never show a trust number the evidence
    ledger contradicts. The workbook's values stay on the record as ``seed_components``.
    """
    seed_comps = dict(res.get("components") or {}) if is_seed else {}
    for d, entry in res["domains"].items():
        conf = float(entry.get("confidence") or 1.0)
        signal_comps = components_from_signals(res, conf, cfg)
        comps = dict(seed_comps) if is_seed else dict(signal_comps)
        comps["trust"] = signal_comps["trust"]
        gov, detail = governance_from_evidence(res.get("compliance", []), d)
        comps["governance"] = gov
        sr = score_for_domain(comps, d, cfg)
        if is_seed and "seed_rank" not in entry:
            entry["seed_rank"] = entry.get("rank")
            entry["seed_score"] = entry.get("score")
        entry.update(
            {
                "score": sr.score,
                "profile": sr.profile,
                "score_version": sr.version,
                "evidence_coverage": sr.evidence_coverage,
                "components": comps,
                "components_version": COMPONENTS_VERSION,
                "unknown": list(sr.unknown),
                "governance_credited": detail["credited"],
            }
        )
    if is_seed:
        res["seed_components"] = seed_comps
    res.pop("components", None)


def _rerank_seed_rows(resources: list[dict[str, Any]]) -> None:
    """Order each domain's Top 100 by the recomputed score; the workbook's order is ``seed_rank``."""
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for res in resources:
        for d, entry in res["domains"].items():
            if entry.get("seed_rank"):
                by_domain.setdefault(d, []).append(entry)
    for entries in by_domain.values():
        entries.sort(key=lambda e: (-float(e["score"]), int(e["seed_rank"])))
        for i, e in enumerate(entries, 1):
            e["rank"] = i


def _trust_summary(res: dict[str, Any]) -> dict[str, int | None]:
    comp = res.get("compliance") or []
    # agent-scoped rows only, the same split the dossier makes (web/src/lib/dossier.ts agentScoped)
    active = [int(c["tier"]) for c in comp if c.get("status") == "active" and _agent_scoped(c)]
    protos = [p.get("status") for p in res["protocols"].values()]
    return {
        "identity": int(res["identity"]["tier"]),
        "compliance": min(active) if active else 5,
        "security": res.get("security", {}).get("tier") if res.get("security") else None,
        "protocols": 1 if "verified" in protos else 3 if "claimed" in protos else 5,
        "issues": _issues_tier(res),
    }


def _agent_scoped(c: dict[str, Any]) -> bool:
    if c.get("covers_resource") == "yes":
        return True
    if c.get("covers_resource") == "inherited":
        return False
    return c.get("scope") != "entity"


def _issues_tier(res: dict[str, Any]) -> int | None:
    issues = res.get("issues")
    if not issues or not res.get("security", {}).get("checked_at") and not res.get("news_checked"):
        return None
    return 1 if not issues.get("links") else 3


_deadline: Deadline = Deadline(None)


def deadline() -> Deadline:
    return _deadline


def collect(opts: BuildOptions) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    global _deadline
    _deadline = Deadline(opts.budget_minutes)
    store = None if opts.offline else SnapshotStore(opts.cache_dir)
    reports: dict[str, dict[str, Any]] = {}
    resources: list[dict[str, Any]] = []
    _deadline.log("collect", f"sources {', '.join(opts.sources)}")

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
        resources.extend(rs[: (opts.limit or opts.mcp_registry_cap)])
        reports["mcp_registry"] = rep.as_dict()
        _deadline.log("mcp_registry", f"{min(len(rs), opts.limit or opts.mcp_registry_cap)} of {len(rs)}")
    if "huggingface" in opts.sources:
        rs, rep = huggingface.run(store=store, policy=opts.policy, limit=(opts.limit or 500))
        resources.extend(rs[: (opts.limit or opts.huggingface_cap)])
        reports["huggingface"] = rep.as_dict()
        _deadline.log("huggingface", f"{min(len(rs), opts.limit or opts.huggingface_cap)} of {len(rs)}")
    if "github" in opts.sources:
        if os.environ.get("GITHUB_TOKEN"):
            rs, rep = github.run(
                store=store,
                policy=opts.policy,
                min_stars=opts.github_min_stars,
                max_pages=(1 if opts.limit else 10),
            )
            # best-first: the cap keeps the most-starred repositories
            rs.sort(key=lambda r: -int((r.get("signals") or {}).get("github_stars") or 0))
            resources.extend(rs[: (opts.limit or opts.github_cap)])
            reports["github"] = rep.as_dict()
            _deadline.log("github", f"{min(len(rs), opts.limit or opts.github_cap)} of {len(rs)} (by stars)")
        else:
            reports["github"] = {"source": "github", "skipped": "GITHUB_TOKEN not set"}
    if opts.hygiene:
        before = len(resources)
        resources, dropped = hygiene.filter_discovered(resources)
        reports["hygiene"] = {
            "source": "hygiene",
            "input": before,
            "kept": len(resources),
            "dropped": dropped,
        }
        _deadline.log("hygiene", f"{before - len(resources)} discovered rows dropped")
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
    _deadline.log("dedup", f"{len(resources)} resources")

    if opts.seed_enrich and not opts.offline:
        # seed rows that point at a GitHub repository: one API call gives them a publisher domain,
        # repository ownership (identity T3) and topics before the protocol and trust crawls run
        rep = seed_enrich.run(
            resources,
            token=os.environ.get("GITHUB_TOKEN"),
            store=SnapshotStore(opts.cache_dir),
            policy=opts.policy,
            deadline=_deadline,
        )
        reports["seed_enrich"] = rep.as_dict()
        _deadline.log("seed_enrich", f"{rep.fetched} repositories, {rep.produced} rows enriched")

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
            deadline=_deadline,
        )
        _deadline.log("ard_web", f"{rep.fetched} origins inspected, {len(new)} ARD entries")
        reports["ard_web"] = rep.as_dict()
        if new:
            resources = dedup(resources + new, decisions=decisions, fuzzy=False).resources

    claim_counts = apply_claims(resources, load_curated_protocols())
    reports["protocol_claims"] = {"source": "protocol_claims", **claim_counts}
    _deadline.log(
        "protocol_claims",
        f"{claim_counts['curated']} curated, {claim_counts['self_description']} self-described",
    )

    cfg = ScoringConfig.load()
    clf = Classifier()
    curated_identity = load_curated_identity()
    for res in resources:
        res["identity"] = _identity(res, curated_identity)
        res.setdefault("compliance", [])
        res.setdefault("news", [])
        res["slug"] = resource_slug(res)

    if opts.compliance and not opts.offline:
        store = SnapshotStore(opts.cache_dir)
        comp_reports, review = compliance_run.run(
            resources,
            store=store,
            policy=opts.policy,
            claim_domain_limit=opts.claim_domain_limit,
            deadline=_deadline,
        )
        _deadline.log("compliance", "done")
        reports.update(comp_reports)
        if opts.write_review and review:
            reports["compliance_review_added"] = {"added": write_review_file(review)}
    if opts.news and not opts.offline:
        store = SnapshotStore(opts.cache_dir)
        reports.update(
            news_run.run(
                resources, store=store, policy=opts.policy, limit=opts.news_limit, deadline=_deadline
            )
        )
        _deadline.log("news", "done")

    for res in resources:
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
            res["domains"] = {
                d: {"rank": None, "confidence": conf, "source": "classifier"} for d, conf in domains.items()
            }
        _score_domains(res, cfg, is_seed=is_seed)
    _rerank_seed_rows(resources)
    for res in resources:
        res["trust"] = _trust_summary(res)
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
    frameworks_version = "frameworks-1.1"

    previous_index = None
    if (out / "index.json").exists():
        try:
            previous_index = json.loads((out / "index.json").read_text())
        except ValueError:
            previous_index = None
    events = changelog_events(previous_index, resources, built)
    reports["changelog"] = {"events": len(events), "appended": append_changelog(events, opts.changelog_path)}

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
                        "credited": c.get("credited", False),
                        "source": c.get("source"),
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
        "scope": opts.scope,
        "tenant": opts.tenant,
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
                "components": d.get("components"),
                "seed_rank": d.get("seed_rank"),
                "trust": r["trust"],
                "protocols": {p: r["protocols"][p]["status"] for p in ("a2a", "mcp", "ard")},
                "confidence": d.get("confidence"),
            }

        doc = {
            "domain": slug_,
            "label": spec["label"],
            "snapshot_date": snapshot,
            "built_at": built,
            "score_version": SCORE_VERSION,
            "profile": ScoringConfig.load().profile_for_domain(slug_),
            "ranked": [row(r) for r in ranked],
            "discovered": [row(r) for r in discovered],
            "disclaimer": DISCLAIMER,
            "note": "Ranked rows are the seed workbook's Top 100, re-ordered by a score whose trust and governance components are recomputed from evidence on every build (seed_rank is the workbook's order). Discovered rows are scored from signals and are not ranked.",
        }
        (out / "domains" / f"{slug_}.json").write_text(
            json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        )
        domain_counts[slug_] = {"ranked": len(ranked), "discovered": len(discovered)}

    page = 100
    listing = [
        {
            "identifier": f"{opts.registry_urn.rsplit(':registry:', 1)[0]}:catalog:{r['slug']}",
            "displayName": r["name"],
            "type": _ard_type(r),
            "url": f"{opts.site}agents/{r['slug']}/",
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
            "identifier": opts.registry_urn,
            "displayName": opts.registry_name,
            "type": "application/ai-registry+json",
            "url": opts.site,
            "description": opts.registry_description,
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
