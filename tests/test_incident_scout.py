"""The incident scout: feeds → candidates, never incidents. Offline: fixtures stand in for the network."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import jsonschema
import pytest

from agentdossier.incidents import scout as sc
from agentdossier.util import FetchResult

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parent.parent
TODAY = dt.date(2026, 10, 12)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Press</title>
<item><title>Zero-click prompt injection makes an AI agent exfiltrate CRM data</title>
  <link>https://press.example/2026/agent-exfil?utm_source=rss</link>
  <pubDate>Mon, 05 Oct 2026 09:00:00 GMT</pubDate>
  <description><![CDATA[<p>Researchers showed a <b>coding agent</b> leaking secrets.</p>]]></description></item>
<item><title>Quarterly earnings beat expectations</title>
  <link>https://press.example/2026/earnings</link>
  <pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate><description>Shares up.</description></item>
<item><title>Storage vendor patches RAID bug</title>
  <link>https://press.example/2026/storage</link>
  <pubDate>Mon, 05 Oct 2026 11:00:00 GMT</pubDate><description>An exploit for the storage array.</description></item>
<item><title>Old AI agent attack from last year</title>
  <link>https://press.example/2025/old-attack</link>
  <pubDate>Mon, 06 Jan 2025 11:00:00 GMT</pubDate><description>prompt injection</description></item>
<item><title>ForcedLeak: Agentforce prompt injection (already an incident)</title>
  <link>https://thehackernews.com/2025/09/salesforce-patches-critical-forcedleak.html</link>
  <pubDate>Thu, 25 Sep 2026 11:00:00 GMT</pubDate><description>agent attack</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Lab</title>
<entry><title>MCP server flaw gives remote code execution in a coding assistant</title>
  <link rel="alternate" href="https://lab.example/posts/mcp-rce"/>
  <published>2026-10-01T12:00:00Z</published>
  <summary>Indirect prompt injection through an MCP tool leads to RCE.</summary></entry>
<entry><title>We hired a new intern</title>
  <link href="https://lab.example/posts/intern"/>
  <updated>2026-10-02T12:00:00Z</updated><summary>Welcome!</summary></entry>
</feed>"""

CONFIG = {
    "since_days": 120,
    "sources": [
        {"id": "press", "name": "Press", "url": "https://press.example/feed", "kind": "press"},
        {"id": "lab", "name": "Lab", "url": "https://lab.example/atom", "kind": "researcher"},
        {"id": "dead", "name": "Dead feed", "url": "https://dead.example/feed", "kind": "press"},
    ],
    "keywords": json.loads((ROOT / "config" / "trace_sources.json").read_text())["keywords"],
}


def fake_fetcher(url: str) -> FetchResult:
    if url == "https://press.example/feed":
        return FetchResult(url, 200, {}, RSS)
    if url == "https://lab.example/atom":
        return FetchResult(url, 200, {}, ATOM)
    return FetchResult(url, 0, {}, b"", error="connection refused")


def test_parse_rss_and_atom_with_dates_and_links():
    rss = sc.parse_feed(RSS, "press")
    assert [i.date for i in rss][:2] == ["2026-10-05", "2026-10-05"]
    assert rss[0].snippet == "Researchers showed a coding agent leaking secrets."  # HTML stripped
    atom = sc.parse_feed(ATOM, "lab")
    assert atom[0].url == "https://lab.example/posts/mcp-rce" and atom[0].date == "2026-10-01"
    assert atom[1].url == "https://lab.example/posts/intern"  # link without rel is alternate


def test_feed_with_doctype_is_refused():
    with pytest.raises(ValueError):
        sc.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>', "x")


def test_match_needs_both_axes_and_whole_words_for_short_terms():
    kw = CONFIG["keywords"]
    hit = sc.Item(
        "p", "Zero-click prompt injection makes an AI agent exfiltrate CRM data", "https://x", None, ""
    )
    score, terms = sc.match(hit, kw)
    assert score > 0 and "prompt injection" in terms and "ai agent" in terms
    only_attack = sc.Item(
        "p", "Storage vendor patches RAID bug", "https://x", None, "An exploit for the array."
    )
    assert sc.match(only_attack, kw) == (0, [])  # "storage" must not match "rag"; no agent term
    only_agent = sc.Item("p", "New AI agent launched", "https://x", None, "Agentic workflows for sales.")
    assert sc.match(only_agent, kw) == (0, [])


def test_normalize_url_and_stable_candidate_id():
    a = "https://www.press.example/2026/agent-exfil/?utm_source=rss&utm_medium=x#top"
    b = "http://press.example/2026/agent-exfil"
    assert sc.normalize_url(a) == sc.normalize_url(b) == "press.example/2026/agent-exfil"
    assert sc.candidate_id(a) == sc.candidate_id(b) and sc.candidate_id(a).startswith("cand-")


KNOWN = {sc.normalize_url("https://thehackernews.com/2025/09/salesforce-patches-critical-forcedleak.html")}


