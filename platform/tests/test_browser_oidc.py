"""Offline synthetic browser identity verification and bounded token transport."""
import copy
import base64
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from typing import Any, cast
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agent_factory.browser_oidc import (BrowserCodeExchanger, BrowserIDTokenVerifier,
                                        BrowserOIDCConfig, BrowserOIDCError)

ISSUER = "https://identity.example.test/tenant"
NONCE = "synthetic-nonce-123"


class Fixture:
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = RSAAlgorithm.to_jwk(cls.key.public_key(), as_dict=True)
        cls.jwk.update(kid="key-1")

    def setUp(self):
        # The verifier owns NumericDate checks (PyJWT temporal checks are off).
        # Freeze both issuance and that verifier clock; signing remains real RSA.
        self.now = 1791130640
        clock = patch('agent_factory.browser_oidc.time', SimpleNamespace(time=lambda: self.now))
        clock.start()
        cast(unittest.TestCase, self).addCleanup(clock.stop)

    def config(self, **changes):
        values: dict[str, Any] = dict(issuer=ISSUER, authorization_endpoint="https://identity.example.test/authorize",
                      token_endpoint="https://identity.example.test/token", client_id="factory-browser",
                      redirect_uri="https://factory.example.test/api/factory/auth/callback",
                      jwks={"keys": [copy.deepcopy(self.jwk)]}, subject_owners={(ISSUER, "subject-1"): "alice"})
        values.update(changes)
        return BrowserOIDCConfig(**values)

    def token(self, *, headers=None, **changes):
        now = self.now
        claims = dict(iss=ISSUER, sub="subject-1", aud="factory-browser", nonce=NONCE, iat=now, exp=now+300)
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "key-1", "typ": "JWT", **(headers or {})})


class Verification(Fixture, unittest.TestCase):
    def test_valid_identity_ignores_external_permissions(self):
        verifier = BrowserIDTokenVerifier(self.config())
        identity = verifier.verify(self.token(roles=["admin"], owner="mallory"), nonce=NONCE)
        self.assertEqual(identity.owner_id, "alice")
        self.assertEqual(set(vars(identity)), {"owner_id", "expires_at"})
        self.assertEqual(verifier.verify(self.token(aud=["factory-browser", "other"], azp="factory-browser"), nonce=NONCE).owner_id, "alice")

    def test_invalid_claims_and_access_tokens(self):
        now = self.now
        changes = [dict(iss="https://wrong.test"), dict(sub="unknown"), dict(aud="other"), dict(nonce="other"),
                   dict(aud=["factory-browser", "other"]), dict(azp="other"), dict(aud=["factory-browser"]*2),
                   dict(iat=True), dict(exp=float(now+300)), dict(iat=now+90), dict(exp=now-90),
                   dict(exp=now+4000), dict(auth_time=True), dict(auth_time=now+1), dict(nbf=True)]
        verifier = BrowserIDTokenVerifier(self.config())
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(BrowserOIDCError, "^BROWSER_OIDC_INVALID$"):
                verifier.verify(self.token(**change), nonce=NONCE)
        for header in [dict(typ="at+jwt"), dict(jku="https://wrong.test"), dict(jwk=self.jwk), dict(kid="unknown")]:
            with self.subTest(header=header), self.assertRaises(BrowserOIDCError):
                verifier.verify(self.token(headers=header), nonce=NONCE)
        for token in ["invalid", "a"*16385, self.token()[:-8]+"invalid"]:
            with self.assertRaises(BrowserOIDCError):
                verifier.verify(token, nonce=NONCE)

    def test_duplicate_json_rejected_before_signature_validation(self):
        token = self.token().split(".")
        duplicate = b'{"alg":"RS256","typ":"JWT","kid":"key-1","kid":"key-1"}'
        token[0] = base64.urlsafe_b64encode(duplicate).decode().rstrip("=")
        with self.assertRaises(BrowserOIDCError):
            BrowserIDTokenVerifier(self.config()).verify(".".join(token), nonce=NONCE)

    def test_auth_age_and_nonce_required(self):
        verifier = BrowserIDTokenVerifier(self.config(max_auth_age_seconds=60))
        for changes in [{}, {"auth_time": self.now-100}]:
            with self.assertRaises(BrowserOIDCError):
                verifier.verify(self.token(**changes), nonce=NONCE)
        self.assertEqual(verifier.verify(self.token(auth_time=self.now), nonce=NONCE).owner_id, "alice")
        with self.assertRaises(BrowserOIDCError):
            verifier.verify(self.token(auth_time=self.now), nonce="")

    def test_config_pins_and_immutable_copy(self):
        jwks = {"keys": [copy.deepcopy(self.jwk)]}
        config = self.config(jwks=jwks)
        jwks["keys"][0]["kid"] = "changed"
        self.assertEqual(config.jwks["keys"][0]["kid"], "key-1")
        self.assertEqual(config.app_origin, "https://factory.example.test")
        self.assertEqual(len(config.fingerprint), 64)
        self.assertEqual(config.fingerprint, self.config().fingerprint)
        self.assertNotEqual(config.fingerprint, self.config(clock_skew_seconds=15).fingerprint)
        with self.assertRaises(FrozenInstanceError):
            setattr(config, "client_id", "changed")
        for changes in [dict(token_endpoint="https://evil.test/token"), dict(authorization_endpoint="http://identity.example.test/authorize"),
                        dict(redirect_uri="https://factory.example.test/wrong"), dict(token_endpoint="https://identity.example.test/token?q=1"),
                        dict(max_auth_age_seconds=True), dict(jwks={"keys": [{**self.jwk, "d": "private"}]}),
                        dict(jwks={"keys": [self.jwk, self.jwk]})]:
            with self.subTest(changes=changes), self.assertRaises(BrowserOIDCError):
                self.config(**changes)


