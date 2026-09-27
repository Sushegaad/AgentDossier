"""Vendor claim extraction (FR-21): tier-4 records from trust and security pages.

For a publisher domain, fetch the homepage, follow up to three same-domain
links whose text or path mentions trust, security, compliance or privacy,
also try ``/trust``, ``/security`` and ``/compliance``, and look for
framework mentions. Everything found is a **claim** (tier 4) with the page
URL as evidence. robots.txt ``Disallow`` rules for ``User-agent: *`` are
honored, and at most five pages per domain are fetched.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from typing import Any

from ..util import NetPolicy, fetch, now_iso, sha256

SOURCE = "vendor_trust_centers"
CANDIDATE_PATHS = ("/trust", "/security", "/compliance", "/trust-center", "/legal/security")
LINK_WORDS = re.compile(r"trust|security|compliance|privacy", re.I)
MAX_PAGES = 5

# framework id, variant, pattern (case-insensitive), required context
PATTERNS: list[tuple[str, str | None, re.Pattern[str]]] = [
    ("soc2", "SOC2_TYPE_II", re.compile(r"soc\s*2\s*type\s*(?:ii|2)", re.I)),
    ("soc2", "SOC2_TYPE_I", re.compile(r"soc\s*2\s*type\s*(?:i|1)\b(?!i)", re.I)),
    ("soc2", None, re.compile(r"\bsoc\s*2\b", re.I)),
    ("iso27001", "ISO27001", re.compile(r"iso(?:/iec)?\s*27001", re.I)),
    ("iso27001", "ISO27017", re.compile(r"iso(?:/iec)?\s*27017", re.I)),
    ("iso27001", "ISO27018", re.compile(r"iso(?:/iec)?\s*27018", re.I)),
    ("iso27701", "ISO27701", re.compile(r"iso(?:/iec)?\s*27701", re.I)),
    ("iso42001", "ISO42001", re.compile(r"iso(?:/iec)?\s*42001", re.I)),
    ("csa_star", None, re.compile(r"csa\s*star|cloud security alliance", re.I)),
    ("fedramp", None, re.compile(r"fedramp", re.I)),
    (
        "hipaa",
        "BAA_AVAILABLE",
        re.compile(
            r"\bhipaa\b.{0,120}?\b(baa|business associate)|\b(baa|business associate agreement)\b.{0,120}?\bhipaa\b",
            re.I | re.S,
        ),
    ),
    ("hipaa", None, re.compile(r"\bhipaa\b", re.I)),
    ("hitrust", None, re.compile(r"hitrust", re.I)),
    ("gdpr", "DPA_AVAILABLE", re.compile(r"data processing (?:agreement|addendum)|\bdpa\b", re.I)),
    ("gdpr", "DPF_ACTIVE", re.compile(r"data privacy framework", re.I)),
    ("gdpr", None, re.compile(r"\bgdpr\b", re.I)),
    ("pci_dss", None, re.compile(r"pci[\s-]*dss", re.I)),
    ("cyber_essentials", "CYBER_ESSENTIALS_PLUS", re.compile(r"cyber essentials plus", re.I)),
    ("cyber_essentials", "CYBER_ESSENTIALS", re.compile(r"cyber essentials", re.I)),
    ("nist_ai_rmf", "NIST_AI_RMF_ALIGNED", re.compile(r"nist ai rmf|ai risk management framework", re.I)),
    ("eu_ai_act", "ART50_STATEMENT", re.compile(r"eu ai act|artificial intelligence act", re.I)),
]
_TAG = re.compile(r"<script.*?</script>|<style.*?</style>", re.I | re.S)
_HREF = re.compile(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.I | re.S)


def robots_disallows(origin: str, policy: NetPolicy | None) -> list[str]:
    r = fetch(origin + "/robots.txt", policy=policy, timeout=6, retries=0)
    if not r.ok:
        return []
    rules, active = [], False
    for line in r.text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            active = val == "*"
        elif key == "disallow" and active and val:
            rules.append(val)
    return rules


def allowed(path: str, disallows: list[str]) -> bool:
    for rule in disallows:
        pat = "^" + re.escape(rule).replace(r"\*", ".*")
        if re.match(pat, path):
            return False
    return True


def text_of(html_body: str) -> str:
    t = _TAG.sub(" ", html_body)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def find_claims(text: str) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    seen_fw: set[tuple[str, str | None]] = set()
    for fw, variant, pat in PATTERNS:
        if pat.search(text):
            key = (fw, variant)
            if key in seen_fw:
                continue
            # a bare framework mention is superseded by a specific variant of the same framework
            if variant is None and any(f == fw and v is not None for f, v in seen_fw):
                continue
            seen_fw.add(key)
            found.append(key)
    return found


def crawl_domain(domain: str, *, policy: NetPolicy | None = None, timeout: float = 8.0) -> dict[str, Any]:
    origin = f"https://{domain}"
    disallows = robots_disallows(origin, policy)
    visited: list[str] = []
    claims: dict[tuple[str, str | None], str] = {}
    hashes: dict[str, str] = {}

    def visit(url: str) -> str | None:
        if len(visited) >= MAX_PAGES:
            return None
        path = urllib.parse.urlparse(url).path or "/"
        if not allowed(path, disallows):
            return None
        r = fetch(url, policy=policy, timeout=timeout, retries=0)
        visited.append(url)
        if not r.ok or "html" not in r.headers.get("Content-Type", r.headers.get("content-type", "")).lower():
            return None
        hashes[r.url] = sha256(r.body)
        body = r.text
        for key in find_claims(text_of(body)):
            claims.setdefault(key, r.url)
        return body

    home = visit(origin + "/")
    links: list[str] = []
    if home:
        for href, label in _HREF.findall(home):
            full = urllib.parse.urljoin(origin + "/", href)
            p = urllib.parse.urlparse(full)
            if p.netloc.lower().removeprefix("www.") != domain.removeprefix("www.").lower():
                continue
            if LINK_WORDS.search(label) or LINK_WORDS.search(p.path):
                if full not in links:
                    links.append(full)
    for url in links[:3]:
        visit(url)
    for path in CANDIDATE_PATHS:
        if len(visited) >= MAX_PAGES:
            break
        url = origin + path
        if url not in visited:
            visit(url)
    return {
        "domain": domain,
        "pages": visited,
        "claims": [{"framework": f, "variant": v, "url": u} for (f, v), u in claims.items()],
        "hashes": hashes,
        "checked_at": now_iso(),
    }


def to_records(crawl: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in crawl["claims"]:
        out.append(
            {
                "framework": c["framework"],
                "variant": c["variant"],
                "status": "active",
                "tier": 4,
                "scope": "entity",
                "covers_resource": "unknown",
                "issuer": None,
                "certificate_id": None,
                "issued": None,
                "valid_until": None,
                "period_end": None,
                "evidence_url": c["url"],
                "source": SOURCE,
                "retrieved_at": crawl["checked_at"],
                "payload_hash": crawl["hashes"].get(c["url"]),
                "match_confidence": 1.0,
                "reviewer": None,
                "review_reason": "framework named on the vendor's own page",
                "next_check": None,
                "display": "",
                "detail": {"pages_visited": len(crawl["pages"])},
            }
        )
    return out
