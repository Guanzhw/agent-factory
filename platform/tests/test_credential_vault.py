"""Synthetic credentials only; no network, real keys, or persistent grants."""
import asyncio
from contextlib import contextmanager
import io
import json
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from agent_factory.browser_auth import BrowserAuthBridge, SESSION_COOKIE
from agent_factory.credential_vault import (CredentialVaultError, EncryptedCredentialVault,
    MAX_CREDENTIAL_REQUEST_BYTES, credential_vault_router)
from agent_factory.personal_remote_provider import PROVIDER_ID, origin
from test_personal_remote_connections import Auth

DESTINATION = "https://runtime.example.com"
PASSWORD = "synthetic-vault-password-only"


class CredentialVaultTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        self.vault = EncryptedCredentialVault(self.engine, b"s" * 32, {PROVIDER_ID: origin})
        self.auth = Auth()
        self.app = FastAPI()
        self.app.include_router(credential_vault_router(self.auth, self.vault))
        self.client = TestClient(self.app)
        self.payload = {"providerId": PROVIDER_ID, "destination": DESTINATION,
                        "username": "synthetic-opencode", "password": PASSWORD, "requestId": "synthetic-request"}
        self.headers = {"x-fixture-owner": "alice"}
        self.root = "/api/factory/personal-credentials"

    def create(self):
        return self.vault.create(owner="alice", provider_id=PROVIDER_ID, destination=DESTINATION,
                                 username="synthetic-opencode", password=PASSWORD)

    def scope(self, created):
        return dict(owner="alice", provider_id=PROVIDER_ID, destination=DESTINATION,
                    reference=created["credentialRef"], revision=created["credentialRevision"])

    def test_disabled_invalid_key_and_redacted_repr(self):
        for key in (None, b"", b"s" * 31, "s" * 32):
            with self.assertRaisesRegex(CredentialVaultError, "^CREDENTIAL_UNAVAILABLE$"):
                EncryptedCredentialVault(self.engine, key, {PROVIDER_ID: origin})
        self.assertNotIn("s" * 32, repr(self.vault))
        self.assertIn("redacted", repr(self.vault))

    def test_ciphertext_only_sql_logs_distinct_nonce_and_restart(self):
        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        logger = logging.getLogger("sqlalchemy.engine")
        before = logger.level
        logger.setLevel(logging.INFO); logger.addHandler(handler)
        try:
            first, second = self.create(), self.create()
        finally:
            logger.removeHandler(handler); logger.setLevel(before)
        with self.engine.connect() as conn:
            rows = conn.execute(select(self.vault.credentials)).mappings().all()
        self.assertNotEqual(rows[0]["nonce"], rows[1]["nonce"])
        self.assertNotEqual(rows[0]["ciphertext"], rows[1]["ciphertext"])
        for sensitive in (PASSWORD, "synthetic-opencode"):
            self.assertNotIn(sensitive, captured.getvalue())
            self.assertNotIn(sensitive, repr(rows))
            self.assertNotIn(sensitive, repr(first))
        restarted = EncryptedCredentialVault(self.engine, b"s" * 32, {PROVIDER_ID: origin})
        self.assertEqual(restarted.resolve(**self.scope(second)).password, PASSWORD)
        self.assertNotIn(PASSWORD, repr(restarted.resolve(**self.scope(first))))

    def test_scope_and_provider_adapter(self):
        created = self.create(); scope = self.scope(created)
        self.assertTrue(self.vault.authorize(**scope))
        for field, value in (("owner", "bob"), ("provider_id", "other"), ("destination", "https://other.example.com"),
                             ("reference", "other"), ("revision", "stale")):
            altered = scope | {field: value}
            self.assertFalse(self.vault.authorize(**altered))
            with self.assertRaises(CredentialVaultError): self.vault.resolve(**altered)
        del scope["provider_id"]
        provider = self.vault.secret_provider(PROVIDER_ID)
        self.assertTrue(provider.authorize(**scope))
        self.assertEqual(provider.resolve(**scope).password, PASSWORD)

    def test_aad_nonce_ciphertext_tampering_fails_closed(self):
        for field in ("owner_id", "reference", "revision", "provider_id", "destination", "nonce", "ciphertext"):
            with self.subTest(field=field):
                created = self.create(); scope = self.scope(created)
                value = {"owner_id": "bob", "reference": "tampered", "revision": "tampered",
                         "provider_id": PROVIDER_ID + "-other", "destination": "https://other.example.com",
                         "nonce": b"x" * 12, "ciphertext": b"x" * 64}[field]
                with self.engine.begin() as conn:
                    conn.execute(self.vault.credentials.update().where(
                        self.vault.credentials.c.reference == created["credentialRef"]).values(**{field: value}))
                parameter = {"owner_id": "owner", "reference": "reference", "revision": "revision",
                             "provider_id": "provider_id", "destination": "destination"}.get(field)
                if parameter: scope[parameter] = value
                with self.assertRaisesRegex(CredentialVaultError, "^CREDENTIAL_UNAVAILABLE$"):
                    self.vault.resolve(**scope)

    def test_rotation_revoke_stale_revision_and_cross_owner(self):
        created = self.create(); scope = self.scope(created)
        command = {key: scope[key] for key in ("owner", "reference", "revision")}
        with self.assertRaises(CredentialVaultError):
            self.vault.rotate(**(command | {"owner": "bob"}), username="synthetic", password="new-synthetic")
        updated = self.vault.rotate(**command, username="synthetic", password="new-synthetic")
        self.assertFalse(self.vault.authorize(**scope))
        with self.assertRaises(CredentialVaultError): self.vault.revoke(**command)
        with self.assertRaises(CredentialVaultError):
            self.vault.rotate(**command, username="synthetic", password="stale-synthetic")
        new_scope = self.scope(updated)
        self.assertEqual(self.vault.resolve(**new_scope).password, "new-synthetic")
        self.vault.revoke(**{key: new_scope[key] for key in ("owner", "reference", "revision")})
        self.assertFalse(self.vault.authorize(**new_scope))
        with self.assertRaises(CredentialVaultError): self.vault.resolve(**new_scope)

    def test_global_provider_policy_and_exact_origin_binding(self):
        created = self.vault.create(owner="alice", provider_id=PROVIDER_ID,
            destination="https://RUNTIME.example.com:443/", username="synthetic", password=PASSWORD)
        self.assertEqual(created["destination"], DESTINATION)
        for destination in ("http://runtime.example.com", "https://127.0.0.1", "https://user:pw@runtime.example.com",
                            "https://runtime.example.com/path", "https://runtime.example.com?secret=x"):
            with self.assertRaises(CredentialVaultError):
                self.vault.create(owner="alice", provider_id=PROVIDER_ID, destination=destination,
                                  username="synthetic", password=PASSWORD)
        with self.assertRaises(CredentialVaultError):
            self.vault.create(owner="alice", provider_id="model-installed", destination=DESTINATION,
                              username="synthetic", password=PASSWORD)

    def test_http_manual_validation_all_errors_redacted(self):
        bad = [self.payload | {"password": {"nested": PASSWORD}}, self.payload | {"owner": PASSWORD},
               self.payload | {"username": PASSWORD + ":"}, self.payload | {"password": PASSWORD * 500},
               self.payload | {"providerId": PASSWORD}]
        for body in bad:
            response = self.client.post(self.root, json=body, headers=self.headers)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"detail": "CREDENTIAL_REQUEST_REJECTED"})
            self.assertNotIn(PASSWORD, response.text)
        for raw in ('{"password": "' + PASSWORD, json.dumps(self.payload)[:-1] + ',"password":"duplicate"}',
                    PASSWORD * MAX_CREDENTIAL_REQUEST_BYTES):
            response = self.client.post(self.root, content=raw,
                headers=self.headers | {"content-type": "application/json"})
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.client.post(self.root, json=self.payload).status_code, 401)
        for failure in (RuntimeError(PASSWORD), HTTPException(403, PASSWORD), CredentialVaultError()):
            with patch.object(self.vault, "create", side_effect=failure):
                response = self.client.post(self.root, json=self.payload, headers=self.headers)
                self.assertEqual(response.status_code, 503); self.assertNotIn(PASSWORD, response.text)
        response = self.client.post(self.root, json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertNotIn(PASSWORD, response.text)
        self.assertIn("no-store", response.headers["cache-control"])
        value = response.json()
        response = self.client.post(self.root + "/" + value["credentialRef"] + "/revoke",
            json={"credentialRevision": value["credentialRevision"], "requestId": "synthetic-revoke"}, headers={"x-fixture-owner": "bob"})
        self.assertEqual(response.status_code, 400)

    def test_browser_bridge_rejects_missing_csrf_before_body_or_vault(self):
        # Actual bridge checks origin and CSRF before session resolution or app IO.
        service = SimpleNamespace(config=SimpleNamespace(app_origin="https://factory.example.test"),
                                  csrf=lambda token: "synthetic-csrf")
        bridge = BrowserAuthBridge(self.app, service)
        client = TestClient(bridge, base_url="https://factory.example.test")
        client.cookies.set(SESSION_COOKIE, "s" * 43)
        with patch.object(self.vault, "create", side_effect=AssertionError("must not be called")):
            response = client.post(self.root, json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(PASSWORD, response.text)

    def test_existing_remote_binding_invalidated_without_retargeting(self):
        from test_personal_remote_connections import PersonalRemoteTests
        from agent_factory.personal_remote_provider import OpenCodeServeProvider
        from fastapi import HTTPException
        fixture = PersonalRemoteTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        vault = EncryptedCredentialVault(self.engine, b"s" * 32, {PROVIDER_ID: origin})
        credential = vault.create(owner="alice", provider_id=PROVIDER_ID, destination=DESTINATION,
                                  username="synthetic", password=PASSWORD)
        fixture.providers[PROVIDER_ID] = OpenCodeServeProvider(vault.secret_provider(PROVIDER_ID), probe=fixture.probe)
        config = fixture.config | {"credentialRef": credential["credentialRef"],
                                   "credentialRevision": credential["credentialRevision"]}
        remote = fixture.personal.configure("alice", PROVIDER_ID, config, "vault-config")
        fixture.personal.verify("alice", remote["registrationRef"], "vault-verify")
        with fixture.service._read() as conn:
            before = fixture.personal.binding(conn, "alice", remote["registrationRef"])
        vault.rotate(owner="alice", reference=credential["credentialRef"], revision=credential["credentialRevision"],
                     username="synthetic", password="synthetic-rotation")
        with fixture.service._read() as conn:
            with self.assertRaises(HTTPException) as raised:
                fixture.personal.binding(conn, "alice", remote["registrationRef"])
            self.assertEqual(raised.exception.detail, "REMOTE_CREDENTIAL_UNAVAILABLE")
            _, saved = fixture.personal._row(conn, "alice", remote["registrationRef"])
            self.assertEqual(saved["configuration"]["credentialRevision"], credential["credentialRevision"])
        self.assertIsNotNone(before)

    def test_idempotent_owner_recovery_changed_intent_and_metadata(self):
        first = self.client.post(self.root, json=self.payload, headers=self.headers)
        self.assertEqual(first.status_code, 201)
        replay = self.client.post(self.root, json=self.payload, headers=self.headers)
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(len(self.vault.list(owner="alice")), 1)
        changed = self.client.post(self.root, json=self.payload | {"password": "synthetic-changed"}, headers=self.headers)
        self.assertEqual(changed.status_code, 400)
        recovery = self.client.get(self.root + "/requests/synthetic-request", headers=self.headers)
        self.assertEqual(recovery.json(), first.json())
        self.assertEqual(self.client.get(self.root + "/requests/synthetic-request",
            headers={"x-fixture-owner": "bob"}).status_code, 404)
        self.assertEqual(self.client.get(self.root, headers={"x-fixture-owner": "bob"}).json(), [])
        self.assertEqual(self.client.get(self.root + "/capabilities", headers=self.headers).json(),
                         {"enabled": True, "providerIds": [PROVIDER_ID]})
        row = first.json()
        path = self.root + "/" + row["credentialRef"]
        rotate = {"credentialRevision": row["credentialRevision"], "username": "synthetic",
                  "password": "synthetic-rotation", "requestId": "rotate-request"}
        rotated = self.client.post(path + "/rotate", json=rotate, headers=self.headers)
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(self.client.post(path + "/rotate", json=rotate, headers=self.headers).json(), rotated.json())
        revoke = {"credentialRevision": rotated.json()["credentialRevision"], "requestId": "revoke-request"}
        revoked = self.client.post(path + "/revoke", json=revoke, headers=self.headers)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.client.post(path + "/revoke", json=revoke, headers=self.headers).json(), revoked.json())
        # Recovery is the immutable operation result, not a claim of current status.
        self.assertEqual(self.client.get(self.root + "/requests/synthetic-request", headers=self.headers).json(), first.json())
        self.assertEqual(self.client.get(self.root, headers=self.headers).json()[0]["status"], "revoked")
        with self.engine.connect() as conn:
            commands = conn.execute(select(self.vault.commands)).mappings().all()
        self.assertNotIn(PASSWORD, repr(commands))
        self.assertNotIn("synthetic-opencode", repr(commands))

    def test_commit_then_error_recovers_matching_durable_result(self):
        begin = self.engine.begin
        @contextmanager
        def ambiguous_commit():
            with begin() as conn:
                yield conn
            raise RuntimeError(PASSWORD)
        with patch.object(self.engine, "begin", side_effect=ambiguous_commit):
            response = self.client.post(self.root, json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertNotIn(PASSWORD, response.text)
        self.assertEqual(self.vault.recover(owner="alice", request_id="synthetic-request"), response.json())
        self.assertEqual(len(self.vault.list(owner="alice")), 1)

    def test_ambiguous_commit_failed_recovery_is_503_then_read_only_recovery(self):
        begin, command = self.engine.begin, self.vault._command
        calls = 0
        @contextmanager
        def ambiguous_commit():
            with begin() as conn:
                yield conn
            raise RuntimeError(PASSWORD)
        def transient_recovery_failure(*args):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise RuntimeError(PASSWORD)
            return command(*args)
        with patch.object(self.engine, "begin", side_effect=ambiguous_commit), \
                patch.object(self.vault, "_command", side_effect=transient_recovery_failure):
            response = self.client.post(self.root, json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "CREDENTIAL_UNAVAILABLE"})
        self.assertNotIn(PASSWORD, response.text)
        recovered = self.client.get(self.root + "/requests/synthetic-request", headers=self.headers)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(len(self.vault.list(owner="alice")), 1)
        self.assertEqual(self.client.post(self.root, json=self.payload, headers=self.headers).json(), recovered.json())

    def test_database_failure_is_503_for_mutation_and_recovery_never_404(self):
        with patch.object(self.engine, "begin", side_effect=RuntimeError(PASSWORD)), \
                patch.object(self.engine, "connect", side_effect=RuntimeError(PASSWORD)):
            for response in (self.client.post(self.root, json=self.payload, headers=self.headers),
                             self.client.get(self.root + "/requests/synthetic-request", headers=self.headers),
                             self.client.get(self.root, headers=self.headers)):
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "CREDENTIAL_UNAVAILABLE"})
                self.assertNotIn(PASSWORD, response.text)
                self.assertIn("no-store", response.headers["cache-control"])
        self.assertIsNone(self.vault.recover(owner="alice", request_id="synthetic-request"))

    def test_stream_limit_without_content_length(self):
        from agent_factory.credential_vault import _body
        class StreamRequest:
            headers = {"content-type": "application/json"}
            async def stream(self):
                yield b"x" * 12_000
                yield b"x" * 13_000
                raise AssertionError("must stop reading")
        with self.assertRaises(CredentialVaultError): asyncio.run(_body(StreamRequest(), set()))


if __name__ == "__main__": unittest.main()
