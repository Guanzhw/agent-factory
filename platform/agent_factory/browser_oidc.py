"""Pinned public-client OIDC code flow; no discovery, provisioning or token storage.

https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation
https://www.rfc-editor.org/rfc/rfc7636.html#section-4
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hmac
import hashlib
import json
import re
import time
from typing import Any, Mapping, cast
from urllib.parse import urlsplit

import httpx
import jwt

from .oidc_identity import (MAX_TOKEN_BYTES, OIDCAccessTokenVerifier, OIDCIdentityConfig,
                            VerifiedIdentity, _json_segment, _text, _unbase64, _unique_object)


class BrowserOIDCError(ValueError):
    def __init__(self):
        super().__init__("BROWSER_OIDC_INVALID")


def _check(value):
    if not value:
        raise BrowserOIDCError()


def _origin(url):
    _check(_text(url, 2048))
    parsed = urlsplit(url)
    _check(parsed.scheme == "https" and parsed.hostname and not parsed.username
           and not parsed.password and not parsed.query and not parsed.fragment
           and "\\" not in url and (parsed.port is None or 1 <= parsed.port <= 65535))
    return parsed, f"https://{parsed.netloc}"


@dataclass(frozen=True)
class BrowserOIDCConfig:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    redirect_uri: str
    jwks: Mapping[str, Any]
    subject_owners: Mapping[tuple[str, str], str]
    clock_skew_seconds: int = 30
    max_token_lifetime_seconds: int = 3600
    max_auth_age_seconds: int | None = None
    app_origin: str = field(init=False)
    fingerprint: str = field(init=False)
    _identity: OIDCIdentityConfig = field(init=False, repr=False)

    def __post_init__(self):
        try:
            _, issuer_origin = _origin(self.issuer)
            _check(_origin(self.authorization_endpoint)[1] == issuer_origin
                   and _origin(self.token_endpoint)[1] == issuer_origin)
            callback, app_origin = _origin(self.redirect_uri)
            _check(callback.path == "/api/factory/auth/callback")
            _check(self.max_auth_age_seconds is None or
                   (type(self.max_auth_age_seconds) is int and 0 <= self.max_auth_age_seconds <= 86400))
            identity = OIDCIdentityConfig(self.issuer, self.client_id, self.jwks, self.subject_owners,
                                         self.clock_skew_seconds, self.max_token_lifetime_seconds)
            OIDCAccessTokenVerifier(identity)  # Validate all pinned RSA keys at configuration time.
            object.__setattr__(self, "_identity", identity)
            object.__setattr__(self, "jwks", identity.jwks)
            object.__setattr__(self, "subject_owners", identity.subject_owners)
            object.__setattr__(self, "app_origin", app_origin)
            fingerprint_body = {
                "issuer": self.issuer, "authorizationEndpoint": self.authorization_endpoint,
                "tokenEndpoint": self.token_endpoint, "clientId": self.client_id,
                "redirectUri": self.redirect_uri,
                "jwks": [{k: list(v) if isinstance(v, tuple) else v for k, v in key.items()}
                         for key in identity.jwks["keys"]],
                "subjects": sorted((issuer, subject, owner) for (issuer, subject), owner in identity.subject_owners.items()),
                "skew": self.clock_skew_seconds, "lifetime": self.max_token_lifetime_seconds,
                "maxAge": self.max_auth_age_seconds,
            }
            object.__setattr__(self, "fingerprint", hashlib.sha256(json.dumps(
                fingerprint_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        except Exception:
            raise BrowserOIDCError() from None


class BrowserIDTokenVerifier:
    def __init__(self, config: BrowserOIDCConfig):
        self.config = config
        self._keys = OIDCAccessTokenVerifier(config._identity)._keys

    def verify(self, token: str, *, nonce: str) -> VerifiedIdentity:
        try:
            _check(_text(nonce, 256) and type(token) is str and token.isascii()
                   and 1 <= len(token) <= MAX_TOKEN_BYTES)
            parts = token.split(".")
            _check(len(parts) == 3 and len(parts[0]) <= 2048)
            header, claims = _json_segment(parts[0]), _json_segment(parts[1])
            _unbase64(parts[2])
            _check(set(header) == {"alg", "typ", "kid"} and header["alg"] == "RS256"
                   and header["typ"] == "JWT" and type(header["kid"]) is str and header["kid"] in self._keys)
            verified = jwt.decode(token, self._keys[header["kid"]], algorithms=["RS256"], options={
                "require": ["iss", "sub", "aud", "exp", "iat", "nonce"], "verify_exp": False,
                "verify_iat": False, "verify_nbf": False, "verify_aud": False, "verify_iss": False})
            _check(verified == claims and claims["iss"] == self.config.issuer and _text(claims["sub"], 255))
            aud = claims["aud"]
            if type(aud) is str:
                _check(aud == self.config.client_id)
            else:
                _check(type(aud) is list and 1 <= len(aud) <= 8 and all(_text(a, 512) for a in aud)
                       and len(set(aud)) == len(aud) and self.config.client_id in aud)
                if len(aud) > 1:
                    _check(claims.get("azp") == self.config.client_id)
            if "azp" in claims:
                _check(type(claims["azp"]) is str and claims["azp"] == self.config.client_id)
            _check(_text(claims["nonce"], 256) and hmac.compare_digest(claims["nonce"], nonce))
            iat, exp = claims["iat"], claims["exp"]
            now, skew = time.time(), self.config.clock_skew_seconds
            _check(type(iat) is int and type(exp) is int and 0 <= iat < exp <= 2**53
                   and exp - iat <= self.config.max_token_lifetime_seconds
                   and iat <= now + skew and exp > now - skew)
            if "nbf" in claims:
                nbf = claims["nbf"]
                _check(type(nbf) is int and 0 <= nbf < exp and nbf <= now + skew)
            if "auth_time" in claims or self.config.max_auth_age_seconds is not None:
                auth_time = claims.get("auth_time")
                _check(type(auth_time) is int and 0 <= auth_time <= iat and auth_time <= now + skew)
                if self.config.max_auth_age_seconds is not None:
                    _check(now - auth_time <= self.config.max_auth_age_seconds + skew)
            owner = self.config.subject_owners.get((claims["iss"], claims["sub"]))
            _check(owner is not None)
            return VerifiedIdentity(cast(str, owner), exp)
        except Exception:
            raise BrowserOIDCError() from None


class BrowserCodeExchanger:
    def __init__(self, config: BrowserOIDCConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        _check(transport is None or isinstance(transport, httpx.AsyncBaseTransport))
        self.config, self._transport = config, transport
        self._verifier = BrowserIDTokenVerifier(config)

    async def exchange(self, code: str, *, code_verifier: str, nonce: str) -> VerifiedIdentity:
        try:
            _check(_text(code, 2048) and _text(nonce, 256) and type(code_verifier) is str
                   and re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", code_verifier) is not None)

            async def guard(request):
                _check(request.method == "POST" and str(request.url) == self.config.token_endpoint
                       and "authorization" not in request.headers and "cookie" not in request.headers)

            async with asyncio.timeout(10):
                async with httpx.AsyncClient(transport=self._transport, verify=True, trust_env=False,
                    follow_redirects=False, timeout=10, auth=None, event_hooks={"request": [guard]}) as client:
                    async with client.stream("POST", self.config.token_endpoint, data={
                        "grant_type": "authorization_code", "code": code, "client_id": self.config.client_id,
                        "redirect_uri": self.config.redirect_uri, "code_verifier": code_verifier},
                        headers={"Accept": "application/json", "Accept-Encoding": "identity",
                                 "User-Agent": "agent-factory-browser-oidc/1"}) as response:
                        _check(response.status_code == 200 and response.headers.get("content-encoding", "identity") == "identity"
                               and response.headers.get("content-type", "").split(";")[0].strip() == "application/json")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            _check(len(body) + len(chunk) <= 65536)
                            body.extend(chunk)
            payload = json.loads(body, object_pairs_hook=_unique_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(BrowserOIDCError()))
            _check(type(payload) is dict and "error" not in payload and type(payload.get("id_token")) is str)
            return self._verifier.verify(cast(str, payload["id_token"]), nonce=nonce)
        except Exception:
            raise BrowserOIDCError() from None
