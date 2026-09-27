"""Canonical Resource model (BRD §3 data model).

Resources are plain dicts so they serialize cleanly to JSON and can carry raw
protocol payloads forward across parser versions. `new_resource` guarantees
the canonical shape; `schema/resource.schema.json` documents it.
"""

from __future__ import annotations

from .util import canonical_url, domain_of, now_iso, sha256, slug

PROTOCOL_STATES = ("verified", "claimed", "not_found", "unknown", "invalid")


def resource_id(key: str) -> str:
    return "res_" + sha256(key)[:16]


def protocol_block(state: str = "unknown", **extra) -> dict:
    assert state in PROTOCOL_STATES, state
    block = {"status": state}
    block.update({k: v for k, v in extra.items() if v is not None})
    return block


def new_resource(
    *,
    name: str,
    source_system: str,
    source_url: str | None = None,
    vendor: str | None = None,
    url: str | None = None,
    resource_type: str = "agent",
    category: str | None = None,
    description: str | None = None,
    scope: str = "public",
    tenant: str | None = None,
    external_ids: dict | None = None,
    raw: dict | str | None = None,
    key: str | None = None,
) -> dict:
    canon = canonical_url(url)
    ident_key = key or canon or f"{slug(vendor or '')}:{slug(name)}"
    retrieved = now_iso()
    return {
        "id": resource_id(f"{scope}:{tenant or ''}:{ident_key}"),
        "name": name.strip(),
        "vendor": (vendor or "").strip() or None,
        "publisher_domain": domain_of(url),
        "canonical_url": canon,
        "url": url,
        "resource_type": resource_type,
        "category": category,
        "description": description,
        "scope": scope,  # public | private
        "tenant": tenant,  # set for private/enterprise records
        "deployment": None,
        "license": None,
        "commercial": None,
        "tags": [],
        "external_ids": external_ids or {},
        "protocols": {
            "a2a": protocol_block(),
            "mcp": protocol_block(),
            "ard": protocol_block(),
        },
        "signals": {},
        "governance": {"claims": [], "evidence_urls": [], "certification_disclaimer": True},
        "domains": {},
        "sources": [
            {
                "system": source_system,
                "url": source_url or url,
                "retrieved_at": retrieved,
                "payload_hash": sha256(str(raw)) if raw is not None else None,
            }
        ],
        "first_seen": retrieved,
        "last_seen": retrieved,
    }


def add_source(res: dict, system: str, url: str | None, raw=None) -> None:
    res["sources"].append(
        {
            "system": system,
            "url": url,
            "retrieved_at": now_iso(),
            "payload_hash": sha256(str(raw)) if raw is not None else None,
        }
    )
    res["last_seen"] = now_iso()
