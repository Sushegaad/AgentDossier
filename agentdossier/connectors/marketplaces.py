"""Curated marketplace records (FR-01, source register: access = manual).

AWS Marketplace, Microsoft Agent Store and Google Cloud Marketplace do not
offer open listing APIs and their terms may restrict automated collection,
so listings are maintainer-entered records in ``data/curated/marketplaces.json``
with the listing URL as evidence. The seed workbook's Source Catalog already
names the AWS listings it drew on; those seed the file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import add_source, new_resource
from ..util import ROOT
from .base import ConnectorReport

SOURCE = "marketplaces"
CURATED = ROOT / "data" / "curated" / "marketplaces.json"
MARKETPLACE_HOSTS = {
    "aws.amazon.com/marketplace": "aws_marketplace",
    "azuremarketplace.microsoft.com": "microsoft_agent_store",
    "appsource.microsoft.com": "microsoft_agent_store",
    "console.cloud.google.com/marketplace": "google_cloud_marketplace",
    "cloud.google.com/marketplace": "google_cloud_marketplace",
}


def marketplace_for(url: str | None) -> str | None:
    if not url:
        return None
    u = url.lower().replace("https://", "").replace("http://", "").replace("www.", "")
    for prefix, name in MARKETPLACE_HOSTS.items():
        if u.startswith(prefix):
            return name
    return None


def load_curated(path: Path = CURATED) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return list(json.loads(path.read_text()).get("listings", []))


def listing_to_resource(listing: dict[str, Any]) -> dict[str, Any]:
    market = listing.get("marketplace") or marketplace_for(listing["url"]) or "marketplace"
    res = new_resource(
        name=listing["product"],
        source_system=market,
        source_url=listing["url"],
        vendor=listing.get("vendor"),
        url=listing.get("product_url") or listing["url"],
        resource_type=listing.get("resource_type", "agent"),
        category=listing.get("category") or "Marketplace listing",
        description=listing.get("description"),
        external_ids={market: listing["url"]},
        raw=listing,
        key=f"{market}:{listing['url'].lower()}",
    )
    res["commercial"] = True
    res["deployment"] = listing.get("deployment") or "marketplace"
    res["signals"] = {
        "marketplace": market,
        "marketplace_listing_url": listing["url"],
        "marketplace_compliance_fields": listing.get("compliance_fields") or [],
        "curated_by": listing.get("curated_by", "maintainer"),
        "curated_on": listing.get("curated_on"),
    }
    if listing.get("domains"):
        res["signals"]["curated_domains"] = listing["domains"]
    return res


def run(path: Path = CURATED) -> tuple[list[dict[str, Any]], ConnectorReport]:
    report = ConnectorReport(SOURCE)
    out = []
    for listing in load_curated(path):
        if not listing.get("url") or not listing.get("product"):
            report.skipped += 1
            continue
        out.append(listing_to_resource(listing))
    report.fetched = 1 if path.exists() else 0
    report.produced = len(out)
    return out, report


def attach_listing(res: dict[str, Any], listing_url: str, market: str) -> None:
    """Record a marketplace listing on an existing resource (identity evidence, tier 2)."""
    res["external_ids"][market] = listing_url
    res.setdefault("signals", {})["marketplace_listing_url"] = listing_url
    add_source(res, market, listing_url)
