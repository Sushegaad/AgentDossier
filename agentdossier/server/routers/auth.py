"""OIDC browser login flow (auth_mode=oidc)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ..deps import deps

router = APIRouter()

# --- OIDC login flow --------------------------------------------------------------------


@router.get("/auth/login")
async def login(request: Request):
    d = deps(request)
    redirect = str(request.url_for("auth_callback"))
    return await d.auth.oauth.idp.authorize_redirect(request, redirect)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    d = deps(request)
    token = await d.auth.oauth.idp.authorize_access_token(request)
    info = token.get("userinfo") or await d.auth.oauth.idp.userinfo(token=token)
    request.session["user"] = {
        "sub": info.get("sub"),
        "name": info.get("name"),
        "email": info.get("email"),
        "groups": info.get("groups") or [],
    }
    d.store.audit(str(info.get("sub")), "login", str(info.get("email") or ""))
    return RedirectResponse("/")


@router.get("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


@router.get("/auth/me")
def me(request: Request):
    d = deps(request)
    u = d.auth.current(request)
    return {"user": u.__dict__ if u else None}
