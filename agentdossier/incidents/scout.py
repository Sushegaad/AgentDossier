"""Scout the public record for candidate incidents.

Reads the feeds in config/trace_sources.json (RSS 2.0 and Atom, parsed with the standard library —
no feed dependency), keeps the items whose title or summary names both an *agent* and an *attack*
(two keyword axes, so "AI agent" alone or "vulnerability" alone is not enough), drops anything that
is already an incident source or an existing candidate, and merges the rest into
data/curated/incident_candidates.yaml.

A candidate is what the source said — title, link, date, outlet, snippet, the terms that matched —
and nothing more. It carries ``status: new`` until a person promotes it (``incidents draft``) or
dismisses it. Candidates are never shown as incidents; the site only counts them.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..util import CONFIG_DIR, ROOT, FetchResult, fetch

SOURCES = CONFIG_DIR / "trace_sources.json"
CANDIDATES = ROOT / "data" / "curated" / "incident_candidates.yaml"
INCIDENTS = ROOT / "data" / "curated" / "incidents.yaml"
VERSION = "incident-candidates-1.0"
FEED_MAX_BYTES = 5_000_000  # advisory feeds (MSRC's update guide, say) run past 2 MB
SNIPPET_CHARS = 280
KEEP_NEW_DAYS = 180  # a candidate nobody touched for this long is dropped from the file
KEEP_DONE_DAYS = 365  # promoted/dismissed rows stay this long so the item does not resurface

Fetcher = Callable[[str], FetchResult]

HEADER = """# Candidate incidents found by the weekly scout (agentdossier incidents scout). Each row is a public
# item that mentioned both an AI agent and an attack, exactly as the source described it: a lead for
# the maintainer, never an incident. Promote one with `agentdossier incidents draft <id>` (it
# scaffolds a placeholder record in incidents.yaml for you to complete) or set its status to
# `dismissed` so it does not come back. Feeds and keywords: config/trace_sources.json.
"""


@dataclass
class Item:
    """One feed entry, before matching."""

    source_id: str
    title: str
    url: str
    date: str | None  # YYYY-MM-DD when the feed gave a usable date
    snippet: str


@dataclass
class ScoutReport:
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    items: int = 0
    matched: int = 0
    added: int = 0
    kept: int = 0
    pruned: int = 0
    already_incident: int = 0
    cve_advisories: int = 0  # advisory URLs handed to the CVE registry instead of filed here

    def as_dict(self) -> dict[str, Any]:
        return {
            "sources": self.sources,
            "items": self.items,
            "matched": self.matched,
            "added": self.added,
            "kept": self.kept,
            "pruned": self.pruned,
            "already_incident": self.already_incident,
            "cve_advisories": self.cve_advisories,
        }


# --- feeds -----------------------------------------------------------------------------------------


def _local(tag: str) -> str:
    """Element name without its namespace."""
    return tag.rsplit("}", 1)[-1].lower()


def _text(el: ET.Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    wanted = {n.lower() for n in names}
    for c in el:
        if _local(c.tag) in wanted:
            return c
    return None


def parse_date(raw: str | None) -> str | None:
    """RFC 2822 (RSS) or ISO 8601 (Atom) → YYYY-MM-DD; None when it cannot be read."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        return email.utils.parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(raw: str, limit: int = SNIPPET_CHARS) -> str:
    text = _WS.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_feed(body: bytes, source_id: str) -> list[Item]:
    """Items from an RSS 2.0 ``<channel><item>`` or Atom ``<feed><entry>`` document."""
    head = body[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:
        raise ValueError("feed declares a DOCTYPE or entities; refused")
    root = ET.fromstring(body)  # noqa: S314 - size-capped, DOCTYPE/entity-free input from a curated list
    items: list[Item] = []
    for el in root.iter():
        kind = _local(el.tag)
        if kind not in ("item", "entry"):
            continue
        title = _text(_child(el, "title"))
        if kind == "item":
            url = _text(_child(el, "link")) or _text(
                _child(el, "guid")
            )  # some feeds only put the URL in guid
            date = parse_date(_text(_child(el, "pubDate", "date", "updated")) or None)
            summary = _text(_child(el, "description", "encoded", "summary"))
        else:
            url = ""
            for link in (c for c in el if _local(c.tag) == "link"):
                href = link.get("href")
                if link.get("rel", "alternate") == "alternate" and href:
                    url = href
                    break
            date = parse_date(_text(_child(el, "published", "updated")) or None)
            summary = _text(_child(el, "summary", "content"))
        if not title or not url or not url.startswith(("http://", "https://")):
            continue
        items.append(Item(source_id, strip_html(title, 300), url.strip(), date, strip_html(summary)))
    return items


# --- matching --------------------------------------------------------------------------------------

_DROP_QUERY = ("utm_", "fbclid", "gclid", "ref", "ref_src", "mc_cid", "mc_eid")


def normalize_url(url: str) -> str:
    """Same page, same key: lower-case host without www, no tracking query, no fragment, no trailing slash."""
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = urllib.parse.urlencode(
        [
            (k, v)
            for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith(_DROP_QUERY)
        ]
    )
    path = re.sub(r"/+$", "", p.path) or ""
    return f"{host}{path}" + (f"?{query}" if query else "")


_ADVISORY_HOSTS = (
    "msrc.microsoft.com/update-guide",
    "nvd.nist.gov/vuln",
    "cve.org/cverecord",
    "cve.mitre.org",
    "github.com/advisories",
)


def is_cve_advisory(url: str) -> bool:
    """A link that is itself a CVE record or vendor advisory page (not a write-up about an event)."""
    low = normalize_url(url)
    return any(low.startswith(h) for h in _ADVISORY_HOSTS)


def candidate_id(url: str) -> str:
    return "cand-" + hashlib.sha256(normalize_url(url).encode()).hexdigest()[:10]


def _term_re(term: str) -> re.Pattern[str]:
    # short terms ("mcp", "rag", "cve-") only as whole words, so "storage" does not match "rag"
    esc = re.escape(term.lower())
    return re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])" if len(term) <= 4 else esc)


