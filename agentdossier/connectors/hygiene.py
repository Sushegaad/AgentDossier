"""Discovery hygiene: which discovered rows do not belong in a registry of agents people deploy.

The discovery connectors are deliberately broad (any repository with enough stars, any Hub
space with enough likes). Broad is fine for finding candidates and wrong for the catalog:
a hackathon demo, a deprecated repository or a project untouched for a year next to
Copilot Studio makes the headline count look padded and the Top 100 pages look careless.
Seed rows are never filtered here; the workbook is curated by hand.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

INACTIVE_DAYS = 365
_MARKERS = re.compile(
    r"\b(deprecated|depreciated|archived|obsolete|discontinued|unmaintained|wip|hackathon|tutorial|"
    r"example|examples|sample|samples|template|boilerplate|playground|homework|test|tests|demo)\b",
    re.I,
)
_VENDOR_MARKERS = re.compile(r"hackathon|contest|challenge|bootcamp|course", re.I)


def _days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).total_seconds() / 86400


def drop_reason(res: dict[str, Any], *, now_days: float | None = None) -> str | None:
    """Why a discovered row should not enter the catalog, or None to keep it."""
    sig = res.get("signals") or {}
    name = res.get("name") or ""
    if _MARKERS.search(name):
        return "name marks it as a demo, sample, test or deprecated project"
    if _VENDOR_MARKERS.search(res.get("vendor") or ""):
        return "published by a hackathon, contest or course account"
    if sig.get("github_archived"):
        return "repository is archived"
    last = sig.get("github_pushed_at") or sig.get("hf_last_modified") or sig.get("mcp_registry_updated_at")
    age = now_days if now_days is not None else _days_since(last)
    if last and age is not None and age > INACTIVE_DAYS:
        return f"no activity for {int(age)} days"
    published = any(s.get("system") == "ard" for s in res.get("sources") or [])
    if not published and not (res.get("description") or res.get("license") or sig.get("homepage")):
        return "no description, license or homepage"  # an ARD manifest entry is the publisher's own word; keep it
    return None


def filter_discovered(resources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep seed rows and clean discovered rows; return (kept, {reason: count})."""
    kept: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    for res in resources:
        if any(s.get("system") == "seed_xlsx" for s in res.get("sources") or []):
            kept.append(res)
            continue
        why = drop_reason(res)
        if why is None:
            kept.append(res)
        else:
            key = why.split(" for ")[0] if why.startswith("no activity") else why
            dropped[key] = dropped.get(key, 0) + 1
    return kept, dropped
