"""Private-network scanner (BRD §4.4, FR-41/42): probe authorized origins for ARD, A2A and MCP metadata.

Metadata only. The scanner fetches ``/.well-known/ard.json`` (plus link rel, in-page
JSON-LD and Agentmap), ``/.well-known/agent.json`` (A2A) and the MCP server card;
it never calls ``tools/call``. The optional MCP handshake is ``initialize`` +
``tools/list`` and is off by default. Every request goes through the enterprise
``NetPolicy`` built from ``scope``; anything outside it is refused before a socket
opens.

Output is an ordinary catalog (``index.json``, ``agents/``, ``domains/`` …) with
``scope: private`` and the tenant name, plus ``scan-report.json`` describing what was
probed, what answered, and what was refused.
"""

from __future__ import annotations

import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import __version__
from ..build import BuildOptions, enrich, write_outputs
from ..connectors.ard_web import inspect_origin
from ..standards import a2a, ard, mcp
from ..util import RateLimiter, fetch, now_iso
from .config import EnterpriseConfig
from .targets import plan

SOURCE = "enterprise_scan"


def probe_origin(origin: str, cfg: EnterpriseConfig, limiter: RateLimiter) -> dict[str, Any]:
    """Run the enabled probes against one origin; returns the raw inspection."""
    headers = cfg.headers()
    timeout = float(cfg.limits.get("timeout_sec", 8))
    policy = cfg.policy
    from urllib.parse import urlparse  # noqa: PLC0415

    limiter.wait(urlparse(origin).hostname or origin)
    result: dict[str, Any] = {"origin": origin, "checked_at": now_iso()}
    if (
        cfg.probes.get("ard", True)
        and cfg.probes.get("a2a", True)
        and cfg.probes.get("mcp_server_card", True)
    ):
        result.update(
            inspect_origin(
                origin, policy=policy, timeout=timeout, mcp_handshake=bool(cfg.probes.get("mcp_handshake"))
            )
        )
        return result
    if cfg.probes.get("ard", True):
        result["ard"] = ard.resolve(origin, policy=policy, headers=headers, timeout=timeout)
    if cfg.probes.get("a2a", True):
        result["a2a"] = a2a.fetch_card(origin, policy=policy, headers=headers, timeout=timeout)
    if cfg.probes.get("mcp_server_card", True):
        result["mcp"] = mcp.fetch_card(origin, policy=policy, headers=headers, timeout=timeout)
        if cfg.probes.get("mcp_handshake") and (result["mcp"].get("summary") or {}).get("remotes"):
            result["mcp_handshake"] = mcp.handshake(
                result["mcp"]["summary"]["remotes"][0]["url"], policy=policy, timeout=timeout
            )
    return result


def list_registry(
    registry: str, cfg: EnterpriseConfig, limiter: RateLimiter
) -> tuple[list[dict[str, Any]], list[str]]:
    """Page through an ARD registry's ``GET /agents`` listing; also read its manifest."""
    from urllib.parse import urlparse  # noqa: PLC0415

    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    base = registry.rstrip("/")
    policy, headers, timeout = cfg.policy, cfg.headers(), float(cfg.limits.get("timeout_sec", 8))
    limiter.wait(urlparse(base).hostname or base)
    rep = ard.resolve(base, policy=policy, headers=headers, timeout=timeout, scan_homepage=False)
    for item in rep.get("entries", []):
        entries.append({"entry": item["entry"], "manifest": item["manifest"]})
    token: str | None = None
    for _ in range(50):  # at most 5,000 listed agents per registry per run
        url = f"{base}/agents?pageSize=100" + (f"&pageToken={token}" if token else "")
        limiter.wait(urlparse(base).hostname or base)
        r = fetch(url, policy=policy, headers=headers, timeout=timeout, retries=0)
        if not r.ok:
            if r.status not in (404, 0):
                errors.append(f"{url}: {r.error}")
            break
        try:
            doc = r.json()
        except ValueError:
            errors.append(f"{url}: not JSON")
            break
        for a in doc.get("agents", []) if isinstance(doc, dict) else []:
            if isinstance(a, dict) and a.get("identifier"):
                entries.append({"entry": a, "manifest": url})
        token = doc.get("nextPageToken") if isinstance(doc, dict) else None
        if not token:
            break
    return entries, errors


