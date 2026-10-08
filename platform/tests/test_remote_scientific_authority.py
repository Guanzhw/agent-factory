"""Scientific debit wire tests; no sockets, database or model execution."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError

from agent_factory.remote_authority import (AUTHORITY_TOOLS, AuthorityScientificCall,
    OriginAuthorityTransport, PATH, SCIENTIFIC_CALL_PATH, SCIENTIFIC_CUSTODY_PATH, ScientificCustodyReply, origin_authority_router)
from agent_factory.remote_handoff import HandoffAuthority, HandoffCancellationRequested
from agent_factory.store import digest


def binding():
    return {"schema": 1, "originRef": "fixture-origin", "targetRef": "fixture-target", "originOwner": "alice",
        "originTaskId": str(uuid4()), "manifestSha256": "a" * 64, "tool": "research_process_run",
        "receiverIdentity": "receiver", "targetRevision": "1", "targetFingerprint": "b" * 64,
        "callId": "native-tool-call:fixture-1", "receiverTaskId": str(uuid4()), "nativeRunId": str(uuid4()),
        "phaseScopeSha256": "c" * 64}


class RouteFixture:
    def __init__(self):
        self.body = binding()
        self.calls = []
        self.debits = {}
        self.actor = "receiver"
        self.allowed = True
        self.cancelled = False
        self.changed_during_check = False
        self.bad_proof = False
        self.target = SimpleNamespace(origin_ref="fixture-origin", identity_map={"alice": "receiver"},
            configuration_revision="1", fingerprint="b" * 64)
        self.row = {"target_ref": "fixture-target", "manifest_hash": "a" * 64, "configuration_hash": "b" * 64}
        self.handoff = SimpleNamespace(targets={"fixture-target": self.target}, _row=lambda *_: self.row,
            _target=lambda *_, **__: None, authority_callback=self.authority,
            store=SimpleNamespace(remote_scientific=SimpleNamespace(consume_remote_tool=self.consume)))
        auth = SimpleNamespace(user=lambda _: {"id": self.actor}, require=self.require)
        app = FastAPI()
        app.include_router(origin_authority_router(auth, self.handoff))
        self.client = TestClient(app)

    def require(self, actor, operation):
        if not self.allowed:
            raise HTTPException(403, "fixture-denied")

    def authority(self, owner, task, manifest, tool):
        if self.cancelled:
            raise HandoffCancellationRequested(owner, task, manifest)
        if self.changed_during_check:
            self.target.fingerprint = "d" * 64
        return HandoffAuthority(frozenset({"compute:local", "research:read"}),
            frozenset({"research_process_run", "research_preparation_verify"}),
            {"toolCalls": 8, "maxDepth": 2, "maxChildren": 4, "experimentSeconds": 8, "outputBytes": 65536},
            origin_ref="fixture-origin", target_ref="fixture-target", receiver_identity="receiver",
            target_revision="1", target_fingerprint="b" * 64)

    def consume(self, body):
        # Synthetic service contract only: production persistence is exercised
        # separately by the service's PostgreSQL tests.
        self.calls.append(body)
        if self.bad_proof:
            return {"callProofSha256": "bad", "private": "must-not-echo"}
        previous = self.debits.setdefault(body["callId"], body)
        if previous != body:
            raise HTTPException(409, "fixture-call-conflict")
        return {"callProofSha256": digest(body)}


class ScientificAuthorityRouteTests(unittest.TestCase):
    def setUp(self):
        self.f = RouteFixture()
        self.addCleanup(self.f.client.close)

    def test_read_only_checks_never_consume_and_stable_call_binding_is_forwarded(self):
        f = self.f
        authority = {k: v for k, v in f.body.items() if k not in {
            "callId", "receiverTaskId", "nativeRunId", "phaseScopeSha256"}}
        for _ in range(3):
            self.assertEqual(f.client.post(PATH, json=authority).status_code, 200)
        self.assertEqual(f.calls, [])
        one = f.client.post(SCIENTIFIC_CALL_PATH, json=f.body)
        two = f.client.post(SCIENTIFIC_CALL_PATH, json=f.body)
        self.assertEqual(one.status_code, 200, one.text)
        self.assertEqual(one.json(), {**f.body, "outcome": "consumed", "callProofSha256": digest(f.body)})
        self.assertEqual(one.json(), two.json())
        self.assertEqual(len(f.debits), 1)
        self.assertEqual(one.headers["cache-control"], "private, no-store")

    def test_mutation_cannot_skip_actor_configuration_placement_or_cancellation(self):
        for case in ("actor", "grant", "config", "placement", "cancel", "rotation"):
            f = RouteFixture()
            try:
                if case == "actor": f.actor = "foreign"
                elif case == "grant": f.allowed = False
                elif case == "config": f.target.configuration_revision = "2"
                elif case == "placement": f.row["manifest_hash"] = "d" * 64
                elif case == "cancel": f.cancelled = True
                elif case == "rotation": f.changed_during_check = True
                self.assertIn(f.client.post(SCIENTIFIC_CALL_PATH, json=f.body).status_code, {403, 409})
                self.assertEqual(f.calls, [])
            finally:
                f.client.close()

    def test_dto_forbids_extra_fields_invalid_calls_and_model_decision_tools(self):
        f = self.f
        for change in ({"schema": True}, {"callId": ""}, {"callId": "x" * 201}, {"callId": "a\nb"},
                       {"nativeRunId": "other"}, {"receiverTaskId": "other"}, {"phaseScopeSha256": "bad"},
                       {"tool": "autoresearch_session_run"}, {"tool": None}, {"ownerId": "foreign"}):
            response = f.client.post(SCIENTIFIC_CALL_PATH, json={**f.body, **change})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(f.calls, [])
        self.assertNotIn("autoresearch_session_run", AUTHORITY_TOOLS)
        with self.assertRaises(ValidationError):
            AuthorityScientificCall.model_validate({**f.body, "tool": "research_candidate_propose"})

    def test_request_size_duplicate_json_and_invalid_service_proof_are_sanitized(self):
        f = self.f
        self.assertEqual(f.client.post(SCIENTIFIC_CALL_PATH, content=b"x" * 8193).status_code, 413)
        raw = json.dumps(f.body)[:-1] + ',"callId":"duplicate"}'
        self.assertEqual(f.client.post(SCIENTIFIC_CALL_PATH, content=raw,
                                      headers={"content-type": "application/json"}).status_code, 422)
        self.assertEqual(f.calls, [])
        f.bad_proof = True
        response = f.client.post(SCIENTIFIC_CALL_PATH, json=f.body)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("must-not-echo", response.text)

    def test_changed_stable_call_binding_is_service_conflict(self):
        f = self.f
        self.assertEqual(f.client.post(SCIENTIFIC_CALL_PATH, json=f.body).status_code, 200)
        self.assertEqual(f.client.post(SCIENTIFIC_CALL_PATH, json={**f.body, "nativeRunId": str(uuid4())}).status_code, 409)
        self.assertEqual(len(f.debits), 1)

    def test_unknown_service_outcome_is_sanitized_without_retry(self):
        f = self.f
        calls = []
        def unavailable(body):
            calls.append(body)
            raise RuntimeError("private-database-details")
        f.handoff.store.remote_scientific.consume_remote_tool = unavailable
        response = f.client.post(SCIENTIFIC_CALL_PATH, json=f.body)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-database-details", response.text)
        self.assertEqual(len(calls), 1)


class ScientificAuthorityTransportTests(unittest.TestCase):
    def call(self, handler, *, change=None):
        body = binding()
        requests = []
        def handle(request):
            requests.append(request)
            return handler(request)
        original = httpx.Client
        def client(**kwargs):
            self.assertIs(kwargs["follow_redirects"], False)
            self.assertIs(kwargs["trust_env"], False)
            return original(**kwargs, transport=httpx.MockTransport(handle))
        transport = OriginAuthorityTransport("https://origin.example.invalid", body["originRef"], body["targetRef"],
            body["targetRevision"], body["targetFingerprint"], {"alice": "receiver"}, lambda _: "synthetic-token")
        args = {"call_id": body["callId"], "receiver_task_id": body["receiverTaskId"],
                "native_run_id": body["nativeRunId"], "phase_scope_sha256": body["phaseScopeSha256"], **(change or {})}
        with patch("agent_factory.remote_authority.httpx.Client", side_effect=client):
            try:
                result = transport.consume_scientific_tool("alice", body["originTaskId"], body["manifestSha256"], body["tool"], **args)
            finally:
                self.assertLessEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, SCIENTIFIC_CALL_PATH)
        self.assertNotIn("synthetic-token", requests[0].content.decode())
        return result

    def test_exact_bound_proof_and_no_credential_in_body(self):
        def handler(request):
            body = json.loads(request.content)
            return httpx.Response(200, json={**body, "outcome": "consumed", "callProofSha256": digest(body)})
        self.assertEqual(self.call(handler)["outcome"], "consumed")

    def test_each_echoed_binding_field_is_required_exact(self):
        for field in ("callId", "receiverTaskId", "nativeRunId", "phaseScopeSha256", "manifestSha256", "originOwner"):
            def handler(request, field=field):
                body = json.loads(request.content)
                body[field] = "d" * 64 if field.endswith("Sha256") else str(uuid4())
                return httpx.Response(200, json={**body, "outcome": "consumed", "callProofSha256": "e" * 64})
            with self.assertRaises(HTTPException):
                self.call(handler)

    def test_unknown_ack_errors_redirects_and_oversize_never_retry(self):
        for status in (401, 403, 409, 422, 429, 500, 302):
            with self.assertRaises(HTTPException):
                self.call(lambda _, status=status: httpx.Response(status, headers={"location": "https://other.invalid"}))
        with self.assertRaises(HTTPException):
            self.call(lambda _: httpx.Response(200, content=b"x" * 17000, headers={"content-type": "application/json"}))
        def disconnected(_):
            raise httpx.ReadError("private-transport-details")
        with self.assertRaises(HTTPException) as error:
            self.call(disconnected)
        self.assertNotIn("private-transport-details", str(error.exception.detail))


if __name__ == "__main__":
    unittest.main()


class ScientificCustodyWireTests(unittest.TestCase):
    def test_distinct_read_proof_never_execution_or_debit(self):
        f = RouteFixture()
        body = {key: value for key, value in f.body.items() if key != 'callId'}
        body.update(tool=None, leaseId=str(uuid4()))
        seen = []
        def custody(value):
            seen.append(value)
            return {'custodyProofSha256': digest(value)}
        f.handoff.store.remote_scientific.authorize_completed_custody = custody
        response = f.client.post(SCIENTIFIC_CUSTODY_PATH, json=body)
        self.assertEqual(response.status_code, 200)
        reply = ScientificCustodyReply.model_validate(response.json())
        self.assertEqual(reply.outcome, 'custody-readable')
        self.assertNotIn('authority', response.json())
        self.assertEqual(f.calls, [])
        self.assertEqual(seen, [body])
        self.assertEqual(f.client.post(SCIENTIFIC_CUSTODY_PATH, json={**body, 'tool': 'research_process_run'}).status_code, 422)
        f.actor = 'other'
        self.assertEqual(f.client.post(SCIENTIFIC_CUSTODY_PATH, json=body).status_code, 403)
        self.assertEqual(len(seen), 1)

    def test_transport_echo_scope_and_readonly_outcome(self):
        f = RouteFixture()
        transport = OriginAuthorityTransport(base_url='https://origin.example', origin_ref='fixture-origin',
            target_ref='fixture-target', target_revision='1', target_fingerprint='b' * 64,
            receiver_identity_map={'alice': 'receiver'}, credential_provider=lambda _: 'mock-only')
        def post(_self, owner, path, body):
            self.assertEqual(path, SCIENTIFIC_CUSTODY_PATH)
            return json.dumps({**body, 'outcome': 'custody-readable', 'custodyProofSha256': digest(body)}).encode()
        with patch.object(OriginAuthorityTransport, '_post', post):
            reply = transport.check_scientific_custody('alice', f.body['originTaskId'], 'a' * 64,
                receiver_task_id=f.body['receiverTaskId'], native_run_id=f.body['nativeRunId'],
                phase_scope_sha256='c' * 64, lease_id=str(uuid4()))
        self.assertIsNone(reply['tool'])
        self.assertEqual(reply['outcome'], 'custody-readable')
