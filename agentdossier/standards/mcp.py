"""Model Context Protocol adapter (FR-04), protocol revision 2025-06-18.

Two levels of inspection, both metadata-only:

* **Server card** (claimed): a description of an MCP server found in an ARD
  entry of type ``application/mcp-server-card+json``, at the community
  well-known path ``/.well-known/mcp.json``, or as a record in the official
  MCP Registry. Nothing is executed.
* **Handshake** (verified, opt-in): a Streamable HTTP session limited to
  ``initialize``, ``notifications/initialized``, ``tools/list``,
  ``resources/list`` and ``prompts/list``, then ``DELETE`` to end the session.
  ``tools/call`` and every other method are never sent.

Every result carries ``PARSER_VERSION`` and a hash of the raw payload.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import new_resource, protocol_block
from ..util import NetPolicy, fetch, now_iso, sha256

PARSER_VERSION = "mcp-2025-06-18"
PROTOCOL_VERSION = "2025-06-18"
WELL_KNOWN_CARD = "/.well-known/mcp.json"
LIST_METHODS = ("tools/list", "resources/list", "prompts/list")
FORBIDDEN_METHODS = frozenset(
    {
        "tools/call",
        "resources/read",
        "resources/subscribe",
        "prompts/get",
        "completion/complete",
        "sampling/createMessage",
    }
)


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Return the JSON payloads of ``data:`` lines in a Server-Sent Events body."""
    out: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data_lines = [ln[5:].lstrip() for ln in block.split("\n") if ln.startswith("data:")]
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except ValueError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def parse_rpc_response(content_type: str, body: str, expect_id: Any) -> dict[str, Any] | None:
    """Pick the JSON-RPC response with ``expect_id`` from a JSON or SSE body."""
    if "text/event-stream" in (content_type or ""):
        for msg in parse_sse(body):
            if msg.get("id") == expect_id:
                return msg
        return None
    try:
        msg = json.loads(body)
    except ValueError:
        return None
    if isinstance(msg, list):
        for m in msg:
            if isinstance(m, dict) and m.get("id") == expect_id:
                return m
        return None
    return msg if isinstance(msg, dict) else None


def validate_card(card: Any) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if not isinstance(card, dict):
        return ["server card is not a JSON object"], []
    if not card.get("name"):
        errors.append("missing 'name'")
    if not (card.get("url") or card.get("endpoint") or card.get("remotes") or card.get("packages")):
        errors.append("missing transport: expected 'url', 'endpoint', 'remotes' or 'packages'")
    if not card.get("description"):
        warnings.append("missing 'description'")
    if not card.get("version"):
        warnings.append("missing 'version'")
    return errors, warnings


def summarize_card(card: dict[str, Any]) -> dict[str, Any]:
    remotes = []
    for r in card.get("remotes") or []:
        if isinstance(r, dict) and r.get("url"):
            remotes.append({"type": r.get("type"), "url": r["url"]})
    url = card.get("url") or card.get("endpoint")
    if url and not remotes:
        remotes.append({"type": card.get("transport", "streamable-http"), "url": url})
    packages = []
    for p in card.get("packages") or []:
        if isinstance(p, dict):
            packages.append(
                {
                    "registry": p.get("registryType") or p.get("registry_name"),
                    "identifier": p.get("identifier") or p.get("name"),
                    "version": p.get("version"),
                    "transport": (p.get("transport") or {}).get("type")
                    if isinstance(p.get("transport"), dict)
                    else None,
                }
            )
    return {
        "name": card.get("name"),
        "title": card.get("title"),
        "version": card.get("version"),
        "remotes": remotes,
        "packages": packages,
        "repository": (card.get("repository") or {}).get("url")
        if isinstance(card.get("repository"), dict)
        else None,
        "website": card.get("websiteUrl") or card.get("homepage"),
        "tools": [t.get("name") for t in card.get("tools") or [] if isinstance(t, dict) and t.get("name")],
    }


def _rpc(
    endpoint: str,
    method: str,
    params: dict[str, Any] | None,
    rpc_id: int | None,
    session: str | None,
    *,
    policy: NetPolicy | None,
    headers: dict[str, str] | None,
    timeout: float,
) -> tuple[dict[str, Any] | None, dict[str, str], str | None]:
    if method in FORBIDDEN_METHODS:
        raise ValueError(f"method {method!r} is never sent during discovery")
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if rpc_id is not None:
        msg["id"] = rpc_id
    hdrs = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if session:
        hdrs["Mcp-Session-Id"] = session
    hdrs.update(headers or {})
    r = fetch(
        endpoint,
        method="POST",
        data=json.dumps(msg).encode(),
        headers=hdrs,
        timeout=timeout,
        policy=policy,
        retries=0,
    )
    if not r.ok:
        return None, dict(r.headers), r.error or f"HTTP {r.status}"
    if rpc_id is None:  # notification: 202 Accepted with no body
        return {}, dict(r.headers), None
    ctype = r.headers.get("Content-Type", r.headers.get("content-type", ""))
    parsed = parse_rpc_response(ctype, r.text, rpc_id)
    if parsed is None:
        return None, dict(r.headers), "no JSON-RPC response for request id"
    return parsed, dict(r.headers), None


