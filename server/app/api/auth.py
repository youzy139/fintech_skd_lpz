from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.core.auth import COOKIE, DOMAINS, auth_enabled, auth_store

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class Bootstrap(Login):
    setup_code: str = Field(min_length=1, max_length=128)


class UserSettings(BaseModel):
    role: str
    domains: list[str] = Field(min_length=1, max_length=2)
    enabled: bool = True
    password: str | None = Field(default=None, min_length=12, max_length=128)


class NewUser(UserSettings):
    username: str
    password: str = Field(min_length=12, max_length=128)


def enabled_store():
    if not auth_enabled():
        raise HTTPException(409, "开发模式未启用认证")
    return auth_store()


def login_response(token, response):
    store = enabled_store()
    principal = store.verify(token)
    response.set_cookie(COOKIE, token, httponly=True, secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true", samesite="strict", path="/", max_age=int(os.getenv("AUTH_SESSION_SECONDS", "3600")))
    response.headers["Cache-Control"] = "no-store"
    return principal.public()


@router.get("/status")
def status(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return auth_store().status() if auth_enabled() else {"enabled": False, "setup_required": False}


@router.post("/bootstrap")
def bootstrap(payload: Bootstrap, request: Request, response: Response):
    store = enabled_store()
    store.throttle("bootstrap:" + (request.client.host if request.client else "unknown"))
    store.bootstrap(payload.setup_code, payload.username, payload.password)
    return login_response(store.login(payload.username, payload.password), response)


@router.post("/login")
def login(payload: Login, request: Request, response: Response):
    store = enabled_store()
    store.throttle("login:" + (request.client.host if request.client else "unknown"))
    return login_response(store.login(payload.username, payload.password), response)


@router.get("/me")
def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not auth_enabled():
        return {"username": "local-dev", "role": "admin", "domains": sorted(DOMAINS), "expires_at": None, "can_control_replay": True}
    return request.state.principal.public()


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.headers.get("authorization", "")[7:] or request.cookies.get(COOKIE, "")
    enabled_store().logout(token)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.get("/users")
def users():
    return enabled_store().users()


@router.get("/audit")
def audit_records(before: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), actor: str | None = Query(None, max_length=40), action: str | None = Query(None, max_length=40)):
    return enabled_store().audit_records(before, limit, actor, action)


@router.post("/users", status_code=201)
def create_user(payload: NewUser, request: Request):
    store = enabled_store()
    store.save_user(request.state.principal.username, payload.username, payload.password, payload.role, payload.domains, payload.enabled, create=True)
    return {"ok": True}


@router.put("/users/{username}")
def update_user(username: str, payload: UserSettings, request: Request):
    store = enabled_store()
    store.save_user(request.state.principal.username, username, payload.password, payload.role, payload.domains, payload.enabled)
    return {"ok": True, "sessions_revoked": True}
