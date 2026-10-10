"""FR-43..FR-47: news tagging, entity linking, clustering, ranking and feed parsing (offline)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentdossier.news import linking, sources


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _item(headline, days_ago=1.0, kind="news", outlet="Example News", url="https://news.example.com/a", **kw):
    it = sources.item(
        headline, url, outlet, _iso(days_ago), kind, kw.pop("summary", None), kw.pop("engagement", None)
    )
    it.update(kw)
    return it


RES = {
    "id": "r1",
    "name": "Salesforce Agentforce",
    "vendor": "Salesforce",
    "publisher_domain": "salesforce.com",
}


def test_tags_follow_first_matching_rule():
    assert sources.tag_for("Agentforce hit by data breach") == "security_incident"
    assert sources.tag_for("Regulator opens investigation into vendor") == "legal_regulatory"
    assert sources.tag_for("Vendor raises $50M Series B") == "funding"
    assert sources.tag_for("Something happened") == "news"


def test_distinctive_names():
    assert linking.distinctive("Salesforce Agentforce")
    assert linking.distinctive("LangGraph")
    assert not linking.distinctive("Muse")
    assert not linking.distinctive("AI Agent")


def test_link_confidence_needs_name_in_title_plus_second_signal():
    assert (
        linking.link_confidence(_item("Salesforce launches Agentforce 3"), RES) == 0.0
    )  # name not contiguous
    it = _item("Salesforce Agentforce adds voice", url="https://www.salesforce.com/news/x")
    assert linking.link_confidence(it, RES) >= linking.MIN_CONFIDENCE
    generic = {"id": "r2", "name": "Muse", "vendor": "Muse Labs"}
    assert linking.link_confidence(_item("Muse fight now"), generic) < linking.MIN_CONFIDENCE


def test_cluster_merges_same_story_within_48h():
    items = [
        _item("Salesforce Agentforce adds voice support", 1.0, outlet="A"),
        _item("Salesforce Agentforce adds voice support", 1.5, outlet="B", kind="community"),
        _item("Salesforce Agentforce adds voice support", 10.0, outlet="C"),
    ]
    out = linking.cluster(items)
    assert len(out) == 2
    top = next(c for c in out if c.get("cluster_size") == 2)
    assert "B" in top["also_in"] or top["outlet"] in ("A", "B")


def test_rank_applies_window_recency_and_diversity_caps():
    items = [
        {
            **_item(f"Salesforce Agentforce story {i}", days_ago=i, outlet="SameOutlet"),
            "link_confidence": 0.95,
        }
        for i in range(1, 7)
    ]
    items += [{**_item("Salesforce Agentforce old", days_ago=120), "link_confidence": 0.95}]
    items += [
        {
            **_item(f"Salesforce Agentforce release {i}", days_ago=2, kind="vendor", outlet=f"v{i}"),
            "link_confidence": 0.95,
        }
        for i in range(4)
    ]
    items += [
        {
            **_item(
                "Salesforce Agentforce on HN",
                days_ago=1,
                kind="community",
                outlet="Hacker News",
                engagement=300,
            ),
            "link_confidence": 0.95,
        }
    ]
    out = linking.rank(items, limit=10)
    outlets = [o["outlet"] for o in out]
    assert outlets.count("SameOutlet") <= 3
    assert sum(1 for o in out if o["kind"] == "vendor") <= 2
    assert all(o["headline"] != "Salesforce Agentforce old" for o in out)
    assert out[0]["kind"] == "community"  # fresh, high engagement wins
    assert all("rank_score" in o for o in out)


def test_parse_rss_and_atom_feeds():
    rss = """<?xml version="1.0"?><rss><channel><item><title>Agentforce 3 released</title>
    <link>https://salesforce.com/news/1</link><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate>
    <description>&lt;p&gt;Now with voice&lt;/p&gt;</description></item></channel></rss>"""
    out = sources.parse_feed(rss, "salesforce.com (vendor)")
    assert out[0]["headline"] == "Agentforce 3 released" and out[0]["kind"] == "vendor"
    assert out[0]["date"].startswith("2026-09-21") and out[0]["summary"] == "Now with voice"
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Release notes</title>
    <link href="https://salesforce.com/news/2"/><updated>2026-09-20T00:00:00Z</updated></entry></feed>"""
    out = sources.parse_feed(atom, "salesforce.com (vendor)")
    assert out[0]["url"] == "https://salesforce.com/news/2"


