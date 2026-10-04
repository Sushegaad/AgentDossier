"""What every route needs, in one object attached to the app.

Routers never touch globals: ``deps(request)`` returns the instance's ``Deps`` and the
small helpers on it (``user``, ``actor``, ``limited``, ``to_result``) replace the closures
the old single-file app used.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from .auth import Auth, User
from .catalog import Catalog
from .federation import Federation
from .notify import Notifier
from .ratelimit import RateLimiter
from .scim import Scim
from .settings import Settings
from .workflow import Actor, Workflow


@dataclass
class Deps:
    settings: Settings
    catalog: Catalog
    store: Any
    auth: Auth
    notifier: Notifier
    flow: Workflow
    scim: Scim
    federation: Federation
    limiter: RateLimiter | None = None
    state: dict[str, Any] = field(
        default_factory=lambda: {"scan_lock": threading.Lock(), "scheduler": None, "config": None}
    )

    def user(self, request: Request, admin: bool = False, reviewer: bool = False) -> User:
        return self.auth.require(request, admin=admin, reviewer=reviewer)

    def actor(self, request: Request, *, reviewer: bool = False) -> Actor:
        u = self.user(request, reviewer=reviewer)
        return Actor(u.subject, u.name, set(u.roles))

    def limited(self, request: Request) -> None:
        if self.limiter is not None:
            self.limiter.check(request)

    def to_result(self, hit) -> dict[str, Any]:  # noqa: ANN001
        r = hit.record
        return {
            "identifier": f"urn:air:{self.catalog.index.get('tenant') or 'agentdossier'}:catalog:{r['slug']}",
            "resourceId": r["id"],
            "displayName": r["name"],
            "vendor": r.get("vendor"),
            "type": r.get("resource_type"),
            "url": f"{self.settings.site.rstrip('/')}/agents/{r['slug']}/",
            "description": r.get("description"),
            "score": hit.score,
            "explanation": hit.explanation,
            "trust": r.get("trust"),
            "protocols": r.get("protocols"),
            "compliance": r.get("compliance_summary", []),
            "domains": r.get("domains", {}),
        }


def deps(request: Request) -> Deps:
    return request.app.state.deps
