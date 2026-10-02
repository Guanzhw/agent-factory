"""Actual loopback HTTP origin mandate checks, never fixed-success callbacks.

Portable cases exercise denial against adversarial HTTP replies. Opt-in native
PostgreSQL cases run the actual wired Factory origin route and managed Auth;
they do not claim cross-process remote execution (a separate acceptance suite).
"""
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from uuid import uuid4

from fastapi import HTTPException
import httpx
from pydantic import ValidationError
import uvicorn

from agent_factory.config import Settings
from agent_factory.connections import TrustedConnectionBinding
from agent_factory.execution_bindings import AdapterRegistration
from agent_factory.main import create_app
from agent_factory.remote_authority import AuthorityCheck, AuthorityReply, OriginAuthorityTransport, PATH
from agent_factory.remote_handoff import HandoffCancellationRequested, HandoffTarget, TrustedOrigin
from pg_fixture import IsolatedPostgres


@contextmanager
def adverse_http(status, payload=b"invalid", *, headers=None, delay=0):
    """Owned adversarial protocol fixture, never a source of an authority grant."""
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("content-length", "0")))
            requests.append({"path": self.path, "body": json.loads(raw)})
            time.sleep(delay)
            value = payload(requests[-1]["body"]) if callable(payload) else payload
            self.send_response(status)
            for key, val in ({"Content-Type": "application/json", **(headers or {})}).items():
                self.send_header(key, val)
            self.send_header("Content-Length", str(len(value)))
            self.end_headers()
            try:
                self.wfile.write(value)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


class OwnedLoopbackFactory:
    """Own exactly one ephemeral listener/server thread; never stop other apps."""
    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.url = "http://127.0.0.1:" + str(self.socket.getsockname()[1])
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0,
            log_level="critical", access_log=False, log_config=None, timeout_graceful_shutdown=3))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)
        self.thread.start()
        end = time.monotonic() + 8
        while not self.server.started and self.thread.is_alive() and time.monotonic() < end:
            time.sleep(.01)
        if not self.server.started:
            self.close()
            raise RuntimeError("Owned loopback Factory did not start")

    def close(self):
        self.server.should_exit = True
        self.thread.join(5)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("Owned loopback Factory did not stop")


