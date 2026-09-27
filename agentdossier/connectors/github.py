"""GitHub connector (FR-01): repositories by topic, plus release and advisory signals.

Uses the REST search API (``/search/repositories``) over the topics listed in
``config/sources.json``. Authentication comes from ``GITHUB_TOKEN`` (the
Actions token allows 1,000 requests/hour; a fine-grained PAT 5,000). Search
returns at most 1,000 results per query, so queries are split by star bands
when a topic is larger than that.

Only repository metadata is stored: no user profiles, no commit authors, no
issue text (source register terms). Everything is metadata the repository
owner published.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from ..models import new_resource
from ..util import NetPolicy
from .base import ConnectorReport, SnapshotStore, get_json

API = "https://api.github.com"
SOURCE = "github"
DEFAULT_TOPICS = ("ai-agents", "ai-agent", "llm-agents", "mcp-server", "a2a", "agentic")
STAR_BANDS = ((5000, None), (1000, 4999), (300, 999), (100, 299), (25, 99))
LICENSE_KEYS = {
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "gpl-3.0": "GPL-3.0",
    "agpl-3.0": "AGPL-3.0",
    "bsd-3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "mpl-2.0": "MPL-2.0",
    "lgpl-3.0": "LGPL-3.0",
    "unlicense": "Unlicense",
    "other": "Other",
}


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def repo_to_resource(
    repo: dict[str, Any], *, topic: str | None = None, payload_hash: str | None = None
) -> dict[str, Any]:
    """Map one search/repos item onto the canonical record."""
    full = repo["full_name"]
    owner = (repo.get("owner") or {}).get("login") or full.split("/")[0]
    lic = (repo.get("license") or {}).get("spdx_id") or (repo.get("license") or {}).get("key")
    lic_norm = LICENSE_KEYS.get(str(lic).lower(), lic) if lic else None
    if lic_norm == "NOASSERTION":
        lic_norm = "Other"
    res = new_resource(
        name=repo.get("name") or full,
        source_system=SOURCE,
        source_url=repo.get("html_url"),
        vendor=owner,
        url=repo.get("homepage") or repo.get("html_url"),
        resource_type=_infer_type(repo),
        category="Open-source project",
        description=(repo.get("description") or "")[:500] or None,
        external_ids={"github": full},
        raw=repo,
        key=f"github:{full.lower()}",
    )
    res["license"] = lic_norm
    res["commercial"] = False
    res["tags"] = sorted(set((repo.get("topics") or [])[:30]))
    res["deployment"] = "self-hosted"
    res["signals"] = {
        "github_stars": repo.get("stargazers_count"),
        "github_forks": repo.get("forks_count"),
        "github_open_issues": repo.get("open_issues_count"),
        "github_pushed_at": repo.get("pushed_at"),
        "github_created_at": repo.get("created_at"),
        "github_archived": bool(repo.get("archived")),
        "github_language": repo.get("language"),
        "github_topic": topic,
        "homepage": repo.get("homepage") or None,
    }
    if payload_hash:
        res["sources"][0]["payload_hash"] = payload_hash
    return res


_TYPE_HINTS = (
    (re.compile(r"mcp[-_ ]?server|model context protocol", re.I), "mcp_server"),
    (re.compile(r"\bsdk\b|framework|toolkit|library", re.I), "framework"),
    (re.compile(r"\bskill", re.I), "skill"),
)


def _infer_type(repo: dict[str, Any]) -> str:
    text = " ".join(
        [repo.get("name") or "", repo.get("description") or "", " ".join(repo.get("topics") or [])]
    )
    if "mcp-server" in (repo.get("topics") or []):
        return "mcp_server"
    for pat, rtype in _TYPE_HINTS:
        if pat.search(text):
            return rtype
    return "agent"


def search_topic(
    topic: str,
    *,
    store: SnapshotStore | None,
    token: str | None,
    min_stars: int = 25,
    max_pages: int = 10,
    policy: NetPolicy | None = None,
    report: ConnectorReport | None = None,
    sleep: float = 2.1,
) -> list[dict[str, Any]]:
    """Search one topic across star bands; returns canonical resources."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lo, hi in STAR_BANDS:
        if hi is not None and hi < min_stars:
            continue
        stars = f"stars:>={lo}" if hi is None else f"stars:{max(lo, min_stars)}..{hi}"
        for page in range(1, max_pages + 1):
            q = f"topic:{topic} {stars} archived:false"
            url = f"{API}/search/repositories?q={q.replace(' ', '+')}&sort=stars&order=desc&per_page=100&page={page}"
            data, r, h = get_json(
                store, SOURCE, f"search:{topic}:{stars}:{page}", url, headers=_headers(token), policy=policy
            )
            if report:
                report.fetched += 1
            if data is None:
                if report and r is not None:
                    report.error(f"{url}: {r.error}")
                break
            items = data.get("items") or []
            for repo in items:
                full = repo.get("full_name", "").lower()
                if not full or full in seen:
                    continue
                seen.add(full)
                out.append(repo_to_resource(repo, topic=topic, payload_hash=h))
            if len(items) < 100:
                break
            time.sleep(sleep)  # search API: 30 requests/minute authenticated
    if report:
        report.produced += len(out)
    return out


def run(
    *,
    store: SnapshotStore | None,
    topics: tuple[str, ...] = DEFAULT_TOPICS,
    token: str | None = None,
    min_stars: int = 25,
    max_pages: int = 10,
    policy: NetPolicy | None = None,
) -> tuple[list[dict[str, Any]], ConnectorReport]:
    token = token or os.environ.get("GITHUB_TOKEN")
    report = ConnectorReport(SOURCE)
    resources: list[dict[str, Any]] = []
    for topic in topics:
        resources.extend(
            search_topic(
                topic,
                store=store,
                token=token,
                min_stars=min_stars,
                max_pages=max_pages,
                policy=policy,
                report=report,
            )
        )
    return resources, report