class Exchange(Fixture, unittest.IsolatedAsyncioTestCase):
    async def test_one_pinned_pkce_post_only_identity_returned(self):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(str(request.url), self.config().token_endpoint)
            self.assertEqual(request.method, "POST")
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("cookie", request.headers)
            form = parse_qs(request.content.decode())
            self.assertEqual(form, {"grant_type": ["authorization_code"], "code": ["synthetic-code"],
                "client_id": ["factory-browser"], "redirect_uri": [self.config().redirect_uri], "code_verifier": ["v"*43]})
            return httpx.Response(200, json={"id_token": self.token(), "access_token": "discard", "refresh_token": "discard"})
        identity = await BrowserCodeExchanger(self.config(), transport=httpx.MockTransport(handler)).exchange(
            "synthetic-code", code_verifier="v"*43, nonce=NONCE)
        self.assertEqual(identity.owner_id, "alice")
        self.assertEqual(len(calls), 1)

    async def test_failures_are_bounded_sanitized_and_not_retried(self):
        cases = [httpx.Response(302, headers={"location": "https://evil.test"}),
                 httpx.Response(500, text="private-provider-error"),
                 httpx.Response(200, content=b"x"*65537, headers={"content-type": "application/json"}),
                 httpx.Response(200, content=b'{"id_token":"a","id_token":"b"}', headers={"content-type": "application/json"}),
                 httpx.Response(200, json={"error": "private-error", "id_token": self.token()}),
                 httpx.Response(200, json={"id_token": self.token(nonce="wrong")})]
        for response in cases:
            calls = []
            def handler(request):
                calls.append(request)
                return response
            with self.subTest(status=response.status_code), self.assertRaisesRegex(BrowserOIDCError, "^BROWSER_OIDC_INVALID$"):
                await BrowserCodeExchanger(self.config(), transport=httpx.MockTransport(handler)).exchange("code", code_verifier="v"*43, nonce=NONCE)
            self.assertEqual(len(calls), 1)

    async def test_transport_timeout_does_not_retry_or_echo(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout("private-provider-payload", request=request)
        with self.assertRaisesRegex(BrowserOIDCError, "^BROWSER_OIDC_INVALID$"):
            await BrowserCodeExchanger(self.config(), transport=httpx.MockTransport(handler)).exchange(
                "code", code_verifier="v"*43, nonce=NONCE)
        self.assertEqual(len(calls), 1)

    async def test_invalid_pkce_fails_before_dispatch(self):
        def handler(request):
            self.fail("invalid input dispatched")
        for verifier in ["short", "v"*129, "v"*42+"!"]:
            with self.assertRaises(BrowserOIDCError):
                await BrowserCodeExchanger(self.config(), transport=httpx.MockTransport(handler)).exchange("code", code_verifier=verifier, nonce=NONCE)


if __name__ == "__main__":
    unittest.main()
