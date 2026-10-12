"""Re-check that every published incident's sources are still where the registry says they are.

Every row in the registry is "as reported" — its claims stand on the linked sources. This job
re-fetches each source URL weekly and records whether it is still reachable, has moved, or is gone,
in data/curated/incident_source_check.json. It never edits an incident and never sets ``checked_on``
(that field means a *person* checked the entry against its sources); it only says which links a
person should look at. The site shows the re-check date and flags sources that did not answer.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..util import ROOT, FetchResult, fetch
from .scout import normalize_url

INCIDENTS = ROOT / "data" / "curated" / "incidents.yaml"
REPORT = ROOT / "data" / "curated" / "incident_source_check.json"
VERSION = "incident-source-check-1.0"
PAGE_MAX_BYTES = 200_000  # a GET only needs to prove the page answers; never pull a whole article

Fetcher = Callable[[str, str], FetchResult]  # (url, method) → result

# ok: answered 2xx at the same place · moved: answered 2xx somewhere else (redirect) · gone: 404/410 ·
# unverified: the site answered but would not serve us (401/403/429, bot walls) — not evidence it is
# gone · error: no usable answer (timeout, DNS, 5xx)
STATUSES = ("ok", "moved", "gone", "unverified", "error")


def _default_fetcher(url: str, method: str) -> FetchResult:
    return fetch(
        url,
        method=method,
        timeout=20.0,
        retries=1,
        max_bytes=PAGE_MAX_BYTES,
        headers={"Accept": "text/html, application/xhtml+xml, application/pdf;q=0.9, */*;q=0.5"},
    )


# Bot-protection services answer 200 from a challenge page on their own domain, with the page we asked
# for tucked into the query string. That is not the source answering; it is "unverified".
_CHALLENGE_MARKERS = (
    "perfdrive.com",
    "shieldsquare",
    "captcha",
    "/challenge",
    "validate.",
    "bot-detection",
    "cdn-cgi/",
)


def site_of(url: str) -> str:
    """The registrable-ish domain (last two labels): assets.example.com and www-cdn.example.com are one site."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def looks_like_challenge(url: str) -> bool:
    low = url.lower()
    return any(m in low for m in _CHALLENGE_MARKERS)


def classify(res: FetchResult, original: str) -> str:
    if res.error and res.status == 0:
        return "error"
    if res.status in (404, 410):
        return "gone"
    if res.status in (401, 403, 429) or res.status == 405:
        return "unverified"
    if 200 <= res.status < 300:
        if normalize_url(res.url) == normalize_url(original):
            return "ok"
        if looks_like_challenge(res.url):
            return "unverified"
        # a redirect within the same site (CDN, trailing slash, locale) still serves the page: ok;
        # a redirect to another site is where a person should look
        return "ok" if site_of(res.url) == site_of(original) else "moved"
    if res.status >= 500:
        return "error"
    return "unverified"


def check_url(url: str, fetcher: Fetcher | None = None) -> dict[str, Any]:
    """HEAD first (cheap); fall back to a capped GET when the site refuses HEAD or does not answer."""
    fetcher = fetcher or _default_fetcher
    res = fetcher(url, "HEAD")
    status = classify(res, url)
    if status in ("unverified", "error") or res.status == 405:
        res = fetcher(url, "GET")
        status = classify(res, url)
    out: dict[str, Any] = {"url": url, "status": status, "http": res.status}
    if normalize_url(res.url) != normalize_url(url):
        out["final_url"] = res.url  # recorded whenever it differs, even when the redirect is benign
    if res.error and status in ("error", "unverified", "gone"):
        out["error"] = res.error
    elif status == "unverified" and looks_like_challenge(res.url):
        out["error"] = "bot-protection challenge page"
    return out


def load_incidents(path: Path = INCIDENTS) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(path.read_text()) or {}
    return [inc for inc in doc.get("incidents") or [] if inc.get("status") == "published"]


def recheck(
    incidents: list[dict[str, Any]],
    *,
    fetcher: Fetcher | None = None,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """One entry per published incident, one line per source. Deterministic order; no exceptions."""
    today = today or dt.date.today()
    seen: dict[str, dict[str, Any]] = {}  # the same URL cited twice is fetched once
    per_incident: dict[str, list[dict[str, Any]]] = {}
    for inc in sorted(incidents, key=lambda i: str(i.get("id"))):
        lines: list[dict[str, Any]] = []
        for src in inc.get("sources") or []:
            url = src.get("url")
            if not url:
                continue
            if url not in seen:
                seen[url] = check_url(url, fetcher)
            lines.append(dict(seen[url]))
        per_incident[str(inc["id"])] = lines
    counts = dict.fromkeys(STATUSES, 0)
    for lines in per_incident.values():
        for line in lines:
            counts[line["status"]] += 1
    attention = sorted(
        iid
        for iid, lines in per_incident.items()
        if any(line["status"] in ("gone", "moved", "error") for line in lines)
    )
    return {
        "version": VERSION,
        "checked_on": today.isoformat(),
        "incidents_checked": len(per_incident),
        "sources_checked": len(seen),
        "summary": counts,
        "needs_attention": attention,
        "incidents": per_incident,
    }


def write_report(report: dict[str, Any], path: Path = REPORT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False) + "\n")


def read_report(path: Path = REPORT) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())