def resources_from(inspection: dict[str, Any], cfg: EnterpriseConfig) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    origin = inspection["origin"]
    for item in (inspection.get("ard") or {}).get("entries", []):
        res = ard.entry_to_resource(item["entry"], item["manifest"], scope="private", tenant=cfg.tenant)
        out.append(res)
    a2a_rep = inspection.get("a2a") or {}
    if a2a_rep.get("status") in ("verified", "invalid") and a2a_rep.get("card"):
        out.append(a2a.card_to_resource(a2a_rep, scope="private", tenant=cfg.tenant))
    mcp_rep = inspection.get("mcp") or {}
    if mcp_rep.get("status") in ("claimed", "verified", "invalid") and mcp_rep.get("card"):
        res = mcp.card_to_resource(
            mcp_rep["card"],
            mcp_rep.get("card_url") or origin,
            source_system="mcp",
            scope="private",
            tenant=cfg.tenant,
        )
        hs = inspection.get("mcp_handshake")
        if hs:
            res["protocols"]["mcp"].update(
                {
                    k: v
                    for k, v in hs.items()
                    if k in ("status", "protocol_version", "tools", "server_info", "error")
                }
            )
        out.append(res)
    for res in out:
        res.setdefault("signals", {})["scan_origin"] = origin
        res["sources"].append({"system": SOURCE, "url": origin, "retrieved_at": inspection.get("checked_at")})
    return out


def scan(
    cfg: EnterpriseConfig, *, dry_run: bool = False, out_dir: Path | None = None, use_dns: bool = True
) -> dict[str, Any]:
    """Plan, probe, build. With ``dry_run`` nothing is fetched; the plan is returned."""
    out = Path(out_dir or cfg.output_dir)
    p = plan(cfg, use_dns=use_dns)
    report: dict[str, Any] = {
        "generator": f"agentdossier {__version__}",
        "tenant": cfg.tenant,
        "authorized_by": cfg.authorized_by,
        "ticket": cfg.ticket,
        "started": now_iso(),
        "dry_run": dry_run,
        "plan": p,
        "probed": [],
        "errors": [],
    }
    if dry_run:
        report["finished"] = now_iso()
        return report
    if cfg.ca_bundle:
        os.environ["SSL_CERT_FILE"] = cfg.ca_bundle
    limiter = RateLimiter(1.0 / float(cfg.limits.get("requests_per_host_per_sec", 4)))
    out.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "raw"
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir()

    def work(origin: str) -> dict[str, Any]:
        try:
            return probe_origin(origin, cfg, limiter)
        except Exception as exc:  # noqa: BLE001 - one bad host must not stop the scan
            return {"origin": origin, "checked_at": now_iso(), "error": f"{type(exc).__name__}: {exc}"}

    resources: list[dict[str, Any]] = []
    origins = [t["origin"] for t in p["targets"]]
    with ThreadPoolExecutor(max_workers=int(cfg.limits.get("concurrency", 16))) as pool:
        for i, insp in enumerate(pool.map(work, origins)):
            (raw_dir / f"origin-{i:05d}.json").write_text(json.dumps(insp, default=str, indent=1))
            probed: dict[str, Any] = {"origin": insp["origin"]}
            for k in ("ard", "a2a", "mcp"):
                if k in insp:
                    probed[k] = (insp.get(k) or {}).get("status")
            if insp.get("error"):
                probed["error"] = insp["error"]
            report["probed"].append(probed)
            if insp.get("error"):
                report["errors"].append(f"{insp['origin']}: {insp['error']}")
                continue
            resources += resources_from(insp, cfg)
    for reg in p["registries"]:
        entries, errs = list_registry(reg, cfg, limiter)
        report["errors"] += errs
        report["probed"].append({"origin": reg, "registry": len(entries)})
        for item in entries:
            resources.append(
                ard.entry_to_resource(item["entry"], item["manifest"], scope="private", tenant=cfg.tenant)
            )

    opts = BuildOptions(
        out_dir=out / "catalog",
        cache_dir=out / "snapshots",
        sources=(),
        offline=True,  # no public registries, no news from inside the network
        write_review=False,
        compliance=False,
        news=False,
        changelog_path=out / "trust-changelog.jsonl",
        scope="private",
        tenant=cfg.tenant,
        site=os.environ.get("AGENTDOSSIER_SITE", "http://localhost:8080/"),
        registry_urn=f"urn:air:{cfg.tenant}:registry:agentdossier",
        registry_name=f"{cfg.tenant} private agent registry",
        registry_description="Self-hosted AgentDossier instance; catalog built from an authorized internal scan.",
        policy=cfg.policy,
    )
    reports: dict[str, dict[str, Any]] = {
        "enterprise_scan": {
            "origins": len(origins),
            "registries": len(p["registries"]),
            "resources": len(resources),
        }
    }
    resources = enrich(resources, opts, reports)
    summary = write_outputs(resources, opts, reports)
    report["catalog"] = str(opts.out_dir)
    report["resources"] = len(resources)
    report["summary"] = {
        k: v
        for k, v in summary.items()
        if k in ("resources", "by_source", "by_type", "protocols", "identity_tiers")
    }
    report["finished"] = now_iso()
    (out / "scan-report.json").write_text(json.dumps(report, indent=1, default=str))
    return report
