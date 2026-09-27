"""Entity linking, clustering and ranking for news items (FR-44, FR-45).

An item is linked to a resource with confidence >= 0.85 only when the
resource name appears in the title *and* a second signal agrees (vendor
name, publisher domain in the URL, or a distinctive multi-word name).
Generic single-word names never link on their own.

Ranking (BRD §8.6): link confidence x source authority x recency x
engagement x coverage breadth, with diversity caps (<= 3 per outlet,
<= 2 vendor items, >= 2 community items when available), 90-day window.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

MIN_CONFIDENCE = 0.85
WINDOW_DAYS = 90
AUTHORITY = {"news": 1.0, "security": 1.0, "community": 0.8, "vendor": 0.7}
HALF_LIFE = {"news": 14.0, "security": 30.0, "community": 3.0, "vendor": 14.0}
GENERIC = {
    "agent",
    "agents",
    "ai",
    "copilot",
    "studio",
    "assistant",
    "platform",
    "cloud",
    "data",
    "search",
    "chat",
    "bot",
    "api",
    "sdk",
    "app",
    "hub",
    "lab",
    "labs",
    "one",
    "pro",
    "core",
    "flow",
    "auto",
    "dev",
    "code",
    "muse",
}
_WS = re.compile(r"\s+")


def _norm(s: str | None) -> str:
    return _WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def distinctive(name: str) -> bool:
    n = _norm(name)
    words = [w for w in n.split() if w not in GENERIC]
    if not words:
        return False
    return len(n) >= 8 and (len(n.split()) >= 2 or (len(words) == 1 and len(words[0]) >= 6))


def link_confidence(item: dict[str, Any], res: dict[str, Any]) -> float:
    title = _norm(item.get("headline"))
    text = f"{title} {_norm(item.get('summary'))}"
    name = _norm(res.get("name"))
    if not name or name not in title:
        return 0.0
    vendor = _norm(res.get("vendor"))
    domain = (res.get("publisher_domain") or "").lower()
    url = (item.get("url") or "").lower()
    signals = 0
    if vendor and vendor != name and (vendor in text):
        signals += 1
    if domain and domain in url:
        signals += 1
    if item.get("kind") == "vendor":
        signals += 1  # vendor's own feed
    if distinctive(res.get("name", "")):
        signals += 1
    if signals >= 2:
        return 0.95
    if signals == 1:
        return 0.88
    return 0.6


def _age_days(date: str | None) -> float | None:
    if not date:
        return None
    try:
        dt = datetime.fromisoformat(date[:19].replace("Z", "")).replace(tzinfo=UTC)
    except ValueError:
        return None
    return max(0.0, (datetime.now(UTC) - dt).total_seconds() / 86400)


def cluster(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group near-identical headlines within 48 hours; keep the highest-authority item and count outlets."""
    out: list[dict[str, Any]] = []
    for it in sorted(items, key=lambda i: i.get("date") or "", reverse=True):
        key = _norm(it["headline"])[:60]
        merged = False
        for c in out:
            if c["_key"] == key or (len(key) > 20 and (key in c["_key"] or c["_key"] in key)):
                a, b = _age_days(it.get("date")), _age_days(c.get("date"))
                if a is not None and b is not None and abs(a - b) <= 2:
                    c["cluster_size"] = c.get("cluster_size", 1) + 1
                    c.setdefault("also_in", []).append(it.get("outlet"))
                    if AUTHORITY.get(it.get("kind", "news"), 1.0) > AUTHORITY.get(c.get("kind", "news"), 1.0):
                        c.update({k: v for k, v in it.items() if k not in ("cluster_size", "also_in")})
                    merged = True
                    break
        if not merged:
            out.append({**it, "_key": key, "cluster_size": it.get("cluster_size", 1)})
    for c in out:
        c.pop("_key", None)
    return out


def rank(items: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    scored = []
    for it in items:
        age = _age_days(it.get("date"))
        if age is None or age > WINDOW_DAYS:
            continue
        kind = it.get("kind", "news")
        recency = math.exp(-age * math.log(2) / HALF_LIFE.get(kind, 14.0))
        engagement = 1.0 + math.log1p(float(it.get("engagement") or 0)) / 5.0
        breadth = 1.0 + 0.2 * (int(it.get("cluster_size") or 1) - 1)
        score = (
            float(it.get("link_confidence", 0)) * AUTHORITY.get(kind, 1.0) * recency * engagement * breadth
        )
        scored.append((score, it))
    scored.sort(key=lambda t: -t[0])
    chosen: list[dict[str, Any]] = []
    per_outlet: dict[str, int] = {}
    vendor_count = 0
    community = [it for _, it in scored if it.get("kind") == "community"]
    for score, it in scored:
        outlet = it.get("outlet") or ""
        if per_outlet.get(outlet, 0) >= 3:
            continue
        if it.get("kind") == "vendor" and vendor_count >= 2:
            continue
        chosen.append({**it, "rank_score": round(score, 4)})
        per_outlet[outlet] = per_outlet.get(outlet, 0) + 1
        if it.get("kind") == "vendor":
            vendor_count += 1
        if len(chosen) >= limit:
            break
    # ensure at least two community items when available
    have = sum(1 for c in chosen if c.get("kind") == "community")
    for it in community:
        if have >= 2 or len(chosen) < limit:
            break
        if it not in chosen:
            chosen[-1] = {**it, "rank_score": 0.0}
            have += 1
    return chosen[:limit]
