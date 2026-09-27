"""Maintainer-entered compliance records (FR-20, FR-26; source register: manual).

``data/curated/compliance.yaml`` holds records the maintainer verified by
hand on a registry page or document, for sources that are not fetched
automatically yet (EU-U.S. Data Privacy Framework list, IAF CertSearch,
CSA STAR entry details, HITRUST letters). Every record needs an evidence
URL and a checked-on date; the tier is set by what was checked:

* ``registry``  -> tier 1 (looked up on the issuing registry)
* ``document``  -> tier 3 (certificate, letter or AOC reviewed)
* ``vendor``    -> tier 4 (claim on a vendor page)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import ROOT, now_iso

CURATED = ROOT / "data" / "curated" / "compliance.yaml"
KIND_TIER = {"registry": 1, "marketplace": 2, "document": 3, "vendor": 4}


def load(path: Path = CURATED) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    return list(doc.get("records", []))


def to_record(entry: dict[str, Any]) -> dict[str, Any]:
    kind = entry.get("checked", "vendor")
    return {
        "framework": entry["framework"],
        "variant": entry.get("variant"),
        "status": entry.get("status", "active"),
        "tier": KIND_TIER.get(kind, 4),
        "scope": entry.get("scope", "entity"),
        "covers_resource": entry.get("covers_resource", "unknown"),
        "issuer": entry.get("issuer"),
        "certificate_id": entry.get("certificate_id"),
        "issued": entry.get("issued"),
        "valid_until": entry.get("valid_until"),
        "period_end": entry.get("period_end"),
        "evidence_url": entry["evidence_url"],
        "source": entry.get("source", "curated"),
        "retrieved_at": f"{entry['checked_on']}T00:00:00Z" if entry.get("checked_on") else now_iso(),
        "payload_hash": None,
        "match_confidence": 1.0,
        "reviewer": entry.get("checked_by", "maintainer"),
        "review_reason": entry.get("note"),
        "next_check": entry.get("next_check"),
        "display": "",
        "detail": {"curated": True},
    }


def records_for(resource: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Curated entries apply by resource id, slug or exact vendor name."""
    out = []
    for e in entries:
        if (
            e.get("resource_id") == resource["id"]
            or e.get("slug") == resource.get("slug")
            or (
                e.get("vendor")
                and resource.get("vendor")
                and e["vendor"].lower() == resource["vendor"].lower()
            )
        ):
            if e.get("framework") and e.get("evidence_url"):
                out.append(to_record(e))
    return out
