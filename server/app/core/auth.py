from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from fastapi import HTTPException
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from app.core.config import load_config
from app.core.observability import current_request_id

COOKIE = "marketlens_session"
ROLES = {"observer", "analyst", "admin"}
DOMAINS = {"market", "catalog"}
authorization_context: ContextVar[str | None] = ContextVar("authorization", default=None)


def auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").lower() == "true"


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def password_matches(password: str, stored: str) -> bool:
    salt, _ = stored.split(":")
    return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), stored)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    domains: frozenset[str]
    expires: int
    service: bool = False
    assets: frozenset[str] = frozenset({"*"})
    sources: frozenset[str] = frozenset({"*"})

    def public(self) -> dict[str, Any]:
        return {"username": self.username, "role": self.role, "domains": sorted(self.domains), "assets": sorted(self.assets), "sources": sorted(self.sources), "expires_at": self.expires, "can_control_replay": self.role in {"analyst", "admin"} and DOMAINS <= self.domains and "*" in self.assets}


class AuthStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS auth_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_users (username TEXT PRIMARY KEY, password TEXT NOT NULL, role TEXT NOT NULL, domains TEXT NOT NULL, enabled INTEGER NOT NULL, version INTEGER NOT NULL, scopes TEXT NOT NULL DEFAULT '{"assets":["*"],"sources":["*"]}');
                CREATE TABLE IF NOT EXISTS auth_sessions (id TEXT PRIMARY KEY, username TEXT NOT NULL, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_attempts (id TEXT PRIMARY KEY, count INTEGER NOT NULL, until INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_audit (id INTEGER PRIMARY KEY, occurred INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_audit_archives (
                    id TEXT PRIMARY KEY, first_id INTEGER NOT NULL, last_id INTEGER NOT NULL,
                    first_occurred INTEGER NOT NULL, last_occurred INTEGER NOT NULL,
                    record_count INTEGER NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
                    bucket TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, created INTEGER NOT NULL,
                    last_verified INTEGER, verification TEXT NOT NULL DEFAULT 'unverified'
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(auth_audit)")}
            for name, definition in {"request_id": "TEXT NOT NULL DEFAULT ''", "status": "INTEGER NOT NULL DEFAULT 0"}.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE auth_audit ADD COLUMN {name} {definition}")
            user_columns = {row[1] for row in db.execute("PRAGMA table_info(auth_users)")}
            if "scopes" not in user_columns:
                db.execute("ALTER TABLE auth_users ADD COLUMN scopes TEXT NOT NULL DEFAULT '{\"assets\":[\"*\"],\"sources\":[\"*\"]}'")
            db.execute("CREATE INDEX IF NOT EXISTS auth_audit_actor_id ON auth_audit(actor,id)")
            db.execute("INSERT OR IGNORE INTO auth_meta VALUES ('key', ?)", (secrets.token_hex(48),))
            db.execute("INSERT OR IGNORE INTO auth_meta VALUES ('bootstrap', ?)", (secrets.token_urlsafe(32),))
            self.key = db.execute("SELECT value FROM auth_meta WHERE name='key'").fetchone()[0]
            if db.execute("SELECT count(*) FROM auth_users").fetchone()[0] == 0:
                code = db.execute("SELECT value FROM auth_meta WHERE name='bootstrap'").fetchone()[0]
                bootstrap_file = path.with_name("auth-bootstrap.txt")
                bootstrap_file.write_text(code, encoding="utf-8")
                bootstrap_file.chmod(0o600)
        path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def audit(db, actor, action, target, status=200):
        db.execute("INSERT INTO auth_audit(occurred,actor,action,target,request_id,status) VALUES(?,?,?,?,?,?)", (int(time.time()), actor, action, target, current_request_id(), status))

    def record_event(self, actor, action, target, status):
        with self.connect() as db:
            self.audit(db, actor, action, target, status)

    def audit_records(self, before=0, limit=25, actor=None, action=None):
        clauses, parameters = [], []
        if before:
            clauses.append("id<?")
            parameters.append(before)
        for name, value in (("actor", actor), ("action", action)):
            if value:
                clauses.append(name + "=?")
                parameters.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT id,occurred,actor,action,target,request_id,status FROM auth_audit" + where + " ORDER BY id DESC LIMIT ?", (*parameters, limit + 1))]
        items = rows[:limit]
        return {"items": items, "next_before": items[-1]["id"] if len(rows) > limit else None}

    def archive_candidates(self, cutoff: int, keep: int, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as db:
            boundary = db.execute("SELECT id FROM auth_audit ORDER BY id DESC LIMIT 1 OFFSET ?", (keep - 1,)).fetchone()
            if boundary is None:
                return []
            return [dict(row) for row in db.execute(
                "SELECT id,occurred,actor,action,target,request_id,status FROM auth_audit WHERE occurred<? AND id<? ORDER BY id LIMIT ?",
                (cutoff, boundary["id"], limit),
            )]

    def commit_archive(self, metadata: dict[str, Any], identifiers: list[int]) -> None:
        placeholders = ",".join("?" for _ in identifiers)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(f"SELECT count(*) FROM auth_audit WHERE id IN ({placeholders})", identifiers).fetchone()[0]
            if count != len(identifiers):
                raise RuntimeError("待归档审计记录已变化，未删除在线记录")
            db.execute(
                "INSERT INTO auth_audit_archives(id,first_id,last_id,first_occurred,last_occurred,record_count,sha256,size,bucket,object_key,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                tuple(metadata[name] for name in ("id", "first_id", "last_id", "first_occurred", "last_occurred", "record_count", "sha256", "size", "bucket", "object_key", "created")),
            )
            db.execute(f"DELETE FROM auth_audit WHERE id IN ({placeholders})", identifiers)

    def audit_archives(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM auth_audit_archives ORDER BY first_id DESC")]

    def audit_archive(self, identifier: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM auth_audit_archives WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return dict(row)

    def record_archive_verification(self, identifier: str, verified: int, result: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE auth_audit_archives SET last_verified=?,verification=? WHERE id=?", (verified, result, identifier))

    def status(self):
        with self.connect() as db:
            return {"enabled": True, "setup_required": db.execute("SELECT count(*) FROM auth_users").fetchone()[0] == 0}

    @staticmethod
    def validate_user(username, password, role, domains):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
            raise HTTPException(422, "用户名须为 3～40 位字母、数字、点、下划线或短横线")
        if password is not None and not 12 <= len(password) <= 128:
            raise HTTPException(422, "密码长度须为 12～128 位")
        if role not in ROLES or not domains or not set(domains) <= DOMAINS:
            raise HTTPException(422, "角色或数据范围无效")
        if role == "admin" and set(domains) != DOMAINS:
            raise HTTPException(422, "管理员须拥有全部数据范围")

    def bootstrap(self, code, username, password):
        self.validate_user(username, password, "admin", sorted(DOMAINS))
        hashed = password_hash(password)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            expected = db.execute("SELECT value FROM auth_meta WHERE name='bootstrap'").fetchone()[0]
            if db.execute("SELECT count(*) FROM auth_users").fetchone()[0] or not hmac.compare_digest(code, expected):
                raise HTTPException(403, "初始化凭据无效或管理员已创建")
            db.execute("INSERT INTO auth_users(username,password,role,domains,enabled,version,scopes) VALUES(?,?,?,?,1,1,?)", (username, hashed, "admin", json.dumps(sorted(DOMAINS)), json.dumps({"assets": ["*"], "sources": ["*"]}, separators=(",", ":"))))
            db.execute("UPDATE auth_meta SET value='' WHERE name='bootstrap'")
            self.audit(db, username, "bootstrap", username)
        self.path.with_name("auth-bootstrap.txt").unlink(missing_ok=True)

    def throttle(self, identity: str):
        identity = hashlib.sha256(identity.encode()).hexdigest()
        now = int(time.time())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM auth_attempts WHERE until<=?", (now,))
            row = db.execute("SELECT * FROM auth_attempts WHERE id=?", (identity,)).fetchone()
            if row and row["count"] >= 8:
                raise HTTPException(429, "尝试过于频繁，请稍后重试", headers={"Retry-After": str(max(1, row["until"] - now))})
            db.execute("INSERT INTO auth_attempts VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1", (identity, now + 60))

    def login(self, username, password):
        with self.connect() as db:
            row = db.execute("SELECT * FROM auth_users WHERE username=?", (username,)).fetchone()
            stored = row["password"] if row else password_hash("dummy-account-password", b"0" * 16)
            valid = password_matches(password, stored)
            if not row or not valid or not row["enabled"]:
                self.audit(db, "anonymous", "login_failed", "", 401)
            else:
                now = int(time.time())
                identifier = secrets.token_hex(24)
                expires = now + int(os.getenv("AUTH_SESSION_SECONDS", "3600"))
                db.execute("DELETE FROM auth_sessions WHERE expires<=?", (now,))
                db.execute("INSERT INTO auth_sessions VALUES(?,?,?)", (identifier, username, expires))
                self.audit(db, username, "login", username)
                claims = {"sub": username, "ver": row["version"], "jti": identifier, "iat": now, "exp": expires, "iss": "marketlens", "aud": "marketlens-api", "kind": "user"}
                return jwt.encode(claims, self.key, algorithm="HS256")
        raise HTTPException(401, "用户名或密码错误", headers={"WWW-Authenticate": "Bearer"})

    def claims(self, token):
        try:
            return jwt.decode(token, self.key, algorithms=["HS256"], issuer="marketlens", audience="marketlens-api", options={"require": ["sub", "exp", "iat", "jti", "kind"]})
        except jwt.InvalidTokenError as error:
            raise HTTPException(401, "登录已失效，请重新登录", headers={"WWW-Authenticate": "Bearer"}) from error

    def verify(self, token):
        claims = self.claims(token)
        if claims["kind"] == "service" and claims["sub"] in {"backend", "feature", "alert"}:
            return Principal(claims["sub"], "service", frozenset(DOMAINS), claims["exp"], True)
        with self.connect() as db:
            user = db.execute("SELECT * FROM auth_users WHERE username=?", (claims["sub"],)).fetchone()
            session = db.execute("SELECT 1 FROM auth_sessions WHERE id=? AND username=? AND expires>?", (claims["jti"], claims["sub"], int(time.time()))).fetchone()
            if claims["kind"] != "user" or not session or not user or not user["enabled"] or user["version"] != claims.get("ver"):
                raise HTTPException(401, "登录已失效，请重新登录", headers={"WWW-Authenticate": "Bearer"})
            scopes = json.loads(user["scopes"]) if "scopes" in user.keys() else {"assets": ["*"], "sources": ["*"]}
            return Principal(user["username"], user["role"], frozenset(json.loads(user["domains"])), claims["exp"], False, frozenset(scopes["assets"]), frozenset(scopes["sources"]))

    def service_token(self, name):
        now = int(time.time())
        return jwt.encode({"sub": name, "kind": "service", "jti": secrets.token_hex(16), "iat": now, "exp": now + 60, "iss": "marketlens", "aud": "marketlens-api"}, self.key, algorithm="HS256")

    def logout(self, token):
        claims = self.claims(token)
        with self.connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE id=?", (claims["jti"],))
            self.audit(db, claims["sub"], "logout", claims["sub"])

    def users(self):
        with self.connect() as db:
            return [{"username": row["username"], "role": row["role"], "domains": json.loads(row["domains"]), **json.loads(row["scopes"]), "enabled": bool(row["enabled"])} for row in db.execute("SELECT * FROM auth_users ORDER BY username")]

    def save_user(self, actor, username, password, role, domains, enabled, assets=None, sources=None, create=False):
        self.validate_user(username, password, role, domains)
        hashed = password_hash(password) if password else None
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM auth_users WHERE username=?", (username,)).fetchone()
            if create:
                assets, sources = self.validate_scopes(assets if assets is not None else ["*"], sources if sources is not None else ["*"], role)
                if old:
                    raise HTTPException(409, "用户名已存在")
                if not hashed:
                    raise HTTPException(422, "新用户必须设置密码")
                db.execute("INSERT INTO auth_users(username,password,role,domains,enabled,version,scopes) VALUES(?,?,?,?,?,1,?)", (username, hashed, role, json.dumps(sorted(set(domains))), int(enabled), json.dumps({"assets": assets, "sources": sources}, separators=(",", ":"))))
            else:
                if not old:
                    raise HTTPException(404, "用户不存在")
                old_scopes = json.loads(old["scopes"]) if "scopes" in old.keys() else {"assets": ["*"], "sources": ["*"]}
                assets, sources = self.validate_scopes(assets if assets is not None else old_scopes["assets"], sources if sources is not None else old_scopes["sources"], role)
                admins = db.execute("SELECT count(*) FROM auth_users WHERE role='admin' AND enabled=1").fetchone()[0]
                if old["role"] == "admin" and old["enabled"] and admins <= 1 and (role != "admin" or not enabled):
                    raise HTTPException(409, "不能停用或降级最后一个管理员")
                db.execute("UPDATE auth_users SET password=?,role=?,domains=?,enabled=?,scopes=?,version=version+1 WHERE username=?", (hashed or old["password"], role, json.dumps(sorted(set(domains))), int(enabled), json.dumps({"assets": assets, "sources": sources}, separators=(",", ":")), username))
                db.execute("DELETE FROM auth_sessions WHERE username=?", (username,))
            self.audit(db, actor, "user_create" if create else "user_update", username)

    @staticmethod
    def validate_scopes(assets, sources, role):
        normalized = []
        for values in (assets, sources):
            selected = sorted(set(values or []))
            if not selected or len(selected) > 500 or any(not isinstance(value, str) or not value or len(value) > 200 for value in selected):
                raise HTTPException(422, "资产和来源范围必须是 1 至 500 个非空标识")
            if "*" in selected and selected != ["*"]:
                raise HTTPException(422, "全范围标记不能与其他标识同时使用")
            normalized.append(selected)
        if role == "admin" and (normalized[0] != ["*"] or normalized[1] != ["*"]):
            raise HTTPException(422, "管理员必须拥有完整资产和来源范围")
        return tuple(normalized)


@lru_cache(maxsize=4)
def store_for(path: str) -> AuthStore:
    return AuthStore(Path(path))


def auth_store() -> AuthStore:
    path = os.getenv("AUTH_DATABASE_PATH") or str(load_config().database_path.with_name("auth.sqlite3"))
    return store_for(str(Path(path).resolve()))


def outgoing_auth_headers() -> dict[str, str]:
    if not auth_enabled():
        return {}
    credential = authorization_context.get()
    if credential:
        return {"Authorization": credential}
    name = os.getenv("AUTH_SERVICE_NAME", "backend")
    return {"Authorization": "Bearer " + auth_store().service_token(name)}


def require_domain(principal: Principal, *domains: str):
    if not set(domains) <= principal.domains:
        raise HTTPException(403, "没有访问此数据范围的权限")


def require_scope(principal: Principal | None, scope: str, identifier: str) -> None:
    if not auth_enabled() or principal is None:
        return
    values = principal.assets if scope == "asset" else principal.sources
    if "*" not in values and identifier not in values:
        raise HTTPException(404, "资源不存在或当前账号无权访问")


def has_full_scope(principal: Principal | None, scope: str) -> bool:
    if not auth_enabled() or principal is None:
        return True
    values = principal.assets if scope == "asset" else principal.sources
    return "*" in values


def authorize(principal: Principal, path: str, method: str):
    if path.startswith("/api/internal/"):
        if not principal.service or principal.username != "alert" or path != "/api/internal/alert-states":
            raise HTTPException(403, "此接口仅供指定内部服务使用")
        return
    if path.startswith(("/api/auth/users", "/api/auth/audit", "/api/system/")):
        if principal.role != "admin" and not principal.service:
            raise HTTPException(403, "此操作需要管理员权限")
        if path.startswith("/api/auth/") and principal.service:
            raise HTTPException(403, "服务身份不能管理用户")
        return
    if path.startswith("/api/auth/"):
        if principal.service:
            raise HTTPException(403, "需要用户身份")
        return
    if path.startswith("/api/alert-rules"):
        require_domain(principal, "market")
        if not has_full_scope(principal, "asset"):
            raise HTTPException(403, "全市场预警规则仅面向全资产范围账号")
        if method not in {"GET", "HEAD"} and principal.role != "admin":
            raise HTTPException(403, "只有管理员可以修改预警规则")
        return
    if path.startswith("/api/data/"):
        require_domain(principal, "catalog")
        if path == "/api/data/version" and not has_full_scope(principal, "source"):
            raise HTTPException(403, "来源范围受限账号不可查看全局数据版本")
    elif path.startswith("/api/replay/") or path.startswith("/ws/") or path in {"/api/kafka/status", "/api/flink/status", "/api/home/summary"}:
        require_domain(principal, "market", "catalog")
        if not has_full_scope(principal, "asset"):
            raise HTTPException(403, "历史回放和全市场状态仅面向全资产范围账号")
        if path == "/api/home/summary" and not has_full_scope(principal, "source"):
            raise HTTPException(403, "来源范围受限账号不可查看全局首页摘要")
    elif path.startswith(("/api/assets", "/api/regimes", "/api/features", "/api/alerts")):
        require_domain(principal, "market")
        if not path.startswith("/api/assets") and not has_full_scope(principal, "asset"):
            raise HTTPException(403, "全市场模型、状态和预警仅面向全资产范围账号")
    elif path not in {"/graphql", "/graphql/", "/docs", "/openapi.json", "/docs/oauth2-redirect", "/api/health", "/api/health/ready"}:
        raise HTTPException(403, "未授权的接口")
    if method not in {"GET", "HEAD", "WEBSOCKET"} and path != "/graphql":
        if not path.startswith("/api/replay/sessions") or principal.role not in {"analyst", "admin"}:
            raise HTTPException(403, "当前账号仅可查看，不能控制回放")


class AuthMiddleware:
    def __init__(self, app, origins: list[str]):
        self.app = app
        self.origins = set(origins)

    async def __call__(self, scope, receive, send):
        if not auth_enabled() or scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        original_send = send
        websocket_accepted = False
        websocket_closed = False

        async def private_send(message):
            nonlocal websocket_accepted, websocket_closed
            if scope["type"] == "websocket":
                if websocket_closed:
                    return
                if message["type"] == "websocket.accept":
                    websocket_accepted = True
                elif message["type"] == "websocket.close":
                    websocket_closed = True
            if message["type"] == "http.response.start":
                message["headers"] = [(key, value) for key, value in message.get("headers", []) if key.lower() != b"cache-control"] + [(b"cache-control", b"no-store")]
            await original_send(message)

        send = private_send
        connection = HTTPConnection(scope)
        path = scope["path"]
        method = scope.get("method", "WEBSOCKET")
        public = method == "OPTIONS" or (method == "GET" and path in {"/api/health", "/api/health/ready", "/api/auth/status"}) or (method == "POST" and path in {"/api/auth/login", "/api/auth/bootstrap"})
        token_context = None
        try:
            auth = connection.headers.get("authorization", "")
            cookie = connection.cookies.get(COOKIE, "")
            token = auth[7:] if auth.startswith("Bearer ") else ("" if auth else cookie)
            origin = connection.headers.get("origin")
            if (cookie and not auth and (method not in {"GET", "HEAD", "OPTIONS"} or scope["type"] == "websocket")) or (public and method == "POST" and origin):
                if origin not in self.origins:
                    raise HTTPException(403, "请求来源不被允许")
            if not public:
                if not token:
                    raise HTTPException(401, "请先登录", headers={"WWW-Authenticate": "Bearer"})
                principal = await asyncio.to_thread(auth_store().verify, token)
                scope.setdefault("state", {})["principal"] = principal
                authorize(principal, path, method)
                token_context = authorization_context.set("Bearer " + token)
            if scope["type"] == "websocket" and not public:
                async def watch():
                    while True:
                        await asyncio.sleep(1)
                        await asyncio.to_thread(auth_store().verify, token)

                work = asyncio.create_task(self.app(scope, receive, send))
                guard = asyncio.create_task(watch())
                try:
                    completed, _ = await asyncio.wait({work, guard}, return_when=asyncio.FIRST_COMPLETED)
                    if guard in completed:
                        try:
                            guard.result()
                        except HTTPException:
                            await send({"type": "websocket.close", "code": 4401})
                        except (sqlite3.Error, OSError):
                            await send({"type": "websocket.close", "code": 1013})
                        work.cancel()
                        await asyncio.gather(work, return_exceptions=True)
                    else:
                        work.result()
                finally:
                    guard.cancel()
                    work.cancel()
                    await asyncio.gather(work, guard, return_exceptions=True)
            else:
                await self.app(scope, receive, send)
        except HTTPException as error:
            principal = scope.get("state", {}).get("principal")
            if principal and not principal.service and method == "POST" and path.startswith("/api/replay/sessions") and getattr(scope["app"].state, "governance_service_name", "") == "marketlens-api":
                try:
                    await asyncio.to_thread(auth_store().record_event, principal.username, "replay_denied", "", error.status_code)
                except (sqlite3.Error, OSError):
                    pass
            if scope["type"] == "websocket":
                if not websocket_accepted:
                    await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": 4401 if error.status_code == 401 else 4403})
            else:
                code = {401: "unauthenticated", 403: "forbidden", 429: "rate_limited"}.get(error.status_code, "auth_error")
                response = JSONResponse({"detail": error.detail, "error": {"code": code, "message": error.detail, "request_id": current_request_id()}}, status_code=error.status_code, headers=error.headers)
                response.headers["Cache-Control"] = "no-store"
                await response(scope, receive, send)
        except (sqlite3.Error, OSError):
            if scope["type"] == "websocket":
                if not websocket_accepted:
                    await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": 1013})
            else:
                await JSONResponse({"detail": "身份服务暂时不可用", "error": {"code": "auth_unavailable", "message": "身份服务暂时不可用", "request_id": current_request_id()}}, status_code=503)(scope, receive, send)
        finally:
            if token_context is not None:
                authorization_context.reset(token_context)


def install_auth(app, origins):
    if auth_enabled() and not 60 <= int(os.getenv("AUTH_SESSION_SECONDS", "3600")) <= 86400:
        raise ValueError("AUTH_SESSION_SECONDS 必须在 60～86400 之间")
    app.add_middleware(AuthMiddleware, origins=origins)
