"""Enrich seed-workbook rows whose URL is a GitHub repository.

61 of the 158 ranked agents point at github.com. The workbook gives them a name, a
vendor and a URL, nothing more, so they sat at identity T4 ("vendor name only"),
were never probed for protocols (code hosts carry no well-known files) and had no
trust page to crawl. One `GET /repos/{owner}/{repo}` fixes all three:

* ``external_ids.github`` → identity T3 (repository ownership) and the GitHub
  release feed in the news stage;
* ``homepage`` → the vendor's own domain becomes ``publisher_domain`` so the ARD /
  A2A / MCP probes and the trust-page crawler have somewhere to look;
* ``topics`` and ``description`` → self-described protocol claims and search text;
* license, stars, last push → signals the discovered rows already carry.

Nothing is overwritten that the workbook stated explicitly (name, vendor, category).
"""

from __future__ import annotations

import re
from typing import Any

from ..util import NetPolicy, domain_of
from .base import ConnectorReport, SnapshotStore, get_json
from .github import API, LICENSE_KEYS, _headers

SOURCE = "seed_enrich"
CODE_HOSTS = {"github.com", "gitlab.com", "huggingface.co", "pypi.org", "npmjs.com", "www.npmjs.com"}
_REPO = re.compile(
    r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[/#?].*)?$"
)


def repo_of(url: str | None) -> str | None:
    """``owner/repo`` for a GitHub repository URL, else None (org and topic pages are not repos)."""
    if not url:
        return None
    m = _REPO.match(url.strip())
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if owner.lower() in {"features", "topics", "orgs", "marketplace", "settings", "about", "apps"}:
        return None
    return f"{owner}/{repo}"


def apply_repo(res: dict[str, Any], repo: dict[str, Any]) -> list[str]:
    """Write repository metadata onto a seed resource; returns what changed."""
    changed: list[str] = []
    full = repo.get("full_name") or ""
    ext = res.setdefault("external_ids", {})
    if full and not ext.get("github"):
        ext["github"] = full
        changed.append("external_ids.github")
    home = (repo.get("homepage") or "").strip()
    hd = domain_of(home if "://" in home else f"https://{home}") if home else None
    if hd and hd not in CODE_HOSTS and not hd.endswith(".github.io"):
        res["homepage"] = home if "://" in home else f"https://{home}"
        if (res.get("publisher_domain") or "") in CODE_HOSTS or not res.get("publisher_domain"):
            res["publisher_domain"] = hd
            changed.append("publisher_domain")
    if not res.get("description") and repo.get("description"):
        res["description"] = str(repo["description"])[:500]
        changed.append("description")
    topics = sorted({str(t) for t in (repo.get("topics") or [])})
    if topics:
        res["tags"] = sorted(set(res.get("tags") or []) | set(topics[:30]))
        changed.append("tags")
    lic = (repo.get("license") or {}).get("spdx_id") or (repo.get("license") or {}).get("key")
    if lic and lic != "NOASSERTION" and not res.get("license"):
        res["license"] = LICENSE_KEYS.get(str(lic).lower(), lic)
        changed.append("license")
    sig = res.setdefault("signals", {})
    for k, v in {
        "github_stars": repo.get("stargazers_count"),
        "github_forks": repo.get("forks_count"),
        "github_open_issues": repo.get("open_issues_count"),
        "github_pushed_at": repo.get("pushed_at"),
        "github_created_at": repo.get("created_at"),
        "github_archived": bool(repo.get("archived")),
        "github_language": repo.get("language"),
        "homepage": res.get("homepage"),
    }.items():
        if v is not None and sig.get(k) is None:
            sig[k] = v
    if changed:
        res.setdefault("enrichment", {})["github"] = {"repo": full, "changed": changed}
    return changed


def run(
    resources: list[dict[str, Any]],
    *,
    token: str | None,
    store: SnapshotStore | None = None,
    policy: NetPolicy | None = None,
    only_sources: tuple[str, ...] = ("seed_xlsx",),
    deadline: Any = None,
) -> ConnectorReport:
    """Fetch repository metadata for every seed resource whose URL is a GitHub repo."""
    rep = ConnectorReport(SOURCE)
    todo = []
    for res in resources:
        systems = {s.get("system") for s in res.get("sources") or []}
        if only_sources and not (systems & set(only_sources)):
            continue
        full = repo_of(res.get("url")) or repo_of(
            res.get("canonical_url") and f"https://{res['canonical_url']}"
        )
        if full and not (res.get("enrichment") or {}).get("github"):
            todo.append((res, full))
    for res, full in todo:
        if deadline is not None and deadline.expired():
            rep.skipped += 1
            continue
        data, r, h = get_json(
            store,
            SOURCE,
            full.lower(),
            f"{API}/repos/{full}",
            headers=_headers(token),
            policy=policy,
            retries=0,
        )
        if not isinstance(data, dict) or not data.get("full_name"):
            rep.error(f"{full}: {(r.error if r else None) or 'no data'}")
            continue
        rep.fetched += 1
        if apply_repo(res, data):
            rep.produced += 1
    return rep