class OriginAuthorityTransportTests(unittest.TestCase):
    def transport(self, url, **changes):
        return OriginAuthorityTransport(base_url=url, origin_ref="owned-origin", target_ref="owned-receiver",
            target_revision="1", target_fingerprint="a" * 64, receiver_identity_map={"owned-source": "owned-receiver-user"},
            credential_provider=lambda _: "owned-adversarial-fixture-token", **changes)

    def call(self, transport):
        return transport("owned-source", str(uuid4()), "b" * 64, "checksum")

    def test_configuration_is_operator_only_bounded_and_fingerprint_has_no_credential(self):
        original = self.transport("http://127.0.0.1:1")
        different_secret = replace(original, credential_provider=lambda _: "different-owned-credential")
        self.assertEqual(original.fingerprint, different_secret.fingerprint)
        self.assertNotEqual(original.fingerprint, replace(original, configuration_revision="2").fingerprint)
        self.assertNotEqual(original.fingerprint, replace(original, target_fingerprint="b" * 64).fingerprint)
        self.assertEqual(original.source_configuration, {"revision": "1", "sha256": "a" * 64})
        invalid = ({"base_url": "http://fixtures.invalid"}, {"base_url": "https://user:secret@fixtures.invalid"},
                   {"base_url": "https://fixtures.invalid/?credential=forbidden"}, {"timeout_seconds": float("nan")},
                   {"timeout_seconds": 0}, {"max_response_bytes": True}, {"target_fingerprint": "not-a-digest"},
                   {"receiver_identity_map": {"source": "actor\nwith-control"}})
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(original, **changes)
        with self.assertRaises(HTTPException):
            original("foreign-owner", str(uuid4()), "b" * 64, None)

    def test_redirect_unauthorized_server_error_and_non_json_over_actual_tcp_deny(self):
        for status, headers in ((302, {"Location": "http://127.0.0.1:1"}), (401, {}), (403, {}), (500, {}),
                                (200, {"Content-Type": "text/html"}), (200, {"Content-Encoding": "gzip"})):
            with self.subTest(status=status, headers=headers), adverse_http(status, headers=headers) as (url, requests):
                with self.assertRaises(HTTPException):
                    self.call(self.transport(url))
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["path"], PATH)
                self.assertFalse(any(key.lower() in {"authorization", "token", "credentials", "url"} for key in requests[0]["body"]))

    def test_malformed_changed_identity_hash_config_and_cancellation_with_grant_fail_closed(self):
        def forged(body, change):
            return json.dumps({**body, "outcome": "cancelled", "authority": None, **change}).encode()
        cases = ({"receiverIdentity": "another-receiver"}, {"manifestSha256": "c" * 64}, {"targetFingerprint": "c" * 64},
                 {"originTaskId": str(uuid4())}, {"originOwner": "other-owner"}, {"schema": True},
                 {"outcome": "authorized", "authority": None}, {"credentialHandle": "must-not-be-returned"},
                 {"authority": {"capabilities": ["checksum:read"], "tools": ["checksum"], "budget": {"toolCalls": 8, "maxDepth": 2, "maxChildren": 4, "experimentSeconds": 8, "outputBytes": 65536}}})
        for change in cases:
            with self.subTest(change=change), adverse_http(200, lambda body: forged(body, change)) as (url, _):
                with self.assertRaises(HTTPException):
                    self.call(self.transport(url))
        with adverse_http(200, b"[1,2,3]") as (url, _), self.assertRaises(HTTPException):
            self.call(self.transport(url))
        with adverse_http(200, b'{"schema":1,"schema":1}') as (url, _), self.assertRaises(HTTPException):
            self.call(self.transport(url))

    def test_response_size_timeout_and_unreachable_over_actual_tcp_deny_without_retry(self):
        with adverse_http(200, b"x" * 17000) as (url, requests), self.assertRaises(HTTPException):
            self.call(self.transport(url))
        self.assertEqual(len(requests), 1)
        with adverse_http(200, delay=.25) as (url, requests), self.assertRaises(HTTPException) as timed_out:
            self.call(self.transport(url, timeout_seconds=.1))
        self.assertEqual(timed_out.exception.status_code, 503)
        self.assertEqual(len(requests), 1)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            closed = "http://127.0.0.1:" + str(listener.getsockname()[1])
        with self.assertRaises(HTTPException) as unreachable:
            self.call(self.transport(closed, timeout_seconds=.1))
        self.assertEqual(unreachable.exception.status_code, 503)

    def test_strict_schema_and_no_default_credentials_or_callback_grant(self):
        value = {"schema": 1, "originRef": "origin", "targetRef": "receiver", "originOwner": "owner",
                 "originTaskId": str(uuid4()), "manifestSha256": "a" * 64, "tool": None,
                 "receiverIdentity": "receiver-user", "targetRevision": "1", "targetFingerprint": "b" * 64}
        self.assertEqual(AuthorityCheck.model_validate(value).model_dump(), value)
        self.assertEqual(AuthorityCheck.model_validate({**value, "originOwner": "subject@example.invalid"}).originOwner, "subject@example.invalid")
        for changed in ({"schema": "1"}, {"tool": "arbitrary/shell"}, {"ownerId": "manager"}, {"originTaskId": "not-uuid"}):
            with self.assertRaises(ValidationError):
                AuthorityCheck.model_validate({**value, **changed})
        with self.assertRaises(ValidationError):
            AuthorityReply.model_validate({**value, "outcome": "cancelled", "authority": {}})
        with self.assertRaises(HTTPException) as credential:
            self.call(replace(self.transport("http://127.0.0.1:1"), credential_provider=lambda _: "invalid token with spaces"))
        self.assertEqual(credential.exception.status_code, 403)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires actual managed native/PostgreSQL loopback acceptance")
class OriginAuthorityPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        # A configured endpoint is inert here: this read-only suite sends no
        # receiver admission, model/API call or experiment.
        self.target = HandoffTarget("owned-receiver", "owned-origin", "http://127.0.0.1:1", {"alice": "bob"},
                                   lambda _: {"Authorization": "Bearer owned-unused-receiver-fixture"})
        self.provider_calls = []
        def forbidden_factory(context):
            self.provider_calls.append(context)
            raise AssertionError("Origin authority preflight cannot construct a model provider")
        connection = TrustedConnectionBinding(owner="alice", kind="model", adapter_ref="owned-authority-model-v1",
            capabilities=frozenset(), revision="1", available=True, opaque_handle=object(), handle_ref="owned-inert-handle-v1")
        adapter = AdapterRegistration("model", "owned-authority-model-v1", "1", forbidden_factory, connection_kind="model")
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1,
                                 handoff_targets={self.target.reference: self.target},
                                 trusted_connections={"owned-source-model": connection}, runtime_adapters=[adapter])
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.addCleanup(self.store.engine.dispose)
        self.loopback = OwnedLoopbackFactory(self.app)
        self.addCleanup(self.loopback.close)
        self.client = httpx.Client(base_url=self.loopback.url, trust_env=False, timeout=5)
        self.addCleanup(self.client.close)
        self.handoff = self.state["handoff_client"]
        self.transport = OriginAuthorityTransport(base_url=self.loopback.url, origin_ref=self.target.origin_ref,
            target_ref=self.target.reference, target_revision=self.target.configuration_revision,
            target_fingerprint=self.target.fingerprint, receiver_identity_map=self.target.identity_map,
            credential_provider=lambda _: self.auth._issue_native_token("bob"))
        self.plan = self.state["composition"].create_plan("alice", "Checksum controlled authority fixture", "literature", "checksum")
        self.placement = self.handoff.reserve("alice", self.plan["id"], self.target.reference, str(uuid4()))

    def call(self, tool="checksum"):
        return self.transport("alice", self.placement["task_id"], self.placement["manifest_hash"], tool)

    def body(self, **changes):
        return {"schema": 1, "originRef": self.target.origin_ref, "targetRef": self.target.reference, "originOwner": "alice",
            "originTaskId": self.placement["task_id"], "manifestSha256": self.placement["manifest_hash"], "tool": "checksum",
            "receiverIdentity": "bob", "targetRevision": self.target.configuration_revision, "targetFingerprint": self.target.fingerprint, **changes}

    def post(self, body=None, actor="bob", **kwargs):
        headers = {"Authorization": "Bearer " + self.auth._issue_native_token(actor)}
        return self.client.post(PATH, json=body or self.body(), headers=headers, **kwargs)

    def test_actual_native_auth_route_current_immutable_plan_authority_and_configuration_proof(self):
        authority = self.call()
        self.assertEqual(authority.tools, frozenset({"checksum"}))
        self.assertEqual(authority.capabilities, frozenset({"checksum:read"}))
        self.assertEqual(authority.receiver_identity, "bob")
        self.assertEqual(authority.target_fingerprint, self.target.fingerprint)
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["outcome"], "authorized")
        self.assertEqual(self.store.task(self.placement["task_id"], "alice")["run_id"], None)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS count FROM af_effects")[0]["count"], 0)
        legacy = TrustedOrigin("owned-origin", {"alice": "bob"}, self.handoff.authority_callback)
        actual = TrustedOrigin("owned-origin", {"alice": "bob"}, self.transport)
        self.assertNotEqual(legacy.fingerprint, actual.fingerprint)
        changed = TrustedOrigin("owned-origin", {"alice": "bob"}, replace(self.transport, configuration_revision="2"))
        self.assertNotEqual(actual.fingerprint, changed.fingerprint)

    def test_wrong_auth_owner_task_target_manifest_tool_and_config_denied_without_side_effects(self):
        self.assertEqual(self.client.post(PATH, json=self.body()).status_code, 401)
        self.assertEqual(self.post(actor="alice").status_code, 403)
        for fields in ({"originOwner": "bob"}, {"originTaskId": str(uuid4())}, {"targetRef": "not-installed"},
                       {"originRef": "different-origin"}, {"receiverIdentity": "alice"}, {"manifestSha256": "0" * 64},
                       {"targetFingerprint": "0" * 64}, {"targetRevision": "2"}, {"tool": "run_experiment"}):
            with self.subTest(fields=fields):
                self.assertIn(self.post(self.body(**fields)).status_code, {403, 404, 409})
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS count FROM af_effects")[0]["count"], 0)

    def test_actual_current_source_and_receiver_native_grants_cannot_be_replaced_by_request(self):
        self.auth.authorization.unassign("alice", "factory-user")
        with self.assertRaises(HTTPException):
            self.call()
        self.auth.authorization.assign("alice", "factory-user")
        self.assertEqual(self.call().tools, frozenset({"checksum"}))
        self.auth.authorization.unassign("bob", "factory-user")
        with self.assertRaises(HTTPException):
            self.call()
        self.assertEqual(self.post(self.body(ownerId="manager", role="manager")).status_code, 422)

    def test_current_material_application_adapter_and_policy_withdrawals_each_deny(self):
        # Each fixture has fresh immutable seed versions; no archive is restored.
        self.state["execution_bindings"].withdraw("model", "local-synthetic-model-v1", "1")
        with self.assertRaises(HTTPException):
            self.call()
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS count FROM af_effects")[0]["count"], 0)

    def test_current_policy_and_application_withdrawal_deny(self):
        self.settings.temporary_policy = "unset"
        with self.assertRaises(HTTPException):
            self.call()
        self.settings.temporary_policy = "bounded-synthetic"
        self.state["applications"].withdraw("manager", "checksum", 1, "owned-withdraw-app", "Controlled fixture")
        with self.assertRaises(HTTPException):
            self.call()

    def test_current_material_withdrawal_deny_and_retains_source_immutable_plan(self):
        self.state["material_governance"].withdraw("manager", "checksum-tool", 1, "owned-withdraw-tool", "Controlled fixture")
        with self.assertRaises(HTTPException):
            self.call()
        self.assertEqual(self.store.plan(self.plan["id"], "alice"), self.plan)

    def test_actual_current_owner_connection_revocation_denies_without_resolving_or_constructing_provider(self):
        # A private inert handle exists only in operator fixture configuration;
        # reviewed material/proposal/HTTP contain its redacted owner pin only.
        self.auth.directory.upsert("owned-publication-reviewer", name="Owned synthetic administrator fixture")
        self.auth.authorization.assign("owned-publication-reviewer", "factory-manager")
        governance = self.state["material_governance"]
        model = governance.create_draft("manager", {"kind": "model", "name": "Owned connection-selected model",
            "content": "No provider construction during authority preflight.", "license": "MIT",
            "provenance": {"kind": "original", "notice": "Original synthetic fixture."},
            "runtimeBinding": {"adapterId": "owned-authority-model-v1", "revision": "1", "config": {"connectionName": "source-model"}}}, "owned-model-draft")
        review = governance.request_publication("manager", model["id"], 1, "owned-model-review")
        governance.decide_publication("owned-publication-reviewer", review["id"], True, "owned-model-approve")
        applications = self.state["applications"]
        original = applications.require_current(self.plan["applicationRef"])
        definition = {key: value for key, value in original.items() if key not in {"schema", "version", "createdAt", "sha256", "origin"}}
        definition = __import__("copy").deepcopy(definition)
        definition["id"] = "connected-authority-fixture"
        for mode in definition["modes"].values():
            mode["materialRefs"] = [{key: model[key] for key in ("id", "version", "sha256")} if ref["id"] == "demo-model" else ref for ref in mode["materialRefs"]]
            mode["connectionRequirements"] = [{"name": "source-model", "kind": "model", "requiredCapabilities": []}]
        application = applications.create_draft("manager", definition, "owned-connected-app")
        review = applications.request_publication("manager", application["id"], 1, "owned-connected-review")
        applications.decide_publication("owned-publication-reviewer", review["id"], True, "owned-connected-approve")
        connection = self.state["connections"].bind("alice", "owned-source-model", "owned-model-binding")
        plan = self.state["composition"].create_plan("alice", "Checksum bound connection authority", "literature",
            application_ref={key: application[key] for key in ("id", "version", "sha256")}, connection_refs={"source-model": connection["ref"]})
        self.assertEqual(plan["status"], "ready", plan["missing"])
        self.placement = self.handoff.reserve("alice", plan["id"], self.target.reference, "owned-connected-placement")
        self.assertEqual(self.call().tools, frozenset({"checksum"}))
        self.state["connections"].revoke("alice", connection["ref"], "owned-revoke-connection")
        with self.assertRaises(HTTPException):
            self.call()
        self.assertEqual(self.provider_calls, [])
        self.assertEqual(self.store.plan(plan["id"], "alice"), plan)

    def test_exact_current_cancellation_is_cleanup_and_prior_failure_remains_failure(self):
        self.store.sql("UPDATE af_tasks SET cancel_requested=TRUE WHERE id=:id", id=self.placement["task_id"])
        with self.assertRaises(HandoffCancellationRequested) as cancelled:
            self.call()
        self.assertEqual((cancelled.exception.owner, cancelled.exception.task_id, cancelled.exception.manifest_hash),
                         ("alice", self.placement["task_id"], self.placement["manifest_hash"]))
        raw = self.post()
        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertEqual(raw.json()["outcome"], "cancelled")
        self.assertIsNone(raw.json()["authority"])
        self.store.event(self.placement["task_id"], "protected_denied", "Owned failure fixture", {})
        with self.assertRaises(HTTPException):
            self.call()

    def test_origin_local_ticket_conflict_target_rotation_and_raw_body_validation_denied(self):
        self.handoff.targets[self.target.reference] = replace(self.target, configuration_revision="2")
        with self.assertRaises(HTTPException):
            self.call()
        self.handoff.targets[self.target.reference] = self.target
        self.store.sql("UPDATE af_tasks SET run_id=:run WHERE id=:id", run=str(uuid4()), id=self.placement["task_id"])
        with self.assertRaises(HTTPException):
            self.call()
        headers = {"Authorization": "Bearer " + self.auth._issue_native_token("bob"), "Content-Type": "application/json"}
        oversized = self.client.post(PATH, content=b"x" * 8193, headers=headers)
        self.assertEqual(oversized.status_code, 413, oversized.text)
        invalid = self.post(self.body(secret="forbidden-untrusted-body-value"))
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertNotIn("forbidden-untrusted-body-value", invalid.text)


if __name__ == "__main__":
    unittest.main()