def test_scout_filters_dedups_reports_and_never_writes_incidents(tmp_path: Path):
    doc, rep = sc.scout(CONFIG, {"candidates": []}, fetcher=fake_fetcher, known_urls=KNOWN, today=TODAY)
    titles = [c["title"] for c in doc["candidates"]]
    assert "Zero-click prompt injection makes an AI agent exfiltrate CRM data" in titles
    assert "MCP server flaw gives remote code execution in a coding assistant" in titles
    assert all("earnings" not in t and "Storage" not in t for t in titles)  # no match
    assert all("Old AI agent" not in t for t in titles)  # outside the window
    assert all("ForcedLeak" not in t for t in titles)  # already an incident source
    assert rep.already_incident == 1 and rep.added == 2
    assert rep.sources["dead"]["error"] == "connection refused" and doc["sources_failed"] == ["dead"]
    assert all(c["status"] == "new" and c["first_seen"] == "2026-10-12" for c in doc["candidates"])
    assert doc["scouted_on"] == "2026-10-12" and doc["sources_checked"] == 3
    # the tracking query was kept off the stored URL? no — the URL is stored as published; the id is normalised
    assert doc["candidates"][0]["url"].startswith("https://")


def test_rerun_keeps_statuses_and_prunes_stale_rows():
    doc1, _ = sc.scout(CONFIG, {"candidates": []}, fetcher=fake_fetcher, known_urls=KNOWN, today=TODAY)
    # a person dismissed one and promoted the other; a stale `new` row from long ago is also present
    for c in doc1["candidates"]:
        c["status"] = "dismissed" if "MCP" in c["title"] else "promoted"
    stale = {
        "id": "cand-stale000",
        "status": "new",
        "title": "old",
        "url": "https://old.example/x",
        "first_seen": "2026-01-01",
        "last_seen": "2026-01-01",
    }
    doc2, rep = sc.scout(
        CONFIG,
        {"candidates": [*doc1["candidates"], stale]},
        fetcher=fake_fetcher,
        known_urls=KNOWN,
        today=TODAY,
    )
    statuses = {c["title"]: c["status"] for c in doc2["candidates"]}
    assert statuses["MCP server flaw gives remote code execution in a coding assistant"] == "dismissed"
    assert statuses["Zero-click prompt injection makes an AI agent exfiltrate CRM data"] == "promoted"
    assert rep.added == 0 and rep.kept == 2 and rep.pruned == 1
    assert all(c["id"] != "cand-stale000" for c in doc2["candidates"])
    assert [c["status"] for c in doc2["candidates"]] == [
        "promoted",
        "dismissed",
    ]  # new first, then promoted, dismissed


def test_candidates_file_roundtrip_and_header(tmp_path: Path):
    doc, _ = sc.scout(CONFIG, {"candidates": []}, fetcher=fake_fetcher, known_urls=set(), today=TODAY)
    path = tmp_path / "incident_candidates.yaml"
    sc.write_candidates(doc, path)
    text = path.read_text()
    assert text.startswith("# Candidate incidents found by the weekly scout")
    assert sc.read_candidates(path)["candidates"] == doc["candidates"]


def test_promote_appends_a_schema_valid_placeholder_and_dismiss_marks(tmp_path: Path):
    doc, _ = sc.scout(CONFIG, {"candidates": []}, fetcher=fake_fetcher, known_urls=set(), today=TODAY)
    cands = tmp_path / "incident_candidates.yaml"
    sc.write_candidates(doc, cands)
    incidents = tmp_path / "incidents.yaml"
    incidents.write_text((ROOT / "data" / "curated" / "incidents.yaml").read_text())
    before = len(yaml.safe_load(incidents.read_text())["incidents"])
    cid = next(c["id"] for c in doc["candidates"] if "MCP" in c["title"])

    expected = sc.next_incident_id(incidents, TODAY.year)  # one past the highest TR-2026-NNN in the file
    new_id = sc.promote(cid, candidates_path=cands, incidents_path=incidents, today=TODAY)
    assert new_id == expected and expected > "TR-2026-013"
    rows = yaml.safe_load(incidents.read_text())["incidents"]
    assert len(rows) == before + 1
    rec = rows[-1]
    assert rec["id"] == new_id and rec["status"] == "placeholder"
    assert rec["sources"][0]["url"] == "https://lab.example/posts/mcp-rce"
    schema = json.loads((ROOT / "schema" / "incident_record.schema.json").read_text())
    rec = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in rec.items()}
    jsonschema.Draft202012Validator(schema).validate(rec)  # a person completes it; it already validates
    # the rest of the file is byte-identical: we appended, never rewrote the hand-formatted records
    assert incidents.read_text().startswith(
        (ROOT / "data" / "curated" / "incidents.yaml").read_text().rstrip("\n")
    )
    assert next(c for c in sc.read_candidates(cands)["candidates"] if c["id"] == cid)["status"] == "promoted"

    other = next(c["id"] for c in doc["candidates"] if c["id"] != cid)
    sc.dismiss(other, "not an agent", candidates_path=cands)
    row = next(c for c in sc.read_candidates(cands)["candidates"] if c["id"] == other)
    assert row["status"] == "dismissed" and row["note"] == "not an agent"
    with pytest.raises(KeyError):
        sc.promote("cand-nope", candidates_path=cands, incidents_path=incidents, today=TODAY)


def test_shipped_sources_config_is_well_formed():
    cfg = json.loads((ROOT / "config" / "trace_sources.json").read_text())
    ids = [s["id"] for s in cfg["sources"]]
    assert len(ids) == len(set(ids)) and all(s["url"].startswith("https://") for s in cfg["sources"])
    assert set(cfg["keywords"]) == {"agent", "attack"} and all(cfg["keywords"].values())
