"""Outbound notifications for the self-hosted server: email (SMTP) and signed webhooks.

Events
------
``scan.done``          a scan finished and the catalog was reloaded (with the diff)
``scan.failed``        preflight failed or the scanner raised
``catalog.changed``    resources appeared, disappeared or changed trust tier (sent with scan.done)
``evidence.expiring``  compliance records with ``valid_until`` inside the warning window,
                       or whose ``next_check`` date has passed (daily job)
``test``               ``POST /api/notify/test``

Every attempt is written to the ``deliveries`` table so an operator can see what
left the instance and whether it arrived. Webhook bodies are JSON and carry
``X-AgentDossier-Event`` and, when a secret is set, ``X-AgentDossier-Signature:
sha256=<hex HMAC of the body>``. Email is plain text through the standard
library; no third-party mail service is involved.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import smtplib
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from typing import Any

from ..util import now_iso

log = logging.getLogger("agentdossier.notify")

EVENTS = ("scan.done", "scan.failed", "catalog.changed", "evidence.expiring", "test")


@dataclass
class NotifySettings:
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    email_to: list[str] = field(default_factory=list)
    webhook_url: str | None = None
    webhook_secret: str | None = None
    events: set[str] = field(default_factory=lambda: set(EVENTS))
    expiry_warning_days: int = 30
    attempts: int = 3
    backoff_sec: float = 2.0
    timeout_sec: float = 10.0

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.email_to)

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.webhook_url)

    def validate(self) -> list[str]:
        problems = []
        if self.smtp_host and not (self.smtp_from and self.email_to):
            problems.append("SMTP_HOST needs SMTP_FROM and AGENTDOSSIER_NOTIFY_EMAIL")
        if self.webhook_url and not self.webhook_url.startswith(("http://", "https://")):
            problems.append("AGENTDOSSIER_WEBHOOK_URL must be http(s)")
        unknown = self.events - set(EVENTS)
        if unknown:
            problems.append(f"unknown notify events: {', '.join(sorted(unknown))}")
        return problems


class Notifier:
    """Fan one event out to every configured channel and record each attempt."""

    def __init__(
        self, settings: NotifySettings, store: Any = None, *, site: str = "", tenant: str | None = None
    ):
        self.settings = settings
        self.store = store
        self.site = site.rstrip("/")
        self.tenant = tenant

    @property
    def channels(self) -> list[str]:
        out = []
        if self.settings.email_enabled:
            out.append("email")
        if self.settings.webhook_enabled:
            out.append("webhook")
        return out

    def send(
        self, event: str, subject: str, text: str, payload: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        if event not in self.settings.events:
            return []
        body = {
            "event": event,
            "at": now_iso(),
            "tenant": self.tenant,
            "site": self.site,
            "subject": subject,
            "text": text,
            "data": payload or {},
        }
        results = []
        if self.settings.email_enabled:
            results.append(
                self._attempt(
                    "email", ", ".join(self.settings.email_to), lambda: self._email(subject, text, body)
                )
            )
        if self.settings.webhook_enabled:
            results.append(
                self._attempt("webhook", self.settings.webhook_url or "", lambda: self._webhook(event, body))
            )
        for r in results:
            if self.store is not None:
                self.store.record_delivery(
                    event, r["channel"], r["target"], r["status"], r["attempts"], r["detail"]
                )
        return results

    # --- channels -----------------------------------------------------------------------

    def _attempt(self, channel: str, target: str, fn: Any) -> dict[str, Any]:
        detail = ""
        for n in range(1, self.settings.attempts + 1):
            try:
                detail = fn() or "ok"
                return {
                    "channel": channel,
                    "target": target,
                    "status": "sent",
                    "attempts": n,
                    "detail": detail,
                }
            except Exception as exc:  # noqa: BLE001 - every failure is recorded, never raised
                detail = f"{type(exc).__name__}: {exc}"
                log.warning("%s delivery attempt %d failed: %s", channel, n, detail)
                if n < self.settings.attempts:
                    time.sleep(self.settings.backoff_sec * n)
        return {
            "channel": channel,
            "target": target,
            "status": "failed",
            "attempts": self.settings.attempts,
            "detail": detail,
        }

    def _email(self, subject: str, text: str, body: dict[str, Any]) -> str:
        s = self.settings
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = ", ".join(s.email_to)
        msg["Subject"] = f"[AgentDossier{(' · ' + self.tenant) if self.tenant else ''}] {subject}"
        msg["X-AgentDossier-Event"] = body["event"]
        msg.set_content(text + "\n\n-- \nAgentDossier " + (self.site or ""))
        with smtplib.SMTP(s.smtp_host or "", s.smtp_port, timeout=s.timeout_sec) as smtp:
            if s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
        return f"{len(s.email_to)} recipient(s)"

    def _webhook(self, event: str, body: dict[str, Any]) -> str:
        s = self.settings
        raw = json.dumps(body, sort_keys=True, default=str).encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentDossier-notify/1",
            "X-AgentDossier-Event": event,
        }
        if s.webhook_secret:
            headers["X-AgentDossier-Signature"] = (
                "sha256=" + hmac.new(s.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
            )
        req = urllib.request.Request(s.webhook_url or "", data=raw, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=s.timeout_sec) as resp:  # noqa: S310 - operator-configured URL
                return f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}") from exc


def verify_signature(secret: str, raw_body: bytes, header: str | None) -> bool:
    """For receivers: check ``X-AgentDossier-Signature`` against the raw body."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


