"""Server settings, all from the environment (twelve-factor; one container, no config UI)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..util import ROOT
from .notify import NotifySettings


@dataclass
class Settings:
    catalog_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("AGENTDOSSIER_CATALOG_DIR", ROOT / "data" / "catalog"))
    )
    enterprise_config: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["AGENTDOSSIER_ENTERPRISE_CONFIG"])
            if os.environ.get("AGENTDOSSIER_ENTERPRISE_CONFIG")
            else None
        )
    )
    web_dist: Path | None = field(
        default_factory=lambda: Path(os.environ.get("AGENTDOSSIER_WEB_DIST", ROOT / "web" / "dist"))
    )
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("AGENTDOSSIER_DB", ROOT / "build" / "agentdossier.db"))
    )
    site: str = field(default_factory=lambda: os.environ.get("AGENTDOSSIER_SITE", "http://localhost:8080/"))
    # auth: none (development only) | token (static bearer) | oidc
    auth_mode: str = field(
        default_factory=lambda: os.environ.get(
            "AGENTDOSSIER_AUTH_MODE", "token" if os.environ.get("AGENTDOSSIER_API_TOKEN") else "none"
        )
    )
    api_token: str | None = field(default_factory=lambda: os.environ.get("AGENTDOSSIER_API_TOKEN"))
    admin_token: str | None = field(default_factory=lambda: os.environ.get("AGENTDOSSIER_ADMIN_TOKEN"))
    oidc_issuer: str | None = field(default_factory=lambda: os.environ.get("OIDC_ISSUER"))
    oidc_client_id: str | None = field(default_factory=lambda: os.environ.get("OIDC_CLIENT_ID"))
    oidc_client_secret: str | None = field(default_factory=lambda: os.environ.get("OIDC_CLIENT_SECRET"))
    oidc_admin_group: str | None = field(default_factory=lambda: os.environ.get("OIDC_ADMIN_GROUP"))
    oidc_reviewer_group: str | None = field(default_factory=lambda: os.environ.get("OIDC_REVIEWER_GROUP"))
    session_secret: str | None = field(default_factory=lambda: os.environ.get("SESSION_SECRET"))
    scan_on_start: bool = field(
        default_factory=lambda: os.environ.get("AGENTDOSSIER_SCAN_ON_START", "0") == "1"
    )
    # notifications: email through SMTP_* and/or a signed webhook; see server/notify.py
    notify: NotifySettings = field(default_factory=lambda: notify_from_env())
    start_scheduler: bool = field(
        default_factory=lambda: os.environ.get("AGENTDOSSIER_SCHEDULER", "1") == "1"
    )
    # daily evidence-expiry job (5-field cron, UTC); empty disables it
    expiry_cron: str = field(default_factory=lambda: os.environ.get("AGENTDOSSIER_EXPIRY_CRON", "0 7 * * *"))

    def validate(self) -> list[str]:
        problems = []
        if self.auth_mode == "oidc" and not (
            self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret and self.session_secret
        ):
            problems.append(
                "auth_mode=oidc needs OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET and SESSION_SECRET"
            )
        if self.auth_mode == "token" and not self.api_token:
            problems.append("auth_mode=token needs AGENTDOSSIER_API_TOKEN")
        if self.auth_mode not in ("none", "token", "oidc"):
            problems.append(f"unknown AGENTDOSSIER_AUTH_MODE {self.auth_mode}")
        problems += self.notify.validate()
        return problems


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def notify_from_env() -> NotifySettings:
    events = _csv("AGENTDOSSIER_NOTIFY_EVENTS")
    return NotifySettings(
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER") or None,
        smtp_password=os.environ.get("SMTP_PASSWORD") or None,
        smtp_from=os.environ.get("SMTP_FROM") or None,
        smtp_starttls=os.environ.get("SMTP_STARTTLS", "1") == "1",
        email_to=_csv("AGENTDOSSIER_NOTIFY_EMAIL"),
        webhook_url=os.environ.get("AGENTDOSSIER_WEBHOOK_URL") or None,
        webhook_secret=os.environ.get("AGENTDOSSIER_WEBHOOK_SECRET") or None,
        events=set(events) if events else NotifySettings().events,
        expiry_warning_days=int(os.environ.get("AGENTDOSSIER_EXPIRY_WARNING_DAYS", "30")),
    )
