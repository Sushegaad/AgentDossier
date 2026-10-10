"""Agentic Resource Discovery (ARD) v0.91 adapter.

Implements consumer resolution (§5.1): MUST fetch /.well-known/ard.json and
MUST honour <link rel="ard">. Also reads in-page JSON-LD entries, robots.txt
`Agentmap:` directives and (optionally) the predecessor ai-catalog.json path.
Validation follows Appendix D.2 (representativeQueries is a warning, not error).
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from ..models import new_resource, protocol_block
from ..util import NetPolicy, fetch, now_iso, sha256

PARSER_VERSION = "ard-0.91"
BASE_CONTEXT = "https://agenticresourcediscovery.org/context/v1"
URN_RE = re.compile(
    r"^urn:air:(?P<publisher>[a-z0-9.-]+\.[a-z]{2,}|localhost|[a-z0-9-]+):(?P<ns>[^:]+)(?::(?P<name>.+))?$",
    re.I,
)

TYPE_TO_RESOURCE = {
    "application/a2a-agent-card+json": "a2a_agent",
    "application/mcp-server-card+json": "mcp_server",
    "application/ai-skill+md": "skill",
    "application/ai-registry+json": "registry",
    "application/openapi+json": "api",
    "application/vnd.oai.openapi+json": "api",
}


def parse_urn(identifier: str) -> dict | None:
    m = URN_RE.match(identifier or "")
    if not m:
        return None
    return {
        "publisher": m.group("publisher").lower(),
        "namespace": m.group("ns"),
        "name": m.group("name") or m.group("ns"),
    }


def validate_entry(entry: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if not isinstance(entry, dict):
        return ["entry is not an object"], []
    for term in ("identifier", "displayName", "type"):
        if not entry.get(term):
            errors.append(f"missing required term '{term}'")
    has_url, has_data = "url" in entry, "data" in entry
    if has_url == has_data:
        errors.append("exactly one of 'url' or 'data' is required (value-or-reference, §4.3)")
    ident = entry.get("identifier")
    urn = parse_urn(ident) if ident else None
    if ident and not urn:
        errors.append(f"identifier is not a urn:air:<publisher>:<namespace>:<name> URN: {ident}")
    rq = entry.get("representativeQueries")
    if not isinstance(rq, list) or not (2 <= len(rq) <= 5):
        warnings.append(
            "representativeQueries should contain 2-5 examples (entry will be hard to find by search)"
        )
    tm = entry.get("trustManifest")
    if tm is not None:
        identity = (tm or {}).get("identity") if isinstance(tm, dict) else None
        if not identity:
            errors.append("trustManifest present without trustManifest.identity (§4.5)")
        elif urn and not publisher_binding_ok(urn["publisher"], identity):
            errors.append(
                f"publisher authority binding failed: identity does not align with {urn['publisher']} (§4.5.1)"
            )
    return errors, warnings


def publisher_binding_ok(publisher: str, identity) -> bool:
    """Structural check of §4.5.1. Cryptographic verification is delegated to the
    declared trust framework and is recorded separately (never assumed)."""
    text = json.dumps(identity) if not isinstance(identity, str) else identity
    text = text.lower()
    return publisher.lower() in text


def validate_manifest(doc) -> dict:
    report: dict[str, Any] = {"errors": [], "warnings": [], "entries": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), list):
        report["errors"].append("manifest must be an object with an 'entries' array (ardManifest)")
        return report
    for i, entry in enumerate(doc["entries"]):
        errs, warns = validate_entry(entry)
        report["entries"].append(
            {"index": i, "identifier": (entry or {}).get("identifier"), "errors": errs, "warnings": warns}
        )
        report["errors"] += [f"entries[{i}]: {e}" for e in errs]
        report["warnings"] += [f"entries[{i}]: {w}" for w in warns]
    return report


_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'(\w[\w-]*)\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))')
_JSONLD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def _attrs(tag: str) -> dict:
    return {
        m.group(1).lower(): (m.group(3) or m.group(4) or m.group(5) or "") for m in _ATTR_RE.finditer(tag)
    }


def find_link_rel(html: str, base_url: str, rels=("ard",)) -> list[str]:
    out = []
    for tag in _LINK_RE.findall(html or ""):
        a = _attrs(tag)
        if a.get("rel", "").lower() in rels and a.get("href"):
            out.append(urllib.parse.urljoin(base_url, a["href"]))
    return out


def find_inpage_entries(html: str) -> list[dict]:
    entries = []
    for block in _JSONLD_RE.findall(html or ""):
        try:
            doc = json.loads(block)
        except ValueError:
            continue
        nodes = doc if isinstance(doc, list) else doc.get("@graph", [doc]) if isinstance(doc, dict) else []
        for node in nodes:
            if isinstance(node, dict) and str(node.get("identifier", "")).startswith("urn:air:"):
                entries.append(node)
    return entries


def find_agentmap(robots_txt: str, base_url: str) -> list[str]:
    return [
        urllib.parse.urljoin(base_url, m.strip())
        for m in re.findall(r"(?im)^\s*agentmap\s*:\s*(\S+)", robots_txt or "")
    ]


def resolve(
    origin: str,
    *,
    policy: NetPolicy | None = None,
    consult_legacy: bool = True,
    headers: dict | None = None,
    timeout: float = 8.0,
    scan_homepage: bool = True,
) -> dict:
    """Resolve ARD entries for an origin (scheme://host[:port]). Returns a report dict."""
    origin = origin.rstrip("/")
    report: dict[str, Any] = {
        "origin": origin,
        "parser_version": PARSER_VERSION,
        "checked_at": now_iso(),
        "status": "not_found",
        "sources": [],
        "entries": [],
        "errors": [],
        "warnings": [],
    }

    def _ingest_manifest(url: str, via: str) -> bool:
        r = fetch(url, policy=policy, headers=headers, timeout=timeout, retries=0)
        if not r.ok or r.is_html:  # an HTML answer is the site's soft 404, not a manifest
            return False
        try:
            doc = r.json()
        except ValueError:
            report["errors"].append(f"{url}: not valid JSON")
            report["status"] = "invalid"
            return False
        v = validate_manifest(doc)
        report["sources"].append({"url": r.url, "via": via, "hash": sha256(r.body)})
        report["errors"] += v["errors"]
        report["warnings"] += v["warnings"]
        for entry in doc.get("entries", []) if isinstance(doc, dict) else []:
            if isinstance(entry, dict):
                report["entries"].append({"entry": entry, "manifest": r.url})
        return True

    found = _ingest_manifest(f"{origin}/.well-known/ard.json", "well-known")
    if scan_homepage:
        home = fetch(origin + "/", policy=policy, headers=headers, timeout=timeout, retries=0)
        if home.ok and "html" in home.headers.get("Content-Type", home.headers.get("content-type", "")):
            for href in find_link_rel(home.text, home.url, ("ard",)):
                found = _ingest_manifest(href, "link-rel") or found
            for e in find_inpage_entries(home.text):
                report["entries"].append({"entry": e, "manifest": home.url + "#jsonld"})
                report["sources"].append(
                    {"url": home.url, "via": "in-page-jsonld", "hash": sha256(json.dumps(e))}
                )
                found = True
        robots = fetch(origin + "/robots.txt", policy=policy, headers=headers, timeout=timeout, retries=0)
        if robots.ok:
            for href in find_agentmap(robots.text, origin + "/"):
                found = _ingest_manifest(href, "agentmap") or found
    if not found and consult_legacy:
        if _ingest_manifest(f"{origin}/.well-known/ai-catalog.json", "legacy-ai-catalog"):
            report["warnings"].append(
                "resolved via predecessor path /.well-known/ai-catalog.json; publisher should move to ard.json"
            )
            found = True
    if found and report["status"] != "invalid":
        report["status"] = "verified" if not report["errors"] else "invalid"
    return report


def entry_to_resource(
    entry: dict, manifest_url: str, *, scope: str = "public", tenant: str | None = None
) -> dict:
    urn = parse_urn(entry.get("identifier", "")) or {}
    rtype = TYPE_TO_RESOURCE.get(entry.get("type", ""), "agent")
    errs, warns = validate_entry(entry)
    url = entry.get("url") if isinstance(entry.get("url"), str) else manifest_url
    res = new_resource(
        name=entry.get("displayName") or urn.get("name") or entry.get("identifier", "unnamed"),
        source_system="ard",
        source_url=manifest_url,
        vendor=urn.get("publisher"),
        url=url,
        resource_type=rtype,
        description=entry.get("description"),
        scope=scope,
        tenant=tenant,
        external_ids={"ard": entry.get("identifier")},
        raw=entry,
        key=entry.get("identifier"),
    )
    res["publisher_domain"] = urn.get("publisher") or res["publisher_domain"]
    res["tags"] = list(entry.get("tags") or [])
    res["capabilities"] = list(entry.get("capabilities") or [])
    res["representative_queries"] = list(entry.get("representativeQueries") or [])
    tm = entry.get("trustManifest")
    res["protocols"]["ard"] = protocol_block(
        "verified" if not errs else "invalid",
        manifest_url=manifest_url,
        identifier=entry.get("identifier"),
        media_type=entry.get("type"),
        errors=errs or None,
        warnings=warns or None,
        parser_version=PARSER_VERSION,
        trust_manifest=(
            "present-binding-ok" if tm and not errs else "present-unverified" if tm else "absent"
        ),
    )
    if rtype == "a2a_agent":
        res["protocols"]["a2a"] = protocol_block("claimed", card_url=entry.get("url"), via="ard-entry")
    if rtype == "mcp_server":
        res["protocols"]["mcp"] = protocol_block("claimed", server_card_url=entry.get("url"), via="ard-entry")
    res["raw"] = {"ard_entry": entry}
    return res
