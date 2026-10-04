"""Explicit demo-only, in-memory OIDC provider; never a production identity.

Uses the existing BrowserOIDCConfig/BrowserCodeExchanger and opaque SQL browser
session flow. No account provisioning, native JWT minting or alternate sessions.
The synthetic fixture's code/PKCE pattern is extended with per-flow persona
selection instead of mutable process-global identity selection.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import time
from types import MappingProxyType
from urllib.parse import parse_qsl, urlencode, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from .browser_oidc import BrowserCodeExchanger, BrowserOIDCConfig

PREFIX = "/api/factory/dev-identity"
FLOW_COOKIE = "__Host-factory_mock_flow"
PERSONAS = MappingProxyType({"alice": "Alice", "bob": "Bob", "manager": "Manager", "manager2": "Second manager / reviewer"})
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")


class DevelopmentIdentityError(ValueError):
    def __init__(self):
        super().__init__("DEVELOPMENT_IDENTITY_REJECTED")


def _require(value):
    if not value:
        raise DevelopmentIdentityError()


def _pairs(raw, expected):
    _require(type(raw) is bytes and len(raw) <= 4096)
    pairs = parse_qsl(raw.decode("ascii"), strict_parsing=True, keep_blank_values=True, max_num_fields=12)
    result = dict(pairs)
    _require(len(result) == len(pairs) and set(result) == set(expected))
    return result


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")


def _private(response):
    response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY", "Content-Security-Policy": "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})
    return response


def validate_development_origin(public_origin: str) -> str:
    """Validate an explicit HTTPS loopback origin without generating any key."""
    try:
        _require(type(public_origin) is str and len(public_origin) <= 512 and public_origin.isascii())
        parsed = urlsplit(public_origin)
        _require(parsed.scheme == "https" and parsed.path == "" and not parsed.query and not parsed.fragment
                 and not parsed.username and not parsed.password and parsed.hostname is not None
                 and "\\" not in public_origin and not any(c.isspace() for c in public_origin)
                 and (parsed.port is None or 1 <= parsed.port <= 65535)
                 and public_origin == "https://" + parsed.netloc)
        assert parsed.hostname is not None
        _require(parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback)
        return public_origin
    except Exception:
        raise DevelopmentIdentityError() from None


class DevelopmentIdentityProvider:
    def __init__(self, *, demo: bool, public_origin: str):
        _require(demo is True)
        validate_development_origin(public_origin)
        parsed = urlsplit(public_origin)
        self.public_origin = public_origin
        self._authority = parsed.netloc
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = RSAAlgorithm.to_jwk(self._key.public_key(), as_dict=True)
        public.update(kid="development-ephemeral-rsa", alg="RS256", use="sig")
        issuer = public_origin + PREFIX
        self.config = BrowserOIDCConfig(issuer=issuer, authorization_endpoint=issuer + "/authorize",
            token_endpoint=issuer + "/token", client_id="factory-development-mock", redirect_uri=public_origin + "/api/factory/auth/callback",
            jwks={"keys": [public]}, subject_owners={(issuer, "development-" + persona): persona for persona in PERSONAS})
        self._flows, self._codes = {}, {}
        self._lock = threading.Lock()
        self.app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        self.app.add_api_route(PREFIX + "/authorize", self.authorize, methods=["GET"])
        self.app.add_api_route(PREFIX + "/select", self.select, methods=["POST"])
        self.app.add_api_route(PREFIX + "/token", self.exchange, methods=["POST"])
        self.exchanger = BrowserCodeExchanger(self.config, transport=httpx.ASGITransport(app=self.app))

    def _transport(self, request):
        _require(request.scope.get("scheme") == "https" and request.headers.getlist("host") == [self._authority])

    def _gc(self):
        now = time.time()
        for records in (self._flows, self._codes):
            for key in [key for key, value in records.items() if value["expires"] <= now]:
                del records[key]

    async def _form(self, request):
        _require(request.headers.get("content-type", "").split(";")[0] == "application/x-www-form-urlencoded"
                 and not request.scope.get("query_string"))
        body = bytearray()
        async for chunk in request.stream():
            _require(len(body) + len(chunk) <= 4096)
            body.extend(chunk)
        return bytes(body)

    async def authorize(self, request: Request):
        try:
            self._transport(request)
            query = _pairs(request.scope.get("query_string", b""), {"response_type", "client_id", "redirect_uri", "scope",
                "state", "nonce", "code_challenge", "code_challenge_method"})
            _require(query["response_type"] == "code" and query["client_id"] == self.config.client_id
                and query["redirect_uri"] == self.config.redirect_uri and query["scope"] == "openid"
                and query["code_challenge_method"] == "S256"
                and all(_TOKEN.fullmatch(query[key]) for key in ("state", "nonce", "code_challenge")))
            flow, binding, csrf = (secrets.token_urlsafe(32) for _ in range(3))
            with self._lock:
                self._gc()
                _require(len(self._flows) < 256 and len(self._codes) < 256)
                self._flows[flow] = {**query, "binding": hashlib.sha256(binding.encode()).hexdigest(), "csrf": csrf,
                                     "expires": time.time() + 300}
            buttons = "".join('<button type="submit" name="persona" value="' + key + '">' + label + '</button>'
                              for key, label in PERSONAS.items())
            html = '<!doctype html><html lang="zh"><meta charset="utf-8"><title>开发模拟登录</title><body>'
            html += '<h1>开发模拟登录</h1><p>仅开发环境。以下为合成身份，不连接真实统一登录服务。</p>'
            html += '<form method="post" action="' + PREFIX + '/select"><input type="hidden" name="flow" value="' + flow + '">'
            html += '<input type="hidden" name="csrf" value="' + csrf + '">' + buttons
            html += '<button type="submit" name="persona" value="cancel">取消登录</button></form></body></html>'
            response = HTMLResponse(html)
            response.set_cookie(FLOW_COOKIE, binding, max_age=300, secure=True, httponly=True, samesite="strict", path="/")
            _private(response)
            # HTML form POSTs inherit this policy: no-referrer makes Origin
            # opaque ("null"). Keep the exact-origin CSRF guard while sending
            # only the origin, never the authorization query, as Referer.
            response.headers["Referrer-Policy"] = "strict-origin"
            return response
        except Exception:
            return _private(JSONResponse({"error": "invalid_request"}, status_code=400))

    async def select(self, request: Request):
        try:
            self._transport(request)
            _require(request.headers.getlist("origin") == [self.public_origin])
            form = _pairs(await self._form(request), {"flow", "csrf", "persona"})
            _require(_TOKEN.fullmatch(form["flow"]) and _TOKEN.fullmatch(form["csrf"]) and form["persona"] in {*PERSONAS, "cancel"})
            cookies = []
            for raw in request.headers.getlist("cookie"):
                _require(len(raw) <= 8192)
                for part in raw.split(";"):
                    name, separator, value = part.strip().partition("=")
                    if name == FLOW_COOKIE:
                        _require(separator == "=" and _TOKEN.fullmatch(value))
                        cookies.append(value)
            _require(len(cookies) == 1)
            with self._lock:
                self._gc()
                grant = self._flows.get(form["flow"])
                _require(grant and hmac.compare_digest(grant["binding"], hashlib.sha256(cookies[0].encode()).hexdigest())
                         and hmac.compare_digest(grant["csrf"], form["csrf"]))
                assert grant is not None
                del self._flows[form["flow"]]
                if form["persona"] == "cancel":
                    response = RedirectResponse("/?auth_error=signin_cancelled", status_code=303)
                else:
                    _require(len(self._codes) < 256)
                    code = secrets.token_urlsafe(32)
                    self._codes[code] = {"subject": "development-" + form["persona"], "nonce": grant["nonce"],
                        "challenge": grant["code_challenge"], "expires": time.time() + 60}
                    response = RedirectResponse(self.config.redirect_uri + "?" + urlencode({
                        "code": code, "state": grant["state"], "iss": self.config.issuer}), status_code=303)
            response.delete_cookie(FLOW_COOKIE, secure=True, httponly=True, samesite="strict", path="/")
            return _private(response)
        except Exception:
            return _private(JSONResponse({"error": "invalid_request"}, status_code=400))

    async def exchange(self, request: Request):
        try:
            self._transport(request)
            form = _pairs(await self._form(request), {"grant_type", "code", "client_id", "redirect_uri", "code_verifier"})
            _require(_TOKEN.fullmatch(form["code"]) and _VERIFIER.fullmatch(form["code_verifier"]))
            with self._lock:
                self._gc()
                grant = self._codes.pop(form["code"], None)
            _require(grant is not None and form["grant_type"] == "authorization_code" and form["client_id"] == self.config.client_id
                and form["redirect_uri"] == self.config.redirect_uri and hmac.compare_digest(_challenge(form["code_verifier"]), grant["challenge"]))
            now = int(time.time())
            encoded = jwt.encode({"iss": self.config.issuer, "sub": grant["subject"], "aud": self.config.client_id,
                "iat": now, "exp": now + 300, "nonce": grant["nonce"]}, self._key, algorithm="RS256",
                headers={"kid": "development-ephemeral-rsa", "typ": "JWT"})
            return _private(JSONResponse({"id_token": encoded, "token_type": "Bearer", "expires_in": 300,
                                          "access_token": "development-unused-token"}))
        except Exception:
            return _private(JSONResponse({"error": "invalid_grant"}, status_code=400))