def test_parse_feed_rejects_dtd_and_garbage():
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "x">]><rss><channel><item><title>&e;</title></item></channel></rss>'
    assert sources.parse_feed(evil, "x") == []
    assert sources.parse_feed("not xml at all", "x") == []


def test_gdelt_circuit_breaker(monkeypatch):
    sources.gdelt_reset()
    calls = []

    def fake_get_json(store, source, key, url, **kw):
        calls.append(url)
        return None, None, None

    monkeypatch.setattr(sources, "get_json", fake_get_json)
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    assert sources.gdelt("Agentforce") == []
    try:
        sources.gdelt("LangGraph")
        raise AssertionError("expected GdeltUnavailableError")
    except sources.GdeltUnavailableError:
        pass
    n = len(calls)
    try:
        sources.gdelt("Third")
    except sources.GdeltUnavailableError:
        pass
    assert len(calls) == n  # no further requests once tripped
    sources.gdelt_reset()


def test_budget_skips_remaining_resources(monkeypatch, tmp_path):
    """A build budget that has already run out leaves resources unchecked, never half-checked."""
    from agentdossier.news import run as news_run
    from agentdossier.util import Deadline

    monkeypatch.setattr(sources, "hackernews", lambda *a, **k: [])
    monkeypatch.setattr(sources, "vendor_feed", lambda *a, **k: [])
    resources = [
        {
            "id": f"r{i}",
            "name": f"Distinctive Agent {i}",
            "vendor": "V",
            "publisher_domain": None,
            "url": None,
        }
        for i in range(3)
    ]
    expired = Deadline(0.0)  # zero minutes: expired immediately
    rep = news_run.run(resources, store=None, use_gdelt=False, use_nvd=False, deadline=expired)
    assert rep["news"]["skipped"] == 3 and rep["news"]["fetched"] == 0
    assert not any(r.get("news_checked") for r in resources)
    fresh = Deadline(None)
    rep = news_run.run(resources, store=None, use_gdelt=False, use_nvd=False, deadline=fresh)
    assert rep["news"]["fetched"] == 3 and all(r.get("news_checked") for r in resources)


def test_own_repository_release_links_without_name_in_title():
    res = {
        "id": "r1",
        "name": "Amazon Bedrock Agents",
        "vendor": "AWS",
        "external_ids": {"github": "awslabs/bedrock-agents"},
    }
    rel = _item(
        "bedrock-agents v1.4.0",
        url="https://github.com/awslabs/bedrock-agents/releases/tag/v1.4.0",
        outlet="GitHub releases",
    )
    assert linking.link_confidence(rel, res) == 1.0
    other = _item("foo v1", url="https://github.com/someone/else/releases/tag/v1", outlet="GitHub releases")
    assert linking.link_confidence(other, res) == 0.0


def test_short_names_still_get_releases_and_feeds_but_no_name_search(monkeypatch):
    from agentdossier.news import run as news_run

    calls: list[str] = []
    monkeypatch.setattr(sources, "hackernews", lambda name, **k: calls.append(f"hn:{name}") or [])
    monkeypatch.setattr(sources, "vendor_feed", lambda dom, **k: calls.append(f"feed:{dom}") or [])
    monkeypatch.setattr(
        sources,
        "github_releases",
        lambda full, **k: (
            calls.append(f"gh:{full}")
            or [
                _item(
                    "aider v0.9",
                    url=f"https://github.com/{full}/releases/tag/v0.9",
                    outlet="GitHub releases",
                    kind="vendor",
                )
            ]
        ),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    short = {
        "id": "a",
        "name": "Aider",
        "vendor": "Aider AI",
        "publisher_domain": "aider.chat",
        "external_ids": {"github": "Aider-AI/aider"},
    }
    long = {
        "id": "b",
        "name": "Salesforce Agentforce",
        "vendor": "Salesforce",
        "publisher_domain": "salesforce.com",
    }
    rep = news_run.run([short, long], store=None, use_gdelt=False, use_nvd=False)
    assert "hn:Aider" not in calls and "hn:Salesforce Agentforce" in calls
    assert "gh:Aider-AI/aider" in calls and "feed:aider.chat" in calls
    assert (
        rep["news"]["fetched"] == 2 and short["news_checked"] and short["news"][0]["headline"] == "aider v0.9"
    )
