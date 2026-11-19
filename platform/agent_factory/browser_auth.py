"""Local password login and revocable browser sessions for the native Agno application."""
from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from functools import partial
import hashlib
import hmac
import json
import re
import secrets

from fastapi import HTTPException
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .local_login import LocalPasswords
from .store import canonical

SESSION_COOKIE = "__Host-factory_session"
PREFIX = "/api/factory/auth"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def _check(value, status=401):
    if not value:
        raise HTTPException(status, "BROWSER_AUTH_REJECTED")


def _valid(value):
    return type(value) is str and _TOKEN.fullmatch(value) is not None


def _hash(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class BrowserSessionService:
    def __init__(self, store, auth, *, local_login_origin):
        self.store, self.auth, self.app_origin = store, auth, local_login_origin
        self.local_passwords = LocalPasswords(store.engine, auth.directory)
        self._csrf_key = hmac.digest(auth._key.encode(), b"factory-browser-csrf-v1", "sha256")
        # Keep the persisted fingerprint used by existing local-only installations.
        self.fingerprint = hashlib.sha256(canonical({'localOrigin': local_login_origin, 'oidc': ''}).encode()).hexdigest()

    @contextmanager
    def _transaction(self):
        with self.store.engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_browser_auth'))"))
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _revoke(conn, token):
        if _valid(token):
            conn.execute(text("DELETE FROM af_browser_auth WHERE id=:id AND kind='session'"), {'id': _hash(token)})

    def local_login(self, owner, password, session_cookie=None):
        verified = self.local_passwords.verified_hash(owner, password)
        token = secrets.token_urlsafe(32)
        with self._transaction() as conn:
            # Reset and issuance share a lock. A pre-reset verification cannot issue a new session.
            _check(self.local_passwords.current_hash(conn, owner) == verified)
            try:
                self.auth.require_member(owner)
            except HTTPException as error:
                if error.status_code == 503:
                    raise
                raise HTTPException(401, 'LOCAL_LOGIN_REJECTED') from None
            self._revoke(conn, session_cookie)
            encoded = "CAST(:body AS JSONB)" if conn.dialect.name == "postgresql" else ":body"
            conn.execute(text(f"INSERT INTO af_browser_auth(id,kind,body) VALUES(:id,'session',{encoded})"), {
                'id': _hash(token), 'body': canonical({'owner': owner, 'config': self.fingerprint,
                                                       'expires': None, 'revoked': False})})
        return token

    def session_owner(self, token):
        _check(_valid(token))
        with self.store.engine.connect() as conn:
            body = conn.execute(text("SELECT body FROM af_browser_auth WHERE id=:id AND kind='session'"),
                                {'id': _hash(token)}).scalar_one_or_none()
        row = json.loads(body) if isinstance(body, str) else body
        _check(row and row.get('revoked') is False and 'expires' in row and row['expires'] is None
               and row.get('config') == self.fingerprint)
        return row['owner']

    def session(self, token):
        return self.auth.identity(self.session_owner(token))

    def native_token(self, token):
        return self.auth._issue_native_token(self.session_owner(token), lifetime_seconds=60)

    def csrf(self, token):
        _check(_valid(token))
        return base64.urlsafe_b64encode(hmac.digest(self._csrf_key, token.encode(), "sha256")).decode().rstrip("=")

    def logout(self, token):
        if _valid(token):
            with self._transaction() as conn:
                self._revoke(conn, token)


class BrowserAuthBridge:
    def __init__(self, app, service: BrowserSessionService):
        self.app, self.service = app, service

    @staticmethod
    def _session_cookie(scope):
        session = None
        for name, value in scope.get("headers", []):
            if name.lower() != b"cookie":
                continue
            for part in value.decode("latin-1").split(";"):
                key, sep, token = part.strip().partition("=")
                if key == SESSION_COOKIE:
                    _check(sep and session is None and _valid(token), 400)
                    session = token
        return session

    def _origin(self, scope):
        origins = [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"origin"]
        _check(scope.get("scheme") == "https" and origins == [self.service.app_origin], 403)

    def _csrf(self, scope, token):
        self._origin(scope)
        values = [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"x-factory-csrf"]
        _check(_valid(token) and len(values) == 1 and _valid(values[0])
               and hmac.compare_digest(values[0], self.service.csrf(token)), 403)

    @staticmethod
    def _private(response):
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"})
        return response

    async def _endpoint(self, request, token):
        path, method = request.url.path, request.method
        _check(request.scope.get("scheme") == "https", 403)
        if path == PREFIX + '/local-login' and method == 'POST':
            self._origin(request.scope)
            try:
                payload = await request.json()
            except (ValueError, UnicodeError):
                raise HTTPException(400, "BROWSER_AUTH_REJECTED") from None
            _check(type(payload) is dict and set(payload) == {'username', 'password'}, 400)
            token = await asyncio.to_thread(self.service.local_login, payload['username'], payload['password'], token)
            response = JSONResponse({'authenticated': True})
            response.set_cookie(SESSION_COOKIE, token, secure=True, httponly=True, samesite='strict', path='/')
            return response
        if path == PREFIX + "/session" and method == "GET":
            if not token:
                return JSONResponse({"authenticated": False})
            try:
                user = await asyncio.to_thread(self.service.session, token)
            except HTTPException as error:
                if error.status_code not in {401, 403}:
                    raise
                return JSONResponse({"authenticated": False})
            return JSONResponse({"authenticated": True, "csrfToken": self.service.csrf(token), "user": user})
        if path in {PREFIX + "/logout", "/api/factory/logout"} and method == "POST":
            if token:
                self._csrf(request.scope, token)
            else:
                self._origin(request.scope)
            await asyncio.to_thread(self.service.logout, token)
            response = Response(status_code=204)
            response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="strict", path="/")
            return response
        raise HTTPException(405 if path in {PREFIX + "/local-login", PREFIX + "/session", PREFIX + "/logout", "/api/factory/logout"} else 404,
                            "BROWSER_AUTH_REJECTED")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        try:
            _check(not any(key.lower() == b"authorization" for key, _ in scope.get("headers", [])))
            token = self._session_cookie(scope)
            if path.startswith(PREFIX + "/") or path == "/api/factory/logout":
                response = self._private(await self._endpoint(Request(scope, receive), token))
                await response(scope, receive, send)
                return
            if token and path not in {"/", "/favicon.ico"} and not path.startswith("/assets/"):
                _check(scope.get("scheme") == "https", 403)
                if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
                    self._csrf(scope, token)
                native = await asyncio.to_thread(self.service.native_token, token)
                scope = {**scope, "factory.browser_session": (_hash(token), partial(self.service.session_owner, token)),
                         "headers": [*scope.get("headers", []), (b"authorization", ("Bearer " + native).encode())]}
            async def private_send(message):
                if message["type"] == "http.response.start":
                    protected = {b"cache-control", b"pragma", b"referrer-policy", b"x-frame-options"}
                    headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in protected]
                    headers.extend([(b"cache-control", b"private, no-store"), (b"pragma", b"no-cache"),
                                    (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY")])
                    message = {**message, "headers": headers}
                await send(message)
            await self.app(scope, receive, private_send)
        except HTTPException as error:
            status = error.status_code if error.status_code in {400, 401, 403, 404, 405, 413, 429, 503} else 401
            code = "AUTHORITY_UNAVAILABLE" if status == 503 else "BROWSER_AUTH_REJECTED"
            await self._private(JSONResponse({"code": code, "message": code}, status_code=status))(scope, receive, send)
        except Exception:
            await self._private(JSONResponse({"code": "BROWSER_AUTH_UNAVAILABLE", "message": "BROWSER_AUTH_UNAVAILABLE"}, status_code=503))(scope, receive, send)
