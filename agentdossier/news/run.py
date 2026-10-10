"""News and security stage: gather items per resource, link, cluster, rank top 10; NVD security check.

Three lanes run concurrently so rate limits overlap instead of adding up:

* a thread pool for the fast sources (Hacker News, GitHub releases, vendor feeds);
* one worker that walks GDELT serially (its own 5.5 s spacing);
* one worker that walks NVD serially (5 requests / 30 s without a key).

Progress is logged to stderr every 10 resources.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..connectors.base import ConnectorReport, SnapshotStore
from ..util import NetPolicy, domain_of
from . import sources
from .linking import MIN_CONFIDENCE, cluster, distinctive, link_confidence, rank

RISK_TAGS = {"security_incident", "outage", "legal_regulatory"}
KEEP = (
    "headline",
    "url",
    "outlet",
    "date",
    "tag",
    "summary",
    "kind",
    "link_confidence",
    "cluster_size",
    "discussion_url",
    "engagement",
)


def _empty_issues() -> dict[str, Any]:
    return {
        "regulator_actions": 0,
        "cves": 0,
        "advisories": 0,
        "incidents": 0,
        "withdrawn_certificates": 0,
        "links": [],
    }


def _log(msg: str) -> None:
    print(f"[news] {msg}", file=sys.stderr, flush=True)


def run(
    resources: list[dict[str, Any]],
    *,
    store: SnapshotStore | None,
    policy: NetPolicy | None = None,
    limit: int | None = None,
    use_gdelt: bool = True,
    use_nvd: bool = True,
    vendor_feeds: bool = True,
    concurrency: int = 6,
    deadline: Any = None,
) -> dict[str, dict[str, Any]]:
    token = os.environ.get("GITHUB_TOKEN")
    nvd_key = os.environ.get("NVD_API_KEY")
    rep = ConnectorReport("news")
    sec = ConnectorReport("nvd")
    # Every resource gets its own repository's releases and its vendor's feed; only names that
    # can be searched for without drowning in noise ("Aider", "Dify" cannot) go to the
    # name-search sources (Hacker News, GDELT, NVD).
    targets = resources[:limit] if limit else list(resources)
    searchable = {r["id"] for r in targets if distinctive(r.get("name", ""))}
    started = time.monotonic()
    _log(
        f"{len(targets)} resources, {len(searchable)} with searchable names; gdelt={use_gdelt} nvd={use_nvd}"
    )

    feed_cache: dict[str, list[dict[str, Any]]] = {}
    fast_items: dict[str, list[dict[str, Any]]] = {}
    gdelt_items: dict[str, list[dict[str, Any]]] = {}
    nvd_results: dict[str, dict[str, Any]] = {}

    skipped: set[str] = set()

    def out_of_time() -> bool:
        return deadline is not None and deadline.expired()

    def fast(res: dict[str, Any]) -> None:
        name = res["name"]
        items: list[dict[str, Any]] = []
        if out_of_time():
            skipped.add(res["id"])
            return
        try:
            if res["id"] in searchable:
                items += sources.hackernews(name, store=store, policy=policy)
            gh = (res.get("external_ids") or {}).get("github")
            if gh and token:
                items += sources.github_releases(gh, token=token, store=store, policy=policy)
            dom = res.get("publisher_domain") or domain_of(res.get("url"))
            if vendor_feeds and dom and dom not in ("github.com", "huggingface.co"):
                if dom not in feed_cache:
                    feed_cache[dom] = sources.vendor_feed(dom, store=store, policy=policy)
                items += feed_cache[dom]
        except Exception as exc:  # noqa: BLE001
            rep.error(f"{name}: {type(exc).__name__}: {exc}")
        fast_items[res["id"]] = items

    def gdelt_lane() -> None:
        for i, res in enumerate((r for r in targets if r["id"] in searchable), 1):
            if out_of_time():
                return
            try:
                gdelt_items[res["id"]] = sources.gdelt(res["name"], store=store, policy=policy)
            except sources.GdeltUnavailableError as exc:
                rep.error(f"gdelt: {exc}")
                _log(str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                rep.error(f"{res['name']}: gdelt {type(exc).__name__}: {exc}")
            if i % 10 == 0:
                _log(f"gdelt {i}/{len(targets)} ({time.monotonic() - started:.0f}s)")

    def nvd_lane() -> None:
        for i, res in enumerate((r for r in targets if r["id"] in searchable), 1):
            if out_of_time():
                return
            try:
                nvd_results[res["id"]] = sources.nvd_cves(
                    res["name"], store=store, policy=policy, api_key=nvd_key
                )
            except Exception as exc:  # noqa: BLE001
                nvd_results[res["id"]] = {"checked": False, "error": f"{type(exc).__name__}: {exc}"}
            if i % 10 == 0:
                _log(f"nvd {i}/{len(targets)} ({time.monotonic() - started:.0f}s)")

    with ThreadPoolExecutor(max_workers=concurrency + 2) as pool:
        lanes = []
        if use_gdelt:
            lanes.append(pool.submit(gdelt_lane))
        if use_nvd:
            lanes.append(pool.submit(nvd_lane))
        list(pool.map(fast, targets))
        _log(f"fast sources done ({time.monotonic() - started:.0f}s); waiting for rate-limited lanes")
        for f in lanes:
            f.result()

    for res in targets:
        if res["id"] in skipped:
            rep.skipped += 1
            continue
        res["news_checked"] = True
        items = fast_items.get(res["id"], []) + gdelt_items.get(res["id"], [])
        rep.fetched += 1
        linked = []
        for it in items:
            conf = link_confidence(it, res)
            if conf >= MIN_CONFIDENCE:
                linked.append({**it, "link_confidence": round(conf, 2)})
        top = rank(cluster(linked))
        res["news"] = [{k: v for k, v in it.items() if k in KEEP} for it in top]
        for it in res["news"]:
            if it.get("engagement") is None:
                it.pop("engagement", None)
        rep.produced += len(res["news"])
        links = [
            {"kind": it["tag"], "url": it["url"], "date": it["date"][:10], "title": it["headline"]}
            for it in res["news"]
            if it["tag"] in RISK_TAGS
        ]
        res["issues"] = {
            **_empty_issues(),
            "incidents": sum(1 for it in links if it["kind"] in ("security_incident", "outage")),
            "links": links,
        }
        nvd = nvd_results.get(res["id"])
        if nvd is not None:
            sec.fetched += 1
            if nvd.get("checked"):
                res["security"] = {
                    "tier": 1,
                    "cves": nvd["total"],
                    "advisories": 0,
                    "checked_at": nvd["checked_at"],
                    "source": "nvd",
                }
                res["issues"]["cves"] = nvd["total"]
                res["issues"]["links"] += [
                    {
                        "kind": "cve",
                        "url": c["url"],
                        "date": (c.get("published") or "")[:10],
                        "title": c["id"],
                    }
                    for c in nvd["cves"]
                ]
                sec.produced += 1
            else:
                sec.error(f"{res['name']}: {nvd.get('error')}")
    for res in resources:
        res.setdefault("news", [])
        res.setdefault("issues", _empty_issues())
    _log(
        f"done: {rep.produced} items on {rep.fetched} resources, {rep.skipped} skipped for time ({time.monotonic() - started:.0f}s)"
    )
    return {"news": rep.as_dict(), "nvd": sec.as_dict()}
