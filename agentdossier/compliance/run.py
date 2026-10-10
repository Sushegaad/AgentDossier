"""Compliance stage orchestration: registries, curated records and vendor claims per resource."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..connectors.base import ConnectorReport, SnapshotStore
from ..dedup import ReviewCandidate
from ..util import NetPolicy, domain_of
from . import claims, csa_star, curated, fedramp
from .engine import finalize
from .matching import AUTO_ACCEPT

# Hosts whose pages say nothing about the publisher of a listing hosted there: a repository's
# owner is not GitHub, a marketplace seller is not AWS. Rows on these hosts are crawled under
# their vendor's own domain when trust_pages.yaml knows it, and otherwise not at all.
SHARED_HOSTS = ("github.com", "huggingface.co", "aws.amazon.com", "azuremarketplace.microsoft.com")


def claim_domain(res: dict[str, Any], trust_pages: claims.TrustPages) -> str | None:
    """Domain whose trust pages speak for this resource's publisher, or None to skip the crawl.

    A row hosted on a shared host (a GitHub repository, an AWS Marketplace listing) is crawled
    under its vendor's domain when the vendor is known (``vendors:`` in trust_pages.yaml).
    """
    d = res.get("publisher_domain") or domain_of(res.get("url"))
    if not d:
        return None
    d = d.lower().removeprefix("www.")
    if d in SHARED_HOSTS:
        return trust_pages.domain_for_vendor(res.get("vendor"))
    return d


def run(
    resources: list[dict[str, Any]],
    *,
    store: SnapshotStore | None,
    policy: NetPolicy | None = None,
    crawl_claims: bool = True,
    claim_domain_limit: int | None = None,
    concurrency: int = 6,
    deadline: Any = None,
) -> tuple[dict[str, dict[str, Any]], list[ReviewCandidate]]:
    reports: dict[str, dict[str, Any]] = {}
    review: list[ReviewCandidate] = []

    # 1. FedRAMP (registry, tier 1)
    products, fr_hash, fr_report = fedramp.load_products(store, policy)
    fr_matched = fr_inherited = 0
    for res in resources:
        if not products or not (res.get("vendor") or res.get("name")):
            continue
        accepted = 0
        for product, m in fedramp.find_matches(res.get("vendor"), res.get("name"), products)[:3]:
            rec = fedramp.to_record(product, m, fr_hash)
            if m.decision == "accept":
                res.setdefault("compliance_raw", []).append(rec)
                fr_matched += 1
                accepted += 1
            else:
                review.append(
                    ReviewCandidate(
                        res["id"],
                        res["name"],
                        f"fedramp:{product.get('id')}",
                        f"{product.get('csp')} / {product.get('cso')}",
                        m.confidence,
                        f"fedramp {m.reason}",
                    )
                )
        if not accepted:
            best = fedramp.best_vendor_authorization(res.get("vendor"), products)
            if best:
                res.setdefault("compliance_raw", []).append(fedramp.inherited_record(*best, fr_hash))
                fr_inherited += 1
    fr_report.produced = fr_matched
    reports["fedramp"] = {**fr_report.as_dict(), "inherited": fr_inherited}

    # 2. CSA STAR presence (registry, tier 1, entity level)
    index, csa_hash, csa_report = csa_star.load_index(store, policy)
    csa_matched = 0
    if index:
        for res in resources:
            found = csa_star.find_match(res.get("vendor"), index)
            if not found:
                continue
            lst, m = found
            if m.confidence >= AUTO_ACCEPT:
                res.setdefault("compliance_raw", []).extend(csa_star.to_records(lst, m, csa_hash))
                csa_matched += 1
            else:
                review.append(
                    ReviewCandidate(
                        res["id"],
                        res["name"],
                        f"csa_star:{lst.slug}",
                        lst.name,
                        m.confidence,
                        f"csa_star {m.reason}",
                    )
                )
    csa_report.produced = csa_matched
    reports["csa_star"] = csa_report.as_dict()

    # 3. Curated records (maintainer-verified)
    entries = curated.load()
    cur_report = ConnectorReport("curated")
    for res in resources:
        recs = curated.records_for(res, entries)
        if recs:
            res.setdefault("compliance_raw", []).extend(recs)
            cur_report.produced += len(recs)
    cur_report.fetched = 1 if entries else 0
    reports["curated"] = cur_report.as_dict()

    # 4. Vendor claims (tier 4) from trust/security pages
    cl_report = ConnectorReport(claims.SOURCE)
    if crawl_claims:
        trust_pages = claims.load_trust_pages()
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for res in resources:
            d = claim_domain(res, trust_pages)
            if d:
                by_domain.setdefault(d, []).append(res)
        domains = sorted(by_domain)[:claim_domain_limit] if claim_domain_limit else sorted(by_domain)

        def work(domain: str) -> tuple[str, dict[str, Any] | None]:
            if deadline is not None and deadline.expired():
                cl_report.skipped += 1
                return domain, None
            try:
                return domain, claims.crawl_domain(domain, pages=trust_pages.pages_for(domain), policy=policy)
            except Exception as exc:  # noqa: BLE001
                cl_report.error(f"{domain}: {type(exc).__name__}: {exc}")
                return domain, None

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for i, (domain, crawl) in enumerate(pool.map(work, domains), 1):
                if i % 25 == 0 and deadline is not None:
                    deadline.log("vendor_claims", f"{i}/{len(domains)} domains")
                if not crawl:
                    continue
                cl_report.fetched += 1
                if store:
                    import json

                    store.save(claims.SOURCE, domain, json.dumps(crawl, sort_keys=True).encode())
                recs = claims.to_records(crawl)
                for res in by_domain[domain]:
                    res.setdefault("compliance_raw", []).extend(recs)
                cl_report.produced += len(recs)
    reports["vendor_claims"] = cl_report.as_dict()

    # 5. Finalize per resource: dedupe, freshness, wording, credit
    for res in resources:
        raw = res.pop("compliance_raw", [])
        res["compliance"] = finalize(raw, int(res.get("identity", {}).get("tier", 5)))
    return reports, review
