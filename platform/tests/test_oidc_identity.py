"""Synthetic RSA access tokens and ASGI requests only; no network or identities."""
import base64
import copy
from dataclasses import FrozenInstanceError
import json
import time
import unittest
from unittest.mock import Mock, patch
from typing import Any, cast

import jwt
from jwt.algorithms import RSAAlgorithm
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes
from fastapi import HTTPException
from starlette.responses import JSONResponse

from agent_factory.oidc_identity import (MAX_TOKEN_BYTES, OIDCAccessTokenVerifier,
    OIDCIdentityBridge, OIDCIdentityConfig, OIDCIdentityError)

ISSUER = "https://issuer.example.test/tenant"
AUDIENCE = "https://factory.example.test/api"
PRIVATE = "synthetic-private-error-token-text"


def encode(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class RSAFixture:
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = RSAAlgorithm.to_jwk(cls.private_key.public_key(), as_dict=True)
        cls.jwk.update(kid="operator-key-1", alg="RS256", use="sig")
        cls.now = int(time.time())

    def config(self, **changes):
        values: dict[str, Any] = dict(issuer=ISSUER, audience=AUDIENCE, jwks={"keys": [copy.deepcopy(self.jwk)]},
                      subject_owners={(ISSUER, "subject-123"): "alice"})
        values.update(changes)
        return OIDCIdentityConfig(**values)

    def claims(self, **changes):
        values = {"iss": ISSUER, "sub": "subject-123", "aud": AUDIENCE,
                  "iat": self.now, "exp": self.now + 300, "jti": "synthetic-token-1", "client_id": "client-1"}
        values.update(changes)
        return values

    def token(self, claims=None, *, headers=None, key=None, algorithm="RS256"):
        return jwt.encode(self.claims() if claims is None else claims, key or self.private_key, algorithm=algorithm,
                          headers={"kid": "operator-key-1", "typ": "at+jwt", **(headers or {})})

    def verify(self, token, config=None):
        with patch("agent_factory.oidc_identity.time.time", return_value=self.now):
            return OIDCAccessTokenVerifier(config or self.config()).verify(token)

    def signed_raw(self, header, claims):
        message = encode(header.encode()) + "." + encode(claims.encode())
        signature = self.private_key.sign(message.encode(), padding.PKCS1v15(), hashes.SHA256())
        return message + "." + encode(signature)


class OIDCVerifierTests(RSAFixture, unittest.TestCase):
    def test_valid_access_token_maps_only_fixed_issuer_subject_owner(self):
        identity = self.verify(self.token(self.claims(roles=["agent_os:admin"], scope="all", owner="mallory")))
        self.assertEqual(identity.owner_id, "alice")
        self.assertEqual(identity.expires_at, self.now + 300)
        self.assertEqual(self.verify(self.token(headers={"typ": "application/at+jwt"})).owner_id, "alice")
        self.assertEqual(set(identity.__dict__), {"owner_id", "expires_at"})
        self.assertEqual(self.verify(self.token(self.claims(aud=["other-resource", AUDIENCE]))).owner_id, "alice")

    def test_wrong_signature_algorithm_idtoken_key_header_and_issuer_audience_rejected(self):
        tokens = [self.token(key=self.other_key), self.token(headers={"typ": "JWT"}),
                  self.token(headers={"typ": "application/id+jwt"}), self.token(headers={"kid": "missing-key"}),
                  self.token(headers={"jku": "https://example.test/"+PRIVATE}),
                  self.token(headers={"x5u": "https://example.test/"+PRIVATE}),
                  self.token(headers={"jwk": self.jwk}), self.token(headers={"crit": ["custom"]}),
                  self.token(self.claims(iss="https://other.example.test")), self.token(self.claims(aud="wrong")),
                  self.token(self.claims(sub="unmapped")),
                  self.token(key="synthetic-hmac-fixture-key-at-least-32bytes", algorithm="HS256")]
        for token in tokens:
            with self.subTest(size=len(token)), self.assertRaises(OIDCIdentityError) as caught:
                self.verify(token)
            self.assertEqual(str(caught.exception), "OIDC_ACCESS_TOKEN_INVALID")
            self.assertNotIn(PRIVATE, str(caught.exception))

    def test_required_claims_exact_types_time_bounds_and_optional_nbf(self):
        for field in ("iss", "sub", "aud", "exp", "iat", "jti", "client_id"):
            claims = self.claims()
            del claims[field]
            with self.subTest(missing=field), self.assertRaises(OIDCIdentityError):
                self.verify(self.token(claims))
        changes = [{"exp": True}, {"iat": False}, {"exp": self.now+300.0}, {"iat": str(self.now)},
                   {"exp": self.now-31, "iat": self.now-100}, {"iat": self.now+31},
                   {"exp": self.now+3601}, {"iat": self.now+301}, {"nbf": self.now+31}, {"nbf": True},
                   {"nbf": self.now+301}, {"sub": 123}, {"jti": ""}, {"client_id": []},
                   {"aud": [AUDIENCE, AUDIENCE]}, {"aud": [True, AUDIENCE]}, {"aud": {"aud": AUDIENCE}}]
        for change in changes:
            with self.subTest(fields=list(change)), self.assertRaises(OIDCIdentityError):
                self.verify(self.token(self.claims(**change)))
        self.assertEqual(self.verify(self.token(self.claims(iat=self.now+30, nbf=self.now+30))).owner_id, "alice")

    def test_compact_token_bounds_duplicate_json_and_malformed_input(self):
        header = '{"alg":"RS256","typ":"at+jwt","kid":"operator-key-1"}'
        claims = json.dumps(self.claims())
        duplicate_header = header[:-1] + ',"typ":"at+jwt"}'
        duplicate_claims = claims[:-1] + ',"sub":"subject-123"}'
        for token in ("", "x"*(MAX_TOKEN_BYTES+1), "a.b.c", "a.b", "é",
                      self.signed_raw(duplicate_header, claims), self.signed_raw(header, duplicate_claims)):
            with self.assertRaises(OIDCIdentityError):
                self.verify(token)

    def test_jwks_rejects_private_remote_weak_or_ambiguous_key_configuration(self):
        variants = [{**self.jwk, "d": PRIVATE}, {**self.jwk, "x5u": "https://example.test/key"},
                    {**self.jwk, "kty": "oct"}, {**self.jwk, "alg": "HS256"}, {**self.jwk, "use": "enc"},
                    {**self.jwk, "key_ops": ["sign"]}, {**self.jwk, "kid": "unsafe/kid"},
                    {**self.jwk, "n": encode(b"\x01"*128)}, {**self.jwk, "e": "AQ"},
                    {**self.jwk, "n": self.jwk["n"]+"="}]
        for key in variants:
            with self.subTest(fields=list(key)), self.assertRaises(OIDCIdentityError):
                OIDCAccessTokenVerifier(self.config(jwks={"keys": [key]}))
        for keys in ([], [self.jwk, self.jwk], [self.jwk]*17):
            with self.assertRaises(OIDCIdentityError):
                OIDCAccessTokenVerifier(self.config(jwks={"keys": keys}))

    def test_config_is_snapshotted_immutable_and_rejects_bad_operator_policy(self):
        keys = {"keys": [copy.deepcopy(self.jwk)]}
        owners = {(ISSUER, "subject-123"): "alice"}
        config = self.config(jwks=keys, subject_owners=owners)
        keys["keys"][0]["kid"] = "changed"
        owners[(ISSUER, "subject-123")] = "mallory"
        self.assertEqual(self.verify(self.token(), config).owner_id, "alice")
        with self.assertRaises(TypeError):
            cast(Any, config.subject_owners)[(ISSUER, "subject-123")] = "mallory"
        with self.assertRaises(FrozenInstanceError):
            setattr(config, "audience", "other")
        for changes in ({"issuer": "http://issuer.example.test"}, {"issuer": "https://user:pw@issuer.example.test"},
                        {"issuer": "https://issuer.example.test?query=1"}, {"clock_skew_seconds": True},
                        {"clock_skew_seconds": 61}, {"max_token_lifetime_seconds": 3601},
                        {"subject_owners": {(ISSUER, "subject-123"): "__admin"}}):
            with self.assertRaises(OIDCIdentityError):
                self.config(**changes)


class OIDCBridgeTests(RSAFixture, unittest.IsolatedAsyncioTestCase):
    async def request(self, headers, *, auth=None, scope_type="http", path="/api/protected", scheme="https"):
        seen, sent = [], []
        async def app(scope, receive, send):
            seen.append(scope)
            await JSONResponse({"downstream": True})(scope, receive, send)
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(value):
            sent.append(value)
        auth = auth or Mock()
        auth._issue_native_token.return_value = "synthetic-internal-token"
        bridge = OIDCIdentityBridge(app, auth, OIDCAccessTokenVerifier(self.config()))
        with patch("agent_factory.oidc_identity.time.time", return_value=self.now):
            await bridge({"type": scope_type, "method": "GET", "path": path, "scheme": scheme, "headers": headers}, receive, send)
        return seen, sent, auth

    async def test_valid_bearer_becomes_short_lived_native_owner_token_only(self):
        external = self.token(self.claims(exp=self.now+35, scope="admin", roles=["admin"]))
        seen, sent, auth = await self.request([(b"authorization", ("Bearer "+external).encode())])
        auth._issue_native_token.assert_called_once_with("alice", lifetime_seconds=35)
        self.assertEqual(seen[0]["headers"], [(b"authorization", b"Bearer synthetic-internal-token")])
        self.assertNotIn(external.encode(), sent[1]["body"])

    async def test_noauth_health_passthrough_cookie_is_not_promoted(self):
        cookie = ("factory_demo_session="+self.token()).encode()
        seen, sent, auth = await self.request([(b"cookie", cookie)], path="/api/health")
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(seen[0]["headers"], [(b"cookie", cookie)])
        auth._issue_native_token.assert_not_called()

    async def test_duplicate_malformed_hmac_auth_and_expired_bridge_fail_closed(self):
        token = self.token()
        cases = [[(b"authorization", ("Bearer "+token).encode()), (b"Authorization", ("Bearer "+token).encode())],
                 [(b"authorization", b"Basic "+PRIVATE.encode())], [(b"authorization", b"Bearer  token")],
                 [(b"authorization", ("Bearer "+"x"*(MAX_TOKEN_BYTES+1)).encode())],
                 [(b"authorization", ("Bearer "+self.token(key="synthetic-hmac-fixture-key-at-least-32bytes", algorithm="HS256")).encode())],
                 [(b"authorization", ("Bearer "+self.token(self.claims(iat=self.now-100, exp=self.now-1))).encode())]]
        for headers in cases:
            seen, sent, auth = await self.request(headers)
            self.assertEqual(seen, [])
            self.assertEqual(sent[0]["status"], 401)
            self.assertNotIn(PRIVATE.encode(), sent[1]["body"])
            auth._issue_native_token.assert_not_called()

    async def test_missing_disabled_or_unavailable_native_identity_never_provisions(self):
        for error in (HTTPException(403, PRIVATE), HTTPException(503, PRIVATE)):
            auth = Mock()
            auth._issue_native_token.side_effect = error
            seen, sent, auth = await self.request([(b"authorization", ("Bearer "+self.token()).encode())], auth=auth)
            self.assertEqual(seen, [])
            self.assertEqual(sent[0]["status"], 503 if error.status_code == 503 else 401)
            self.assertEqual(json.loads(sent[1]["body"])["detail"],
                             "AUTHORITY_UNAVAILABLE" if error.status_code == 503 else "OIDC_ACCESS_TOKEN_INVALID")
            self.assertNotIn(PRIVATE.encode(), sent[1]["body"])
            auth.directory.upsert.assert_not_called()

    async def test_websocket_is_not_an_alternate_authentication_route(self):
        seen, sent, auth = await self.request([], scope_type="websocket")
        self.assertEqual(seen, [])
        self.assertEqual(sent, [{"type": "websocket.close", "code": 1008}])
        auth._issue_native_token.assert_not_called()

    async def test_http_and_forged_forwarded_proto_cannot_carry_bearer(self):
        bearer = (b"authorization", ("Bearer "+self.token()).encode())
        for extra in ([], [(b"x-forwarded-proto", b"https")], [(b"forwarded", b"proto=https")]):
            seen, sent, auth = await self.request([bearer, *extra], scheme="http")
            self.assertEqual(seen, [])
            self.assertEqual(sent[0]["status"], 401)
            auth._issue_native_token.assert_not_called()
        seen, sent, auth = await self.request([], scheme="http", path="/api/health")
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(len(seen), 1)
        auth._issue_native_token.assert_not_called()
