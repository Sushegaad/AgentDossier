"""Official records: NVD API 2.0 (the CVE.org record plus CVSS, CWE and CPE) and the CISA KEV catalog.

Everything network-facing takes a ``fetcher`` so tests and container runs replay saved responses
(``--offline <dir>``: any ``*.json`` NVD responses plus ``kev.json``). The parser is pure.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.parse
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..util import FetchResult, fetch

NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
PAGE = 2000
WINDOW_DAYS = 120  # NVD caps a date range at 120 days
Fetcher = Callable[[str], FetchResult]


# --- parsing (pure) --------------------------------------------------------------------------------


def _english(descs: Iterable[dict[str, Any]]) -> str:
    for d in descs:
        if d.get("lang") == "en" and d.get("value"):
            return str(d["value"]).strip()
    return ""


def _cvss(metrics: dict[str, Any]) -> dict[str, Any] | None:
    """Best available score: v4.0, then v3.1, v3.0, v2; NVD's own ("Primary") before a CNA's."""
    for key, version in (
        ("cvssMetricV40", "4.0"),
        ("cvssMetricV31", "3.1"),
        ("cvssMetricV30", "3.0"),
        ("cvssMetricV2", "2.0"),
    ):
        entries = metrics.get(key) or []
        if not entries:
            continue
        entries = sorted(entries, key=lambda e: 0 if e.get("type") == "Primary" else 1)
        e = entries[0]
        data = e.get("cvssData") or {}
        score = data.get("baseScore")
        if score is None:
            continue
        severity = data.get("baseSeverity") or e.get("baseSeverity")
        if not severity:  # v2 keeps severity outside cvssData
            s = float(score)
            severity = "LOW" if s < 4 else "MEDIUM" if s < 7 else "HIGH" if s < 9 else "CRITICAL"
        return {
            "version": version,
            "score": float(score),
            "severity": str(severity).upper(),
            "vector": str(data.get("vectorString") or ""),
            "source": str(e.get("source") or ""),
        }
    return None


def _cwes(weaknesses: Iterable[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for w in weaknesses:
        for d in w.get("description") or []:
            v = str(d.get("value") or "")
            if v and v not in out:
                out.append(v)
    return out


def _products(configurations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Affected products from CPE match criteria: cpe:2.3:part:vendor:product:version:..."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for cfg in configurations:
        for node in cfg.get("nodes") or []:
            for m in node.get("cpeMatch") or []:
                if not m.get("vulnerable", True):
                    continue
                parts = str(m.get("criteria") or "").split(":")
                if len(parts) < 5:
                    continue
                vendor, product = parts[3], parts[4]
                key = (vendor, product)
                row = seen.setdefault(
                    key,
                    {
                        "vendor": vendor,
                        "product": product,
                        "versions_affected": None,
                        "fixed_in": None,
                        "product_id": None,
                    },
                )
                lo = m.get("versionStartIncluding")
                hi_ex = m.get("versionEndExcluding")
                hi_in = m.get("versionEndIncluding")
                if hi_ex and not row["fixed_in"]:
                    row["fixed_in"] = str(hi_ex)
                rng = ""
                if lo:
                    rng += f">= {lo} "
                if hi_ex:
                    rng += f"< {hi_ex}"
                elif hi_in:
                    rng += f"<= {hi_in}"
                elif parts[5] not in ("*", "-"):
                    rng += parts[5]
                if rng.strip() and not row["versions_affected"]:
                    row["versions_affected"] = rng.strip()
    return list(seen.values())


def _references(refs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in refs:
        url = str(r.get("url") or "")
        if not url.startswith("http"):
            continue
        tags = [str(t) for t in (r.get("tags") or [])]
        if "Exploit" in tags:  # the registry links advisories and records, never exploit write-ups
            continue
        out.append({"url": url, "source": r.get("source"), "tags": tags})
    return out


def parse_item(item: dict[str, Any], retrieved_on: str) -> dict[str, Any] | None:
    """One NVD ``vulnerabilities[]`` entry → the registry's record shape (before match/overrides)."""
    c = item.get("cve") or {}
    cid = str(c.get("id") or "")
    if not cid.startswith("CVE-"):
        return None
    products = _products(c.get("configurations") or [])
    refs = _references(c.get("references") or [])
    patch = next((r for r in refs if "Patch" in r["tags"]), None)
    fixed_in = next((p["fixed_in"] for p in products if p.get("fixed_in")), None)
    fix = {
        "status": "fixed" if (patch or fixed_in) else "unknown",
        "version": fixed_in,
        "url": patch["url"] if patch else None,
    }
    return {
        "id": cid,
        "description": _english(c.get("descriptions") or []),
        "published": str(c.get("published") or "")[:10],
        "last_modified": str(c.get("lastModified") or "")[:10],
        "vuln_status": c.get("vulnStatus"),
        "cna": c.get("sourceIdentifier"),
        "cvss": _cvss(c.get("metrics") or {}),
        "cwe": _cwes(c.get("weaknesses") or []),
        "products": products,
        "category": "unclassified",
        "surface": [],
        "kev": None,
        "fix": fix,
        "references": refs,
        "related_agents": [],
        "related_incidents": [],
        "match": {"tests": [], "terms": []},
        "status": "candidate",
        "note": None,
        "reviewer": None,
        "checked_on": None,
        "retrieved_on": retrieved_on,
    }


def parse_response(doc: dict[str, Any], retrieved_on: str) -> list[dict[str, Any]]:
    out = []
    for item in doc.get("vulnerabilities") or []:
        rec = parse_item(item, retrieved_on)
        if rec:
            out.append(rec)
    return out


