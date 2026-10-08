"""Opt-in RFC 9068 resource-server identity bridge; no browser/OAuth flow.

RS256 access tokens use operator-pinned public keys and issuer/subject mappings.
No discovery, token key URLs, claim roles, scope grants or user provisioning.
Standards: https://www.rfc-editor.org/rfc/rfc9068.html#section-4
https://pyjwt.readthedocs.io/en/stable/usage.html
ID tokens are a separate contract: https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import re
import time
from types import MappingProxyType
from typing import Any, Mapping, cast
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException
from starlette.responses import JSONResponse

MAX_TOKEN_BYTES = 16384
_KID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_B64 = re.compile(r"[A-Za-z0-9_-]+\Z")
_REQUIRED = ("iss", "sub", "aud", "exp", "iat", "jti", "client_id")


class OIDCIdentityError(ValueError):
    def __init__(self):
        super().__init__("OIDC_ACCESS_TOKEN_INVALID")


def _require(value):
    if not value:
        raise OIDCIdentityError()


def _text(value, limit=256):
    return (type(value) is str and 1 <= len(value) <= limit and value.isascii()
            and all(33 <= ord(c) <= 126 for c in value))


def _unbase64(value):
    _require(type(value) is str and _B64.fullmatch(value) is not None)
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    _require(base64.urlsafe_b64encode(raw).decode().rstrip("=") == value)
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _json_segment(segment):
    result = json.loads(_unbase64(segment), object_pairs_hook=_unique_object,
                        parse_constant=lambda _: (_ for _ in ()).throw(OIDCIdentityError()))
    _require(type(result) is dict)
    return result


@dataclass(frozen=True)
class OIDCIdentityConfig:
    issuer: str
    audience: str
    jwks: Mapping[str, Any]
    subject_owners: Mapping[tuple[str, str], str]
    clock_skew_seconds: int = 30
    max_token_lifetime_seconds: int = 3600

    def __post_init__(self):
        try:
            _require(_text(self.issuer, 512) and _text(self.audience, 512))
            issuer = urlsplit(self.issuer)
            _require(issuer.scheme == "https" and bool(issuer.hostname) and not issuer.username
                     and not issuer.password and not issuer.query and not issuer.fragment
                     and (issuer.port is None or 1 <= issuer.port <= 65535))
            _require(type(self.clock_skew_seconds) is int and 0 <= self.clock_skew_seconds <= 60)
            _require(type(self.max_token_lifetime_seconds) is int and 1 <= self.max_token_lifetime_seconds <= 3600)
            _require(type(self.jwks) is dict and set(self.jwks) == {"keys"})
            keys: Any = self.jwks["keys"]
            _require(type(keys) is list and 1 <= len(keys) <= 16)
            _require(len(json.dumps(self.jwks, allow_nan=False).encode()) <= 32768)
            copied = []
            for raw_key in keys:
                _require(type(raw_key) is dict)
                key = cast(dict[str, Any], raw_key)
                _require( {"kty", "kid", "n", "e"} <= set(key)
                         and set(key) <= {"kty", "kid", "n", "e", "alg", "use", "key_ops"})
                _require(key["kty"] == "RSA" and type(key["kid"]) is str and _KID.fullmatch(key["kid"]) is not None)
                _require(key.get("alg", "RS256") == "RS256" and key.get("use", "sig") == "sig")
                _require("key_ops" not in key or key["key_ops"] == ["verify"])
                _require(type(key["n"]) is str and len(key["n"]) <= 684 and type(key["e"]) is str and len(key["e"]) <= 8)
                copied.append(MappingProxyType({k: tuple(v) if k == "key_ops" else v for k, v in key.items()}))
            _require(isinstance(self.subject_owners, Mapping) and 1 <= len(self.subject_owners) <= 1024)
            owners = {}
            for pair, owner in self.subject_owners.items():
                _require(type(pair) is tuple and len(pair) == 2 and pair[0] == self.issuer and _text(pair[1], 255)
                         and type(owner) is str and _OWNER.fullmatch(owner) is not None and not owner.startswith("__"))
                owners[pair] = owner
            object.__setattr__(self, "jwks", MappingProxyType({"keys": tuple(copied)}))
            object.__setattr__(self, "subject_owners", MappingProxyType(owners))
        except Exception:
            raise OIDCIdentityError() from None


@dataclass(frozen=True)
class VerifiedIdentity:
    owner_id: str
    expires_at: int


class OIDCAccessTokenVerifier:
    def __init__(self, config: OIDCIdentityConfig):
        self.config = config
        try:
            from cryptography.hazmat.primitives.asymmetric import rsa
            keys = {}
            for item in config.jwks["keys"]:
                _require(item["kid"] not in keys)
                n_bytes, e_bytes = _unbase64(item["n"]), _unbase64(item["e"])
                _require(bool(n_bytes) and n_bytes[0] != 0 and bool(e_bytes) and e_bytes[0] != 0)
                n, e = int.from_bytes(n_bytes, "big"), int.from_bytes(e_bytes, "big")
                _require(2048 <= n.bit_length() <= 4096 and n % 2 == 1 and e in {3, 65537})
                keys[item["kid"]] = rsa.RSAPublicNumbers(e, n).public_key()
            self._keys = MappingProxyType(keys)
        except Exception:
            raise OIDCIdentityError() from None

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            _require(type(token) is str and token.isascii() and 1 <= len(token) <= MAX_TOKEN_BYTES)
            segments = token.split(".")
            _require(len(segments) == 3 and len(segments[0]) <= 2048)
            header = _json_segment(segments[0])
            claims = _json_segment(segments[1])
            _unbase64(segments[2])
            _require(set(header) == {"alg", "typ", "kid"} and header["alg"] == "RS256" and header["typ"] in {"at+jwt", "application/at+jwt"})
            kid = header["kid"]
            _require(type(kid) is str and _KID.fullmatch(kid) is not None and kid in self._keys)
            # Hard-code the algorithm. Never select it from token claims/headers.
            verified = jwt.decode(token, key=self._keys[kid], algorithms=["RS256"],
                options={"require": list(_REQUIRED), "verify_exp": False, "verify_iat": False,
                         "verify_nbf": False, "verify_aud": False, "verify_iss": False})
            _require(verified == claims and all(key in claims for key in _REQUIRED))
            _require(type(claims["iss"]) is str and claims["iss"] == self.config.issuer)
            _require(_text(claims["sub"], 255) and _text(claims["jti"]) and _text(claims["client_id"]))
            audience = claims["aud"]
            if type(audience) is str:
                _require(audience == self.config.audience)
            else:
                _require(type(audience) is list and 1 <= len(audience) <= 8 and all(_text(a, 512) for a in audience)
                         and len(set(audience)) == len(audience) and self.config.audience in audience)
            iat, exp = claims["iat"], claims["exp"]
            _require(type(iat) is int and type(exp) is int and 0 <= iat < exp <= 2**53
                     and exp - iat <= self.config.max_token_lifetime_seconds)
            now, skew = time.time(), self.config.clock_skew_seconds
            _require(iat <= now + skew and exp > now - skew)
            if "nbf" in claims:
                nbf = claims["nbf"]
                _require(type(nbf) is int and 0 <= nbf < exp and nbf <= now + skew)
            owner = self.config.subject_owners.get((claims["iss"], claims["sub"]))
            _require(owner is not None)
            return VerifiedIdentity(cast(str, owner), exp)
        except Exception:
            raise OIDCIdentityError() from None


class OIDCIdentityBridge:
    """Install only when explicitly enabled; downstream SQL remains authoritative."""
    def __init__(self, app: Any, auth: Any, verifier: OIDCAccessTokenVerifier):
        self.app, self.auth, self.verifier = app, auth, verifier

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = list(scope.get("headers", []))
        authorization = [value for name, value in headers if name.lower() == b"authorization"]
        if not authorization:
            # No cookies are parsed or promoted. Native public routes remain public;
            # native middleware rejects protected routes without authentication.
            await self.app(scope, receive, send)
            return
        try:
            _require(scope.get("scheme") == "https")
            _require(len(authorization) == 1)
            value = authorization[0]
            _require(type(value) is bytes and len(value) <= MAX_TOKEN_BYTES + 7)
            scheme, separator, token = value.partition(b" ")
            _require(scheme.lower() == b"bearer" and separator == b" " and bool(token)
                     and b" " not in token and b"\t" not in token)
            identity = self.verifier.verify(token.decode("ascii"))
            remaining = int(identity.expires_at - time.time())
            _require(remaining > 0)
            # Existing SQL user lookup refuses unknown/disabled owners; external
            # roles/scopes/names never enter the internal token or native authority.
            try:
                native = self.auth._issue_native_token(identity.owner_id, lifetime_seconds=min(60, remaining))
            except HTTPException as error:
                if error.status_code == 503:
                    await JSONResponse({"detail": "AUTHORITY_UNAVAILABLE"}, status_code=503)(scope, receive, send)
                    return
                raise
            new_headers = [(name, value) for name, value in headers if name.lower() != b"authorization"]
            new_headers.append((b"authorization", ("Bearer " + native).encode("ascii")))
        except Exception:
            await JSONResponse({"detail": "OIDC_ACCESS_TOKEN_INVALID"}, status_code=401,
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})(scope, receive, send)
            return
        await self.app({**scope, "headers": new_headers}, receive, send)
