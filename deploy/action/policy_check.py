#!/usr/bin/env python3
"""AgentDossier policy check for CI (Wk 15, FR-38 in a pipeline).

Reads an ``agents.lock.json`` manifest — the agents a repository depends on — asks a
self-hosted AgentDossier instance to qualify each one against a policy, and fails the
job when any verdict is at or below the configured threshold. Standard library only,
so the GitHub Action runs without installing the package.

    python policy_check.py agents.lock.json --registry https://agents.corp.example.com \\
        --token "$AGENTDOSSIER_TOKEN" [--policy pol_insurer_default] [--fail-on disallowed|needs_review|unknown]

Manifest::

    {
      "registry": "https://agents.corp.example.com",      # optional; --registry wins
      "policyId": "pol_insurer_default",                   # optional; --policy wins
      "agents": [
        {"id": "res_…", "use": "claims intake"},           # id, slug or ARD identifier
        {"slug": "acme-claims-intake-agent"},
        {"identifier": "urn:air:acme:catalog:acme-claims-intake-agent"}
      ]
    }

Exit codes: 0 pass · 1 policy failure · 2 configuration or registry error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

SEVERITY = {"eligible": 0, "needs_review": 1, "unknown": 2, "disallowed": 3}
FAIL_ON = {"disallowed": 3, "unknown": 2, "needs_review": 1}


def agent_ref(a: dict[str, Any]) -> str:
    ident = a.get("id") or a.get("slug") or a.get("identifier") or ""
    if ident.startswith("urn:air:"):
        ident = ident.rsplit(":", 1)[-1]
    return str(ident)


def http_qualify(
    registry: str, token: str | None, timeout: float = 30.0
) -> Callable[[str, list[str]], dict[str, Any]]:
    def call(policy_id: str, ids: list[str]) -> dict[str, Any]:
        raw = json.dumps({"policyId": policy_id, "resourceIds": ids}).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "agentdossier-policy-check/1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            f"{registry.rstrip('/')}/qualify", data=raw, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"registry returned HTTP {exc.code}: {exc.read(300).decode(errors='replace')}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"registry unreachable: {exc.reason}") from exc

    return call


def check(
    manifest: dict[str, Any],
    qualify: Callable[[str, list[str]], dict[str, Any]],
    *,
    policy_id: str | None = None,
    fail_on: str = "disallowed",
) -> dict[str, Any]:
    """Qualify every agent in the manifest; returns rows and whether the job passes."""
    pid = policy_id or manifest.get("policyId")
    if not pid:
        raise ValueError("no policy: set policyId in the manifest or pass --policy")
    agents = manifest.get("agents") or []
    if not agents:
        raise ValueError("manifest lists no agents")
    refs = [agent_ref(a) for a in agents]
    if any(not r for r in refs):
        raise ValueError("every agent needs id, slug or identifier")
    resp = qualify(pid, refs)
    by_id = {r["resourceId"]: r for r in resp.get("results", [])}
    by_id.update({r["slug"]: r for r in resp.get("results", []) if r.get("slug")})
    threshold = FAIL_ON[fail_on]
    rows = []
    for a, ref in zip(agents, refs, strict=True):
        r = by_id.get(ref)
        if r is None:
            rows.append(
                {
                    "ref": ref,
                    "use": a.get("use"),
                    "verdict": "unknown",
                    "name": None,
                    "reasons": ["not in the registry"],
                    "fails": threshold <= 2,
                }
            )
            continue
        verdict = r.get("verdict", "unknown")
        rules = r.get("rules") if isinstance(r.get("rules"), list) else []
        reasons = [
            f"{x.get('kind', 'rule')} {x.get('id')}: {x.get('evidence') or x.get('result')}"
            for x in rules
            if x.get("result") in ("fail", "unknown")
        ]
        rows.append(
            {
                "ref": ref,
                "use": a.get("use"),
                "name": r.get("name"),
                "verdict": verdict,
                "reasons": reasons[:5],
                "fails": SEVERITY.get(verdict, 2) >= threshold,
            }
        )
    return {
        "policyId": pid,
        "failOn": fail_on,
        "rows": rows,
        "passed": not any(r["fails"] for r in rows),
        "catalog": resp.get("catalog"),
    }


def summary_markdown(result: dict[str, Any]) -> str:
    icon = {"eligible": "✅", "needs_review": "🟡", "unknown": "⚪", "disallowed": "⛔"}
    lines = [
        f"### AgentDossier policy check — {'passed' if result['passed'] else 'failed'}",
        f"Policy `{result['policyId']}` · fail on `{result['failOn']}` or worse",
        "",
        "| Agent | Use | Verdict | Why |",
        "|---|---|---|---|",
    ]
    for r in result["rows"]:
        why = "; ".join(x for x in r["reasons"] if x) or "—"
        lines.append(
            f"| {r.get('name') or r['ref']} | {r.get('use') or '—'} | {icon.get(r['verdict'], '')} {r['verdict']}{' **(blocks)**' if r['fails'] else ''} | {why} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", nargs="?", default="agents.lock.json")
    ap.add_argument("--registry", default=os.environ.get("AGENTDOSSIER_REGISTRY"))
    ap.add_argument("--token", default=os.environ.get("AGENTDOSSIER_TOKEN"))
    ap.add_argument("--policy", default=os.environ.get("AGENTDOSSIER_POLICY"))
    ap.add_argument(
        "--fail-on", default=os.environ.get("AGENTDOSSIER_FAIL_ON", "disallowed"), choices=sorted(FAIL_ON)
    )
    ap.add_argument(
        "--summary",
        default=os.environ.get("GITHUB_STEP_SUMMARY"),
        help="append a markdown summary to this file",
    )
    ap.add_argument("--json", dest="json_out", help="write the full result as JSON")
    a = ap.parse_args(argv)
    try:
        with open(a.manifest, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"::error::cannot read {a.manifest}: {exc}")
        return 2
    registry = a.registry or manifest.get("registry")
    if not registry:
        print("::error::no registry: set --registry, AGENTDOSSIER_REGISTRY or manifest.registry")
        return 2
    try:
        result = check(manifest, http_qualify(registry, a.token), policy_id=a.policy, fail_on=a.fail_on)
    except (ValueError, SystemExit) as exc:
        print(f"::error::{exc}")
        return 2
    md = summary_markdown(result)
    print(md)
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    for r in result["rows"]:
        if r["fails"]:
            print(
                f"::error title=AgentDossier policy::{r.get('name') or r['ref']}: {r['verdict']} — {'; '.join(x for x in r['reasons'] if x) or 'see registry'}"
            )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
