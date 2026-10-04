"""Server settings, all from the environment (twelve-factor; one container, no config UI).

One pydantic-settings model: each field names its environment variable, types are
parsed and checked at construction, and ``validate()`` returns the cross-field
problems (auth mode, OIDC completeness, egress) that ``create_app`` refuses to start
on. Nested channel settings (``notify``, ``integrations``) keep their own small
dataclasses and read their variables the same way.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..util import ROOT, NetPolicy
from .integrations import IntegrationSettings
from .notify import NotifySettings

LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def _env(name: str) -> AliasChoices:
    return AliasChoices(name)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True, arbitrary_types_allowed=True)

    catalog_dir: Path = Field(
        default=ROOT / "data" / "catalog", validation_alias=_env("AGENTDOSSIER_CATALOG_DIR")
    )
    enterprise_config: Path | None = Field(
        default=None, validation_alias=_env("AGENTDOSSIER_ENTERPRISE_CONFIG")
    )
    web_dist: Path | None = Field(
        default=ROOT / "web" / "dist", validation_alias=_env("AGENTDOSSIER_WEB_DIST")
    )
    db_path: Path = Field(
        default=ROOT / "build" / "agentdossier.db", validation_alias=_env("AGENTDOSSIER_DB")
    )
    site: str = Field(default="http://localhost:8080/", validation_alias=_env("AGENTDOSSIER_SITE"))
    # auth: token (static bearer) | oidc | none. There is no inferred default: an instance that is
    # not told how to authenticate refuses to start rather than starting open. `none` is for local
    # development only and additionally needs AGENTDOSSIER_DEV=1 and a loopback bind.
    auth_mode: str = Field(default="", validation_alias=_env("AGENTDOSSIER_AUTH_MODE"))
    dev: bool = Field(default=False, validation_alias=_env("AGENTDOSSIER_DEV"))
    bind_host: str = Field(default="", validation_alias=_env("AGENTDOSSIER_BIND_HOST"))
    api_token: str | None = Field(default=None, validation_alias=_env("AGENTDOSSIER_API_TOKEN"))
    admin_token: str | None = Field(default=None, validation_alias=_env("AGENTDOSSIER_ADMIN_TOKEN"))
    oidc_issuer: str | None = Field(default=None, validation_alias=_env("OIDC_ISSUER"))
    oidc_client_id: str | None = Field(default=None, validation_alias=_env("OIDC_CLIENT_ID"))
    oidc_client_secret: str | None = Field(default=None, validation_alias=_env("OIDC_CLIENT_SECRET"))
    oidc_admin_group: str | None = Field(default=None, validation_alias=_env("OIDC_ADMIN_GROUP"))
    oidc_reviewer_group: str | None = Field(default=None, validation_alias=_env("OIDC_REVIEWER_GROUP"))
    session_secret: str | None = Field(default=None, validation_alias=_env("SESSION_SECRET"))
    scan_on_start: bool = Field(default=False, validation_alias=_env("AGENTDOSSIER_SCAN_ON_START"))
    # notifications: email through SMTP_* and/or a signed webhook; see server/notify.py
    notify: NotifySettings = Field(default_factory=NotifySettings.from_env)
    integrations: IntegrationSettings = Field(default_factory=IntegrationSettings.from_env)
    # ARD federation: peer registries and the widest mode this instance allows (none | referrals | auto)
    federation_peers: str = Field(default="", validation_alias=_env("AGENTDOSSIER_FEDERATION_PEERS"))
    federation_mode: str = Field(default="referrals", validation_alias=_env("AGENTDOSSIER_FEDERATION_MODE"))
    federation_token: str | None = Field(default=None, validation_alias=_env("AGENTDOSSIER_FEDERATION_TOKEN"))
    federation_timeout: float = Field(default=5.0, validation_alias=_env("AGENTDOSSIER_FEDERATION_TIMEOUT"))
    # egress for everything the server itself calls (webhooks, tickets, chat, federation peers):
    # public addresses only, unless AGENTDOSSIER_EGRESS_ALLOW lists the private CIDRs/hosts
    # (on-prem Jira, an internal peer registry) it may reach as well
    egress_allow: str = Field(default="", validation_alias=_env("AGENTDOSSIER_EGRESS_ALLOW"))
    # SCIM 2.0 provisioning (off until a token is set)
    scim_token: str | None = Field(default=None, validation_alias=_env("SCIM_TOKEN"))
    # hardening
    rate_limit: str = Field(default="120/minute", validation_alias=_env("AGENTDOSSIER_RATE_LIMIT"))
    max_body_bytes: int = Field(default=1024 * 1024, validation_alias=_env("AGENTDOSSIER_MAX_BODY_BYTES"))
    behind_tls_proxy: bool = Field(default=False, validation_alias=_env("AGENTDOSSIER_BEHIND_TLS_PROXY"))
    start_scheduler: bool = Field(default=True, validation_alias=_env("AGENTDOSSIER_SCHEDULER"))
    # daily evidence-expiry job (5-field cron, UTC); empty disables it
    expiry_cron: str = Field(default="0 7 * * *", validation_alias=_env("AGENTDOSSIER_EXPIRY_CRON"))

    @field_validator("enterprise_config", "web_dist", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    def egress_policy(self) -> NetPolicy:
        """Public-only by default; private targets only when listed; loopback only in dev."""
        items = [x.strip() for x in self.egress_allow.split(",") if x.strip()]
        cidrs = [
            x for x in items if "/" in x or (x[0].isdigit() and x.replace(".", "").replace(":", "").isalnum())
        ]
        hosts = [x for x in items if x not in cidrs]
        if self.dev:
            cidrs = [*cidrs, "127.0.0.0/8", "::1/128"]
            hosts = [*hosts, "localhost"]
        if not cidrs and not hosts:
            return NetPolicy()
        return NetPolicy(mode="enterprise", allow_cidrs=cidrs, allow_hosts=hosts, allow_public=True)

    def validate(self) -> list[str]:  # type: ignore[override]
        problems = []
        if not self.auth_mode:
            problems.append(
                "AGENTDOSSIER_AUTH_MODE is not set (token | oidc; `none` only for local development with "
                "AGENTDOSSIER_DEV=1 on a loopback address)"
            )
        elif self.auth_mode not in ("none", "token", "oidc"):
            problems.append(f"unknown AGENTDOSSIER_AUTH_MODE {self.auth_mode}")
        if self.auth_mode == "oidc" and not (
            self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret and self.session_secret
        ):
            problems.append(
                "auth_mode=oidc needs OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET and SESSION_SECRET"
            )
        if self.auth_mode == "token" and not self.api_token:
            problems.append("auth_mode=token needs AGENTDOSSIER_API_TOKEN")
        if self.auth_mode == "none":
            if not self.dev:
                problems.append(
                    "auth_mode=none needs AGENTDOSSIER_DEV=1 (every request would be an administrator)"
                )
            if self.bind_host and self.bind_host not in LOOPBACK_HOSTS:
                problems.append(f"auth_mode=none may only bind a loopback address, not {self.bind_host}")
        problems += self.notify.validate()
        problems += self.integrations.validate()
        if self.federation_mode not in ("none", "referrals", "auto"):
            problems.append(f"unknown AGENTDOSSIER_FEDERATION_MODE {self.federation_mode}")
        for peer in [p.strip() for p in self.federation_peers.split(",") if p.strip()]:
            if not peer.startswith(("https://", "http://localhost", "http://127.0.0.1")):
                problems.append(f"federation peer must be https: {peer}")
        if self.rate_limit:
            from .ratelimit import parse_limit  # noqa: PLC0415

            try:
                parse_limit(self.rate_limit)
            except ValueError as exc:
                problems.append(str(exc))
        return problems
