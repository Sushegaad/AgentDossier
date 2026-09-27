"""News and security sources (FR-43): Hacker News, GDELT, GitHub releases, RSS/Atom feeds, NVD.

Only headline, URL, outlet, date, tag and the source's own short description
are kept (FR-47). GDELT rate-limits aggressively, so requests are spaced
and a 429 is retried once after a pause.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

from ..connectors.base import SnapshotStore, get_json
from ..util import NetPolicy, fetch, now_iso

TAG_RULES = [
    (
        "security_incident",
        re.compile(r"breach|vulnerab|cve-|exploit|hacked|leak|malware|prompt injection", re.I),
    ),
    ("outage", re.compile(r"outage|downtime|incident report|degraded", re.I)),
    (
        "legal_regulatory",
        re.compile(
            r"lawsuit|sued|regulator|fine[ds]?\b|antitrust|ftc|sec\b|gdpr|investigation|settlement", re.I
        ),
    ),
    ("funding", re.compile(r"raises|funding|series [a-f]\b|valuation|acquire|acquisition", re.I)),
    ("pricing", re.compile(r"pricing|price|\$\d|per seat|free tier", re.I)),
    ("partnership", re.compile(r"partner|integration with|teams up|collaborat", re.I)),
    ("launch", re.compile(r"launch|introduc|announc|unveil|debut|now available|general availability", re.I)),
    ("product_update", re.compile(r"update|release|version|v\d|new feature|adds|improv", re.I)),
    ("review", re.compile(r"review|hands-on|tested|i tried|first look|vs\.?\b", re.I)),
    ("opinion", re.compile(r"why |opinion|column|should ", re.I)),
]


def tag_for(headline: str, summary: str | None = None) -> str:
    text = f"{headline} {summary or ''}"
    for tag, pat in TAG_RULES:
        if pat.search(text):
            return tag
    return "news"


def item(
    headline: str,
    url: str,
    outlet: str,
    date: str,
    kind: str,
    summary: str | None = None,
    engagement: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    it = {
        "headline": headline.strip(),
        "url": url,
        "outlet": outlet,
        "date": date,
        "kind": kind,
        "tag": tag_for(headline, summary),
        "summary": (summary or "").strip()[:240] or None,
        "engagement": engagement,
    }
    if extra:
        it.update(extra)
    return it


# --- Hacker News (Algolia) ---------------------------------------------------


def hackernews(
    query: str, *, store: SnapshotStore | None = None, policy: NetPolicy | None = None, min_points: int = 5
) -> list[dict[str, Any]]:
    url = f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(chr(34) + query + chr(34))}&tags=story&hitsPerPage=20"
    data, r, _ = get_json(store, "hackernews", query, url, policy=policy)
    out = []
    for h in (data or {}).get("hits", []) if isinstance(data, dict) else []:
        if (h.get("points") or 0) < min_points or not h.get("title"):
            continue
        link = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        out.append(
            item(
                h["title"],
                link,
                "Hacker News",
                h.get("created_at", ""),
                "community",
                None,
                (h.get("points") or 0) + (h.get("num_comments") or 0),
                {
                    "discussion_url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                    "comments": h.get("num_comments"),
                },
            )
        )
    return out


# --- GDELT DOC 2.0 -------------------------------------------------------------

_last_gdelt = 0.0
_gdelt_lock = threading.Lock()
_gdelt_failures = 0
GDELT_MAX_FAILURES = 2  # consecutive 429/timeouts before GDELT is skipped for the rest of the run


class GdeltUnavailableError(RuntimeError):
    """GDELT tripped the circuit breaker; callers skip it for the rest of the build."""


def gdelt_reset() -> None:
    global _gdelt_failures
    _gdelt_failures = 0


def gdelt(
    query: str, *, store: SnapshotStore | None = None, policy: NetPolicy | None = None, timespan: str = "90d"
) -> list[dict[str, Any]]:
    global _last_gdelt, _gdelt_failures
    if _gdelt_failures >= GDELT_MAX_FAILURES:
        raise GdeltUnavailableError("GDELT rate-limited this client; skipped for the rest of the run")
    q = urllib.parse.quote(f'"{query}"')
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json&maxrecords=25&timespan={timespan}&sort=datedesc"
    with _gdelt_lock:  # one GDELT request in flight, spaced 5.5 s apart
        wait = 5.5 - (time.monotonic() - _last_gdelt)
        if wait > 0:
            time.sleep(wait)
        data, r, _ = get_json(store, "gdelt", query, url, policy=policy, timeout=20, retries=0)
        _last_gdelt = time.monotonic()
        if data is None and r is not None and r.status == 429 and _gdelt_failures == 0:
            time.sleep(20)
            data, r, _ = get_json(store, "gdelt", query, url, policy=policy, timeout=20, retries=0)
            _last_gdelt = time.monotonic()
    if data is None:
        _gdelt_failures += 1
        if _gdelt_failures >= GDELT_MAX_FAILURES:
            raise GdeltUnavailableError(
                f"GDELT unavailable ({r.error if r else 'no response'}); skipped for the rest of the run"
            )
        return []
    _gdelt_failures = 0
    out = []
    for a in (data or {}).get("articles", []) if isinstance(data, dict) else []:
        if (a.get("language") or "English") != "English" or not a.get("title"):
            continue
        d = a.get("seendate", "")
        date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}T{d[9:11]}:{d[11:13]}:00Z" if len(d) >= 13 else ""
        out.append(item(a["title"], a["url"], a.get("domain") or "news", date, "news"))
    return out


# --- GitHub releases (needs GITHUB_TOKEN; runs in Actions) -----------------------


def github_releases(
    full_name: str, *, token: str | None, store: SnapshotStore | None = None, policy: NetPolicy | None = None
) -> list[dict[str, Any]]:
    if not token:
        return []
    url = f"https://api.github.com/repos/{full_name}/releases?per_page=5"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data, r, _ = get_json(store, "github_releases", full_name, url, headers=headers, policy=policy)
    out = []
    for rel in data if isinstance(data, list) else []:
        if rel.get("draft"):
            continue
        name = rel.get("name") or rel.get("tag_name") or "release"
        out.append(
            item(
                f"{full_name.split('/')[-1]} {name}",
                rel.get("html_url", ""),
                "GitHub releases",
                rel.get("published_at", ""),
                "vendor",
                (rel.get("body") or "")[:240],
                None,
                {"tag": "product_update"},
            )
        )
    return out


# --- RSS / Atom discovery on the vendor homepage ------------------------------------

_ALT = re.compile(r'<link\b[^>]*rel="alternate"[^>]*>', re.I)
_ATTR = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')
COMMON_FEEDS = ("/feed", "/rss.xml", "/blog/feed", "/blog/rss.xml", "/news/feed", "/newsroom/rss")


def discover_feeds(origin: str, *, policy: NetPolicy | None = None) -> list[str]:
    r = fetch(origin + "/", policy=policy, timeout=8, retries=0)
    feeds: list[str] = []
    if r.ok:
        for tag in _ALT.findall(r.text):
            a = dict(_ATTR.findall(tag))
            if "rss" in a.get("type", "") or "atom" in a.get("type", ""):
                feeds.append(urllib.parse.urljoin(origin + "/", a.get("href", "")))
    return feeds[:2]


def parse_feed(body: str, outlet: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if re.search(r"<!DOCTYPE|<!ENTITY", body[:4096], re.I):
        return out  # feeds never need DTDs; refusing them blocks entity-expansion attacks (S314)
    try:
        root = ET.fromstring(body)  # noqa: S314 - DTD/entity declarations rejected above; body capped at 2 MB
    except ET.ParseError:
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for e in root.findall(".//item")[:15]:
        title, link, date, desc = (
            e.findtext("title"),
            e.findtext("link"),
            e.findtext("pubDate") or e.findtext("{http://purl.org/dc/elements/1.1/}date"),
            e.findtext("description"),
        )
        if title and link:
            out.append(
                item(
                    title,
                    link.strip(),
                    outlet,
                    _rfc822_to_iso(date),
                    "vendor",
                    re.sub(r"<[^>]+>", " ", desc or "")[:240],
                )
            )
    for e in root.findall(".//a:entry", ns)[:15]:
        title = e.findtext("a:title", namespaces=ns)
        link_el = e.find("a:link", ns)
        link = link_el.get("href") if link_el is not None else None
        date = e.findtext("a:updated", namespaces=ns) or e.findtext("a:published", namespaces=ns)
        summary = e.findtext("a:summary", namespaces=ns) or ""
        if title and link:
            out.append(
                item(title, link, outlet, date or "", "vendor", re.sub(r"<[^>]+>", " ", summary)[:240])
            )
    return out


def _rfc822_to_iso(s: str | None) -> str:
    if not s:
        return ""
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(s).astimezone().isoformat()
    except (TypeError, ValueError):
        return s


def vendor_feed(
    domain: str, *, store: SnapshotStore | None = None, policy: NetPolicy | None = None
) -> list[dict[str, Any]]:
    origin = f"https://{domain}"
    urls = discover_feeds(origin, policy=policy) or [origin + p for p in COMMON_FEEDS[:2]]
    for url in urls:
        r = fetch(url, policy=policy, timeout=8, retries=0)
        if r.ok and (
            "xml" in r.headers.get("Content-Type", r.headers.get("content-type", "")).lower()
            or r.text.lstrip().startswith("<")
        ):
            if store:
                store.save("vendor_feeds", domain, r.body)
            items = parse_feed(r.text, f"{domain} (vendor)")
            if items:
                return items
    return []


# --- NVD (security) --------------------------------------------------------------


def nvd_cves(
    product: str,
    *,
    store: SnapshotStore | None = None,
    policy: NetPolicy | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    q = urllib.parse.quote(product)
    url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch={q}&keywordExactMatch&resultsPerPage=20"
    headers = {"apiKey": api_key} if api_key else None
    data, r, _ = get_json(store, "nvd", product, url, headers=headers, policy=policy, timeout=30)
    time.sleep(6.5 if not api_key else 0.7)  # NVD: 5 requests / 30 s without a key
    if not isinstance(data, dict):
        return {"checked": False, "error": r.error if r else "no data"}
    cves = []
    for v in data.get("vulnerabilities", []):
        c = v.get("cve", {})
        desc = next((d["value"] for d in c.get("descriptions", []) if d.get("lang") == "en"), "")
        cves.append(
            {
                "id": c.get("id"),
                "published": c.get("published"),
                "url": f"https://nvd.nist.gov/vuln/detail/{c.get('id')}",
                "summary": desc[:200],
            }
        )
    return {
        "checked": True,
        "checked_at": now_iso(),
        "total": int(data.get("totalResults") or 0),
        "cves": cves[:10],
    }
