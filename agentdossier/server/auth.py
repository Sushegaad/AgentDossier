"""Authentication for the self-hosted server (FR-29 in its minimal form).

Three modes, chosen by ``AGENTDOSSIER_AUTH_MODE``:

* ``none``  – development only; every request is ``anonymous``.
* ``token`` – static bearer tokens: ``AGENTDOSSIER_API_TOKEN`` for readers, optional
  ``AGENTDOSSIER_ADMIN_TOKEN`` for scan control. Fine for service accounts and CI.
* ``oidc``  – browser login through the organization's identity provider (Authlib,
  OpenID Connect discovery). Admin rights come from membership of
  ``OIDC_ADMIN_GROUP`` in the ``groups`` claim. API clients may still use a token.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request

from .settings import Settings


@dataclass
class User:
    subject: str
    name: str
    admin: bool = False
    via: str = "none"
    # member: read, comment, open decisions, feedback · reviewer: sign off, change stages · admin: operate
    roles: set[str] = field(default_factory=lambda: {"member"})

    def __post_init__(self) -> None:
        self.roles = set(self.roles) | {"member"}
        if self.admin:
            self.roles |= {"reviewer", "admin"}

    @property
    def reviewer(self) -> bool:
        return "reviewer" in self.roles


class Auth:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.oauth: Any = None
        if settings.auth_mode == "oidc":
            from authlib.integrations.starlette_client import OAuth  # noqa: PLC0415

            self.oauth = OAuth()
            self.oauth.register(
                name="idp",
                client_id=settings.oidc_client_id,
                client_secret=settings.oidc_client_secret,
                server_metadata_url=f"{(settings.oidc_issuer or '').rstrip('/')}/.well-known/openid-configuration",
                client_kwargs={"scope": "openid profile email groups"},
            )

    def _token_user(self, request: Request) -> User | None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        token = header[7:].strip()
        s = self.settings
        if s.admin_token and hmac.compare_digest(token, s.admin_token):
            return User("admin-token", "admin token", admin=True, via="token")
        if s.api_token and hmac.compare_digest(token, s.api_token):
            return User("api-token", "api token", admin=False, via="token")
        return None

    def current(self, request: Request) -> User | None:
        if self.settings.auth_mode == "none":
            return User("anonymous", "anonymous", admin=True, via="none")
        u = self._token_user(request)
        if u:
            return u
        if self.settings.auth_mode == "oidc":
            sess = request.session.get("user") if "session" in request.scope else None
            if sess:
                groups = sess.get("groups") or []
                admin = bool(self.settings.oidc_admin_group and self.settings.oidc_admin_group in groups)
                roles = {"member"}
                if self.settings.oidc_reviewer_group and self.settings.oidc_reviewer_group in groups:
                    roles.add("reviewer")
                return User(
                    sess.get("sub", "?"),
                    sess.get("name") or sess.get("email") or "user",
                    admin=admin,
                    via="oidc",
                    roles=roles,
                )
        return None

    def require(self, request: Request, *, admin: bool = False, reviewer: bool = False) -> User:
        u = self.current(request)
        if u is None:
            raise HTTPException(
                401,
                "authentication required"
                + (" (sign in at /auth/login)" if self.settings.auth_mode == "oidc" else ""),
            )
        if admin and not u.admin:
            raise HTTPException(403, "administrator rights required")
        if reviewer and not u.reviewer:
            raise HTTPException(403, "reviewer rights required")
        return u
