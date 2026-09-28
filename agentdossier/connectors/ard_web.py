"""ARD web ingestion (FR-02) and standards inspection over publisher domains.

For every publisher domain in the catalog (and the extra domains listed in
``config/sources.json``), resolve ARD entries, fetch the A2A Agent Card and
the MCP server card. Results attach protocol status to existing resources
and create new resources for ARD entries that are not yet known.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..models import protocol_block
from ..standards import a2a, ard, mcp
from ..util import NetPolicy, domain_of
from .base import ConnectorReport, SnapshotStore

SOURCE = "ard_web"


def inspect_origin(
    origin: str, *, policy: NetPolicy | None = None, timeout: float = 8.0, mcp_handshake: bool = False
) -> dict[str, Any]:
    """Run the three standards checks against one origin. Metadata only."""
    ard_report = ard.resolve(origin, policy=policy, timeout=timeout)
    a2a_report = a2a.fetch_card(origin, policy=policy, timeout=timeout)
    mcp_report = mcp.fetch_card(origin, policy=policy, timeout=timeout)
    result: dict[str, Any] = {"origin": origin, "ard": ard_report, "a2a": a2a_report, "mcp": mcp_report}
    if mcp_handshake and mcp_report.get("summary") and mcp_report["summary"].get("remotes"):
        result["mcp_handshake"] = mcp.handshake(
            mcp_report["summary"]["remotes"][0]["url"], policy=policy, timeout=timeout
        )
    return result


def apply_to_resource(res: dict[str, Any], inspection: dict[str, Any]) -> None:
    """Write protocol status from an origin inspection onto a resource (best status wins)."""
    rank = {"verified": 4, "claimed": 3, "invalid": 2, "not_found": 1, "unknown": 0}

    def better(current: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
        return (
            new
            if rank.get(new.get("status", "unknown"), 0) > rank.get(current.get("status", "unknown"), 0)
            else current
        )

    a = inspection["ard"]
    ard_block = protocol_block(
        a["status"] if a["status"] in ("verified", "invalid", "not_found", "unknown") else "unknown",
        sources=[s["url"] for s in a.get("sources", [])] or None,
        entries=len(a.get("entries", [])) or None,
        errors=a.get("errors") or None,
        parser_version=ard.PARSER_VERSION,
        checked_at=a["checked_at"],
    )
    res["protocols"]["ard"] = better(res["protocols"]["ard"], ard_block)

    c = inspection["a2a"]
    s = c.get("summary") or {}
    a2a_block = protocol_block(
        c["status"],
        card_url=c.get("card_url"),
        version=s.get("version"),
        protocol_version=s.get("protocol_version"),
        signed=s.get("signed"),
        skills=[k.get("name") for k in s.get("skills", [])] or None,
        auth_schemes=s.get("auth_schemes") or None,
        errors=c.get("errors") or None,
        parser_version=a2a.PARSER_VERSION,
        checked_at=c["checked_at"],
    )
    res["protocols"]["a2a"] = better(res["protocols"]["a2a"], a2a_block)

    m = inspection["mcp"]
    ms = m.get("summary") or {}
    mcp_block = protocol_block(
        m["status"],
        card_url=m.get("card_url"),
        remotes=ms.get("remotes") or None,
        tools=ms.get("tools") or None,
        parser_version=mcp.PARSER_VERSION,
        checked_at=m["checked_at"],
    )
    hs = inspection.get("mcp_handshake")
    if hs and hs.get("status") == "verified":
        mcp_block = protocol_block(
            "verified",
            endpoint=hs["endpoint"],
            protocol_version=hs.get("protocol_version"),
            server_info=hs.get("server_info"),
            tools=[t["name"] for t in hs.get("tools", [])] or None,
            resources=[t["name"] for t in hs.get("resources", [])] or None,
            prompts=[t["name"] for t in hs.get("prompts", [])] or None,
            methods_sent=hs.get("methods_sent"),
            parser_version=mcp.PARSER_VERSION,
            checked_at=hs["checked_at"],
        )
    res["protocols"]["mcp"] = better(res["protocols"]["mcp"], mcp_block)


def run(
    resources: list[dict[str, Any]],
    *,
    extra_domains: list[str] | None = None,
    store: SnapshotStore | None = None,
    policy: NetPolicy | None = None,
    concurrency: int = 8,
    limit: int | None = None,
    mcp_handshake: bool = False,
    deadline: Any = None,
) -> tuple[list[dict[str, Any]], ConnectorReport]:
    """Inspect every distinct publisher domain; returns new resources from ARD entries."""
    report = ConnectorReport(SOURCE)
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for res in resources:
        d = res.get("publisher_domain") or domain_of(res.get("url"))
        if d and d not in ("github.com", "huggingface.co", "pypi.org", "npmjs.com"):
            by_domain.setdefault(d, []).append(res)
    for d in extra_domains or []:
        by_domain.setdefault(d, [])
    domains = sorted(by_domain)[:limit] if limit else sorted(by_domain)

    def work(domain: str) -> tuple[str, dict[str, Any] | None]:
        if deadline is not None and deadline.expired():
            report.skipped += 1
            return domain, None
        try:
            return domain, inspect_origin(f"https://{domain}", policy=policy, mcp_handshake=mcp_handshake)
        except Exception as exc:  # noqa: BLE001 - one bad host must not stop the run
            report.error(f"{domain}: {type(exc).__name__}: {exc}")
            return domain, None

    new_resources: list[dict[str, Any]] = []
    known_ids = {r.get("external_ids", {}).get("ard") for r in resources}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for i, (domain, inspection) in enumerate(pool.map(work, domains), 1):
            if i % 50 == 0 and deadline is not None:
                deadline.log("ard_web", f"{i}/{len(domains)} origins")
            if inspection is None:
                continue
            report.fetched += 1
            if store:
                import json

                store.save(SOURCE, domain, json.dumps(inspection, sort_keys=True, default=str).encode())
            for res in by_domain.get(domain, []):
                apply_to_resource(res, inspection)
            for item in inspection["ard"].get("entries", []):
                entry = item["entry"]
                if entry.get("identifier") in known_ids:
                    continue
                new_resources.append(ard.entry_to_resource(entry, item["manifest"]))
                known_ids.add(entry.get("identifier"))
    report.produced = len(new_resources)
    return new_resources, report
