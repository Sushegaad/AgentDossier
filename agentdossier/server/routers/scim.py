"""SCIM 2.0 user provisioning (on when SCIM_TOKEN is set)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from ..deps import deps
from ..scim import LIST_SCHEMA

router = APIRouter()

# --- SCIM 2.0 ------------------------------------------------------------------------------
scim_mt = "application/scim+json"


@router.get("/scim/v2/ServiceProviderConfig")
def scim_spc(request: Request):
    d = deps(request)
    d.scim.require(request)
    return JSONResponse(d.scim.service_provider_config(), media_type=scim_mt)


@router.get("/scim/v2/Users")
def scim_users(request: Request, filter: str | None = None, startIndex: int = 1, count: int = 100):  # noqa: A002, N803
    d = deps(request)
    d.scim.require(request)
    return JSONResponse(d.scim.list(filter, startIndex, min(count, 200)), media_type=scim_mt)


@router.post("/scim/v2/Users", status_code=201)
def scim_create(request: Request, body: dict[str, Any] = Body(...)):
    d = deps(request)
    d.scim.require(request)
    u = d.scim.create(body)
    d.store.audit("scim", "scim.user.create", f"{u['userName']} id={u['id']}")
    return JSONResponse(u, status_code=201, media_type=scim_mt)


@router.get("/scim/v2/Users/{uid}")
def scim_get(request: Request, uid: str):
    d = deps(request)
    d.scim.require(request)
    return JSONResponse(d.scim.get(uid), media_type=scim_mt)


@router.put("/scim/v2/Users/{uid}")
def scim_put(request: Request, uid: str, body: dict[str, Any] = Body(...)):
    d = deps(request)
    d.scim.require(request)
    u = d.scim.replace(uid, body)
    d.store.audit("scim", "scim.user.replace", f"{u['userName']} active={u['active']}")
    return JSONResponse(u, media_type=scim_mt)


@router.patch("/scim/v2/Users/{uid}")
def scim_patch(request: Request, uid: str, body: dict[str, Any] = Body(...)):
    d = deps(request)
    d.scim.require(request)
    u = d.scim.patch(uid, body)
    d.store.audit("scim", "scim.user.patch", f"{u['userName']} active={u['active']}")
    return JSONResponse(u, media_type=scim_mt)


@router.delete("/scim/v2/Users/{uid}", status_code=204)
def scim_delete(request: Request, uid: str):
    d = deps(request)
    d.scim.require(request)
    d.scim.delete(uid)
    d.store.audit("scim", "scim.user.delete", uid)
    return JSONResponse(None, status_code=204)


@router.get("/scim/v2/Groups")
def scim_groups(request: Request):
    d = deps(request)
    d.scim.require(request)
    return JSONResponse(
        {
            "schemas": [LIST_SCHEMA],
            "totalResults": 0,
            "startIndex": 1,
            "itemsPerPage": 0,
            "Resources": [],
        },
        media_type=scim_mt,
    )
