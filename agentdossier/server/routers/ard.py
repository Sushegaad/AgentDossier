"""ARD REST: manifest, search (with federation), explore, agents, policies, qualify."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ..deps import deps
from ..federation import HOP_HEADER

router = APIRouter()


# --- ARD REST ----------------------------------------------------------------------
@router.get("/.well-known/ard.json")
def ard_manifest(request: Request):
    d = deps(request)
    # a private registry's manifest maps internal endpoints: readers (and federation peers,
    # which carry a token) must authenticate; a public-scope catalog stays open for discovery
    if d.catalog.index.get("scope") == "private":
        d.user(request)
    p = d.catalog.path / "ard.json"
    if p.exists():
        return FileResponse(p, media_type="application/ai-registry+json")
    return {"entries": []}


@router.post("/search")
def search(request: Request, body: dict[str, Any] = Body(default={})):
    d = deps(request)
    d.limited(request)
    d.user(request)
    q = str(body.get("query") or "")
    limit = min(int(body.get("limit") or 20), 100)
    f = body.get("filters") or {}
    hits = d.catalog.search(
        q,
        limit=limit,
        domain=f.get("domain"),
        resource_type=f.get("type"),
        framework=f.get("framework"),
        max_tier=f.get("maxTier"),
        protocol=f.get("protocol"),
    )
    out: dict[str, Any] = {
        "query": q,
        "count": len(hits),
        "results": [d.to_result(h) for h in hits],
        "catalog": d.catalog.meta,
    }
    mode = d.federation.effective_mode(body.get("federation"), request.headers.get(HOP_HEADER))
    if mode == "referrals":
        out["federation"] = {"mode": mode, "referrals": d.federation.referrals(q)}
    elif mode == "auto":
        peers = d.federation.query(body)
        merged = []
        for p in peers:
            for r in p["results"]:
                merged.append({**r, "source_registry": p["registry"]})
        out["federation"] = {
            "mode": mode,
            "peers": [{k: v for k, v in p.items() if k != "results"} for p in peers],
        }
        out["results"] += merged
        out["count"] = len(out["results"])
    return out


@router.post("/explore")
def explore(request: Request, body: dict[str, Any] = Body(default={})):
    d = deps(request)
    d.limited(request)
    d.user(request)
    domain, rtype = body.get("domain"), body.get("type")
    recs = [
        r
        for r in d.catalog.records
        if (not domain or domain in r.get("domains", {})) and (not rtype or r.get("resource_type") == rtype)
    ]
    by_domain: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_protocol: dict[str, int] = {}
    for r in recs:
        for d in r.get("domains", {}):
            by_domain[d] = by_domain.get(d, 0) + 1
        by_type[r.get("resource_type", "?")] = by_type.get(r.get("resource_type", "?"), 0) + 1
        t = f"T{r.get('trust', {}).get('compliance', 5)}"
        by_tier[t] = by_tier.get(t, 0) + 1
        for p, s in (r.get("protocols") or {}).items():
            if s in ("verified", "claimed"):
                by_protocol[p] = by_protocol.get(p, 0) + 1
    return {
        "total": len(recs),
        "byDomain": by_domain,
        "byType": by_type,
        "byEvidenceTier": dict(sorted(by_tier.items())),
        "byProtocol": by_protocol,
    }


@router.get("/agents")
def agents(request: Request, pageSize: int = Query(100, ge=1, le=500), pageToken: str | None = None):  # noqa: N803 - ARD REST names
    d = deps(request)
    d.user(request)
    recs = sorted(d.catalog.records, key=lambda r: r["name"].lower())
    start = int(pageToken) if pageToken and pageToken.isdigit() else 0
    page = recs[start : start + pageSize]
    nxt = str(start + pageSize) if start + pageSize < len(recs) else None
    return {
        "agents": [
            {
                "identifier": f"urn:air:{d.catalog.index.get('tenant') or 'agentdossier'}:catalog:{r['slug']}",
                "displayName": r["name"],
                "type": r.get("resource_type"),
                "url": f"{d.settings.site.rstrip('/')}/agents/{r['slug']}/",
                "resourceId": r["id"],
            }
            for r in page
        ],
        "total": len(recs),
        "pageSize": pageSize,
        "nextPageToken": nxt,
    }


@router.get("/agents/{ident}")
def agent(request: Request, ident: str):
    d = deps(request)
    d.user(request)
    res = d.catalog.resource(ident)
    if not res:
        raise HTTPException(404, "unknown resource")
    return res


@router.get("/policies")
def policies(request: Request):
    d = deps(request)
    d.user(request)
    return {
        "policies": [
            {
                "id": k,
                "name": v.get("name"),
                "version": v.get("version"),
                "jurisdictions": v.get("jurisdictions"),
                "rules": len(v.get("rules", [])),
            }
            for k, v in d.catalog.policies.items()
        ]
    }


@router.post("/qualify")
def qualify(request: Request, body: dict[str, Any] = Body(...)):
    d = deps(request)
    d.limited(request)
    u = d.user(request)
    policy = body.get("policy") or body.get("policyId")
    if not policy:
        raise HTTPException(400, "policy (inline) or policyId is required")
    if isinstance(policy, str) and policy not in d.catalog.policies:
        raise HTTPException(404, f"unknown policyId {policy}")
    ids = body.get("resourceIds")
    results = d.catalog.qualify(policy, ids)
    not_found = [i for i in ids or [] if d.catalog.resource(str(i)) is None]
    for r in results:  # echo the slug so callers that asked by slug can match the answer
        rec = d.catalog.by_id.get(r["resourceId"])
        if rec:
            r["slug"] = rec.get("slug")
    d.store.audit(
        u.subject,
        "qualify",
        f"policy={policy if isinstance(policy, str) else policy.get('id', 'inline')} n={len(results)}",
    )
    return {
        "policyId": policy if isinstance(policy, str) else policy.get("id", "inline"),
        "count": len(results),
        "results": results,
        "notFound": not_found,
    }
