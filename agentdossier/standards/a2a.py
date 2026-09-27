"""A2A Agent Card adapter (A2A 0.3 and 1.0 card shapes).

Discovery: GET {origin}/.well-known/agent-card.json (registered well-known URI),
falling back to the pre-0.3 /.well-known/agent.json. Metadata only: SAR never
sends tasks/messages to an agent during discovery.
"""

from __future__ import annotations

from typing import Any

from ..models import new_resource, protocol_block
from ..util import NetPolicy, fetch, now_iso, sha256

PARSER_VERSION = "a2a-0.3+1.0"
WELL_KNOWN = ("/.well-known/agent-card.json", "/.well-known/agent.json")


def validate_card(card) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if not isinstance(card, dict):
        return ["agent card is not a JSON object"], []
    for f in ("name", "description", "version"):
        if not card.get(f):
            errors.append(f"missing '{f}'")
    if not card.get("url") and not card.get("supportedInterfaces"):
        errors.append("missing service endpoint ('url' or 'supportedInterfaces')")
    if not isinstance(card.get("skills"), list) or not card.get("skills"):
        warnings.append("no skills advertised")
    if "capabilities" not in card:
        warnings.append("missing 'capabilities'")
    if not card.get("defaultInputModes"):
        warnings.append("missing 'defaultInputModes'")
    if not card.get("securitySchemes"):
        warnings.append("no securitySchemes declared (anonymous or undocumented auth)")
    for i, s in enumerate(card.get("skills") or []):
        if not isinstance(s, dict) or not s.get("id") or not s.get("name"):
            errors.append(f"skills[{i}] missing id/name")
    return errors, warnings


def summarize(card: dict) -> dict:
    interfaces = []
    for it in card.get("supportedInterfaces") or []:
        if isinstance(it, dict):
            interfaces.append(
                {
                    "url": it.get("url"),
                    "binding": it.get("protocolBinding") or it.get("transport"),
                    "protocol_version": it.get("protocolVersion"),
                }
            )
    if card.get("url"):
        interfaces.insert(
            0,
            {
                "url": card["url"],
                "binding": card.get("preferredTransport", "JSONRPC"),
                "protocol_version": card.get("protocolVersion"),
            },
        )
    for it in card.get("additionalInterfaces") or []:
        if isinstance(it, dict):
            interfaces.append(
                {
                    "url": it.get("url"),
                    "binding": it.get("transport"),
                    "protocol_version": card.get("protocolVersion"),
                }
            )
    caps = card.get("capabilities") or {}
    return {
        "name": card.get("name"),
        "version": card.get("version"),
        "protocol_version": next(
            (i["protocol_version"] for i in interfaces if i.get("protocol_version")),
            card.get("protocolVersion"),
        ),
        "interfaces": interfaces,
        "streaming": bool(caps.get("streaming")) if isinstance(caps, dict) else None,
        "push_notifications": bool(caps.get("pushNotifications")) if isinstance(caps, dict) else None,
        "auth_schemes": sorted((card.get("securitySchemes") or {}).keys()),
        "signed": bool(card.get("signatures")),
        "provider": card.get("provider"),
        "skills": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "tags": s.get("tags") or [],
                "examples": (s.get("examples") or [])[:3],
            }
            for s in card.get("skills") or []
            if isinstance(s, dict)
        ],
        "input_modes": card.get("defaultInputModes"),
        "output_modes": card.get("defaultOutputModes"),
    }


def fetch_card(
    origin: str, *, policy: NetPolicy | None = None, headers: dict | None = None, timeout: float = 8.0
) -> dict:
    origin = origin.rstrip("/")
    report: dict[str, Any] = {
        "origin": origin,
        "status": "not_found",
        "checked_at": now_iso(),
        "parser_version": PARSER_VERSION,
    }
    for path in WELL_KNOWN:
        r = fetch(origin + path, policy=policy, headers=headers, timeout=timeout, retries=0)
        if not r.ok:
            continue
        try:
            card = r.json()
        except ValueError:
            report.update(status="invalid", card_url=r.url, errors=["not valid JSON"])
            continue
        errs, warns = validate_card(card)
        report.update(
            status="verified" if not errs else "invalid",
            card_url=r.url,
            errors=errs,
            warnings=warns,
            summary=summarize(card) if isinstance(card, dict) else None,
            card=card,
            hash=sha256(r.body),
            legacy_path=path.endswith("agent.json") and "agent-card" not in path,
        )
        return report
    return report


def card_to_resource(
    report: dict, *, scope: str = "public", tenant: str | None = None, vendor: str | None = None
) -> dict:
    card = report["card"]
    s = report.get("summary") or {}
    provider = card.get("provider") or {}
    res = new_resource(
        name=card.get("name") or report["origin"],
        source_system="a2a",
        source_url=report["card_url"],
        vendor=vendor or provider.get("organization"),
        url=report["origin"],
        resource_type="a2a_agent",
        category="A2A agent",
        description=card.get("description"),
        scope=scope,
        tenant=tenant,
        raw=card,
        key=report["card_url"],
    )
    res["protocols"]["a2a"] = protocol_block(
        report["status"],
        card_url=report["card_url"],
        version=s.get("version"),
        protocol_version=s.get("protocol_version"),
        interfaces=s.get("interfaces"),
        auth_schemes=s.get("auth_schemes"),
        signed=s.get("signed"),
        skills=s.get("skills"),
        errors=report.get("errors") or None,
        warnings=report.get("warnings") or None,
        parser_version=PARSER_VERSION,
    )
    res["capabilities"] = [sk.get("name") for sk in s.get("skills", []) if sk.get("name")]
    res["tags"] = sorted({t for sk in s.get("skills", []) for t in sk.get("tags", [])})
    res["representative_queries"] = [
        ex for sk in s.get("skills", []) for ex in sk.get("examples", []) if isinstance(ex, str)
    ][:5]
    res["deployment"] = "private network" if scope == "private" else None
    res["raw"] = {"a2a_card": card}
    return res
