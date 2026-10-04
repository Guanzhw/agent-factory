"""Browser boundary regressions: synthetic signed identity and disk SQLite only."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import HTTPException
import httpx
import jwt
from sqlalchemy import create_engine, text
from starlette.responses import JSONResponse

from agent_factory.browser_auth import BrowserAuthBridge, BrowserSessionService, FLOW_COOKIE, PREFIX, SESSION_COOKIE
from agent_factory.browser_oidc import BrowserIDTokenVerifier, BrowserOIDCConfig
from test_oidc_identity import RSAFixture, ISSUER  # type: ignore[reportMissingImports]

ORIGIN = "https://factory.example.test"
PRIVATE = "synthetic-provider-private-error"


class Authority:
    _key = "synthetic-browser-test-signing-key-not-a-credential"

    def __init__(self):
        self.status: int | None = None
        self.issued = []

    def _current_user(self, owner):
        if self.status:
            raise HTTPException(self.status, PRIVATE)
        if owner != "alice":
            raise HTTPException(403, PRIVATE)
        return {"id": owner}

    def _issue_native_token(self, owner, *, lifetime_seconds):
        self._current_user(owner)
        self.issued.append((owner, lifetime_seconds))
        return "synthetic-native-token-never-client-visible"


class Exchange:
    def __init__(self, fixture, config):
        self.fixture, self.verifier = fixture, BrowserIDTokenVerifier(config)
        self.calls = []
        self.failure: BaseException | None = None
        self.bad_nonce = False
        self.token_lifetime = 300
        self.pause: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def exchange(self, code, *, code_verifier, nonce):
        self.calls.append({"code": code, "verifier": code_verifier, "nonce": nonce})
        self.entered.set()
        if self.pause:
            await self.pause.wait()
        if self.failure:
            raise self.failure
        claims = {"iss": ISSUER, "sub": "subject-123", "aud": "browser-client", "iat": self.fixture.now,
                  "exp": self.fixture.now + self.token_lifetime, "nonce": "wrong-nonce" if self.bad_nonce else nonce}
        token = jwt.encode(claims, self.fixture.private_key, algorithm="RS256", headers={"kid": "operator-key-1", "typ": "JWT"})
        return self.verifier.verify(token, nonce=nonce)


class BrowserAuthTests(RSAFixture, unittest.IsolatedAsyncioTestCase):
    def browser_config(self, **changes):
        values: dict[str, Any] = dict(issuer=ISSUER, authorization_endpoint=ISSUER + "/authorize", token_endpoint=ISSUER + "/token",
                      client_id="browser-client", redirect_uri=ORIGIN + PREFIX + "/callback",
                      jwks={"keys": [copy.deepcopy(self.jwk)]}, subject_owners={(ISSUER, "subject-123"): "alice"})
        values.update(changes)
        return BrowserOIDCConfig(**values)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = create_engine("sqlite:///" + str(Path(self.temp.name) / "browser.sqlite"))
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as conn:
            conn.execute(text("CREATE TABLE af_browser_auth(id TEXT PRIMARY KEY,kind TEXT,body TEXT)"))
        self.auth = Authority()
        self.config = self.browser_config()
        self.exchange = Exchange(self, self.config)
        self.clock = float(self.now)
        self.store = SimpleNamespace(engine=self.engine)
        self.service = BrowserSessionService(self.store, self.auth, self.config, self.exchange, clock=lambda: self.clock)
        self.seen = []

        async def app(scope, receive, send):
            auth = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
            self.seen.append(auth)
            response = JSONResponse({"ok": bool(auth)}, status_code=200 if auth else 401)
            await response(scope, receive, send)

        self.app = app
        self.bridge = BrowserAuthBridge(app, self.service)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.bridge), base_url=ORIGIN)
        self.addAsyncCleanup(self.client.aclose)

    def start(self, **kwargs):
        url, binding = self.service.start(**kwargs)
        return parse_qs(urlsplit(url).query), binding

    async def sign_in(self):
        params, binding = self.start()
        return await self.service.finish("synthetic-code", params["state"][0], binding)

    def cookie(self, token):
        return {"Cookie": SESSION_COOKIE + "=" + token}

    def rows(self):
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text("SELECT * FROM af_browser_auth")).mappings()]

    async def test_pkce_flow_keeps_verifier_encrypted_and_stores_only_session_hash(self):
        params, binding = self.start(flow_cookie="A"*43, session_cookie="B"*43)
        self.assertNotEqual(binding, "A"*43)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["scope"], ["openid"])
        state = params["state"][0]
        token = await self.service.finish("synthetic-code", state, binding)
        stored = json.dumps(self.rows())
        for value in (token, binding, state, "synthetic-code", *self.exchange.calls[0].values()):
            self.assertNotIn(value, stored)
        self.assertEqual(self.service.session(token)["owner"], "alice")
        self.assertIn(hashlib.sha256(token.encode()).hexdigest(), stored)

    async def test_state_cookie_mismatch_and_missing_binding_never_exchange(self):
        params, binding = self.start()
        for state, cookie in (("A"*43, binding), (params["state"][0], "B"*43), (params["state"][0], None)):
            with self.assertRaises(HTTPException): await self.service.finish("synthetic-code", state, cookie)
        self.assertEqual(self.exchange.calls, [])

    async def test_nonce_mismatch_consumes_flow_and_never_replays_code(self):
        params, binding = self.start()
        self.exchange.bad_nonce = True
        with self.assertRaises(ValueError): await self.service.finish("synthetic-code", params["state"][0], binding)
        self.exchange.bad_nonce = False
        with self.assertRaises(HTTPException): await self.service.finish("synthetic-code", params["state"][0], binding)
        self.assertEqual(len(self.exchange.calls), 1)
        self.assertFalse(any(row["kind"] == "session" for row in self.rows()))

    async def test_lost_exchange_and_cancelled_coroutine_are_never_replayed(self):
        for error in (TimeoutError(PRIVATE), asyncio.CancelledError()):
            params, binding = self.start()
            self.exchange.failure = error
            with self.assertRaises(type(error)): await self.service.finish("synthetic-code", params["state"][0], binding)
            self.exchange.failure = None
            with self.assertRaises(HTTPException): await self.service.finish("synthetic-code", params["state"][0], binding)
        self.assertEqual(len(self.exchange.calls), 2)
        self.assertTrue(all(json.loads(row["body"])["sealed"] is None for row in self.rows()))

    async def test_lost_success_receipt_never_replays_and_session_fixation_rotates(self):
        old = await self.sign_in()
        params, binding = self.start(session_cookie=old)
        new = await self.service.finish("replacement-code", params["state"][0], binding)
        self.assertNotEqual(new, old)
        with self.assertRaises(HTTPException): self.service.session(old)
        self.assertEqual(self.service.session(new)["owner"], "alice")
        with self.assertRaises(HTTPException): await self.service.finish("replacement-code", params["state"][0], binding)
        self.assertEqual(len(self.exchange.calls), 2)

    async def test_new_login_cancels_previous_flow(self):
        params, binding = self.start()
        fresh, fresh_binding = self.start(flow_cookie=binding)
        with self.assertRaises(HTTPException): await self.service.finish("old-code", params["state"][0], binding)
        await self.service.finish("new-code", fresh["state"][0], fresh_binding)
        self.assertEqual(len(self.exchange.calls), 1)

    async def test_concurrent_callback_claim_permits_exactly_one_exchange(self):
        params, binding = self.start()
        self.exchange.pause = asyncio.Event()
        first = asyncio.create_task(self.service.finish("synthetic-code", params["state"][0], binding))
        await self.exchange.entered.wait()
        with self.assertRaises(HTTPException):
            await self.service.finish("synthetic-code", params["state"][0], binding)
        self.exchange.pause.set()
        token = await first
        self.assertEqual(self.service.session(token)["owner"], "alice")
        self.assertEqual(len(self.exchange.calls), 1)

    async def test_expired_flow_cannot_exchange_and_expiry_during_exchange_cannot_issue(self):
        params, binding = self.start()
        self.clock += 301
        with self.assertRaises(HTTPException):
            await self.service.finish("synthetic-code", params["state"][0], binding)
        self.assertEqual(self.exchange.calls, [])
        self.clock = float(self.now)
        params, binding = self.start()
        self.exchange.pause = asyncio.Event()
        pending = asyncio.create_task(self.service.finish("synthetic-code", params["state"][0], binding))
        await self.exchange.entered.wait()
        self.clock += 301
        self.exchange.pause.set()
        with self.assertRaises(HTTPException): await pending
        self.assertFalse(any(row["kind"] == "session" for row in self.rows()))

    async def test_logout_during_exchange_prevents_late_session_issuance(self):
        params, binding = self.start()
        self.exchange.pause = asyncio.Event()
        task = asyncio.create_task(self.service.finish("synthetic-code", params["state"][0], binding))
        await self.exchange.entered.wait()
        self.service.logout(binding=binding)
        self.exchange.pause.set()
        with self.assertRaises(HTTPException): await task
        self.assertFalse(any(row["kind"] == "session" for row in self.rows()))

    async def test_logout_flow_binding_revokes_completed_but_delayed_session_cookie(self):
        params, binding = self.start()
        token = await self.service.finish("synthetic-code", params["state"][0], binding)
        # Callback committed, but its Set-Cookie response has not reached the browser.
        response = await self.client.post(PREFIX + "/logout", headers={"Origin": ORIGIN, "Cookie": FLOW_COOKIE + "=" + binding})
        self.assertEqual(response.status_code, 204)
        with self.assertRaises(HTTPException): self.service.session(token)
        delayed = await self.client.get("/api/protected", headers=self.cookie(token))
        self.assertEqual(delayed.status_code, 401)
        with self.assertRaises(HTTPException): await self.service.finish("synthetic-code", params["state"][0], binding)
        self.assertEqual(len(self.exchange.calls), 1)

    async def test_completed_flow_survives_gc_past_pending_ttl_to_revoke_late_cookie(self):
        self.exchange.token_lifetime = 1200
        params, binding = self.start()
        token = await self.service.finish("synthetic-code", params["state"][0], binding)
        self.clock += 301
        self.assertEqual(self.service.session(token)["owner"], "alice")
        # A different browser starts login, triggering bounded expiry collection.
        self.start()
        completed = [json.loads(row["body"]) for row in self.rows()
                     if row["kind"] == "flow" and json.loads(row["body"])["status"] == "COMPLETE"]
        self.assertEqual(len(completed), 1)
        self.assertGreater(completed[0]["expires"], self.clock)
        response = await self.client.post(PREFIX + "/logout", headers={
            "Origin": ORIGIN, "Cookie": FLOW_COOKIE + "=" + binding})
        self.assertEqual(response.status_code, 204)
        with self.assertRaises(HTTPException): self.service.session(token)
        self.assertEqual((await self.client.get("/api/protected", headers=self.cookie(token))).status_code, 401)

    async def test_expired_session_and_current_disabled_user_deny(self):
        token = await self.sign_in()
        self.auth.status = 403
        with self.assertRaises(HTTPException) as disabled: self.service.session(token)
        self.assertEqual(disabled.exception.status_code, 403)
        self.auth.status = 503
        response = await self.client.get(PREFIX + "/session", headers=self.cookie(token))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(PRIVATE, response.text)
        self.auth.status = None
        self.clock += 901
        with self.assertRaises(HTTPException): self.service.session(token)

    async def test_restart_preserves_revocation_and_changed_config_denies_old_flow_session(self):
        token = await self.sign_in()
        params, binding = self.start()
        restart = BrowserSessionService(self.store, self.auth, self.config, self.exchange, clock=lambda: self.clock)
        self.assertEqual(restart.session(token)["owner"], "alice")
        changed = BrowserSessionService(self.store, self.auth, self.browser_config(client_id="different-client"), self.exchange, clock=lambda: self.clock)
        with self.assertRaises(HTTPException): changed.session(token)
        with self.assertRaises(HTTPException): await changed.finish("synthetic-code", params["state"][0], binding)
        restart.logout(token)
        restart.logout(token)
        with self.assertRaises(HTTPException): self.service.session(token)

    async def test_origin_csrf_missing_wrong_and_duplicates_rejected(self):
        token = await self.sign_in()
        good = [*self.cookie(token).items(), ("Origin", ORIGIN), ("X-Factory-CSRF", self.service.csrf(token))]
        cases = [good[:1], good[:1] + [("Origin", ORIGIN)],
                 good[:1] + [("Origin", "https://evil.example"), good[-1]],
                 good[:2] + [("X-Factory-CSRF", "A"*43)], good + [("Origin", ORIGIN)], good + [good[-1]]]
        for headers in cases:
            response = await self.client.post("/api/protected", headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.seen, [])
        self.assertEqual((await self.client.post("/api/protected", headers=good)).status_code, 200)
        self.assertEqual(self.auth.issued, [("alice", 60)])

    async def test_native_success_and_unauthenticated_responses_override_cache_and_framing(self):
        async def downstream(scope, receive, send):
            response = JSONResponse({"fixture": True}, headers={
                "Cache-Control": "public, max-age=3600", "Pragma": "cache",
                "Referrer-Policy": "unsafe-url", "X-Frame-Options": "SAMEORIGIN"})
            await response(scope, receive, send)

        token = await self.sign_in()
        bridge = BrowserAuthBridge(downstream, self.service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge), base_url=ORIGIN) as client:
            for path, headers in (("/api/protected", self.cookie(token)), ("/", {}), ("/api/protected", {})):
                response = await client.get(path, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get_list("cache-control"), ["private, no-store"])
                self.assertEqual(response.headers.get_list("pragma"), ["no-cache"])
                self.assertEqual(response.headers.get_list("referrer-policy"), ["no-referrer"])
                self.assertEqual(response.headers.get_list("x-frame-options"), ["DENY"])
        # Real unauthenticated downstream denial receives the same private policy.
        denied = await self.client.get("/api/protected")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.headers["cache-control"], "private, no-store")
        self.assertEqual(denied.headers["referrer-policy"], "no-referrer")
        self.assertEqual(denied.headers["x-frame-options"], "DENY")

    async def test_login_requires_pinned_origin_not_host_or_forwarded_headers(self):
        for headers in ({}, {"Origin": "https://evil.example", "Host": "evil.example", "X-Forwarded-Host": "factory.example.test"}):
            self.assertEqual((await self.client.post(PREFIX + "/login", headers=headers)).status_code, 403)
        response = await self.client.post(PREFIX + "/login", headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=lax", "path=/", "max-age=1200"):
            self.assertIn(flag, cookie)
        self.assertNotIn("domain=", cookie)
        self.assertNotIn("code_verifier", response.text)

    async def test_duplicate_cookies_and_bearer_ambiguity_fail_closed(self):
        token = await self.sign_in()
        cookie = SESSION_COOKIE + "=" + token
        for headers in ([("Cookie", cookie + "; " + cookie)], [("Cookie", cookie), ("Cookie", cookie)],
                        [("Cookie", cookie), ("Authorization", "Bearer synthetic")],
                        [("Authorization", "Bearer synthetic"), ("Authorization", "Bearer other")]):
            response = await self.client.get("/api/protected", headers=headers)
            self.assertIn(response.status_code, (400, 401))
        self.assertEqual(self.auth.issued, [])
        self.assertEqual(self.seen, [])

    async def test_callback_duplicate_query_rejected_and_credentials_never_in_browser_body(self):
        params, binding = self.start()
        query = urlencode({"code": "synthetic-code", "state": params["state"][0]})
        headers = {"Cookie": FLOW_COOKIE + "=" + binding}
        for suffix in ("&code=other", "&state=other", "&iss=wrong-issuer"):
            response = await self.client.get(PREFIX + "/callback?" + query + suffix, headers=headers)
            self.assertEqual(response.headers["location"], "/?auth_error=signin_failed")
        self.assertEqual(self.exchange.calls, [])
        response = await self.client.get(PREFIX + "/callback?" + query, headers=headers)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        self.assertEqual(response.text, "")
        cookie = response.headers.get_list("set-cookie")[0].lower()
        for flag in ("httponly", "secure", "samesite=strict", "path=/"):
            self.assertIn(flag, cookie)
        session = await self.client.get(PREFIX + "/session")
        self.assertEqual(set(session.json()), {"authenticated", "csrfToken"})
        self.assertEqual(session.headers["cache-control"], "no-store")
        self.assertEqual(session.headers["referrer-policy"], "no-referrer")
        for value in self.exchange.calls[0].values():
            self.assertNotIn(value, session.text)
        self.assertNotIn("synthetic-native-token", session.text)

    async def test_logout_lost_receipt_replay_does_not_resurrect_session(self):
        token = await self.sign_in()
        headers = {**self.cookie(token), "Origin": ORIGIN, "X-Factory-CSRF": self.service.csrf(token)}
        first = await self.client.post(PREFIX + "/logout", headers=headers)
        second = await self.client.post(PREFIX + "/logout", headers=headers)
        self.assertEqual((first.status_code, second.status_code), (204, 204))
        self.assertEqual((await self.client.get("/api/protected", headers=self.cookie(token))).status_code, 401)
        self.assertFalse((await self.client.get(PREFIX + "/session", headers=self.cookie(token))).json()["authenticated"])


if __name__ == "__main__":
    unittest.main()