# --- event builders ------------------------------------------------------------------------


def catalog_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    """What changed between two index record lists: added, removed, trust-tier changes."""
    b = {r["id"]: r for r in before}
    a = {r["id"]: r for r in after}
    added = [{"id": i, "name": a[i]["name"]} for i in a if i not in b]
    removed = [{"id": i, "name": b[i]["name"]} for i in b if i not in a]
    changed = []
    for i in a.keys() & b.keys():
        tb, ta = b[i].get("trust") or {}, a[i].get("trust") or {}
        delta = {
            k: {"from": tb.get(k), "to": ta.get(k)}
            for k in ("identity", "compliance", "security", "protocols")
            if tb.get(k) != ta.get(k)
        }
        if delta:
            changed.append({"id": i, "name": a[i]["name"], "trust": delta})
    return {"added": added, "removed": removed, "changed": changed, "total": len(a)}


def scan_text(report: dict[str, Any], diff: dict[str, Any] | None, site: str) -> str:
    lines = [
        f"Scan finished for tenant {report.get('tenant')} (ticket {report.get('ticket')}).",
        f"Origins probed: {len(report.get('probed', []))} · resources: {report.get('resources')} · errors: {len(report.get('errors', []))}",
    ]
    if diff:
        lines.append(
            f"Catalog: +{len(diff['added'])} added, -{len(diff['removed'])} removed, {len(diff['changed'])} trust changes, {diff['total']} total."
        )
        for x in diff["added"][:10]:
            lines.append(f"  + {x['name']}")
        for x in diff["removed"][:10]:
            lines.append(f"  - {x['name']}")
        for x in diff["changed"][:10]:
            lines.append(
                f"  ~ {x['name']}: "
                + ", ".join(f"{k} T{v['from']}→T{v['to']}" for k, v in x["trust"].items())
            )
    if site:
        lines.append(f"Details: {site}/api/scans")
    return "\n".join(lines)


def _as_date(v: Any) -> date | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except ValueError:
        return None


def evidence_expiring(
    resources: list[dict[str, Any]], *, days: int = 30, today: date | None = None
) -> list[dict[str, Any]]:
    """Compliance records that expire within ``days`` or whose ``next_check`` has passed."""
    today = today or datetime.now(UTC).date()
    horizon = today + timedelta(days=days)
    out = []
    for res in resources:
        for rec in res.get("compliance") or []:
            vu, nc = _as_date(rec.get("valid_until")), _as_date(rec.get("next_check"))
            reason = None
            if vu and today <= vu <= horizon:
                reason = f"expires {vu.isoformat()}"
            elif vu and vu < today and rec.get("status") == "active":
                reason = f"expired {vu.isoformat()} but still marked active"
            elif nc and nc < today:
                reason = f"recheck due since {nc.isoformat()}"
            if reason:
                out.append(
                    {
                        "resource_id": res.get("id"),
                        "name": res.get("name"),
                        "framework": rec.get("framework"),
                        "variant": rec.get("variant"),
                        "tier": rec.get("tier"),
                        "valid_until": rec.get("valid_until"),
                        "next_check": rec.get("next_check"),
                        "reason": reason,
                        "evidence_url": rec.get("evidence_url"),
                    }
                )
    out.sort(key=lambda x: (x["valid_until"] or "9999", x["name"] or ""))
    return out


def expiry_text(items: list[dict[str, Any]], site: str) -> str:
    lines = [f"{len(items)} compliance record(s) need attention:"]
    for it in items[:50]:
        lines.append(
            f"  {it['name']}: {it['framework']}{(' ' + it['variant']) if it.get('variant') else ''} (T{it['tier']}) — {it['reason']}"
        )
    if len(items) > 50:
        lines.append(f"  … and {len(items) - 50} more")
    if site:
        lines.append(f"Review: {site}/changelog/")
    return "\n".join(lines)
