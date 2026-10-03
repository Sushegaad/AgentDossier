"""Wk 12: notification delivery (email + signed webhook), catalog diff, evidence-expiry job,
and the reference deployment running end to end (scan -> catalog -> notification)."""

from __future__ import annotations

import http.server
import json
import threading
import time
from datetime import date
from pathlib import Path

import pytest

from agentdossier.server.notify import (
    Notifier,
    NotifySettings,
    catalog_diff,
    evidence_expiring,
    verify_signature,
)
from agentdossier.storage.db import Store


class WebhookSink:
    """A tiny HTTP receiver that records every POST (and can be told to fail first)."""

    def __init__(self, fail_first: int = 0):
        self.received: list[dict] = []
        self.fail_first = fail_first
        sink = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if sink.fail_first > 0:
                    sink.fail_first -= 1
                    self.send_response(503)
                    self.end_headers()
                    return
                sink.received.append(
                    {
                        "body": raw,
                        "json": json.loads(raw),
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                    }
                )
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):  # silence
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/hook"


def test_webhook_is_signed_recorded_and_retried(tmp_path):
    store = Store(tmp_path / "n.db")
    with WebhookSink(fail_first=1) as sink:
        s = NotifySettings(webhook_url=sink.url, webhook_secret="s3cret", attempts=3, backoff_sec=0)
        n = Notifier(s, store, site="https://registry.example", tenant="acme")
        out = n.send("test", "hello", "body text", {"k": 1})
        assert out == [
            {"channel": "webhook", "target": sink.url, "status": "sent", "attempts": 2, "detail": "HTTP 204"}
        ]
        got = sink.received[0]
        assert got["headers"]["x-agentdossier-event"] == "test"
        assert verify_signature("s3cret", got["body"], got["headers"]["x-agentdossier-signature"])
        assert not verify_signature("wrong", got["body"], got["headers"]["x-agentdossier-signature"])
        assert got["json"]["tenant"] == "acme" and got["json"]["data"] == {"k": 1}
    d = store.deliveries()
    assert d[0]["status"] == "sent" and d[0]["attempts"] == 2 and d[0]["event"] == "test"


def test_webhook_failure_is_recorded_not_raised(tmp_path):
    store = Store(tmp_path / "n.db")
    s = NotifySettings(webhook_url="http://127.0.0.1:9/nothing", attempts=2, backoff_sec=0, timeout_sec=1)
    out = Notifier(s, store).send("scan.failed", "x", "y")
    assert out[0]["status"] == "failed" and out[0]["attempts"] == 2
    assert store.deliveries()[0]["status"] == "failed"


def test_event_filter_and_no_channels():
    assert Notifier(NotifySettings(), None).send("test", "x", "y") == []
    s = NotifySettings(webhook_url="http://127.0.0.1:9/x", events={"scan.done"}, attempts=1, timeout_sec=1)
    assert Notifier(s, None).send("test", "x", "y") == []  # filtered before any attempt


def test_email_goes_through_smtplib(monkeypatch, tmp_path):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["conn"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def starttls(self, context=None):
            sent["tls"] = True

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, msg):
            sent["msg"] = msg

    import agentdossier.server.notify as mod

    monkeypatch.setattr(mod.smtplib, "SMTP", FakeSMTP)
    s = NotifySettings(
        smtp_host="mail.example",
        smtp_port=2525,
        smtp_user="u",
        smtp_password="p",
        smtp_from="reg@example",
        email_to=["a@example", "b@example"],
    )
    assert s.validate() == [] and s.email_enabled
    out = Notifier(s, Store(tmp_path / "n.db"), tenant="acme").send("scan.done", "done", "text")
    assert out[0]["status"] == "sent" and sent["conn"] == ("mail.example", 2525) and sent["tls"]
    assert (
        sent["msg"]["To"] == "a@example, b@example" and sent["msg"]["Subject"] == "[AgentDossier · acme] done"
    )
    assert sent["msg"]["X-AgentDossier-Event"] == "scan.done"
    assert NotifySettings(smtp_host="x").validate()  # incomplete SMTP is rejected


def test_catalog_diff_reports_added_removed_and_tier_changes():
    before = [
        {"id": "a", "name": "A", "trust": {"identity": 3, "compliance": 5}},
        {"id": "b", "name": "B", "trust": {"identity": 3, "compliance": 5}},
    ]
    after = [
        {"id": "a", "name": "A", "trust": {"identity": 2, "compliance": 5}},
        {"id": "c", "name": "C", "trust": {"identity": 3, "compliance": 5}},
    ]
    d = catalog_diff(before, after)
    assert [x["id"] for x in d["added"]] == ["c"] and [x["id"] for x in d["removed"]] == ["b"]
    assert (
        d["changed"] == [{"id": "a", "name": "A", "trust": {"identity": {"from": 3, "to": 2}}}]
        and d["total"] == 2
    )


