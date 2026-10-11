"""``self_test`` traces: what this registry observed at an agent's public endpoints.

Every refresh asks each publisher's domain for its ARD manifest, A2A agent card and MCP
server card and validates what comes back. That exchange is a trace — a reproducible
observation of how the agent presents itself — and it is the one kind of trace this
registry can produce for every agent with a live endpoint. A bundle is written when the
probes found something (a card or manifest, valid or not) and the outcome differs from
the last bundle for that agent; a "not found" everywhere is recorded in the dossier's
protocol block, not as a trace.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .store import TraceStore

HARNESS_VERSION = "probe-1.0"
FOUND = ("verified", "invalid")
NAMES = {
    "ard": "Agentic Resource Discovery (ARD)",
    "a2a": "Agent2Agent (A2A)",
    "mcp": "Model Context Protocol (MCP)",
}


def _urls(b: dict[str, Any]) -> list[str]:
    """Every URL a probe block names; ``sources`` may be URLs or {url, via, hash} dicts."""
    if b.get("card_url") or b.get("manifest_url"):
        return [str(b.get("card_url") or b.get("manifest_url"))]
    out = []
    for s in b.get("sources") or []:
        u = s.get("url") if isinstance(s, dict) else s
        if u:
            out.append(str(u))
    return out


def _probe_blocks(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The probe result per protocol (a curated claim keeps the probe under ``probe``)."""
    out = {}
    for p, block in (res.get("protocols") or {}).items():
        b = block.get("probe") if block.get("source") == "curated_claim" and block.get("probe") else block
        if b and b.get("status") in FOUND:
            out[p] = b
    return out


def _key(res: dict[str, Any], probes: dict[str, dict[str, Any]]) -> str:
    facts = {
        p: {
            "status": b.get("status"),
            "url": _urls(b),
            "errors": sorted(b.get("errors") or []),
            "signed": b.get("signed"),
            "auth": b.get("auth_schemes"),
            "skills": sorted(b.get("skills") or []),
        }
        for p, b in probes.items()
    }
    return "sha256:" + hashlib.sha256(json.dumps([res["id"], facts], sort_keys=True).encode()).hexdigest()


def _transcript(res: dict[str, Any], probes: dict[str, dict[str, Any]], date: str) -> str:
    lines = [
        f"# Probe transcript — {res['name']}",
        "",
        f"Agent `{res['id']}` · publisher domain `{res.get('publisher_domain') or '—'}` · {date} · harness {HARNESS_VERSION}",
        "",
    ]
    for p, b in probes.items():
        lines += [f"## {NAMES.get(p, p)}", ""]
        for u in _urls(b):
            lines.append(f"- requested `{u}`")
        lines.append(f"- result: **{b.get('status')}**")
        if b.get("protocol_version") or b.get("version"):
            lines.append(
                f"- declared version: {b.get('protocol_version') or ''} {('(card ' + str(b.get('version')) + ')') if b.get('version') else ''}".rstrip()
            )
        if b.get("auth_schemes") is not None:
            lines.append(f"- auth schemes: {', '.join(b.get('auth_schemes') or []) or 'none declared'}")
        if b.get("signed") is not None:
            lines.append(f"- signed: {'yes' if b.get('signed') else 'no'}")
        if b.get("skills"):
            lines.append(
                f"- skills advertised: {', '.join(b['skills'][:20])}{' …' if len(b['skills']) > 20 else ''}"
            )
        entries = b.get("entries")
        if entries:
            lines.append(f"- manifest entries: {entries if isinstance(entries, int) else len(entries)}")
        for e in b.get("errors") or []:
            lines.append(f"- validation error: {e}")
        for w in b.get("warnings") or []:
            lines.append(f"- warning: {w}")
        lines.append("")
    lines += [
        "---",
        "Observation only: the registry fetched public well-known paths and validated the documents against the protocol specifications. No credentials, no message exchange beyond discovery, nothing written.",
    ]
    return "\n".join(lines) + "\n"


def _verdict(probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    parts = []
    for p, b in probes.items():
        s = b.get("status")
        extra = []
        if p == "a2a" and b.get("auth_schemes") is not None:
            extra.append("auth " + (", ".join(b["auth_schemes"]) or "none"))
        if b.get("signed") is False:
            extra.append("unsigned")
        if b.get("errors"):
            extra.append(f"{len(b['errors'])} validation error{'s' if len(b['errors']) != 1 else ''}")
        parts.append(f"{p.upper()} {s}" + (f" ({'; '.join(extra)})" if extra else ""))
    return {
        "entry": "GET on the publisher's well-known discovery paths",
        "actions": [f"served {NAMES.get(p, p)} document" for p in probes],
        "egress": False,
        "approval": None,
        "secrets_touched": False,
        "refused": None,
        "outcome": "; ".join(parts),
    }


def record_probes(
    resources: list[dict[str, Any]], store: TraceStore, *, site: str, date: str
) -> dict[str, int]:
    """Append a self_test bundle for every agent whose probes found something new. Returns counts."""
    existing = store.keys()
    counts = {"candidates": 0, "appended": 0, "unchanged": 0}
    for res in resources:
        probes = _probe_blocks(res)
        if not probes:
            continue
        counts["candidates"] += 1
        key = _key(res, probes)
        if key in existing:
            counts["unchanged"] += 1
            continue
        tid = f"tr_st_{res['id'].removeprefix('res_')}_{key[7:15]}"
        verdict = _verdict(probes)
        manifest = {
            "id": tid,
            "agent": res["id"],
            "slug": res.get("slug"),
            "name": res["name"],
            "kind": "self_test",
            "date": date,
            "harness_version": HARNESS_VERSION,
            "protocols": {p: {k: v for k, v in b.items() if k != "entries"} for p, b in probes.items()},
        }
        files = {
            "manifest.json": json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False).encode(),
            "transcript.md": _transcript(res, probes, date).encode(),
            "verdict.json": json.dumps(verdict, indent=1, sort_keys=True, ensure_ascii=False).encode(),
        }
        record = {
            "id": tid,
            "kind": "self_test",
            "tier": 1,
            "scope": "product",
            "title": f"Registry probe of {res['name']}'s discovery endpoints",
            "scenario": "Fetch and validate the ARD manifest, A2A agent card and MCP server card at the publisher's well-known paths",
            "source": "AgentDossier refresh",
            "url": f"{site.rstrip('/')}/traces/{tid}/",
            "date": date,
            "format": "bundle",
            "observed": verdict,
            "vendor_response": None,
            "agent_version": None,
            "harness_version": HARNESS_VERSION,
            "reviewer": None,
            "checked_on": None,
            "notes": "Produced automatically on every refresh; a new bundle is written only when the observation changes",
        }
        store.append(record, agent=res["id"], key=key, files=files)
        existing.add(key)
        counts["appended"] += 1
    return counts
