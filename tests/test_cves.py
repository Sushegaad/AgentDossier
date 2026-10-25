"""The CVE registry: parsing official records, the two inclusion tests, overrides, links, determinism."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from agentdossier.cves import build as cb
from agentdossier.cves import match as m
from agentdossier.cves import nvd

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).parent.parent
CONFIG = json.loads((ROOT / "config" / "cve_products.json").read_text())
TODAY = dt.date(2026, 10, 25)


def _item(
    cid,
    desc,
    *,
    cpes=(),
    cwes=(),
    score=None,
    sev=None,
    refs=(),
    status="Analyzed",
    pub="2026-07-14",
    end_excl=None,
):
    metrics = {}
    if score is not None:
        metrics = {
            "cvssMetricV31": [
                {
                    "type": "Primary",
                    "source": "nvd@nist.gov",
                    "cvssData": {"baseScore": score, "baseSeverity": sev, "vectorString": "CVSS:3.1/AV:N"},
                }
            ]
        }
    cfg = []
    if cpes:
        cfg = [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {
                                "vulnerable": True,
                                "criteria": f"cpe:2.3:a:{c}:*:*:*:*:*:*:*:*",
                                **({"versionEndExcluding": end_excl} if end_excl else {}),
                            }
                            for c in cpes
                        ]
                    }
                ]
            }
        ]
    return {
        "cve": {
            "id": cid,
            "sourceIdentifier": "secure@microsoft.com",
            "published": f"{pub}T17:15:00.000",
            "lastModified": f"{pub}T18:00:00.000",
            "vulnStatus": status,
            "descriptions": [{"lang": "es", "value": "ignorar"}, {"lang": "en", "value": desc}],
            "metrics": metrics,
            "weaknesses": [{"description": [{"lang": "en", "value": c}]} for c in cwes],
            "configurations": cfg,
            "references": [{"url": u, "source": "x", "tags": t} for u, t in refs],
        }
    }


ITEMS = [
    _item(
        "CVE-2026-50510",
        "Improper restriction of names for files and other resources in GitHub Copilot allows an unauthorized attacker to execute code locally.",
        cpes=["github:copilot"],
        cwes=["CWE-641"],
        score=8.8,
        sev="HIGH",
        refs=[
            (
                "https://msrc.microsoft.com/update-guide/vulnerability/CVE-2026-50510",
                ["Patch", "Vendor Advisory"],
            )
        ],
    ),
    _item(
        "CVE-2026-11111",
        "Improper neutralization of input used for LLM prompting in Acme Helper lets a crafted document make the assistant exfiltrate files.",
        cwes=["CWE-1427"],
        score=7.5,
        sev="HIGH",
    ),
    _item(
        "CVE-2026-22222",
        "A prompt injection in the FooBot MCP server allows an attacker to execute arbitrary commands on the host.",
        cwes=["CWE-77"],
        refs=[
            ("https://example.com/poc", ["Exploit"]),
            ("https://example.com/advisory", ["Vendor Advisory"]),
        ],
    ),
    _item(
        "CVE-2026-33333",
        "Windows Program Compatibility Assistant Service Elevation of Privilege Vulnerability",
        cpes=["microsoft:windows_11_24h2"],
        cwes=["CWE-269"],
        score=7.8,
        sev="HIGH",
    ),
    _item(
        "CVE-2026-44444",
        "A buffer overflow in the ACME image library allows remote code execution.",
        cwes=["CWE-120"],
        score=9.8,
        sev="CRITICAL",
    ),
    _item(
        "CVE-2026-55555",
        "Prompt injection in Langflow lets an attacker run code.",
        cpes=["langflow:langflow"],
        status="Rejected",
    ),
    _item(
        "CVE-2026-12957",
        "The Amazon Q Developer extension for VS Code automatically loaded MCP server configurations from workspace files without consent, allowing code execution.",
        cpes=["amazon:q_developer"],
        cwes=["CWE-829"],
        score=8.6,
        sev="HIGH",
        end_excl="1.65.0",
        pub="2026-06-26",
    ),
]
KEV = {
    "vulnerabilities": [
        {
            "cveID": "CVE-2026-50510",
            "dateAdded": "2026-08-01",
            "dueDate": "2026-08-22",
            "knownRansomwareCampaignUse": "Unknown",
        }
    ]
}


def _fixture_dir(tmp_path: Path) -> Path:
    d = tmp_path / "nvd"
    d.mkdir()
    (d / "resp.json").write_text(
        json.dumps({"totalResults": len(ITEMS), "resultsPerPage": 2000, "vulnerabilities": ITEMS})
    )
    (d / "kev.json").write_text(json.dumps(KEV))
    return d


def test_parse_item_takes_english_best_cvss_products_fix_and_drops_exploit_refs():
    rec = nvd.parse_item(ITEMS[6], "2026-10-25")
    assert (
        rec["description"].startswith("The Amazon Q Developer extension") and rec["published"] == "2026-06-26"
    )
    assert rec["cvss"] == {
        "version": "3.1",
        "score": 8.6,
        "severity": "HIGH",
        "vector": "CVSS:3.1/AV:N",
        "source": "nvd@nist.gov",
    }
    assert rec["products"][0]["vendor"] == "amazon" and rec["products"][0]["fixed_in"] == "1.65.0"
    assert rec["fix"] == {"status": "fixed", "version": "1.65.0", "url": None}
    rec3 = nvd.parse_item(ITEMS[2], "2026-10-25")
    assert [r["url"] for r in rec3["references"]] == [
        "https://example.com/advisory"
    ]  # Exploit-tagged link dropped
    assert rec3["cvss"] is None  # unscored


def test_classify_applies_both_tests_and_exclusions():
    recs = {i["cve"]["id"]: nvd.parse_item(i, "2026-10-25") for i in ITEMS}
    a = m.classify(recs["CVE-2026-50510"], CONFIG)
    assert (
        a
        and a["match"]["tests"] == ["A:cpe"]
        and a["category"] == "product"
        and "code_execution" in a["surface"]
    )
    assert (
        a["related_agents"] == ["github-microsoft-github-copilot-coding-agent"]
        and a["products"][0]["product_id"] == "github-copilot"
    )
    b = m.classify(recs["CVE-2026-11111"], CONFIG)
    assert (
        b
        and "B:cwe" in b["match"]["tests"]
        and "prompt_injection" in b["surface"]
        and "exfiltration" in b["surface"]
    )
    assert b["category"] == "unclassified"  # Test B only: no listed product
    c = m.classify(recs["CVE-2026-22222"], CONFIG)
    assert (
        c
        and "B:vocabulary" in c["match"]["tests"]
        and "tool_execution" in c["surface"]
        and "code_execution" in c["surface"]
    )
    # "MCP server" is vocabulary, not a listed product's name: a third-party server is a protocol
    # implementation by its own words, with no product link.
    assert "A:name" not in c["match"]["tests"] and c["category"] == "protocol" and not c["related_agents"]
    assert (
        m.classify(recs["CVE-2026-33333"], CONFIG) is None
    )  # Windows: excluded vendor, and "assistant" alone is not enough
    assert m.classify(recs["CVE-2026-44444"], CONFIG) is None  # not agent-related


def test_vocabulary_needs_a_strong_phrase_or_two_weak_ones():
    r = {"description": "A chatbot in a large language model app leaks data."}
    assert m.vocabulary_match(r, CONFIG) == [
        "chatbot",
        "large language model",
        "language model",
        "llm",
    ] or set(m.vocabulary_match(r, CONFIG)) >= {"chatbot", "large language model"}
    assert m.vocabulary_match({"description": "The LLM returned an error."}, CONFIG) == []  # one weak term
    assert m.vocabulary_match({"description": "Agentless scanner bug."}, CONFIG) == []  # whole-word


def test_queries():
    urls = nvd.backfill_queries(CONFIG)
    assert any("keywordSearch=prompt%20injection&keywordExactMatch=" in u for u in urls)
    assert any("cweId=CWE-1427" in u for u in urls)
    w = nvd.window_queries(dt.date(2026, 1, 1), dt.date(2026, 6, 30))
    assert len(w) == 2 and "lastModStartDate=2026-01-01T00" in w[0] and "lastModEndDate=2026-06-30T23" in w[1]


def test_update_offline_is_deterministic_and_schema_valid(tmp_path: Path):
    d = _fixture_dir(tmp_path)
    kw = dict(
        config=CONFIG,
        overrides={"cves": {}, "exclude_products": []},
        fetcher=nvd.offline_fetcher(d),
        backfill=True,
        today=TODAY,
        existing={"records": []},
        state={},
        links={"CVE-2026-12957": ["TR-2026-020"]},
        catalog_slugs={"github-microsoft-github-copilot-coding-agent"},
    )
    doc1, state1, rep1 = cb.update(**kw)
    doc2, _, _ = cb.update(**kw)
    assert doc1 == doc2 and json.dumps(doc1) == json.dumps(doc2)
    ids = [r["id"] for r in doc1["records"]]
    assert ids == [
        "CVE-2026-11111",
        "CVE-2026-22222",
        "CVE-2026-50510",
        "CVE-2026-12957",
    ]  # newest first, rejected and unrelated gone
    assert rep1["rejected"] == ["CVE-2026-55555"] and rep1["mode"] == "backfill" and rep1["errors"] == []
    by = {r["id"]: r for r in doc1["records"]}
    assert by["CVE-2026-50510"]["kev"] == {
        "added": "2026-08-01",
        "due": "2026-08-22",
        "ransomware": "Unknown",
    } and rep1["kev_new"] == ["CVE-2026-50510"]
    assert by["CVE-2026-12957"]["related_incidents"] == ["TR-2026-020"]
    assert by["CVE-2026-12957"]["related_agents"] == []  # slug not in the catalog set → dropped
    assert all(r["status"] == "candidate" for r in doc1["records"])
    assert doc1["counts"] == {
        "total": 4,
        "included": 0,
        "candidate": 4,
        "excluded": 0,
        "kev": 1,
        "unscored": 1,
    }
    assert cb.validate(doc1["records"]) == []
    assert state1["last_modified_cursor"] == "2026-10-25"
    cb.write(doc1, state1, out_dir=tmp_path / "out")
    assert json.loads((tmp_path / "out" / "index.json").read_text()) == doc1


def test_overrides_and_set_status(tmp_path: Path):
    d = _fixture_dir(tmp_path)
    ov = tmp_path / "cve_overrides.yaml"
    cb.set_status(
        "CVE-2026-50510", "included", "a real Copilot RCE", reviewer="Hemant Naik", today=TODAY, path=ov
    )
    cb.set_status("CVE-2026-11111", "excluded", "not a product we track", path=ov)
    overrides = cb.load_overrides(ov)
    assert overrides["cves"]["CVE-2026-50510"]["checked_on"] == "2026-10-25"
    overrides["exclude_products"] = [{"cpe": "amazon:q_developer", "why": "test"}]
    doc, _, _ = cb.update(
        config=CONFIG,
        overrides=overrides,
        fetcher=nvd.offline_fetcher(d),
        backfill=True,
        today=TODAY,
        existing={"records": []},
        state={},
        links={},
        catalog_slugs=None,
    )
    by = {r["id"]: r for r in doc["records"]}
    assert by["CVE-2026-50510"]["status"] == "included" and by["CVE-2026-50510"]["reviewer"] == "Hemant Naik"
    assert (
        by["CVE-2026-11111"]["status"] == "excluded"
        and by["CVE-2026-11111"]["note"] == "not a product we track"
    )
    assert "CVE-2026-12957" not in by  # excluded product from the overrides file
    assert ov.read_text().startswith("# The curated layer")


def test_window_run_keeps_prior_records_and_reclassifies(tmp_path: Path):
    d = _fixture_dir(tmp_path)
    doc1, state1, _ = cb.update(
        config=CONFIG,
        overrides={"cves": {}, "exclude_products": []},
        fetcher=nvd.offline_fetcher(d),
        backfill=True,
        today=TODAY,
        existing={"records": []},
        state={},
        links={},
        catalog_slugs=None,
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "kev.json").write_text(json.dumps(KEV))
    doc2, _, rep2 = cb.update(
        config=CONFIG,
        overrides={"cves": {}, "exclude_products": []},
        fetcher=nvd.offline_fetcher(empty),
        backfill=False,
        today=TODAY + dt.timedelta(days=7),
        existing=doc1,
        state=state1,
        links={},
        catalog_slugs=None,
    )
    assert rep2["mode"] == "window" and rep2["fetched"] == 0 and rep2["new"] == []
    assert [r["id"] for r in doc2["records"]] == [r["id"] for r in doc1["records"]]


def test_incident_links_find_cves_in_the_shipped_registry():
    links = cb.incident_links(ROOT / "data" / "curated" / "incidents.yaml")
    assert links.get("CVE-2025-32711") == ["TR-2026-002"]  # EchoLeak names its CVE in the summary
    assert all(k.startswith("CVE-") for k in links)


def test_shipped_config_slugs_exist_in_the_catalog():
    cat = ROOT / "data" / "catalog" / "index.json"
    if not cat.exists():
        pytest.skip("no built catalog")
    slugs = {r["slug"] for r in json.loads(cat.read_text())["records"]}
    for prod in CONFIG["products"]:
        for s in prod.get("agents") or []:
            assert s in slugs, f"{prod['id']}: {s} not in catalog"
    assert len({p["id"] for p in CONFIG["products"]}) == len(CONFIG["products"])


def test_display_name_never_matches_and_ordinary_words_do_not_list():
    """ "Continue" and "Cursor" are products and ordinary words: only their specific names count."""
    rec = {
        "id": "CVE-2026-55555",
        "description": "TypeBot lets a request continue past the SSRF validator and read local files.",
        "products": [],
        "cwe": [],
        "references": [],
    }
    assert m.classify(rec, CONFIG) is None
    rec["description"] = (
        "Cursor IDE for macOS allows an agent run to execute commands via a prompt injection."
    )
    out = m.classify(rec, CONFIG)
    assert out and out["category"] == "product" and out["products"][0]["product_id"] == "cursor"