def test_evidence_expiring_windows():
    today = date(2026, 10, 2)
    res = [
        {
            "id": "r",
            "name": "R",
            "compliance": [
                {"framework": "soc2", "tier": 4, "status": "active", "valid_until": "2026-10-20"},
                {"framework": "iso27001", "tier": 1, "status": "active", "valid_until": "2027-06-01"},
                {"framework": "fedramp", "tier": 1, "status": "active", "valid_until": "2026-09-01"},
                {"framework": "gdpr", "tier": 4, "status": "active", "next_check": "2026-09-30"},
                {"framework": "hipaa", "tier": 4, "status": "active", "next_check": "2026-12-30"},
            ],
        }
    ]
    items = evidence_expiring(res, days=30, today=today)
    reasons = {i["framework"]: i["reason"] for i in items}
    assert reasons == {
        "soc2": "expires 2026-10-20",
        "fedramp": "expired 2026-09-01 but still marked active",
        "gdpr": "recheck due since 2026-09-30",
    }


# --- reference deployment end to end -------------------------------------------------------

fastapi = pytest.importorskip("fastapi")


def test_reference_deployment_scan_notifies_and_expiry_job_runs(tmp_path: Path):
    """The Wk 12 gate: one instance scans mock agents, rebuilds its catalog, and the
    operator's webhook receives scan.done / catalog.changed; the expiry job runs on demand."""
    from fastapi.testclient import TestClient

    from agentdossier.enterprise.selftest import FixturePublisher
    from agentdossier.server.app import create_app
    from agentdossier.server.settings import Settings

    with FixturePublisher() as pub, WebhookSink() as sink:
        cfg_path = tmp_path / "enterprise.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "tenant": "acme-ref",
                    "authorized_by": "Reference Deployment",
                    "ticket": "CHG-1",
                    "scope": {"allow_cidrs": ["127.0.0.0/8"]},
                    "targets": {"hosts": ["127.0.0.1"]},
                    "ports": [pub.port],
                    "limits": {"requests_per_host_per_sec": 20, "concurrency": 2, "timeout_sec": 5},
                    "output_dir": str(tmp_path / "scan"),
                    "schedule": {"cron": "0 6 * * 1"},
                }
            )
        )
        empty = tmp_path / "empty"
        empty.mkdir()
        settings = Settings(
            catalog_dir=empty,
            db_path=tmp_path / "ref.db",
            web_dist=None,
            auth_mode="token",
            api_token="reader",
            admin_token="admin",
            enterprise_config=cfg_path,
            start_scheduler=False,
            notify=NotifySettings(webhook_url=sink.url, webhook_secret="k", attempts=1, backoff_sec=0),
        )
        c = TestClient(create_app(settings))
        adm = {"Authorization": "Bearer admin"}
        st = c.get("/api/status", headers=adm).json()
        assert st["notify"]["channels"] == ["webhook"]
        assert {j["id"] for j in st["jobs"]} == {"scan", "evidence_expiry"}
        assert c.post("/api/notify/test", headers=adm).json()["deliveries"][0]["status"] == "sent"
        assert c.post("/api/scan", headers=adm).json()["status"] == "running"
        for _ in range(100):
            scans = c.get("/api/scans", headers=adm).json()["scans"]
            if scans and scans[0]["status"] != "running":
                break
            time.sleep(0.2)
        assert scans[0]["status"] == "done", scans
        time.sleep(0.5)
        events = [r["json"]["event"] for r in sink.received]
        assert events[:1] == ["test"] and "scan.done" in events and "catalog.changed" in events
        done = next(r["json"] for r in sink.received if r["json"]["event"] == "scan.done")
        assert (
            done["tenant"] == "acme-ref"
            and done["data"]["diff"]["total"] >= 2
            and done["data"]["diff"]["added"]
        )
        assert verify_signature(
            "k", sink.received[1]["body"], sink.received[1]["headers"]["x-agentdossier-signature"]
        )
        dl = c.get("/api/deliveries", headers=adm).json()["deliveries"]
        assert len(dl) >= 3 and all(d["status"] == "sent" for d in dl)
        assert c.get("/api/deliveries", headers={"Authorization": "Bearer reader"}).status_code == 403
        exp = c.get("/api/evidence/expiring?days=30", headers={"Authorization": "Bearer reader"}).json()
        assert exp["days"] == 30 and isinstance(exp["items"], list)
        job = c.post("/api/jobs/evidence-expiry", headers=adm).json()
        assert "items" in job and "deliveries" in job
        audit = c.get("/api/audit", headers=adm).json()["events"]
        assert any(e["action"] == "evidence.expiry" for e in audit)
