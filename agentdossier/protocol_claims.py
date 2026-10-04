"""Protocol support that is *claimed* rather than observed (FR-18 tier 3 of the protocol axis).

The ARD/A2A/MCP probes only ever report what a publisher exposes at well-known
endpoints on its own domain. Most vendors document protocol support in prose
instead, so two further signals mark a protocol as ``claimed``:

* ``data/curated/protocols.yaml`` — maintainer-entered claims with a link to the
  vendor's documentation (checked by a person, dated);
* the resource's own description, tags and deployment text naming the protocol
  (``mcp-server`` tag on a repository, "Model Context Protocol" in a listing).

A claim never outranks an observation: ``verified`` stays, ``invalid`` and
``not_found`` from a real probe are kept alongside the claim in ``probe``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import protocol_block
from .util import ROOT, domain_of

PROTOCOLS = ("mcp", "a2a", "ard")
_RANK = {"verified": 4, "claimed": 3, "invalid": 2, "not_found": 1, "unknown": 0}
_TEXT_PATTERNS = {
    "mcp": re.compile(r"\bmcp\b|model[\s-]context[\s-]protocol", re.I),
    "a2a": re.compile(r"\ba2a\b|agent2agent|agent-to-agent protocol", re.I),
    "ard": re.compile(r"\bard\b.*(manifest|registry|descriptor)|agentic resource discovery", re.I),
}
_TAG_HINTS = {
    "mcp": ("mcp", "mcp-server", "mcp-servers", "mcp-client", "model-context-protocol"),
    "a2a": ("a2a", "a2a-protocol", "agent2agent"),
}


def load_curated_protocols(path: Path | None = None) -> list[dict[str, Any]]:
    """``data/curated/protocols.yaml`` entries that carry a reviewer and date."""
    path = path or ROOT / "data" / "curated" / "protocols.yaml"
    if not path.exists():
        return []
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    out = []
    for e in doc.get("claims", []) or []:
        if not e.get("checked_on") or not any(e.get(p) for p in PROTOCOLS):
            continue
        if str(e.get("checked_by") or "").strip().lower() in ("", "maintainer", "todo", "tbd", "unknown"):
            # the file's whole point is that a named person looked; a placeholder is not that
            continue
        if not (e.get("name") or e.get("publisher_domain") or e.get("slug")):
            continue
        out.append(e)
    return out


def _entry_matches(entry: dict[str, Any], res: dict[str, Any]) -> bool:
    if entry.get("slug") and entry["slug"] == res.get("slug"):
        return True
    if entry.get("name") and entry["name"].strip().lower() == (res.get("name") or "").strip().lower():
        return True
    dom = (res.get("publisher_domain") or domain_of(res.get("url")) or "").lower().removeprefix("www.")
    if entry.get("publisher_domain") and dom == str(entry["publisher_domain"]).lower().removeprefix("www."):
        if not entry.get("name"):
            return True
    return False


def _claim(res: dict[str, Any], proto: str, block: dict[str, Any]) -> bool:
    current = res["protocols"].get(proto) or protocol_block("unknown")
    if _RANK.get(current.get("status", "unknown"), 0) >= _RANK["claimed"]:
        return False
    if current.get("status") in ("invalid", "not_found"):
        block["probe"] = {
            k: v for k, v in current.items() if k in ("status", "checked_at", "errors", "card_url")
        }
    res["protocols"][proto] = block
    return True


def _self_described(res: dict[str, Any]) -> dict[str, str]:
    """Protocol → the field that names it, from the resource's own text."""
    hits: dict[str, str] = {}
    tags = {str(t).lower() for t in (res.get("tags") or [])}
    for proto, hints in _TAG_HINTS.items():
        if tags & set(hints):
            hits[proto] = "tags"
    for proto, pat in _TEXT_PATTERNS.items():
        if proto in hits:
            continue
        for field in ("description", "deployment", "category"):
            val = res.get(field)
            if isinstance(val, str) and pat.search(val):
                hits[proto] = field
                break
    return hits


def apply_claims(
    resources: list[dict[str, Any]],
    curated: list[dict[str, Any]] | None = None,
    *,
    self_description: bool = True,
) -> dict[str, int]:
    """Mark claimed protocol support on every resource; returns counts per signal."""
    counts = {"curated": 0, "self_description": 0}
    for res in resources:
        res.setdefault("protocols", {p: protocol_block("unknown") for p in PROTOCOLS})
        for entry in curated or []:
            if not _entry_matches(entry, res):
                continue
            for proto in PROTOCOLS:
                claim = entry.get(proto)
                if not claim:
                    continue
                if isinstance(claim, str):
                    claim = {"evidence_url": claim}
                block = protocol_block(
                    "claimed",
                    source="curated_claim",
                    evidence_url=claim.get("evidence_url") or entry.get("evidence_url"),
                    note=claim.get("note") or entry.get("note"),
                    checked_by=entry.get("checked_by", "maintainer"),
                    checked_on=str(entry.get("checked_on")),
                )
                if _claim(res, proto, block):
                    counts["curated"] += 1
        if self_description:
            for proto, field in _self_described(res).items():
                block = protocol_block(
                    "claimed",
                    source="self_description",
                    note=f"named in the resource's own {field}",
                    evidence_url=res.get("url") or (res.get("sources") or [{}])[0].get("url"),
                )
                if _claim(res, proto, block):
                    counts["self_description"] += 1
    return counts
