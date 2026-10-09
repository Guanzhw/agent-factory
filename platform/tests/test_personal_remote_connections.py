"""Offline, synthetic owner onboarding; no external endpoint or secret is used."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import http.client
import socket
import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool

from agent_factory.connections import ConnectionService, connection_router
from agent_factory.personal_connections import personal_connection_router
from agent_factory.personal_remote_provider import (PROVIDER_ID, OpenCodeServeProvider,
    PinnedHTTPSProbe, RemoteConnectionError, RemoteNetworkPolicy, SecretLease, origin)


class Secrets:
    enabled = True
    def authorize(self, *, owner, reference, revision, destination):
        return self.enabled and (owner, reference, revision, destination) == (
            "alice", "synthetic-vault-ref", "v1", "https://runtime.example.com")
    def resolve(self, **scope):
        if not self.authorize(**scope):
            raise ValueError("never expose backend detail")
        return SecretLease("opencode", "synthetic-only-password")


class Probe:
    fail = False
    project = "project-fixture"
    def __init__(self):
        self.calls = []
    def addresses(self, destination):
        return ["93.184.216.34"]
    def get(self, destination, address, path, lease=None):
        self.calls.append((destination, address, path, lease is not None))
        if self.fail:
            raise ValueError("synthetic-only-password must never leak")
        if lease is None:
            return 401, None
        return 200, {"/global/health": {"healthy": True, "version": "1.2.3"},
                     "/project/current": {"id": self.project}, "/agent": [{"name": "build"}]}[path]


class Auth:
    reader = False
    disabled = False
    def require(self, owner, action):
        if self.disabled or (self.reader and action == "run"):
            raise HTTPException(403, "denied")
    def user(self, request: Request):
        owner = request.headers.get("x-fixture-owner")
        if not owner:
            raise HTTPException(401)
        return {"id": owner}


class PersonalRemoteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        Table("af_audit", metadata, Column("id", Integer, primary_key=True), Column("actor_id", String),
              Column("action", String), Column("target_id", String), Column("body", JSON), Column("created_at", String))
        metadata.create_all(self.engine)
        self.auth, self.secrets, self.probe = Auth(), Secrets(), Probe()
        self.provider = OpenCodeServeProvider(self.secrets, probe=self.probe)
        self.providers = {PROVIDER_ID: self.provider}
        self.at = datetime(2026, 10, 8, tzinfo=timezone.utc)
        self.service = ConnectionService(SimpleNamespace(engine=self.engine), self.auth,
            clock=lambda: self.at, personal_providers=self.providers)
        self.personal = self.service.personal
        self.config = {"origin": "https://runtime.example.com", "credentialRef": "synthetic-vault-ref",
                       "credentialRevision": "v1", "projectId": "project-fixture"}
        app = FastAPI()
        app.include_router(connection_router(self.auth, self.service))
        app.include_router(personal_connection_router(self.auth, self.personal))
        self.client = TestClient(app)

    def create(self):
        return self.personal.configure("alice", PROVIDER_ID, self.config, uuid4().hex)
    def verified(self):
        created = self.create()
        return self.personal.verify("alice", created["registrationRef"], uuid4().hex)
    def bound(self):
        verified = self.verified()
        return self.service.bind("alice", verified["registrationRef"], uuid4().hex,
                                 capabilities=["runtime:health"])

    def registration(self, ref):
        calls = list(self.probe.calls)
        response = self.client.get('/api/factory/user-connections/registrations', headers={'x-fixture-owner': 'alice'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.probe.calls, calls, 'Listing registrations must not probe the remote')
        rows = response.json()
        for row in rows:
            self.assertEqual(set(row), {'registrationRef', 'kind', 'revision', 'capabilities', 'expiresAt', 'status', 'available', 'allowedActions'})
            self.assertIn(row['status'], {'available', 'unavailable', 'expired', 'changed'})
            self.assertEqual(row['available'], row['status'] == 'available')
            self.assertTrue(set(row['allowedActions']) <= {'inspect', 'bind'})
            if not row['available']:
                self.assertNotIn('bind', row['allowedActions'])
        return next(row for row in rows if row['registrationRef'] == ref)

    def test_registration_endpoint_projects_personal_lifecycle_and_current_permission(self):
        created = self.create(); ref = created['registrationRef']
        self.assertEqual(self.registration(ref)['status'], 'unavailable')
        verified = self.personal.verify('alice', ref, uuid4().hex)
        row = self.registration(ref)
        self.assertEqual(row['status'], 'available')
        self.assertEqual(row['capabilities'], verified['capabilities'])
        self.assertEqual(row['revision'], verified['revision'])
        self.assertEqual(row['allowedActions'], ['inspect', 'bind'])
        # The dedicated personal API retains its separate lifecycle contract.
        personal = self.personal.list('alice')[0]
        self.assertEqual(personal['status'], 'verified')
        self.assertIn('verify', personal['allowedActions'])
        self.auth.reader = True
        self.assertEqual(self.registration(ref)['allowedActions'], ['inspect'])
        self.auth.reader = False
        self.personal.revoke('alice', ref, uuid4().hex)
        self.assertEqual(self.registration(ref)['status'], 'unavailable')
        self.assertEqual(self.client.get('/api/factory/user-connections/registrations', headers={'x-fixture-owner': 'bob'}).json(), [])

    def test_registration_endpoint_projects_expiry_and_changed_authority_without_binding(self):
        verified = self.verified(); ref = verified['registrationRef']
        self.at += timedelta(minutes=16)
        self.assertEqual(self.registration(ref)['status'], 'expired')
        self.at -= timedelta(minutes=16)
        self.secrets.enabled = False
        self.assertEqual(self.registration(ref)['status'], 'changed')
        self.secrets.enabled = True
        self.provider.policy_revision = 'synthetic-changed-policy'
        self.assertEqual(self.registration(ref)['status'], 'changed')
        with self.assertRaises(HTTPException):
            self.service.bind('alice', ref, uuid4().hex)

    def test_read_only_request_recovery_is_owner_scoped_and_action_partitioned(self):
        created = self.personal.configure('alice', PROVIDER_ID, self.config, 'configure-request')
        recovered = self.personal.request_result('alice', 'configure-request')
        self.assertEqual(recovered['remote']['registrationRef'], created['registrationRef'])
        with self.assertRaises(HTTPException):
            self.personal.request_result('bob', 'configure-request')
        with self.assertRaises(HTTPException):
            self.service.request_result('alice', 'configure-request')
        self.personal.verify('alice', created['registrationRef'], 'verify-request')
        bound = self.service.bind('alice', created['registrationRef'], 'bind-request', capabilities=['runtime:health'])
        self.probe.calls.clear()
        recovered = self.service.request_result('alice', 'bind-request')
        self.assertEqual(recovered['connection']['ref'], bound['ref'])
        self.assertEqual(self.probe.calls, [])
        with self.assertRaises(HTTPException):
            self.personal.request_result('alice', 'bind-request')
        with self.assertRaises(HTTPException):
            self.service.request_result('bob', 'bind-request')

    def test_successful_response_cannot_persist_known_authentication_echo(self):
        import base64
        from agent_factory.personal_remote_provider import reject_credential_echo
        lease = self.secrets.resolve(owner='alice', reference='synthetic-vault-ref', revision='v1',
            destination='https://runtime.example.com')
        encoded = base64.b64encode((lease.username + ':' + lease.password).encode()).decode()
        for value in ({'text': lease.password}, {lease.password: 'key'}, [{'text': encoded}],
                {'text': 'Bearer ' + lease.password}):
            with self.assertRaisesRegex(RemoteConnectionError, '^REMOTE_CREDENTIAL_ECHO_REJECTED$'):
                reject_credential_echo(value, lease)
        original = self.probe.get
        def echo(destination, address, path, credentials=None):
            if path == '/agent' and credentials is not None:
                return 200, [{'name': credentials.password}]
            return original(destination, address, path, credentials)
        self.probe.get = echo
        created = self.create()
        with self.assertRaises(HTTPException):
            self.personal.verify('alice', created['registrationRef'], 'auth-echo-request')
        with self.engine.connect() as conn:
            records = [dict(row) for row in conn.execute(self.personal.resources.select()).mappings()]
        self.assertNotIn(lease.password, repr(records))
        self.assertFalse(self.personal.inspect('alice', created['registrationRef'])['available'])

    def test_create_verify_bind_resolve_revoke_and_restart(self):
        created = self.create()
        self.assertEqual(created["status"], "configured")
        with self.assertRaises(HTTPException):
            self.service.bind("alice", created["registrationRef"], uuid4().hex)
        verified = self.personal.verify("alice", created["registrationRef"], "verify-1")
        self.assertEqual(verified["status"], "verified")
        bound = self.service.bind("alice", verified["registrationRef"], "bind-1")
        handle = self.service.resolve("alice", bound["ref"], "environment", required_capabilities=["runtime:health"])
        self.assertEqual(handle.inspect_identity()["projectId"], "project-fixture")
        restarted = ConnectionService(SimpleNamespace(engine=self.engine), self.auth,
            clock=lambda: self.at, personal_providers=self.providers)
        self.assertEqual(restarted.preflight("alice", bound["ref"], "environment")["status"], "active")
        self.personal.revoke("alice", verified["registrationRef"], "revoke-1")
        with self.assertRaises(HTTPException):
            restarted.resolve("alice", bound["ref"], "environment")
        with self.assertRaises(HTTPException):
            handle.inspect_identity()

    def test_owner_auth_secret_scope_http_and_public_redaction(self):
        root = "/api/factory/personal-remotes"
        self.assertEqual(self.client.get(root).status_code, 401)
        payload = dict(self.config, providerId=PROVIDER_ID, requestId="http-create")
        headers = {"x-fixture-owner": "alice"}
        for extra in ({"password": "do-not-store"}, {"ownerId": "bob"}):
            self.assertEqual(self.client.post(root, headers=headers, json=payload | extra).status_code, 422)
        result = self.client.post(root, headers=headers, json=payload)
        self.assertEqual(result.status_code, 201)
        self.assertNotIn("credential", result.text.lower())
        reference = result.json()["registrationRef"]
        for path in (root + "/" + reference,):
            self.assertEqual(self.client.get(path, headers={"x-fixture-owner": "bob"}).status_code, 404)
        self.assertEqual(self.client.post(root, headers={"x-fixture-owner": "bob"}, json=payload).status_code, 403)
        self.assertEqual(self.personal.list("bob"), [])
        self.auth.reader = True
        self.assertEqual(self.personal.inspect("alice", reference)["allowedActions"], ["inspect", "revoke"])
        with self.assertRaises(HTTPException):
            self.personal.verify("alice", reference, "denied")

    def test_reconfigure_reverify_and_credential_rotation_invalidate_pins(self):
        bound = self.bound()
        reference = bound["registrationRef"]
        self.personal.configure("alice", PROVIDER_ID, self.config, "configure-new", reference=reference)
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "environment")
        self.personal.verify("alice", reference, "verify-new")
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "environment")
        fresh = self.service.bind("alice", reference, "bind-fresh")
        self.secrets.enabled = False
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", fresh["ref"], "environment")

    def test_policy_expiry_revocation_grants_and_failed_probe(self):
        bound = self.bound()
        self.auth.reader = True
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "environment")
        self.auth.reader = False
        self.at += timedelta(minutes=16)
        self.assertEqual(self.personal.inspect("alice", bound["registrationRef"])["status"], "expired")
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "environment")
        self.personal.verify("alice", bound["registrationRef"], "renew")
        self.probe.fail = True
        with self.assertRaises(HTTPException) as caught:
            self.personal.verify("alice", bound["registrationRef"], "failed-probe")
        self.assertEqual(caught.exception.detail, "REMOTE_VERIFICATION_FAILED")
        self.assertEqual(self.personal.inspect("alice", bound["registrationRef"])["status"], "failed")

    def test_idempotency_and_metadata_only_storage(self):
        first = self.personal.configure("alice", PROVIDER_ID, self.config, "same-create")
        self.assertEqual(first, self.personal.configure("alice", PROVIDER_ID, self.config, "same-create"))
        with self.assertRaises(HTTPException):
            self.personal.configure("alice", PROVIDER_ID, self.config | {"projectId": "changed"}, "same-create")
        reference = first["registrationRef"]
        one = self.personal.verify("alice", reference, "same-verify")
        self.assertEqual(one, self.personal.verify("alice", reference, "same-verify"))
        self.assertEqual(len(self.probe.calls), 4)
        with self.engine.connect() as conn:
            serialized = str([dict(row) for row in conn.execute(self.personal.configs.select()).mappings()])
        self.assertIn("synthetic-vault-ref", serialized)
        self.assertNotIn("synthetic-only-password", serialized)
        self.assertNotIn("Authorization", serialized)

    def test_handle_rechecks_after_observation_before_releasing_evidence(self):
        verified = self.verified()
        bound = self.service.bind("alice", verified["registrationRef"], "full-bind")
        handle = self.service.resolve("alice", bound["ref"], "environment")
        original = self.provider.verify
        def revoke_after_read(*args):
            evidence = original(*args)
            self.service.revoke("alice", bound["ref"], "during-read-revoke")
            return evidence
        with patch.object(self.provider, "verify", side_effect=revoke_after_read):
            with self.assertRaises(HTTPException):
                handle.inspect_identity()

    def test_binding_scope_tamper_and_removed_provider(self):
        bound = self.bound()
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "environment", required_capabilities=["session:create"])
        with self.assertRaises(HTTPException):
            self.service.resolve("bob", bound["ref"], "environment")
        handle = self.service.resolve("alice", bound["ref"], "environment")
        calls = len(self.probe.calls)
        with self.assertRaises(HTTPException):
            handle.inspect_identity()
        self.assertEqual(len(self.probe.calls), calls)
        self.providers.clear()
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "environment")


class NetworkPolicyTests(unittest.TestCase):
    def test_origin_and_global_default_deny(self):
        for value in ("http://runtime.example.com", "https://127.0.0.1", "https://user:pass@runtime.example.com",
                      "https://runtime.example.com/path", "https://runtime.example.com?token=x",
                      "https://runtime.example.com#", "https://runtime.example.com:444", "https://localhost"):
            with self.subTest(value=value), self.assertRaises(RemoteConnectionError):
                origin(value)
        policy = RemoteNetworkPolicy()
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "100.100.100.200", "168.63.129.16"):
            self.assertFalse(policy.permits("runtime.example.com", address))

    def test_reviewed_private_requires_host_and_cidr_and_metadata_stays_denied(self):
        policy = RemoteNetworkPolicy(frozenset({"runtime.internal.example"}), ("10.20.0.0/16",))
        self.assertTrue(policy.permits("runtime.internal.example", "10.20.1.2"))
        self.assertFalse(policy.permits("other.internal.example", "10.20.1.2"))
        self.assertFalse(policy.permits("runtime.internal.example", "10.21.1.2"))
        self.assertFalse(policy.permits("runtime.internal.example", "169.254.169.254"))

    def test_dns_mixed_answers_rejected_and_connection_pinned(self):
        probe = PinnedHTTPSProbe()
        with patch("subprocess.run", return_value=SimpleNamespace(stdout='["93.184.216.34", "127.0.0.1"]')):
            with self.assertRaises(RemoteConnectionError):
                probe.addresses("https://runtime.example.com")
        from agent_factory.personal_remote_provider import _PinnedHTTPS
        with patch("socket.create_connection") as connect:
            connection = _PinnedHTTPS("runtime.example.com", "93.184.216.34")
            with patch.object(connection._tls_context, "wrap_socket") as wrap:
                connection.connect()
                connect.assert_called_once_with(("93.184.216.34", 443), 5)
                wrap.assert_called_once_with(connect.return_value, server_hostname="runtime.example.com")

    def test_redirect_is_not_followed_and_error_body_is_not_exposed(self):
        response = Mock(status=302)
        response.getheader.return_value = "identity"
        response.read1.side_effect = [b"synthetic-secret-in-error", b""]
        connection = Mock()
        connection.getresponse.return_value = response
        with patch("agent_factory.personal_remote_provider._PinnedHTTPS", return_value=connection) as create:
            status, body = PinnedHTTPSProbe().get("https://runtime.example.com", "93.184.216.34",
                "/global/health", SecretLease("opencode", "synthetic-password"))
        self.assertEqual((status, body), (302, None))
        create.assert_called_once_with("runtime.example.com", "93.184.216.34")
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_tls_and_transport_failures_do_not_expose_exception_text(self):
        connection = Mock()
        connection.request.side_effect = ValueError("synthetic-password URL or header detail")
        with patch("agent_factory.personal_remote_provider._PinnedHTTPS", return_value=connection):
            with self.assertRaisesRegex(RemoteConnectionError, "^REMOTE_PROBE_FAILED$"):
                PinnedHTTPSProbe().get("https://runtime.example.com", "93.184.216.34", "/global/health")
        connection.close.assert_called_once()

    def test_dns_timeout_is_bounded_by_killed_and_reaped_helper(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("synthetic-helper", 3)) as run:
            with self.assertRaisesRegex(RemoteConnectionError, "REMOTE_ADDRESS_DENIED"):
                PinnedHTTPSProbe().addresses("https://runtime.example.com")
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_slow_drip_headers_interrupted_by_absolute_socket_deadline(self):
        reader, writer = socket.socketpair()
        stopped = threading.Event()
        def drip():
            try:
                writer.recv(4096)
                for byte in b"HTTP/1.1 200 OK\r\nX-Slow: endlessly-dripping-header":
                    if stopped.wait(.025):
                        return
                    writer.send(bytes([byte]))
            except OSError:
                return
        thread = threading.Thread(target=drip, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("runtime.example.com", timeout=5)
        connection.sock = reader
        started = time.monotonic()
        try:
            with patch("agent_factory.personal_remote_provider.HTTP_TOTAL_SECONDS", .15), patch(
                    "agent_factory.personal_remote_provider._PinnedHTTPS", return_value=connection):
                with self.assertRaises(RemoteConnectionError):
                    PinnedHTTPSProbe().get("https://runtime.example.com", "93.184.216.34", "/global/health")
            self.assertLess(time.monotonic() - started, 1)
            self.assertIsNone(connection.sock)
        finally:
            stopped.set()
            reader.close(); writer.close()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_connection_close_chunk_size_drip_keeps_socket_interruptible(self):
        reader, writer = socket.socketpair()
        stopped = threading.Event()
        def drip():
            try:
                writer.recv(4096)
                writer.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\nTransfer-Encoding: chunked\r\n\r\n")
                while not stopped.wait(.025):
                    writer.send(b"1")  # Never finish the chunk-size line.
            except OSError:
                return
        thread = threading.Thread(target=drip, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("runtime.example.com", timeout=5)
        connection.sock = reader
        started = time.monotonic()
        try:
            with patch("agent_factory.personal_remote_provider.HTTP_TOTAL_SECONDS", .15), patch(
                    "agent_factory.personal_remote_provider._PinnedHTTPS", return_value=connection):
                with self.assertRaises(RemoteConnectionError):
                    PinnedHTTPSProbe().get("https://runtime.example.com", "93.184.216.34", "/global/health")
            self.assertLess(time.monotonic() - started, 1)
        finally:
            stopped.set()
            reader.close(); writer.close()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
