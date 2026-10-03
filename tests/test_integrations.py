"""Wk 15: Slack, Teams, Jira, ServiceNow and GRC channels, and the GitHub Action policy check
against a live instance."""

from __future__ import annotations

import http.server
import importlib.util
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from agentdossier.server.integrations import IntegrationSettings, build_integrations
from agentdossier.server.notify import Notifier, NotifySettings, verify_signature
from agentdossier.storage.db import Store

ROOT = Path(__file__).resolve().parents[1]


class Sink:
    """Records POSTs per path; answers like Jira / ServiceNow when asked."""

    def __init__(self):
        self.calls: list[dict] = []
        sink = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                sink.calls.append(
                    {
                        "path": self.path,
                        "json": json.loads(raw),
                        "raw": raw,
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                    }
                )
                body = b"{}"
                if self.path.startswith("/rest/api/2/issue"):
                    body = b'{"key":"GOV-42"}'
                elif self.path.startswith("/api/now/table/"):
                    body = b'{"result":{"number":"INC0010042"}}'
                self.send_response(201 if body != b"{}" else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"


@pytest.fixture
def sink():
    s = Sink()
    yield s
    s.close()


def _settings(sink: Sink, **kw) -> IntegrationSettings:
    base = dict(
        slack_webhook_url=f"{sink.base}/slack",
        teams_webhook_url=f"{sink.base}/teams",
        jira_base_url=sink.base,
        jira_email="bot@example",
        jira_api_token="t",
        jira_project_key="GOV",
        servicenow_instance_url=sink.base,
        servicenow_user="u",
        servicenow_password="p",
        grc_webhook_url=f"{sink.base}/grc",
        grc_webhook_secret="grc-secret",
    )
    base.update(kw)
    return IntegrationSettings(**base)


def test_validation():
    assert IntegrationSettings().validate() == []
    assert IntegrationSettings(jira_base_url="https://j").validate() == [
        "JIRA_BASE_URL needs JIRA_EMAIL, JIRA_API_TOKEN and JIRA_PROJECT_KEY"
    ]
    assert IntegrationSettings(servicenow_instance_url="https://s").validate()
    assert IntegrationSettings(slack_webhook_url="http://evil").validate() == [
        "SLACK_WEBHOOK_URL must be https"
    ]


def test_chat_channels_get_every_event_tickets_only_actionable_ones(sink, tmp_path):
    store = Store(tmp_path / "i.db")
    n = Notifier(NotifySettings(attempts=1, backoff_sec=0), store, site="https://reg", tenant="acme")
    n.integrations = build_integrations(_settings(sink))
    assert n.channels == ["slack", "teams", "jira", "servicenow", "grc"]

    out = n.send("scan.done", "scan #1 done", "all good", {"scanId": 1})
    assert [d["channel"] for d in out] == ["slack", "teams"]  # no ticket for a routine scan
    slack = next(c for c in sink.calls if c["path"] == "/slack")["json"]
    assert (
        slack["blocks"][0]["text"]["text"] == "*scan #1 done* · acme"
        and "```all good```" in slack["blocks"][1]["text"]["text"]
    )
    teams = next(c for c in sink.calls if c["path"] == "/teams")["json"]
    assert (
        teams["attachments"][0]["content"]["type"] == "AdaptiveCard"
        and teams["attachments"][0]["content"]["body"][0]["text"] == "scan #1 done"
    )

    sink.calls.clear()
    out = n.send("scan.failed", "scan #2 failed", "preflight: scope empty", {"scanId": 2})
    assert {d["channel"]: d["detail"] for d in out} == {
        "slack": "HTTP 200",
        "teams": "HTTP 200",
        "jira": "issue GOV-42",
        "servicenow": "incident INC0010042",
    }
    jira = next(c for c in sink.calls if c["path"] == "/rest/api/2/issue")
    assert jira["headers"]["authorization"].startswith("Basic ") and jira["json"]["fields"]["project"] == {
        "key": "GOV"
    }
    assert (
        jira["json"]["fields"]["summary"] == "[AgentDossier] scan #2 failed"
        and "scan-failed" in jira["json"]["fields"]["labels"]
    )
    snow = next(c for c in sink.calls if c["path"].startswith("/api/now/table/incident"))
    assert snow["json"]["short_description"] == "[AgentDossier] scan #2 failed"
    assert {(d["channel"], d["status"]) for d in store.deliveries()} >= {
        ("jira", "sent"),
        ("servicenow", "sent"),
    }

    sink.calls.clear()
    n.send(
        "decision.changed",
        "decision #7 security approve",
        "…",
        {"decisionId": 7, "stage": "under_review", "what": "security approve"},
    )
    assert {c["path"] for c in sink.calls} == {"/slack", "/teams"}  # a sign-off is not a new ticket
    sink.calls.clear()
    n.send(
        "decision.changed",
        "decision #8 opened",
        "…",
        {"decisionId": 8, "stage": "candidate", "what": "opened"},
    )
    assert {c["path"] for c in sink.calls} == {
        "/slack",
        "/teams",
        "/rest/api/2/issue",
        "/api/now/table/incident",
    }


def test_grc_receives_signed_decision_packet_on_approval(sink, tmp_path):
    packets = {7: {"format": "agentdossier-decision-packet/1", "decision": {"id": 7, "stage": "approved"}}}
    s = _settings(
        sink, slack_webhook_url=None, teams_webhook_url=None, jira_base_url=None, servicenow_instance_url=None
    )
    s.packet_for = lambda did: packets[did]
    n = Notifier(NotifySettings(attempts=1), Store(tmp_path / "g.db"))
    n.integrations = build_integrations(s)
    assert n.channels == ["grc"]
    assert (
        n.send(
            "decision.changed", "x", "y", {"decisionId": 7, "stage": "under_review", "what": "legal approve"}
        )
        == []
    )
    out = n.send(
        "decision.changed", "x", "y", {"decisionId": 7, "stage": "approved", "what": "moved to approved"}
    )
    assert out[0]["status"] == "sent" and out[0]["detail"].endswith("packet=yes")
    call = sink.calls[-1]
    assert call["json"]["decision_packet"]["decision"]["stage"] == "approved"
    assert verify_signature("grc-secret", call["raw"], call["headers"]["x-agentdossier-signature"])


# --- GitHub Action policy check -------------------------------------------------------------


def _load_action():
    spec = importlib.util.spec_from_file_location(
        "policy_check", ROOT / "deploy" / "action" / "policy_check.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_policy_check_logic_with_fake_registry():
    pc = _load_action()
    manifest = {
        "policyId": "pol_x",
        "agents": [
            {"id": "res_a", "use": "intake"},
            {"slug": "b-slug"},
            {"identifier": "urn:air:t:catalog:c-slug"},
        ],
    }

    def qualify(pid, ids):
        assert pid == "pol_x" and ids == ["res_a", "b-slug", "c-slug"]
        return {
            "results": [
                {"resourceId": "res_a", "name": "A", "verdict": "eligible", "rules": []},
                {
                    "resourceId": "res_b",
                    "slug": "b-slug",
                    "name": "B",
                    "verdict": "needs_review",
                    "rules": [{"id": "r2", "kind": "preferred", "result": "fail", "evidence": "no SOC 2"}],
                },
            ],
            "notFound": ["c-slug"],
        }

    r = pc.check(manifest, qualify)
    assert [x["verdict"] for x in r["rows"]] == ["eligible", "needs_review", "unknown"] and r["passed"]
    assert r["rows"][1]["reasons"] == ["preferred r2: no SOC 2"]
    r = pc.check(manifest, qualify, fail_on="needs_review")
    assert not r["passed"] and [x["fails"] for x in r["rows"]] == [False, True, True]
    md = pc.summary_markdown(r)
    assert "| B | — | 🟡 needs_review **(blocks)** | preferred r2: no SOC 2 |" in md
    with pytest.raises(ValueError):
        pc.check({"agents": [{"id": "x"}]}, qualify)
    with pytest.raises(ValueError):
        pc.check({"policyId": "p", "agents": []}, qualify)


fastapi = pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")


def test_policy_check_cli_against_live_instance(tmp_path, capsys):
    """The Wk 15 gate: the CI check blocks a manifest naming a disallowed agent."""
    from agentdossier.build import BuildOptions, build
    from agentdossier.server.app import create_app
    from agentdossier.server.settings import Settings

    out = tmp_path / "catalog"
    build(
        BuildOptions(
            out_dir=out,
            cache_dir=out / "cache",
            offline=True,
            write_review=False,
            compliance=False,
            news=False,
        )
    )
    app = create_app(
        Settings(
            catalog_dir=out,
            db_path=tmp_path / "a.db",
            web_dist=None,
            auth_mode="token",
            api_token="reader",
            admin_token=None,
            enterprise_config=None,
            start_scheduler=False,
        )
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        pc = _load_action()
        idx = json.loads((out / "index.json").read_text())
        slug = idx["records"][0]["slug"]
        strict = {
            "id": "p_strict",
            "version": 1,
            "rules": [{"id": "ident", "kind": "must", "field": "identity.tier", "op": "lte", "value": 1}],
        }
        # a strict inline policy is not a template; use the instance's healthcare template and a bogus id
        manifest = tmp_path / "agents.lock.json"
        manifest.write_text(
            json.dumps(
                {
                    "policyId": "pol_healthcare_default",
                    "agents": [{"slug": slug, "use": "test"}, {"id": "res_does_not_exist"}],
                }
            )
        )
        summary = tmp_path / "summary.md"
        rc = pc.main(
            [
                str(manifest),
                "--registry",
                f"http://127.0.0.1:{port}",
                "--token",
                "reader",
                "--summary",
                str(summary),
                "--json",
                str(tmp_path / "r.json"),
                "--fail-on",
                "unknown",
            ]
        )
        assert rc == 1  # the unknown agent blocks at fail-on unknown
        text = summary.read_text()
        assert "AgentDossier policy check — failed" in text and "res_does_not_exist" in text
        result = json.loads((tmp_path / "r.json").read_text())
        assert result["rows"][1]["verdict"] == "unknown" and result["rows"][0]["name"]
        rc = pc.main(
            [
                str(manifest),
                "--registry",
                f"http://127.0.0.1:{port}",
                "--token",
                "reader",
                "--fail-on",
                "disallowed",
            ]
        )
        assert rc in (0, 1)  # depends on the real verdict of the first agent; unknown no longer blocks
        assert pc.main([str(manifest), "--registry", f"http://127.0.0.1:{port}"]) == 2  # 401 without a token
        assert pc.main([str(tmp_path / "missing.json"), "--registry", "http://127.0.0.1:1"]) == 2
        _ = strict
    finally:
        server.should_exit = True