def parse_kev(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for v in doc.get("vulnerabilities") or []:
        cid = str(v.get("cveID") or "")
        if cid:
            out[cid] = {
                "added": str(v.get("dateAdded") or ""),
                "due": v.get("dueDate"),
                "ransomware": v.get("knownRansomwareCampaignUse"),
            }
    return out


# --- query planning --------------------------------------------------------------------------------


def _q(params: dict[str, str | int]) -> str:
    return NVD_API + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def backfill_queries(config: dict[str, Any]) -> list[str]:
    """Targeted queries that find candidates without reading every CVE since 2023: an exact-phrase
    keyword search per product name and vocabulary phrase, and one query per agent-specific CWE."""
    bf = config.get("backfill") or {}
    out: list[str] = []
    for kw in bf.get("keyword_queries") or []:
        out.append(_q({"keywordSearch": kw, "keywordExactMatch": "", "resultsPerPage": PAGE}))
    for cwe in bf.get("cwe_queries") or []:
        out.append(_q({"cweId": cwe, "resultsPerPage": PAGE}))
    return out


def window_queries(since: dt.date, until: dt.date) -> list[str]:
    """Everything modified in [since, until], in ≤120-day windows (the weekly run uses one)."""
    out: list[str] = []
    start = since
    while start <= until:
        end = min(start + dt.timedelta(days=WINDOW_DAYS - 1), until)
        out.append(
            _q(
                {
                    "lastModStartDate": f"{start.isoformat()}T00:00:00.000",
                    "lastModEndDate": f"{end.isoformat()}T23:59:59.999",
                    "resultsPerPage": PAGE,
                }
            )
        )
        start = end + dt.timedelta(days=1)
    return out


# --- fetching --------------------------------------------------------------------------------------


def _default_fetcher(api_key: str | None) -> Fetcher:
    headers = {"apiKey": api_key} if api_key else {}
    delay = 0.7 if api_key else 6.5  # NVD: 50 requests / 30 s with a key, 5 without

    def _get(url: str) -> FetchResult:
        r = fetch(url, headers=headers, timeout=60.0, retries=2, max_bytes=50_000_000)
        time.sleep(delay)
        return r

    return _get


def fetch_all_pages(url: str, fetcher: Fetcher) -> tuple[list[dict[str, Any]], list[str]]:
    """Follow NVD's startIndex paging; returns (vulnerability items, errors)."""
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    start = 0
    while True:
        page_url = url if start == 0 else f"{url}&startIndex={start}"
        r = fetcher(page_url)
        if not r.ok:
            errors.append(f"{page_url[:120]}… {r.error or r.status}")
            break
        try:
            doc = r.json()
        except ValueError:
            errors.append(f"{page_url[:120]}… invalid JSON")
            break
        items.extend(doc.get("vulnerabilities") or [])
        total = int(doc.get("totalResults") or 0)
        start += int(doc.get("resultsPerPage") or PAGE)
        if start >= total:
            break
    return items, errors


def collect(
    urls: Iterable[str], fetcher: Fetcher, retrieved_on: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Run the queries, parse, dedupe by id (newest last_modified wins)."""
    recs: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for url in urls:
        items, errs = fetch_all_pages(url, fetcher)
        errors.extend(errs)
        for item in items:
            rec = parse_item(item, retrieved_on)
            if rec and (rec["id"] not in recs or rec["last_modified"] >= recs[rec["id"]]["last_modified"]):
                recs[rec["id"]] = rec
    return recs, errors


def fetch_kev(fetcher: Fetcher) -> tuple[dict[str, dict[str, Any]], str | None]:
    r = fetcher(KEV_URL)
    if not r.ok:
        return {}, r.error or f"HTTP {r.status}"
    try:
        return parse_kev(r.json()), None
    except ValueError:
        return {}, "invalid JSON"


def offline_fetcher(directory: Path) -> Fetcher:
    """Replay a directory of saved responses: ``kev.json`` for the KEV URL, and for NVD queries a
    manifest ``queries.json`` ({url: filename}) or, failing that, every other ``*.json`` concatenated
    and served for each NVD query (collect dedupes, so a plain dump of responses works). Stateless."""
    manifest: dict[str, str] = {}
    mf = directory / "queries.json"
    if mf.exists():
        manifest = json.loads(mf.read_text())

    def _dump() -> bytes:
        vulns: list[dict[str, Any]] = []
        for f in sorted(directory.glob("*.json")):
            if f.name in ("kev.json", "queries.json"):
                continue
            try:
                vulns.extend(json.loads(f.read_text()).get("vulnerabilities") or [])
            except (ValueError, AttributeError):
                continue
        return json.dumps(
            {"totalResults": len(vulns), "resultsPerPage": max(len(vulns), 1), "vulnerabilities": vulns}
        ).encode()

    def _get(url: str) -> FetchResult:
        if url == KEV_URL:
            f = directory / "kev.json"
            return (
                FetchResult(url, 200, {}, f.read_bytes())
                if f.exists()
                else FetchResult(url, 0, {}, b"", error="offline: no kev.json")
            )
        name = manifest.get(url)
        if name:
            f = directory / name
            return (
                FetchResult(url, 200, {}, f.read_bytes())
                if f.exists()
                else FetchResult(url, 0, {}, b"", error=f"offline: no {name}")
            )
        if manifest:  # a manifest exists but does not know this query: an empty page, not the dump
            return FetchResult(url, 200, {}, b'{"totalResults":0,"resultsPerPage":2000,"vulnerabilities":[]}')
        return FetchResult(url, 200, {}, _dump())

    return _get
