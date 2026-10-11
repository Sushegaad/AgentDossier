"""Vendor-published traces: a bundle the vendor serves, named in its ARD manifest entry (PR 4).

A vendor who runs its own attack/defense evaluation can publish the trace bundle at a stable URL
and point to it from its ARD entry (``traces: [{url, format, sha256}]``, see docs/traces-spec.md).
The build fetches it, checks the hash the vendor gave, and records a ``vendor_published`` trace:
tier 1 when the bundle is fetched and its hash matches (or no hash was given but the body is a
valid trace document), tier 4 when it is only claimed — unreachable, oversized or hash-mismatched.
No vendor publishes this yet; the dossier shows "not published" until one does.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..util import NetPolicy, fetch
from .store import TraceStore

PAGE_MAX_BYTES = 4_000_000


def _record(
    res: dict[str, Any], ptr: dict[str, str], *, tier: int, outcome: str, site: str, date: str
) -> dict[str, Any]:
    tid = "tr_vp_" + hashlib.sha256((res["id"] + ptr["url"]).encode()).hexdigest()[:16]
    return {
        "id": tid,
        "kind": "vendor_published",
        "tier": tier,
        "scope": "product",
        "title": f"Vendor-published trace for {res['name']}",
        "scenario": None,
        "source": res.get("vendor") or res.get("publisher_domain") or "vendor",
        "url": ptr["url"],
        "date": date,
        "format": ptr.get("format", "bundle")
        if ptr.get("format") in {"bundle", "spans", "transcript", "report"}
        else "bundle",
        "observed": {"outcome": outcome},
        "vendor_response": None,
        "agent_version": None,
        "harness_version": None,
        "sha256": ptr.get("sha256"),
        "reviewer": None,
        "checked_on": None,
        "notes": "Declared in the vendor's ARD manifest; fetched and hash-checked by the registry.",
    }


def fetch_vendor_traces(
    resources: list[dict[str, Any]],
    store: TraceStore,
    *,
    policy: NetPolicy | None = None,
    site: str,
    date: str,
) -> dict[str, int]:
    """Fetch and record every vendor-declared trace bundle. Deduped by url+hash via the store key."""
    counts = {"declared": 0, "verified": 0, "claimed": 0}
    seen = store.keys()
    for res in resources:
        for ptr in (res.get("signals") or {}).get("ard_trace_pointers") or []:
            counts["declared"] += 1
            key = f"vendor:{res['id']}:{ptr['url']}:{ptr.get('sha256', '')}"
            if key in seen:
                continue
            r = fetch(ptr["url"], policy=policy, timeout=8, retries=0, max_bytes=PAGE_MAX_BYTES)
            tier, outcome = 4, "declared by the vendor; bundle not reachable"
            if r.ok and not r.is_html:
                digest = "sha256:" + hashlib.sha256(r.body).hexdigest()
                if ptr.get("sha256") and ptr["sha256"].removeprefix("sha256:") != digest.removeprefix(
                    "sha256:"
                ):
                    tier, outcome = (
                        4,
                        "declared by the vendor; published bundle does not match the stated hash",
                    )
                else:
                    try:
                        json.loads(r.body)
                        tier, outcome = 1, "vendor-published bundle fetched and hash-checked"
                    except ValueError:
                        tier, outcome = 4, "declared by the vendor; bundle is not a valid trace document"
            counts["verified" if tier == 1 else "claimed"] += 1
            store.append(
                _record(res, ptr, tier=tier, outcome=outcome, site=site, date=date), agent=res["id"], key=key
            )
            seen.add(key)
    return counts
