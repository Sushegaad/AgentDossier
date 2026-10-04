"""SCIM 2.0 stub (RFC 7643/7644) for user provisioning (Wk 16).

Enough for an identity provider (Okta, Entra ID, …) to push users and
deprovision them: ``ServiceProviderConfig``, ``Users`` (list with ``filter``,
create, read, replace, patch ``active``, delete) and an empty ``Groups``
collection. Access is a dedicated bearer token (``SCIM_TOKEN``). The point of
the stub is **deprovisioning**: a user whose SCIM record is inactive — or who
was deleted — is refused at sign-in even while their IdP session is alive,
because ``Auth`` asks :meth:`Scim.allowed` on every request.

Users are stored in the instance database; nothing is sent anywhere.
"""

from __future__ import annotations

import hmac
import json
import re
import sqlite3
import threading
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..storage.db import ensure_schema
from ..util import now_iso

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
_FILTER = re.compile(r'^\s*(userName|externalId|emails(?:\.value)?)\s+eq\s+"([^"]*)"\s*$', re.I)


def scim_error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        {"schemas": [ERROR_SCHEMA], "status": str(status), "detail": detail},
        status_code=status,
        media_type="application/scim+json",
    )


class Scim:
    def __init__(self, db: sqlite3.Connection, lock: threading.RLock, token: str | None, site: str = ""):
        self.db, self.lock, self.token = db, lock, token
        self.site = site.rstrip("/")
        ensure_schema(self.db, self.lock)

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    # --- auth -------------------------------------------------------------------------

    def require(self, request: Request) -> None:
        header = request.headers.get("authorization", "")
        if (
            not self.token
            or not header.lower().startswith("bearer ")
            or not hmac.compare_digest(header[7:].strip(), self.token)
        ):
            raise HTTPException(401, "SCIM bearer token required")

    def allowed(self, *, subject: str | None, email: str | None) -> bool:
        """False when the IdP has deprovisioned this person. Unknown people are allowed:
        SCIM may not be in use for every group, and the IdP already authenticated them."""
        if not self.enabled:
            return True
        with self.lock:
            row = self.db.execute(
                "SELECT active FROM scim_users WHERE (email=? AND ?!='') OR (external_id=? AND ?!='') OR (user_name=? AND ?!='') LIMIT 1",
                (email or "", email or "", subject or "", subject or "", email or "", email or ""),
            ).fetchone()
        return True if row is None else bool(row[0])

    # --- resources ---------------------------------------------------------------------

    def _to_scim(self, row: dict[str, Any]) -> dict[str, Any]:
        raw = json.loads(row.get("raw") or "{}")
        name = raw.get("name") or {}
        return {
            "schemas": [USER_SCHEMA],
            "id": row["id"],
            "externalId": row.get("external_id"),
            "userName": row["user_name"],
            "displayName": row.get("display_name"),
            "name": name,
            "emails": [{"value": row["email"], "primary": True}] if row.get("email") else [],
            "active": bool(row["active"]),
            "groups": raw.get("groups") or [],
            "meta": {
                "resourceType": "User",
                "created": row["created"],
                "lastModified": row["updated"],
                "location": f"{self.site}/scim/v2/Users/{row['id']}",
            },
        }

    def _row(self, uid: str) -> dict[str, Any] | None:
        with self.lock:
            cur = self.db.execute("SELECT * FROM scim_users WHERE id=?", (uid,))
            r = cur.fetchone()
            return dict(zip([c[0] for c in cur.description], r, strict=True)) if r else None

    def list(self, filt: str | None, start: int = 1, count: int = 100) -> dict[str, Any]:
        q, args = "SELECT * FROM scim_users", []  # type: str, list[Any]
        if filt:
            m = _FILTER.match(filt)
            if not m:
                raise HTTPException(400, 'unsupported filter; use <userName|externalId|emails.value> eq "…"')
            col = {"username": "user_name", "externalid": "external_id"}.get(
                m.group(1).lower().replace(".value", ""), "email"
            )
            q += f" WHERE {col}=?"
            args.append(m.group(2))
        with self.lock:
            cur = self.db.execute(q + " ORDER BY user_name", args)
            rows = [dict(zip([c[0] for c in cur.description], r, strict=True)) for r in cur.fetchall()]
        page = rows[max(start - 1, 0) : max(start - 1, 0) + count]
        return {
            "schemas": [LIST_SCHEMA],
            "totalResults": len(rows),
            "startIndex": start,
            "itemsPerPage": len(page),
            "Resources": [self._to_scim(r) for r in page],
        }

    def get(self, uid: str) -> dict[str, Any]:
        row = self._row(uid)
        if not row:
            raise HTTPException(404, "User not found")
        return self._to_scim(row)

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        user_name = str(body.get("userName") or "").strip()
        if not user_name:
            raise HTTPException(400, "userName is required")
        emails = body.get("emails") or []
        email = next((e.get("value") for e in emails if e.get("primary")), None) or (
            emails[0].get("value") if emails else None
        )
        now = now_iso()
        uid = str(uuid.uuid4())
        with self.lock:
            if self.db.execute("SELECT 1 FROM scim_users WHERE user_name=?", (user_name,)).fetchone():
                raise HTTPException(409, "userName already exists")
            self.db.execute(
                "INSERT INTO scim_users (id, external_id, user_name, display_name, email, active, created, updated, raw) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    body.get("externalId"),
                    user_name,
                    body.get("displayName"),
                    email,
                    1 if body.get("active", True) else 0,
                    now,
                    now,
                    json.dumps({"name": body.get("name"), "groups": body.get("groups")}),
                ),
            )
            self.db.commit()
        return self.get(uid)

    def replace(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self._row(uid):
            raise HTTPException(404, "User not found")
        emails = body.get("emails") or []
        email = next((e.get("value") for e in emails if e.get("primary")), None) or (
            emails[0].get("value") if emails else None
        )
        with self.lock:
            self.db.execute(
                "UPDATE scim_users SET external_id=?, user_name=?, display_name=?, email=?, active=?, updated=?, raw=? WHERE id=?",
                (
                    body.get("externalId"),
                    body.get("userName"),
                    body.get("displayName"),
                    email,
                    1 if body.get("active", True) else 0,
                    now_iso(),
                    json.dumps({"name": body.get("name"), "groups": body.get("groups")}),
                    uid,
                ),
            )
            self.db.commit()
        return self.get(uid)

    def patch(self, uid: str, body: dict[str, Any]) -> dict[str, Any]:
        row = self._row(uid)
        if not row:
            raise HTTPException(404, "User not found")
        active = bool(row["active"])
        display = row.get("display_name")
        for op in body.get("Operations") or []:
            kind = str(op.get("op") or "").lower()
            path = str(op.get("path") or "").lower()
            value = op.get("value")
            if kind not in ("replace", "add"):
                continue
            if path == "active":
                active = str(value).lower() in ("true", "1")
            elif path == "displayname":
                display = str(value)
            elif not path and isinstance(
                value, dict
            ):  # Entra style: {"op":"replace","value":{"active":false}}
                if "active" in value:
                    active = str(value["active"]).lower() in ("true", "1")
                if "displayName" in value:
                    display = str(value["displayName"])
        with self.lock:
            self.db.execute(
                "UPDATE scim_users SET active=?, display_name=?, updated=? WHERE id=?",
                (1 if active else 0, display, now_iso(), uid),
            )
            self.db.commit()
        return self.get(uid)

    def delete(self, uid: str) -> None:
        with self.lock:
            n = self.db.execute("DELETE FROM scim_users WHERE id=?", (uid,)).rowcount
            self.db.commit()
        if not n:
            raise HTTPException(404, "User not found")

    def service_provider_config(self) -> dict[str, Any]:
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
            "documentationUri": "https://github.com/Sushegaad/AgentDossier/blob/main/docs/enterprise-runbook.md",
            "patch": {"supported": True},
            "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": 200},
            "changePassword": {"supported": False},
            "sort": {"supported": False},
            "etag": {"supported": False},
            "authenticationSchemes": [
                {
                    "type": "oauthbearertoken",
                    "name": "Bearer token",
                    "description": "SCIM_TOKEN configured on the instance",
                }
            ],
            "meta": {
                "resourceType": "ServiceProviderConfig",
                "location": f"{self.site}/scim/v2/ServiceProviderConfig",
            },
        }
