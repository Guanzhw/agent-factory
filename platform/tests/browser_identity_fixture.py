"""Synthetic loopback/ASGI OpenID provider for browser acceptance only.

Fresh RSA/TLS keys live only in fixture memory or private scratch files. No
real identity, discovery, host trust changes, or remote network is used.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlencode

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from starlette.responses import JSONResponse, RedirectResponse


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")


class BrowserIdentityFixture:
    """Strict one-use authorization codes; explicit synthetic subject selection."""
    def __init__(self, issuer="https://identity.example.test", redirect_uri="https://testserver/api/factory/auth/callback"):
        self.issuer, self.redirect_uri = issuer, redirect_uri
        self.client_id = "factory-browser-synthetic-client"
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        self.jwk.update(kid="browser-synthetic-key", alg="RS256", use="sig")
        self.codes = {}
        self.subject = "subject-alice"
        self.exchanges = 0
        self.authorizations = 0
        self.app = FastAPI()
        self.app.add_api_route("/authorize", self.authorize, methods=["GET"])
        self.app.add_api_route("/token", self.exchange, methods=["POST"])
        self.transport = httpx.ASGITransport(app=self.app)

    def config(self, **changes):
        from agent_factory.browser_oidc import BrowserOIDCConfig
        return BrowserOIDCConfig(issuer=self.issuer, authorization_endpoint=self.issuer + "/authorize",
            token_endpoint=self.issuer + "/token", client_id=self.client_id, redirect_uri=self.redirect_uri,
            jwks=self.jwks, subject_owners={(self.issuer, "subject-alice"): "alice",
                (self.issuer, "subject-bob"): "bob", (self.issuer, "subject-missing"): "missing"}, **changes)

    @property
    def jwks(self):
        return {"keys": [self.jwk]}

    async def authorize(self, request: Request):
        query = request.query_params
        if (query.get("client_id") != self.client_id or query.get("redirect_uri") != self.redirect_uri
                or query.get("response_type") != "code" or query.get("code_challenge_method") != "S256"
                or not query.get("state") or not query.get("nonce") or not query.get("code_challenge")):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        code = secrets.token_urlsafe(32)
        self.codes[code] = {"subject": self.subject, "nonce": query["nonce"], "challenge": query["code_challenge"]}
        self.authorizations += 1
        return RedirectResponse(self.redirect_uri + "?" + urlencode({"code": code, "state": query["state"]}), status_code=302)

    async def exchange(self, request: Request):
        values = parse_qs((await request.body()).decode("ascii"), strict_parsing=True)
        if any(len(value) != 1 for value in values.values()):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        form = {key: value[0] for key, value in values.items()}
        self.exchanges += 1
        grant = self.codes.pop(form.get("code"), None)
        if (grant is None or form.get("grant_type") != "authorization_code"
                or form.get("client_id") != self.client_id or form.get("redirect_uri") != self.redirect_uri
                or challenge(form.get("code_verifier", "")) != grant["challenge"]):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        now = int(time.time())
        claims = {"iss": self.issuer, "sub": grant["subject"], "aud": self.client_id,
                  "iat": now, "exp": now + 300, "nonce": grant["nonce"]}
        token = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "browser-synthetic-key", "typ": "JWT"})
        return JSONResponse({"token_type": "Bearer", "expires_in": 300, "id_token": token,
                             "access_token": "synthetic-unused-access-token"})


def private_tls_files(directory):
    """Self-signed fixture certificate, never installed into any trust store."""
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic browser loopback fixture")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=2)).add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    result = []
    for filename, data in (("fixture-cert.pem", cert.public_bytes(serialization.Encoding.PEM)),
                           ("fixture-key.pem", key.private_bytes(serialization.Encoding.PEM,
                               serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))):
        path = directory / filename
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        result.append(path)
    return tuple(result)