def match(item: Item, keywords: dict[str, list[str]]) -> tuple[int, list[str]]:
    """(score, matched terms). Score 0 unless at least one *agent* and one *attack* term match."""
    text = f"{item.title} {item.snippet}".lower()
    hits: dict[str, list[str]] = {}
    for axis, terms in keywords.items():
        hits[axis] = [t for t in terms if _term_re(t).search(text)]
    if not hits.get("agent") or not hits.get("attack"):
        return 0, []
    matched = sorted({t for ts in hits.values() for t in ts})
    title = item.title.lower()
    in_title = sum(1 for t in matched if _term_re(t).search(title))
    return len(matched) + in_title, matched


# --- files -----------------------------------------------------------------------------------------


def load_sources(path: Path = SOURCES) -> dict[str, Any]:
    import json  # noqa: PLC0415

    return json.loads(path.read_text())


def _yaml():  # noqa: ANN202
    import yaml  # noqa: PLC0415

    return yaml


def read_candidates(path: Path = CANDIDATES) -> dict[str, Any]:
    if not path.exists():
        return {"version": VERSION, "scouted_on": None, "candidates": []}
    doc = _yaml().safe_load(path.read_text()) or {}
    doc.setdefault("candidates", [])
    return doc


def write_candidates(doc: dict[str, Any], path: Path = CANDIDATES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _yaml().safe_dump(doc, sort_keys=False, allow_unicode=True, width=110, default_flow_style=False)
    path.write_text(HEADER + body)


def incident_source_urls(path: Path = INCIDENTS) -> set[str]:
    """Normalised URLs already cited by an incident (published or placeholder)."""
    if not path.exists():
        return set()
    doc = _yaml().safe_load(path.read_text()) or {}
    out: set[str] = set()
    for inc in doc.get("incidents") or []:
        for s in inc.get("sources") or []:
            if s.get("url"):
                out.add(normalize_url(s["url"]))
    return out


# --- the run ---------------------------------------------------------------------------------------


def _default_fetcher(url: str) -> FetchResult:
    return fetch(
        url,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"},
        timeout=20.0,
        retries=1,
        max_bytes=FEED_MAX_BYTES,
    )


def offline_fetcher(feed_dir: Path, config: dict[str, Any]) -> Fetcher:
    """A fetcher that reads ``<source_id>.xml`` from a directory: tests and dry runs, no network."""
    by_url = {s["url"]: s["id"] for s in config.get("sources") or []}

    def _get(url: str) -> FetchResult:
        sid = by_url.get(url)
        f = feed_dir / f"{sid}.xml"
        if sid is None or not f.exists():
            return FetchResult(url, 0, {}, b"", error="offline: no fixture")
        return FetchResult(url, 200, {}, f.read_bytes())

    return _get


def scout(
    config: dict[str, Any],
    existing: dict[str, Any],
    *,
    fetcher: Fetcher | None = None,
    known_urls: set[str] | None = None,
    today: dt.date | None = None,
) -> tuple[dict[str, Any], ScoutReport]:
    """Fetch every source, match, dedup, merge into ``existing``. Returns (new document, report).

    Source failures are recorded in the report, never raised: one dead feed must not stop the run."""
    fetcher = fetcher or _default_fetcher
    today = today or dt.date.today()
    known_urls = incident_source_urls() if known_urls is None else known_urls
    since_days = int(config.get("since_days", 120))
    cutoff = (today - dt.timedelta(days=since_days)).isoformat()
    keywords: dict[str, list[str]] = config.get("keywords") or {}
    report = ScoutReport()

    by_id: dict[str, dict[str, Any]] = {c["id"]: dict(c) for c in existing.get("candidates") or []}
    seen_this_run: set[str] = set()

    for src in config.get("sources") or []:
        sid = src["id"]
        rep: dict[str, Any] = {"name": src.get("name", sid), "items": 0, "matched": 0}
        res = fetcher(src["url"])
        if not res.ok:
            rep["error"] = res.error or f"HTTP {res.status}"
            report.sources[sid] = rep
            continue
        try:
            items = parse_feed(res.body, sid)
        except (ET.ParseError, ValueError) as exc:
            rep["error"] = f"unparseable: {exc}"
            report.sources[sid] = rep
            continue
        rep["items"] = len(items)
        report.items += len(items)
        for it in items:
            if it.date and it.date < cutoff:
                continue
            score, terms = match(it, keywords)
            if not score:
                continue
            rep["matched"] += 1
            report.matched += 1
            key = normalize_url(it.url)
            if key in known_urls:
                report.already_incident += 1
                continue
            if is_cve_advisory(it.url):
                # a bare advisory is a vulnerability record, not an incident: the CVE registry lists
                # it (agentdossier cves update reads NVD, which carries every CNA advisory)
                report.cve_advisories += 1
                continue
            cid = candidate_id(it.url)
            if cid in seen_this_run:
                continue
            seen_this_run.add(cid)
            if cid in by_id:
                row = by_id[cid]
                row["last_seen"] = today.isoformat()
                row["score"] = max(int(row.get("score") or 0), score)
                report.kept += 1
                continue
            by_id[cid] = {
                "id": cid,
                "status": "new",
                "title": it.title,
                "url": it.url,
                "date": it.date,
                "outlet": src.get("name", sid),
                "source_id": sid,
                "kind": src.get("kind"),
                "matched": terms,
                "score": score,
                "snippet": it.snippet,
                "first_seen": today.isoformat(),
                "last_seen": today.isoformat(),
            }
            report.added += 1
        report.sources[sid] = rep

    # prune: untouched `new` rows age out; promoted/dismissed rows are kept longer so they do not resurface
    kept_rows: list[dict[str, Any]] = []
    for row in by_id.values():
        anchor = row.get("last_seen") or row.get("first_seen") or today.isoformat()
        age = (today - dt.date.fromisoformat(anchor)).days
        limit = KEEP_NEW_DAYS if row.get("status") == "new" else KEEP_DONE_DAYS
        if age > limit:
            report.pruned += 1
            continue
        kept_rows.append(row)

    # new first, then by score, newest date, id — a stable order so the weekly diff is readable
    order = {"new": 0, "promoted": 1, "dismissed": 2}
    kept_rows.sort(
        key=lambda r: (
            order.get(r.get("status", "new"), 9),
            -int(r.get("score") or 0),
            r.get("date") or "",
            r["id"],
        ),
    )
    doc = {
        "version": VERSION,
        "scouted_on": today.isoformat(),
        "sources_checked": len(config.get("sources") or []),
        "sources_failed": sorted(k for k, v in report.sources.items() if v.get("error")),
        "candidates": kept_rows,
    }
    return doc, report


# --- promote / dismiss -----------------------------------------------------------------------------


def next_incident_id(path: Path = INCIDENTS, year: int | None = None) -> str:
    year = year or dt.date.today().year
    doc: dict[str, Any] = (_yaml().safe_load(path.read_text()) or {}) if path.exists() else {}
    nums = [
        int(inc["id"].rsplit("-", 1)[1])
        for inc in doc.get("incidents") or []
        if isinstance(inc.get("id"), str) and inc["id"].startswith(f"TR-{year}-")
    ]
    return f"TR-{year}-{(max(nums) + 1 if nums else 1):03d}"


def _q(s: str) -> str:
    """A double-quoted YAML scalar."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def placeholder_block(cand: dict[str, Any], new_id: str, today: dt.date) -> str:
    """A schema-valid ``status: placeholder`` record, hand-formatted like the rest of incidents.yaml,
    with the candidate's title/link/date/outlet filled in and TODO markers where a person must write."""
    date = cand.get("date") or today.isoformat()
    outlet = cand.get("outlet") or "source"
    lines = [
        "",
        f"  - id: {new_id}",
        "    status: placeholder  # TODO: complete the record, then set to published",
        f"    title: {_q(cand['title'])}",
        f"    date: {date}",
        "    window: null",
        "    ai_role: target  # TODO: attacker | defender | target",
        "    category: red_team  # TODO: red_team | injection_eval | incident | ctf",
        "    summary: >-",
        f"      TODO (as reported). Candidate {cand['id']} from {outlet}: {cand.get('snippet') or cand['title']}",
        "    attacker:",
        '      description: "TODO"',
        "    defender:",
        '      description: "TODO"',
        "    scale: null",
        "    impact: null",
        "    tactics: []  # TODO: MITRE ATT&CK tactic ids, e.g. [TA0001, TA0010]",
        "    timeline:",
        f'      - {{ date: "{date}", text: "TODO", tier: null, source: "1" }}',
        "    lessons: []",
        "    models_named: []",
        "    related_agents: []",
        "    vendor_response: null",
        "    sources:",
        f"      - {{ title: {_q(cand['title'])}, url: {_q(cand['url'])}, outlet: {_q(outlet)}, date: {_q(date)} }}",
        "    reviewer: null",
        "    checked_on: null",
        "",
    ]
    return "\n".join(lines)


def promote(
    cand_id: str,
    *,
    candidates_path: Path = CANDIDATES,
    incidents_path: Path = INCIDENTS,
    new_id: str | None = None,
    today: dt.date | None = None,
) -> str:
    """Append a placeholder record for the candidate to incidents.yaml and mark it promoted."""
    today = today or dt.date.today()
    doc = read_candidates(candidates_path)
    row = next((c for c in doc["candidates"] if c["id"] == cand_id), None)
    if row is None:
        raise KeyError(cand_id)
    new_id = new_id or next_incident_id(incidents_path, today.year)
    text = incidents_path.read_text()
    incidents_path.write_text(text.rstrip("\n") + "\n" + placeholder_block(row, new_id, today))
    row["status"] = "promoted"
    row["promoted_to"] = new_id
    row["last_seen"] = today.isoformat()
    write_candidates(doc, candidates_path)
    return new_id


def dismiss(cand_id: str, note: str | None = None, *, candidates_path: Path = CANDIDATES) -> None:
    doc = read_candidates(candidates_path)
    row = next((c for c in doc["candidates"] if c["id"] == cand_id), None)
    if row is None:
        raise KeyError(cand_id)
    row["status"] = "dismissed"
    if note:
        row["note"] = note
    write_candidates(doc, candidates_path)
