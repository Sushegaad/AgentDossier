"""Official MCP Registry connector (FR-01, FR-04): ``GET /v0/servers``.

Cursor-paginated; ``version=latest`` returns one record per server. Each
record becomes an ``mcp_server`` resource with protocol status ``claimed``
(the registry lists it; the handshake, when enabled, upgrades it to
``verified``).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..standards import mcp
from ..util import NetPolicy
from .base import ConnectorReport, SnapshotStore, get_json

API = "https://registry.modelcontextprotocol.io/v0/servers"
SOURCE = "mcp_registry"


def record_to_resource(record: dict[str, Any], payload_hash: str | None = None) -> dict[str, Any] | None:
    server = record.get("server") or record
    meta = (record.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
    if meta.get("status") not in (None, "active"):
        return None
    name = server.get("name")
    if not name:
        return None
    res = mcp.card_to_resource(server, f"{API}?search={quote(name)}", source_system=SOURCE)
    publisher_ns = name.split("/")[0]  # reverse-DNS namespace, e.g. io.github.owner or com.vendor
    parts = publisher_ns.split(".")
    if parts[:2] == ["io", "github"] and len(parts) >= 3:
        res["vendor"] = parts[2]
        res["external_ids"]["github_owner"] = parts[2]
    else:
        res["vendor"] = ".".join(reversed(parts)) if len(parts) > 1 else publisher_ns
    res["signals"] = {
        "mcp_registry_status": meta.get("status"),
        "mcp_registry_published_at": meta.get("publishedAt"),
        "mcp_registry_updated_at": meta.get("updatedAt"),
        "mcp_transports": sorted(
            {r.get("type") for r in server.get("remotes") or [] if isinstance(r, dict) and r.get("type")}
        ),
        "mcp_packages": len(server.get("packages") or []),
    }
    repo = (server.get("repository") or {}).get("url") if isinstance(server.get("repository"), dict) else None
    if repo and "github.com/" in repo:
        full = repo.split("github.com/", 1)[1].strip("/").removesuffix(".git")
        if full.count("/") == 1:
            res["external_ids"]["github"] = full
    if payload_hash:
        res["sources"][0]["payload_hash"] = payload_hash
    return res


def run(
    *, store: SnapshotStore | None, max_pages: int = 200, policy: NetPolicy | None = None
) -> tuple[list[dict[str, Any]], ConnectorReport]:
    report = ConnectorReport(SOURCE)
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for page in range(max_pages):
        url = f"{API}?limit=100&version=latest" + (f"&cursor={quote(cursor)}" if cursor else "")
        data, r, h = get_json(store, SOURCE, f"page:{page}", url, policy=policy)
        report.fetched += 1
        if not isinstance(data, dict):
            report.error(f"{url}: {r.error if r else 'no data'}")
            break
        for rec in data.get("servers") or []:
            res = record_to_resource(rec, h)
            if res:
                out.append(res)
            else:
                report.skipped += 1
        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break
    report.produced = len(out)
    return out, report
