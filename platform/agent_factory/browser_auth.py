"""Pinned OIDC browser flow and revocable opaque sessions; native SQL owns rights.

No IdP tokens/authorization codes are persisted or returned to JavaScript. Flow
verifiers are encrypted with a domain-separated key from the existing native key.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import parse_qsl, urlencode

from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .browser_oidc import BrowserCodeExchanger, BrowserOIDCConfig
from .store import canonical

FLOW_COOKIE = "__Host-factory_flow"
SESSION_COOKIE = "__Host-factory_session"
PREFIX = "/api/factory/auth"
CONFIG = {"enabled": True, "loginPath": PREFIX + "/login", "logoutPath": PREFIX + "/logout"}
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
FLOW_SECONDS = 300
SESSION_SECONDS = 900


def _check(value, status=401):
    if not value:
        raise HTTPException(status, "BROWSER_AUTH_REJECTED")


def _valid(value):
    return type(value) is str and _TOKEN.fullmatch(value) is not None


def _hash(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class BrowserSessionService:
    def __init__(self, store, auth, config: BrowserOIDCConfig, exchanger=None, *, clock=time.time):
        self.store, self.auth, self.config, self.clock = store, auth, config, clock
        self.exchanger = exchanger or BrowserCodeExchanger(config)
        key = hmac.digest(auth._key.encode(), b"factory-browser-flow-v1", "sha256")
        self._cipher = Fernet(base64.urlsafe_b64encode(key))
        self._csrf_key = hmac.digest(auth._key.encode(), b"factory-browser-csrf-v1", "sha256")
        self.fingerprint = config.fingerprint

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

    def _get(self, conn, identity, kind):
        row = conn.execute(text("SELECT body FROM af_browser_auth WHERE id=:id AND kind=:kind"),
                           {"id": identity, "kind": kind}).first()
        if row is None:
            return None
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]

    def _save(self, conn, identity, kind, body, *, insert=False):
        encoded = "CAST(:body AS JSONB)" if conn.dialect.name == "postgresql" else ":body"
        query = (f"INSERT INTO af_browser_auth(id,kind,body) VALUES(:id,:kind,{encoded})" if insert else
                 f"UPDATE af_browser_auth SET body={encoded} WHERE id=:id AND kind=:kind")
        conn.execute(text(query), {"id": identity, "kind": kind, "body": canonical(body)})

    def _gc(self, conn):
        # Bounded cleanup of browser metadata only, never resource/usage custody.
        rows = conn.execute(text("SELECT id FROM af_browser_auth WHERE CAST(body->>'expires' AS DOUBLE PRECISION)<:now ORDER BY id LIMIT 100"),
                            {"now": self.clock()}).all()
        for row in rows:
            conn.execute(text("DELETE FROM af_browser_auth WHERE id=:id"), {"id": row[0]})

    def _capacity(self, conn, kind, limit):
        count = conn.execute(text("SELECT COUNT(*) FROM af_browser_auth WHERE kind=:kind AND CAST(body->>'expires' AS DOUBLE PRECISION)>:now"),
                             {"kind": kind, "now": self.clock()}).scalar_one()
        _check(count < limit, 429)

    def _cancel_flows(self, conn, binding):
        if not _valid(binding):
            return
        rows = conn.execute(text("SELECT id,body FROM af_browser_auth WHERE kind='flow' AND body->>'binding'=:binding LIMIT 1000"),
                            {"binding": _hash(binding)}).all()
        for row in rows:
            body = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            if body.get("issued"):
                issued = self._get(conn, body["issued"], "session")
                if issued:
                    issued["revoked"] = True
                    self._save(conn, body["issued"], "session", issued)
            if body["status"] in {"PENDING", "EXCHANGING", "COMPLETE"}:
                body.update(status="CANCELLED", sealed=None)
                self._save(conn, row[0], "flow", body)

    def start(self, flow_cookie=None, session_cookie=None):
        state, binding, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(4))
        identity = _hash(state)
        sealed = self._cipher.encrypt(canonical({"verifier": verifier, "nonce": nonce,
            "id": identity, "config": self.fingerprint}).encode()).decode()
        with self._transaction() as conn:
            self._gc(conn)
            self._cancel_flows(conn, flow_cookie)
            self._capacity(conn, "flow", 1000)
            prior = _hash(session_cookie) if _valid(session_cookie) else None
            prior_row = self._get(conn, prior, "session") if prior else None
            if not prior_row or prior_row["revoked"] or prior_row["expires"] <= self.clock():
                prior = None
            self._save(conn, identity, "flow", {"status": "PENDING", "binding": _hash(binding),
                "config": self.fingerprint, "expires": self.clock() + FLOW_SECONDS,
                "sealed": sealed, "prior": prior}, insert=True)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        params = {"response_type": "code", "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri, "scope": "openid", "state": state,
            "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
        if self.config.max_auth_age_seconds is not None:
            params["max_age"] = str(self.config.max_auth_age_seconds)
        return self.config.authorization_endpoint + "?" + urlencode(params), binding

    def _claim(self, state, binding):
        _check(_valid(state) and _valid(binding))
        with self._transaction() as conn:
            row = self._get(conn, _hash(state), "flow")
            _check(row and row["status"] == "PENDING" and row["expires"] > self.clock()
                   and row["config"] == self.fingerprint and hmac.compare_digest(row["binding"], _hash(binding)))
            assert row is not None
            sealed = row["sealed"]
            row.update(status="EXCHANGING", sealed=None)
            self._save(conn, _hash(state), "flow", row)
        # State remains consumed even on decryption, network, cancellation or crash.
        context = json.loads(self._cipher.decrypt(sealed.encode()))
        _check(context["id"] == _hash(state) and context["config"] == self.fingerprint)
        return context

    async def finish(self, code, state, binding):
        _check(type(code) is str and 1 <= len(code) <= 2048 and code.isascii()
               and all(33 <= ord(c) <= 126 for c in code))
        context = await asyncio.to_thread(self._claim, state, binding)
        identity = await self.exchanger.exchange(code, code_verifier=context["verifier"], nonce=context["nonce"])
        return await asyncio.to_thread(self._complete, state, identity)

    def _complete(self, state, identity):
        self.auth._current_user(identity.owner_id)
        token = secrets.token_urlsafe(32)
        with self._transaction() as conn:
            row = self._get(conn, _hash(state), "flow")
            _check(row and row["status"] == "EXCHANGING" and row["expires"] > self.clock()
                   and row["config"] == self.fingerprint)
            assert row is not None
            if row["prior"]:
                prior = self._get(conn, row["prior"], "session")
                _check(prior and not prior["revoked"] and prior["expires"] > self.clock())
                assert prior is not None
                prior["revoked"] = True
                self._save(conn, row["prior"], "session", prior)
            expires = min(self.clock() + SESSION_SECONDS, identity.expires_at)
            _check(expires > self.clock() + 1)
            self._capacity(conn, "session", 2000)
            # Recheck inside the serialization boundary immediately before issuance.
            self.auth._current_user(identity.owner_id)
            self._save(conn, _hash(token), "session", {"owner": identity.owner_id,
                "expires": expires, "config": self.fingerprint, "revoked": False}, insert=True)
            row.update(status="COMPLETE", issued=_hash(token), expires=expires)
            self._save(conn, _hash(state), "flow", row)
        return token

    def session(self, token):
        _check(_valid(token))
        with self._transaction() as conn:
            row = self._get(conn, _hash(token), "session")
            _check(row and not row["revoked"] and row["expires"] > self.clock()
                   and row["config"] == self.fingerprint)
        assert row is not None
        self.auth._current_user(row["owner"])
        return row

    def csrf(self, token):
        _check(_valid(token))
        return base64.urlsafe_b64encode(hmac.digest(self._csrf_key, token.encode(), "sha256")).decode().rstrip("=")

    def logout(self, token=None, binding=None):
        with self._transaction() as conn:
            self._cancel_flows(conn, binding)
            if _valid(token):
                row = self._get(conn, _hash(token), "session")
                if row:
                    row["revoked"] = True
                    self._save(conn, _hash(token), "session", row)


class BrowserAuthBridge:
    def __init__(self, app, service: BrowserSessionService, *, bearer_app=None, development_app=None):
        if development_app is not None and (getattr(service.auth.settings, "development_mock_login", False) is not True
                or service.auth.settings.demo is not True):
            raise ValueError("Development identity routing is disabled")
        self.app, self.service, self.bearer_app = app, service, bearer_app
        self.development_app = development_app

    @staticmethod
    def _cookies(scope):
        values = {}
        for name, value in scope.get("headers", []):
            if name.lower() != b"cookie":
                continue
            _check(len(value) <= 8192, 400)
            for part in value.decode("latin-1").split(";"):
                key, sep, token = part.strip().partition("=")
                if key in {SESSION_COOKIE, FLOW_COOKIE}:
                    _check(sep and key not in values and _valid(token), 400)
                    values[key] = token
        return values

    def _origin(self, scope):
        origins = [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"origin"]
        _check(scope.get("scheme") == "https" and origins == [self.service.config.app_origin], 403)

    def _csrf(self, scope, token):
        self._origin(scope)
        values = [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == b"x-factory-csrf"]
        _check(_valid(token) and len(values) == 1 and _valid(values[0])
               and hmac.compare_digest(values[0], self.service.csrf(token)), 403)

    @staticmethod
    def _private(response):
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"})
        return response

    async def _endpoint(self, request, cookies):
        path, method = request.url.path, request.method
        if path == PREFIX + "/config" and method == "GET":
            return JSONResponse({**CONFIG, **({"developmentOnly": True} if self.development_app is not None else {})})
        _check(request.scope.get("scheme") == "https", 403)
        if path == PREFIX + "/login" and method == "POST":
            self._origin(request.scope)
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                _check(size <= 1024, 413)
            url, binding = await asyncio.to_thread(self.service.start, cookies.get(FLOW_COOKIE), cookies.get(SESSION_COOKIE))
            response = JSONResponse({"authorizationUrl": url})
            response.set_cookie(FLOW_COOKIE, binding, max_age=FLOW_SECONDS + SESSION_SECONDS, secure=True, httponly=True, samesite="lax", path="/")
            return response
        if path == PREFIX + "/callback" and method == "GET":
            try:
                raw = request.scope.get("query_string", b"")
                _check(len(raw) <= 8192)
                items = parse_qsl(raw.decode("ascii"), keep_blank_values=True, strict_parsing=True)
                params = dict(items)
                _check(len(params) == len(items) and set(params) <= {"code", "state", "iss"}
                       and {"code", "state"} <= set(params)
                       and params.get("iss", self.service.config.issuer) == self.service.config.issuer)
                token = await self.service.finish(params["code"], params["state"], cookies.get(FLOW_COOKIE))
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS, secure=True, httponly=True, samesite="strict", path="/")
                response.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite="lax", path="/")
                return response
            except Exception:
                # Static error only: never reflect code/state/provider error/token.
                return RedirectResponse("/?auth_error=signin_failed", status_code=303)
        if path == PREFIX + "/session" and method == "GET":
            token = cookies.get(SESSION_COOKIE)
            if not token:
                return JSONResponse({"authenticated": False})
            try:
                await asyncio.to_thread(self.service.session, token)
            except HTTPException as error:
                if error.status_code not in {401, 403}:
                    raise
                return JSONResponse({"authenticated": False})
            return JSONResponse({"authenticated": True, "csrfToken": self.service.csrf(token)})
        if path in {PREFIX + "/logout", "/api/factory/logout"} and method == "POST":
            token = cookies.get(SESSION_COOKIE)
            if token:
                self._csrf(request.scope, token)
            else:
                self._origin(request.scope)
            await asyncio.to_thread(self.service.logout, token, cookies.get(FLOW_COOKIE))
            response = Response(status_code=204)
            response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite="strict", path="/")
            response.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite="lax", path="/")
            return response
        raise HTTPException(405, "BROWSER_AUTH_REJECTED")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if self.development_app is not None:
            if path.startswith("/api/factory/dev-identity/"):
                await self.development_app(scope, receive, send)
                return
            if path == "/api/factory/demo/login":
                await self._private(JSONResponse({"detail": "Use the development browser login"}, status_code=404))(scope, receive, send)
                return
        endpoint = path.startswith(PREFIX + "/") or path == "/api/factory/logout"
        try:
            cookies = self._cookies(scope)
            bearer = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
            _check(not bearer or len(bearer) == 1 and SESSION_COOKIE not in cookies and not endpoint, 401)
            if bearer:
                _check(self.bearer_app is not None)
                assert self.bearer_app is not None
                await self.bearer_app(scope, receive, send)
                return
            if endpoint:
                response = self._private(await self._endpoint(Request(scope, receive), cookies))
                await response(scope, receive, send)
                return
            token = cookies.get(SESSION_COOKIE)
            if token and path not in {"/", "/favicon.ico"} and not path.startswith("/assets/"):
                _check(scope.get("scheme") == "https", 403)
                if scope.get("method") not in {"GET", "HEAD", "OPTIONS"}:
                    self._csrf(scope, token)
                row = await asyncio.to_thread(self.service.session, token)
                remaining = int(row["expires"] - self.service.clock())
                _check(remaining > 0)
                native = self.service.auth._issue_native_token(row["owner"], lifetime_seconds=min(60, remaining))
                scope = {**scope, "headers": [*scope.get("headers", []), (b"authorization", ("Bearer " + native).encode())]}
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
            status = error.status_code if error.status_code in {400, 401, 403, 405, 413, 429, 503} else 401
            code = "AUTHORITY_UNAVAILABLE" if status == 503 else "BROWSER_AUTH_REJECTED"
            await self._private(JSONResponse({"code": code, "message": code}, status_code=status))(scope, receive, send)
        except Exception:
            await self._private(JSONResponse({"code": "BROWSER_AUTH_UNAVAILABLE", "message": "BROWSER_AUTH_UNAVAILABLE"}, status_code=503))(scope, receive, send)
