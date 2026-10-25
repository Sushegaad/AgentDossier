"""Machine review of incident candidates: offline, no network, no model."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from agentdossier.incidents import review as rv
from agentdossier.incidents import scout as sc

jsonschema = pytest.importorskip("jsonschema")
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "incident_record.schema.json").read_text())
TODAY = dt.date(2026, 10, 26)

PAGE = (
    "<html><head><title>x</title><script>var a=1;</script><style>p{}</style></head><body>"
    "<h1>Report</h1><p>"
    + "On 2 October 2026 an autonomous coding agent operated by an unknown actor gained access to "
    "Acme's build servers after a maintainer merged a pull request the agent had opened. The agent exfiltrated "
    "signing keys over the following day. Acme rotated the keys and published a post-mortem. "
    * 6
    + "</p></body></html>"
)

GOOD = {
    "incident": True,
    "confidence": 0.92,
    "reason": "a specific, dated intrusion driven by an agent, with a vendor post-mortem",
    "source_type": "vendor",
    "title": "Acme build-server intrusion by an autonomous coding agent",
    "date": "2026-10-02",
    "window": "2–3 October 2026",
    "ai_role": "attacker",
    "category": "incident",
    "summary": "An autonomous coding agent opened a pull request that a maintainer merged, giving it access to Acme's build servers. It exfiltrated signing keys over the following day; Acme rotated them and published a post-mortem.",
    "attacker": "an autonomous coding agent operated by an unknown actor",
    "defender": "Acme (build infrastructure)",
    "scale": "one build cluster",
    "impact": "signing keys exfiltrated, then rotated",
    "tactics": ["TA0001", "TA0010", "bogus"],
    "models_named": [{"name": "Langflow", "role": "attacker"}, {"name": "x", "role": "nope"}],
    "agents_named": ["Langflow"],
    "vendor_response": "keys rotated; post-mortem published",
    "timeline": [
        {"date": "2026-10-02", "text": "pull request merged; access gained"},
        {"date": "2026-10-03", "text": "keys exfiltrated"},
    ],
}
WEAK = {
    "incident": True,
    "confidence": 0.55,
    "reason": "mostly opinion about agent risks",
    "source_type": "press",
    "date": "2026-10-01",
    "ai_role": "target",
    "category": "incident",
    "summary": "s",
    "attacker": "a",
    "defender": "d",
}
NOT = {"incident": False, "confidence": 0.95, "reason": "a product announcement, no event"}


def _save(directory: Path, url: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.html").write_text(body)


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    off = tmp_path / "offline"
    urls = {
        "good": "https://acme.example/blog/post-mortem",
        "weak": "https://press.example/opinion",
        "not": "https://vendor.example/launch",
        "ph_pub": "https://lab.example/disclosure",
        "ph_drop": "https://news.example/roundup",
        "dead": "https://gone.example/404",
    }
    for k in ("good", "weak", "not", "ph_pub", "ph_drop"):
        _save(off, urls[k], PAGE)
    (off / "verdicts.json").write_text(
        json.dumps(
            {
                urls["good"]: GOOD,
                urls["weak"]: WEAK,
                urls["not"]: NOT,
                urls["ph_pub"]: {**GOOD, "title": "Lab disclosure"},
                urls["ph_drop"]: NOT,
            }
        )
    )
    cands = tmp_path / "cands.yaml"
    incs = tmp_path / "incidents.yaml"
    doc = {
        "version": "incident-candidates-1.0",
        "scouted_on": "2026-10-19",
        "candidates": [
            {
                "id": "cand-good",
                "status": "new",
                "title": "Acme post-mortem",
                "url": urls["good"],
                "date": "2026-10-04",
                "outlet": "Acme",
            },
            {
                "id": "cand-weak",
                "status": "new",
                "title": "Opinion",
                "url": urls["weak"],
                "date": "2026-10-04",
                "outlet": "Press",
            },
            {
                "id": "cand-not",
                "status": "new",
                "title": "Launch",
                "url": urls["not"],
                "date": "2026-10-04",
                "outlet": "Vendor",
            },
            {
                "id": "cand-dead",
                "status": "new",
                "title": "Dead link",
                "url": urls["dead"],
                "date": "2026-10-04",
                "outlet": "X",
            },
            {
                "id": "cand-done",
                "status": "dismissed",
                "title": "Old",
                "url": "https://old.example/",
                "note": "person: no",
            },
            {
                "id": "cand-ph",
                "status": "promoted",
                "promoted_to": "TR-2026-002",
                "title": "Roundup",
                "url": urls["ph_drop"],
            },
        ],
    }
    sc.write_candidates(doc, cands)
    text = (
        "# header comment\nversion: incidents-1.1\ncollected_on: 2026-10-11\ncollected_by: test\nincidents:\n"
        '  - id: TR-2026-001\n    status: published\n    title: "Real one"\n    date: 2026-01-01\n    summary: s\n'
        "    ai_role: target\n    category: incident\n    attacker: { description: a }\n    defender: { description: d }\n"
        '    tactics: [TA0001]\n    sources:\n      - { title: t, url: "https://a.example/" }\n    reviewer: "Hemant Naik"\n    checked_on: 2026-01-02\n'
    )
    text += sc.placeholder_block(
        {"id": "cand-ph", "title": "Roundup", "url": urls["ph_drop"], "outlet": "News", "date": "2026-10-01"},
        "TR-2026-002",
        TODAY,
    )
    text += sc.placeholder_block(
        {
            "id": "cand-x",
            "title": "Lab disclosure",
            "url": urls["ph_pub"],
            "outlet": "Lab",
            "date": "2026-10-02",
        },
        "TR-2026-003",
        TODAY,
    )
    incs.write_text(text)
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "index.json").write_text(
        json.dumps({"records": [{"slug": "langflow-langflow", "name": "Langflow"}]})
    )
    return {"off": off, "cands": cands, "incs": incs, "catalog": catalog}


def test_parse_verdict_validates_every_field():
    v = rv.parse_verdict("Sure, here it is:\n" + json.dumps(GOOD))
    assert v.incident and v.confidence == 0.92 and v.tactics == ["TA0001", "TA0010"]
    assert v.models_named == [{"name": "Langflow", "role": "attacker"}]
    assert rv.parse_verdict("no json here").incident is False
    assert rv.parse_verdict('{"incident": true, "confidence": "x", "date": "yesterday"}').date is None
    assert rv.parse_verdict(json.dumps({**GOOD, "category": "weird"})).publishable()[0] is False
    assert rv.parse_verdict(json.dumps({**GOOD, "source_type": "aggregator"})).publishable()[0] is False
    assert rv.parse_verdict(json.dumps(WEAK)).publishable()[0] is False
    assert rv.parse_verdict(json.dumps(GOOD)).publishable() == (True, GOOD["reason"])


def test_article_text_strips_scripts_and_rejects_thin_pages(tmp_path: Path):
    _save(tmp_path, "https://x.example/a", PAGE)
    _save(tmp_path, "https://x.example/thin", "<html><body>hi</body></html>")
    get = rv.offline_fetcher(tmp_path)
    text, err = rv.article_text("https://x.example/a", get)
    assert text and "var a=1" not in text and "Acme" in text and err is None
    assert rv.article_text("https://x.example/thin", get) == (
        None,
        "page has no readable text (bot wall or empty)",
    )
    assert rv.article_text("https://x.example/missing", get)[1] == "HTTP 404"


def test_review_publishes_dismisses_and_rewrites_placeholders(world: dict[str, Path]):
    rep = rv.review(
        completer=rv.offline_completer(world["off"]),
        fetcher=rv.offline_fetcher(world["off"]),
        model="test-model",
        candidates_path=world["cands"],
        incidents_path=world["incs"],
        catalog_dir=world["catalog"],
        today=TODAY,
    )
    assert rep.candidates_reviewed == 4 and rep.placeholders_reviewed == 2
    assert {r["id"] for r in rep.published} == {"TR-2026-003", "TR-2026-004"}
    assert {r["id"] for r in rep.dismissed} == {"TR-2026-002", "cand-weak", "cand-not"}
    assert [r["id"] for r in rep.unreadable] == ["cand-dead"] and not rep.errors

    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(world["incs"].read_text())
    incs = {i["id"]: i for i in doc["incidents"]}
    assert set(incs) == {"TR-2026-001", "TR-2026-003", "TR-2026-004"}  # TR-002 removed in place
    for inc in incs.values():
        jsonschema.validate(json.loads(json.dumps(inc, default=str)), SCHEMA)
    new = incs["TR-2026-004"]
    assert new["status"] == "published" and new["reviewer"] == "model: test-model (automated review)"
    assert str(new["checked_on"]) == "2026-10-26" and new["tactics"] == ["TA0001", "TA0010"]
    assert new["related_agents"] == ["langflow-langflow"] and new["sources"][0]["url"].endswith("post-mortem")
    assert len(new["timeline"]) == 2 and new["window"] == "2–3 October 2026"
    assert incs["TR-2026-003"]["title"] == "Lab disclosure" and incs["TR-2026-003"]["status"] == "published"
    assert incs["TR-2026-001"]["reviewer"] == "Hemant Naik"  # untouched
    assert world["incs"].read_text().startswith("# header comment\n")

    cdoc = sc.read_candidates(world["cands"])
    by = {c["id"]: c for c in cdoc["candidates"]}
    assert by["cand-good"]["status"] == "promoted" and by["cand-good"]["promoted_to"] == "TR-2026-004"
    assert by["cand-weak"]["status"] == "dismissed" and "confidence 0.55" in by["cand-weak"]["note"]
    assert by["cand-not"]["status"] == "dismissed" and "announcement" in by["cand-not"]["note"]
    assert by["cand-dead"]["status"] == "new"  # unreadable: left for next week
    assert by["cand-ph"]["status"] == "dismissed" and "promoted_to" not in by["cand-ph"]
    assert cdoc["reviewed_by"] == "model: test-model"

    # a second run finds nothing to do and changes nothing
    before = world["incs"].read_text()
    rep2 = rv.review(
        completer=rv.offline_completer(world["off"]),
        fetcher=rv.offline_fetcher(world["off"]),
        model="test-model",
        candidates_path=world["cands"],
        incidents_path=world["incs"],
        today=TODAY,
    )
    assert rep2.candidates_reviewed == 1 and not rep2.published and world["incs"].read_text() == before


def test_dry_run_writes_nothing(world: dict[str, Path]):
    before = (world["incs"].read_text(), world["cands"].read_text())
    rep = rv.review(
        completer=rv.offline_completer(world["off"]),
        fetcher=rv.offline_fetcher(world["off"]),
        candidates_path=world["cands"],
        incidents_path=world["incs"],
        today=TODAY,
        dry_run=True,
    )
    assert rep.published and (world["incs"].read_text(), world["cands"].read_text()) == before


def test_anthropic_completer_posts_and_reads_text():
    seen: dict[str, object] = {}

    def post(url: str, **kw):  # noqa: ANN202
        seen.update(url=url, **kw)
        from agentdossier.util import FetchResult  # noqa: PLC0415

        return FetchResult(
            url, 200, {}, json.dumps({"content": [{"type": "text", "text": '{"incident": false}'}]}).encode()
        )

    out = rv.anthropic_completer("k", "m", post=post)("sys", "user")
    assert out == '{"incident": false}' and seen["url"] == rv.API_URL
    body = json.loads(seen["data"])  # type: ignore[arg-type]
    assert body["model"] == "m" and body["system"] == "sys" and seen["headers"]["x-api-key"] == "k"  # type: ignore[index]
    assert "temperature" not in body  # the API rejects it for current models
