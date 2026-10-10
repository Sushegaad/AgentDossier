"""FedRAMP Marketplace connector (FR-20). Source: public data.json on GitHub (US Government work).

Each product row names the cloud service provider (``csp``) and the offering
(``cso``), with status (FedRAMP Authorized / Ready / In Process), impact
level, authorization date and assessor. Matches against catalog vendor and
product names produce registry-matched (tier 1) records.
"""

from __future__ import annotations

from typing import Any

from ..connectors.base import ConnectorReport, SnapshotStore, get_json
from ..util import NetPolicy, now_iso
from .matching import Match, match

SOURCE = "fedramp"
DATA_URL = "https://raw.githubusercontent.com/FedRAMP/marketplace-fedramp-gov-data/main/data.json"
MARKETPLACE_URL = "https://marketplace.fedramp.gov/products/"
STATUS_MAP = {
    "FedRAMP Authorized": "active",
    "FedRAMP Ready": "in_process",
    "FedRAMP In Process": "in_process",
    "Agency In Process": "in_process",
}
LEVEL_VARIANT = {
    "low": "FEDRAMP_LOW",
    "moderate": "FEDRAMP_MODERATE",
    "high": "FEDRAMP_HIGH",
    "li-saas": "FEDRAMP_LI_SAAS",
}


def load_products(
    store: SnapshotStore | None, policy: NetPolicy | None = None
) -> tuple[list[dict[str, Any]], str | None, ConnectorReport]:
    report = ConnectorReport(SOURCE)
    data, r, h = get_json(
        store, SOURCE, "data.json", DATA_URL, policy=policy, timeout=60, max_bytes=32_000_000
    )
    report.fetched = 1
    if not isinstance(data, dict):
        report.error(f"{DATA_URL}: {r.error if r else 'no data'}")
        return [], None, report
    products = ((data.get("data") or {}).get("Products")) or []
    report.produced = len(products)
    return products, h, report


def find_matches(
    vendor: str | None, product: str | None, products: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], Match]]:
    """All FedRAMP rows matching a catalog vendor/product, best first."""
    out = []
    for p in products:
        m = match(vendor, product, p.get("csp") or p.get("name"), p.get("cso") or p.get("service_offering"))
        if m.decision != "drop":
            out.append((p, m))
    out.sort(key=lambda t: -t[1].confidence)
    return out


_LEVEL_RANK = {"high": 3, "moderate": 2, "low": 1, "li-saas": 0}


def best_vendor_authorization(
    vendor: str | None, products: list[dict[str, Any]]
) -> tuple[dict[str, Any], Match] | None:
    """The vendor's highest FedRAMP Authorized offering, when the vendor itself is a clear match.

    Used when no offering matches the agent: "Amazon Bedrock Agents" is not on the marketplace,
    but AWS holds authorizations the dossier can show as vendor-level, inherited evidence.
    """
    if not vendor:
        return None
    best: tuple[dict[str, Any], Match] | None = None
    for p in products:
        if p.get("status") != "FedRAMP Authorized":
            continue
        m = match(vendor, None, p.get("csp") or p.get("name"))
        if m.decision != "accept":
            continue
        rank = _LEVEL_RANK.get(str(p.get("impact_level") or "").lower(), -1)
        if best is None or (rank, m.confidence) > (
            _LEVEL_RANK.get(str(best[0].get("impact_level") or "").lower(), -1),
            best[1].confidence,
        ):
            best = (p, m)
    return best


def inherited_record(product: dict[str, Any], m: Match, payload_hash: str | None) -> dict[str, Any]:
    """A vendor-level record: the authorization is real, but it covers another offering."""
    rec = to_record(product, m, payload_hash)
    rec["scope"] = "entity"
    rec["covers_resource"] = "inherited"
    rec["review_reason"] = f"vendor authorization for {product.get('cso') or 'another offering'}; {m.reason}"
    return rec


def to_record(product: dict[str, Any], m: Match, payload_hash: str | None) -> dict[str, Any]:
    level = str(product.get("impact_level") or "").lower()
    variant = LEVEL_VARIANT.get(level) or ("FEDRAMP_20X" if "20x" in level else None)
    status = STATUS_MAP.get(product.get("status") or "", "unknown")
    auth_date = (
        (product.get("auth_date") or "")[:10]
        if product.get("auth_date") and product.get("auth_date") != "Not Active"
        else None
    )
    return {
        "framework": "fedramp",
        "variant": variant,
        "status": status if status != "unknown" else "in_process",
        "tier": 1,
        "scope": "product",
        "covers_resource": "yes" if m.product_score and m.product_score >= 0.9 else "partial",
        "issuer": (product.get("auth_type") or "")
        + (f" / 3PAO {product['independent_assessor']}" if product.get("independent_assessor") else ""),
        "certificate_id": product.get("id"),
        "issued": auth_date,
        "valid_until": None,
        "period_end": None,
        "evidence_url": f"{MARKETPLACE_URL}{product.get('id')}",
        "source": SOURCE,
        "retrieved_at": now_iso(),
        "payload_hash": payload_hash,
        "match_confidence": m.confidence,
        "reviewer": None,
        "review_reason": m.reason,
        "next_check": None,
        "display": "",
        "detail": {
            "csp": product.get("csp"),
            "cso": product.get("cso"),
            "impact_level": product.get("impact_level"),
            "fedramp_status": product.get("status"),
            "deployment_model": product.get("deployment_model"),
        },
    }
