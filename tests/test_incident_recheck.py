"""The weekly source re-check: which incident sources still answer. Offline, with a scripted fetcher."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from agentdossier.incidents import recheck as rc
from agentdossier.util import FetchResult

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).parent.parent
TODAY = dt.date(2026, 10, 12)

# url → (HEAD result, GET result)
SCRIPT: dict[str, tuple[FetchResult, FetchResult]] = {
    "https://ok.example/a": (
        FetchResult("https://ok.example/a", 200, {}, b""),
        FetchResult("https://ok.example/a", 200, {}, b"x"),
    ),
    "https://moved.example/old": (
        FetchResult("https://archive.other/new-home", 200, {}, b""),
        FetchResult("https://archive.other/new-home", 200, {}, b""),
    ),
    "https://gone.example/x": (
        FetchResult("https://gone.example/x", 404, {}, b"", error="HTTP 404"),
        FetchResult("https://gone.example/x", 404, {}, b"", error="HTTP 404"),
    ),
    "https://nohead.example/p": (
        FetchResult("https://nohead.example/p", 405, {}, b"", error="HTTP 405"),  # HEAD not allowed
        FetchResult("https://nohead.example/p", 200, {}, b"ok"),  # GET fine → ok
    ),
    "https://botwall.example/p": (
        FetchResult("https://botwall.example/p", 403, {}, b"", error="HTTP 403"),
        FetchResult("https://botwall.example/p", 403, {}, b"", error="HTTP 403"),
    ),
    "https://down.example/p": (
        FetchResult("https://down.example/p", 0, {}, b"", error="TimeoutError: timed out"),
        FetchResult("https://down.example/p", 0, {}, b"", error="TimeoutError: timed out"),
    ),
}
CALLS: list[tuple[str, str]] = []


def scripted(url: str, method: str) -> FetchResult:
    CALLS.append((url, method))
    head, get = SCRIPT[url]
    return head if method == "HEAD" else get


def test_classify_every_status_class():
    assert rc.classify(FetchResult("https://a/b", 200, {}, b""), "https://a/b") == "ok"
    assert rc.classify(FetchResult("https://a/c", 200, {}, b""), "https://www.a/b/") == "moved"
    assert (
        rc.classify(FetchResult("https://a/b", 200, {}, b""), "https://www.a/b/?utm_source=x") == "ok"
    )  # same page
    assert rc.classify(FetchResult("https://a/b", 410, {}, b"", error="HTTP 410"), "https://a/b") == "gone"
    assert (
        rc.classify(FetchResult("https://a/b", 429, {}, b"", error="HTTP 429"), "https://a/b") == "unverified"
    )
    assert rc.classify(FetchResult("https://a/b", 503, {}, b"", error="HTTP 503"), "https://a/b") == "error"
    assert rc.classify(FetchResult("https://a/b", 0, {}, b"", error="DNS"), "https://a/b") == "error"


def test_check_url_falls_back_to_get_only_when_needed():
    CALLS.clear()
    assert rc.check_url("https://ok.example/a", scripted)["status"] == "ok"
    assert CALLS == [("https://ok.example/a", "HEAD")]  # HEAD was enough
    CALLS.clear()
    line = rc.check_url("https://nohead.example/p", scripted)
    assert line["status"] == "ok" and CALLS == [
        ("https://nohead.example/p", "HEAD"),
        ("https://nohead.example/p", "GET"),
    ]
    moved = rc.check_url("https://moved.example/old", scripted)
    assert moved["status"] == "moved" and moved["final_url"] == "https://archive.other/new-home"
    assert rc.check_url("https://gone.example/x", scripted) == {
        "url": "https://gone.example/x",
        "status": "gone",
        "http": 404,
        "error": "HTTP 404",
    }
    assert (
        rc.check_url("https://botwall.example/p", scripted)["status"] == "unverified"
    )  # a 403 is not "gone"
    down = rc.check_url("https://down.example/p", scripted)
    assert down["status"] == "error" and down["error"].startswith("TimeoutError")


def test_recheck_report_dedups_urls_and_flags_attention():
    incidents = [
        {
            "id": "TR-2026-002",
            "status": "published",
            "sources": [{"url": "https://ok.example/a"}, {"url": "https://gone.example/x"}],
        },
        {
            "id": "TR-2026-001",
            "status": "published",
            "sources": [{"url": "https://ok.example/a"}, {"url": "https://botwall.example/p"}],
        },
        {
            "id": "TR-2026-003",
            "status": "published",
            "sources": [{"url": "https://moved.example/old"}, {"title": "no url"}],
        },
    ]
    CALLS.clear()
    rep = rc.recheck(incidents, fetcher=scripted, today=TODAY)
    assert rep["checked_on"] == "2026-10-12" and rep["version"] == rc.VERSION
    assert list(rep["incidents"]) == ["TR-2026-001", "TR-2026-002", "TR-2026-003"]  # sorted, deterministic
    assert rep["incidents_checked"] == 3 and rep["sources_checked"] == 4  # ok.example fetched once
    assert sum(1 for u, m in CALLS if u == "https://ok.example/a") == 1
    assert rep["summary"] == {"ok": 2, "moved": 1, "gone": 1, "unverified": 1, "error": 0}
    assert rep["needs_attention"] == [
        "TR-2026-002",
        "TR-2026-003",
    ]  # gone and moved; a bot wall is not attention
    assert rep["incidents"]["TR-2026-003"] == [
        {
            "url": "https://moved.example/old",
            "status": "moved",
            "http": 200,
            "final_url": "https://archive.other/new-home",
        }
    ]


def test_report_roundtrip_and_shipped_incidents_load(tmp_path: Path):
    rep = rc.recheck([], fetcher=scripted, today=TODAY)
    path = tmp_path / "incident_source_check.json"
    rc.write_report(rep, path)
    assert rc.read_report(path) == rep and path.read_text().endswith("\n")
    assert rc.read_report(tmp_path / "missing.json") is None
    published = rc.load_incidents(ROOT / "data" / "curated" / "incidents.yaml")
    assert len(published) >= 13 and all(inc["sources"] for inc in published)