def handshake(
    endpoint: str,
    *,
    policy: NetPolicy | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """List-only MCP handshake over Streamable HTTP. Returns a report; never raises for protocol errors."""
    report: dict[str, Any] = {
        "endpoint": endpoint,
        "status": "not_found",
        "checked_at": now_iso(),
        "parser_version": PARSER_VERSION,
        "methods_sent": [],
    }
    init_params = {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "AgentDossier discovery", "version": "0.1"},
    }
    resp, hdrs, err = _rpc(
        endpoint, "initialize", init_params, 1, None, policy=policy, headers=headers, timeout=timeout
    )
    report["methods_sent"].append("initialize")
    if err or resp is None:
        report["error"] = err
        if err and err.startswith("HTTP 4"):
            report["status"] = "not_found" if "404" in err else "unknown"
        else:
            report["status"] = "unknown"
        return report
    if "error" in resp:
        report.update(status="invalid", error=f"initialize error: {resp['error']}")
        return report
    result = resp.get("result") or {}
    session = hdrs.get("Mcp-Session-Id") or hdrs.get("mcp-session-id")
    caps = result.get("capabilities") or {}
    report.update(
        status="verified",
        protocol_version=result.get("protocolVersion"),
        server_info=result.get("serverInfo"),
        instructions_present=bool(result.get("instructions")),
        capabilities=sorted(caps.keys()),
        session_id_issued=bool(session),
        raw_hash=sha256(json.dumps(result, sort_keys=True)),
    )
    _rpc(
        endpoint,
        "notifications/initialized",
        None,
        None,
        session,
        policy=policy,
        headers=headers,
        timeout=timeout,
    )
    report["methods_sent"].append("notifications/initialized")
    rpc_id = 2
    for method, cap, key in (
        ("tools/list", "tools", "tools"),
        ("resources/list", "resources", "resources"),
        ("prompts/list", "prompts", "prompts"),
    ):
        if cap not in caps:
            continue
        lst, _, lerr = _rpc(
            endpoint, method, {}, rpc_id, session, policy=policy, headers=headers, timeout=timeout
        )
        report["methods_sent"].append(method)
        rpc_id += 1
        if lst and "result" in lst:
            items = lst["result"].get(key) or []
            report[key] = [
                {"name": i.get("name"), "description": (i.get("description") or "")[:200]}
                for i in items
                if isinstance(i, dict)
            ]
        else:
            report[f"{key}_error"] = lerr or (lst or {}).get("error")
    if session:
        fetch(
            endpoint,
            method="DELETE",
            headers={"Mcp-Session-Id": session, **(headers or {})},
            timeout=timeout,
            policy=policy,
            retries=0,
        )
        report["methods_sent"].append("DELETE session")
    return report


def fetch_card(
    origin: str,
    *,
    policy: NetPolicy | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    origin = origin.rstrip("/")
    report: dict[str, Any] = {
        "origin": origin,
        "status": "not_found",
        "checked_at": now_iso(),
        "parser_version": PARSER_VERSION,
    }
    r = fetch(origin + WELL_KNOWN_CARD, policy=policy, headers=headers, timeout=timeout, retries=0)
    if not r.ok:
        if r.error and r.error.startswith("blocked"):
            report["status"] = "unknown"
        return report
    if r.is_html:  # an HTML answer is the site's soft 404, not a server card
        return report
    try:
        card = r.json()
    except ValueError:
        report.update(status="invalid", card_url=r.url, errors=["not valid JSON"])
        return report
    errs, warns = validate_card(card)
    report.update(
        status="claimed" if not errs else "invalid",
        card_url=r.url,
        errors=errs,
        warnings=warns,
        summary=summarize_card(card) if isinstance(card, dict) else None,
        card=card,
        hash=sha256(r.body),
    )
    return report


def card_to_resource(
    card: dict[str, Any],
    source_url: str,
    *,
    source_system: str = "mcp",
    scope: str = "public",
    tenant: str | None = None,
) -> dict[str, Any]:
    s = summarize_card(card)
    url = s["website"] or s["repository"] or (s["remotes"][0]["url"] if s["remotes"] else source_url)
    res = new_resource(
        name=s["title"] or s["name"] or source_url,
        source_system=source_system,
        source_url=source_url,
        vendor=None,
        url=url,
        resource_type="mcp_server",
        category="MCP server",
        description=card.get("description"),
        scope=scope,
        tenant=tenant,
        external_ids={"mcp_registry": s["name"]} if source_system == "mcp_registry" else {},
        raw=card,
        key=f"mcp:{s['name']}",
    )
    res["protocols"]["mcp"] = protocol_block(
        "claimed",
        server_name=s["name"],
        version=s["version"],
        remotes=s["remotes"] or None,
        packages=s["packages"] or None,
        tools=s["tools"] or None,
        via=source_system,
        parser_version=PARSER_VERSION,
    )
    res["capabilities"] = list(s["tools"])
    res["raw"] = {"mcp_card": card}
    return res
