"""Outbound integrations for the self-hosted server (Wk 15): Slack, Microsoft Teams, Jira,
ServiceNow and a GRC webhook. Each one is a notification channel like email and the
generic webhook — the same events, the same delivery log — so an operator configures
them with environment variables and sees every attempt in ``GET /api/deliveries``.

Chat channels (Slack, Teams) post every enabled event. Ticketing channels (Jira,
ServiceNow) open one ticket per *actionable* event: ``scan.failed``,
``evidence.expiring``, and a decision being opened for review. The GRC webhook
receives the full decision packet whenever a decision reaches ``approved``,
``rejected`` or ``retired`` so the system of record keeps the signed-off state.

Only the standard library is used; credentials never appear in the payloads or
the delivery log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TICKET_EVENTS = ("scan.failed", "evidence.expiring", "decision.changed")
GRC_STAGES = ("approved", "rejected", "retired")


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> str:
    raw = json.dumps(body, default=str).encode()
    req = urllib.request.Request(
        url, data=raw, headers={"Content-Type": "application/json", **headers}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-configured URL
            return f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode(errors="replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code} {detail.strip()}".strip()) from exc


def _basic(user: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


@dataclass
class Integration:
    """One outbound channel: ``name`` for the delivery log, ``target`` (never a secret),
    ``wants(event, body)`` to filter, ``send(event, body)`` returning a short detail."""

    name: str
    target: str
    wants: Callable[[str, dict[str, Any]], bool]
    send: Callable[[str, dict[str, Any]], str]


@dataclass
class IntegrationSettings:
    slack_webhook_url: str | None = None
    teams_webhook_url: str | None = None
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None
    jira_issue_type: str = "Task"
    servicenow_instance_url: str | None = None
    servicenow_user: str | None = None
    servicenow_password: str | None = None
    servicenow_table: str = "incident"
    grc_webhook_url: str | None = None
    grc_webhook_secret: str | None = None
    timeout_sec: float = 15.0
    # callback that renders a decision packet for the GRC channel; set by the app
    packet_for: Callable[[int], dict[str, Any]] | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> IntegrationSettings:
        e = os.environ.get
        return cls(
            slack_webhook_url=e("SLACK_WEBHOOK_URL") or None,
            teams_webhook_url=e("TEAMS_WEBHOOK_URL") or None,
            jira_base_url=(e("JIRA_BASE_URL") or "").rstrip("/") or None,
            jira_email=e("JIRA_EMAIL") or None,
            jira_api_token=e("JIRA_API_TOKEN") or None,
            jira_project_key=e("JIRA_PROJECT_KEY") or None,
            jira_issue_type=e("JIRA_ISSUE_TYPE") or "Task",
            servicenow_instance_url=(e("SERVICENOW_INSTANCE_URL") or "").rstrip("/") or None,
            servicenow_user=e("SERVICENOW_USER") or None,
            servicenow_password=e("SERVICENOW_PASSWORD") or None,
            servicenow_table=e("SERVICENOW_TABLE") or "incident",
            grc_webhook_url=e("GRC_WEBHOOK_URL") or None,
            grc_webhook_secret=e("GRC_WEBHOOK_SECRET") or None,
        )

    def validate(self) -> list[str]:
        p = []
        if self.jira_base_url and not (self.jira_email and self.jira_api_token and self.jira_project_key):
            p.append("JIRA_BASE_URL needs JIRA_EMAIL, JIRA_API_TOKEN and JIRA_PROJECT_KEY")
        if self.servicenow_instance_url and not (self.servicenow_user and self.servicenow_password):
            p.append("SERVICENOW_INSTANCE_URL needs SERVICENOW_USER and SERVICENOW_PASSWORD")
        for name, url in (
            ("SLACK_WEBHOOK_URL", self.slack_webhook_url),
            ("TEAMS_WEBHOOK_URL", self.teams_webhook_url),
            ("GRC_WEBHOOK_URL", self.grc_webhook_url),
        ):
            if (
                url
                and not url.startswith("https://")
                and not url.startswith("http://127.0.0.1")
                and not url.startswith("http://localhost")
            ):
                p.append(f"{name} must be https")
        return p


def _ticket_worthy(event: str, body: dict[str, Any]) -> bool:
    if event not in TICKET_EVENTS:
        return False
    if event == "decision.changed":
        return body.get("data", {}).get("what") == "opened"
    return True


def _grc_worthy(event: str, body: dict[str, Any]) -> bool:
    return event == "decision.changed" and body.get("data", {}).get("stage") in GRC_STAGES


def build_integrations(s: IntegrationSettings) -> list[Integration]:
    out: list[Integration] = []
    t = s.timeout_sec

    if s.slack_webhook_url:

        def slack(event: str, body: dict[str, Any]) -> str:
            head = f"*{body['subject']}*" + (f" · {body['tenant']}" if body.get("tenant") else "")
            text = body["text"][:2800]
            payload = {
                "text": f"{body['subject']} — {event}",
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": head}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"```{text}```"}},
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"`{event}` · {body['at']} · {body.get('site') or 'AgentDossier'}",
                            }
                        ],
                    },
                ],
            }
            return _post_json(s.slack_webhook_url or "", payload, {}, t)

        out.append(Integration("slack", "slack incoming webhook", lambda e, b: True, slack))

    if s.teams_webhook_url:

        def teams(event: str, body: dict[str, Any]) -> str:
            card = {
                "type": "message",
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": {
                            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                            "type": "AdaptiveCard",
                            "version": "1.4",
                            "body": [
                                {
                                    "type": "TextBlock",
                                    "size": "Medium",
                                    "weight": "Bolder",
                                    "text": body["subject"],
                                    "wrap": True,
                                },
                                {
                                    "type": "TextBlock",
                                    "text": body["text"][:3000],
                                    "wrap": True,
                                    "fontType": "Monospace",
                                },
                                {
                                    "type": "TextBlock",
                                    "text": f"{event} · {body['at']}"
                                    + (f" · {body['tenant']}" if body.get("tenant") else ""),
                                    "isSubtle": True,
                                    "wrap": True,
                                },
                            ],
                        },
                    }
                ],
            }
            return _post_json(s.teams_webhook_url or "", card, {}, t)

        out.append(Integration("teams", "teams incoming webhook", lambda e, b: True, teams))

    if s.jira_base_url and s.jira_email and s.jira_api_token and s.jira_project_key:

        def jira(event: str, body: dict[str, Any]) -> str:
            payload = {
                "fields": {
                    "project": {"key": s.jira_project_key},
                    "issuetype": {"name": s.jira_issue_type},
                    "summary": f"[AgentDossier] {body['subject']}"[:255],
                    "description": body["text"][:30000]
                    + f"\n\nevent: {event}\nat: {body['at']}"
                    + (f"\ntenant: {body['tenant']}" if body.get("tenant") else ""),
                    "labels": ["agentdossier", event.replace(".", "-")],
                }
            }
            url = f"{s.jira_base_url}/rest/api/2/issue"
            raw = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=raw,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": _basic(s.jira_email or "", s.jira_api_token or ""),
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=t) as resp:  # noqa: S310
                    data = json.loads(resp.read() or b"{}")
                    return f"issue {data.get('key', '?')}"
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"HTTP {exc.code}") from exc

        out.append(
            Integration("jira", f"{s.jira_base_url} project {s.jira_project_key}", _ticket_worthy, jira)
        )

    if s.servicenow_instance_url and s.servicenow_user and s.servicenow_password:

        def servicenow(event: str, body: dict[str, Any]) -> str:
            payload = {
                "short_description": f"[AgentDossier] {body['subject']}"[:160],
                "description": body["text"][:4000] + f"\n\nevent: {event}\nat: {body['at']}",
                "category": "software",
                "u_source": "agentdossier",
            }
            url = f"{s.servicenow_instance_url}/api/now/table/{s.servicenow_table}"
            raw = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=raw,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": _basic(s.servicenow_user or "", s.servicenow_password or ""),
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=t) as resp:  # noqa: S310
                    data = json.loads(resp.read() or b"{}").get("result", {})
                    return f"{s.servicenow_table} {data.get('number', '?')}"
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"HTTP {exc.code}") from exc

        out.append(
            Integration(
                "servicenow",
                f"{s.servicenow_instance_url} table {s.servicenow_table}",
                _ticket_worthy,
                servicenow,
            )
        )

    if s.grc_webhook_url:

        def grc(event: str, body: dict[str, Any]) -> str:
            did = body.get("data", {}).get("decisionId")
            packet = s.packet_for(int(did)) if (s.packet_for and did is not None) else None
            payload = {
                "event": event,
                "at": body["at"],
                "tenant": body.get("tenant"),
                "decision_packet": packet,
                "summary": body.get("data"),
            }
            raw = json.dumps(payload, sort_keys=True, default=str).encode()
            headers = {"X-AgentDossier-Event": event}
            if s.grc_webhook_secret:
                headers["X-AgentDossier-Signature"] = (
                    "sha256=" + hmac.new(s.grc_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
                )
            req = urllib.request.Request(
                s.grc_webhook_url or "",
                data=raw,
                headers={"Content-Type": "application/json", **headers},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=t) as resp:  # noqa: S310
                    return f"HTTP {resp.status} packet={'yes' if packet else 'no'}"
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"HTTP {exc.code}") from exc

        out.append(Integration("grc", s.grc_webhook_url, _grc_worthy, grc))

    return out
