from fixture_auth import disabled_member_request
"""Dual-database command receipts across the real guarded Factory routes."""
import os
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_remote_execution_postgres as fixture


from agno.models.response import ModelResponse
from agent_factory.execution_bindings import AdapterRegistration
from agent_factory.usage_ledger import PricingRevision
from core_native_fixture import FixtureModel, build_tools, create_fixture_app

APPROVAL_APP = 'fixture-remote-approved-operation'
APPROVAL_MODEL = 'fixture-remote-approval-model-v1'
APPROVAL_TOOL = 'fixture-remote-approved-process-v1'


class ApprovalFixtureModel(FixtureModel):
    """Drive native approval for an inert owned process; no provider request."""
    def _response(self, messages):
        result = next((message for message in reversed(messages)
                       if message.role == 'tool' and message.tool_name == 'bounded_process_run'), None)
        if result is not None:
            return ModelResponse(role='assistant', content=json.dumps({
                'status': 'failed' if result.tool_call_error else 'synthetic-complete',
                'result': str(result.content)}))
        return ModelResponse(role='assistant', tool_calls=[{
            'id': 'fixture-approved-process', 'type': 'function',
            'function': {'name': 'bounded_process_run', 'arguments': '{}'}}])


def create_approval_fixture_app(settings, *, source=None):
    """Explicit v1 contract fixture, not compute-pool/provider compatibility."""
    settings.runtime_tool_contract = 'bounded-process-v1'
    settings.runtime_adapters = [*settings.runtime_adapters,
        AdapterRegistration('model', APPROVAL_MODEL, '1', lambda _: ApprovalFixtureModel(id=APPROVAL_MODEL), ),
        AdapterRegistration('tool', APPROVAL_TOOL, '1',
            lambda context: build_tools(context.settings, context.store, operation_name='bounded_process_run')['bounded_process_run'],
            tool_name='bounded_process_run', permissions=('compute:local',), )]
    settings.usage_pricing = (*settings.usage_pricing,
        PricingRevision(APPROVAL_MODEL, '1', 'controlled-fixture', APPROVAL_MODEL,
                        'fixture-zero-local-v1', local_model_type=ApprovalFixtureModel))
    app = create_fixture_app(settings)
    state = app.app.state.factory
    governance, applications = state['material_governance'], state['applications']
    refs = []
    for identifier, kind, content, adapter, permissions in (
        ('fixture-remote-approval-model', 'model', 'Controlled native approval driver', APPROVAL_MODEL, []),
        ('fixture-remote-approved-process-tool', 'tool', 'bounded_process_run', APPROVAL_TOOL, ['compute:local'])):
        material = governance.create_draft('manager', {'id': identifier, 'kind': kind, 'name': identifier,
            'content': content, 'permissions': permissions,
            'runtimeBinding': {'adapterId': adapter, 'revision': '1', 'config': {}}}, identifier + ':draft')
        governance.publish('manager', material['id'], material['version'], identifier + ':publish')
        refs.append({key: material[key] for key in ('id', 'version', 'sha256')})
    environment = next(item for item in state['store'].materials(published_only=True) if item['id'] == 'fixture-environment')
    refs.append({key: environment[key] for key in ('id', 'version', 'sha256')})
    if source is None:
        application = applications.create_draft('manager', {'id': APPROVAL_APP, 'name': 'Controlled remote approval',
            'defaultMode': 'experiment', 'modes': {'experiment': {'materialRefs': refs,
                'capabilities': ['compute:local'], 'toolOrder': ['bounded_process_run']}}}, APPROVAL_APP + ':draft')
    else:
        # Governed application hashes include creation time. Import the exact
        # source snapshot instead of independently authoring a lookalike.
        application = applications.import_snapshot('manager', source['fixture_approval_application'], APPROVAL_APP + ':import')
    applications.publish('manager', application['id'], application['version'], APPROVAL_APP + ':publish')
    state['fixture_approval_application'] = applications.require_current(applications.pin(application))
    return app


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class RemoteControlCommandPostgresTests(unittest.TestCase):
    make_app = staticmethod(create_approval_fixture_app)
    trusted_origin_options = {
        "tool_contract": "bounded-process-v1", "configuration_revision": "fixture-approved-operation-v1",
        "tools": frozenset({"ask_scope", "checksum", "bounded_process_run"}),
        "capabilities": frozenset({"question:ask", "checksum:read", "compute:local"})}

    headers = fixture.RemoteExecutionProductPostgresTests.headers
    request = fixture.RemoteExecutionProductPostgresTests.request
    plan = fixture.RemoteExecutionProductPostgresTests.plan
    submit = fixture.RemoteExecutionProductPostgresTests.submit
    wait = fixture.RemoteExecutionProductPostgresTests.wait
    ticket_count = fixture.RemoteExecutionProductPostgresTests.ticket_count
    install_transport = fixture.RemoteExecutionProductPostgresTests.install_transport
    setUp = fixture.RemoteExecutionProductPostgresTests.setUp
    tearDown = fixture.RemoteExecutionProductPostgresTests.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.RemoteExecutionProductPostgresTests.setUpClass.__func__(cls)

    def waiting(self):
        job, _ = self.submit(self.plan("sort", application="fixture-text"))
        return self.wait(job["id"], {"waiting_input"})

    def command(self, detail):
        question = detail["job"]["questionDetail"]
        return {"commandId": str(uuid4()), "action": "answer", "requirementId": question["id"],
                "version": question["version"], "answer": "Controlled remote decision scope"}

    def test_remote_answer_commit_lost_reply_recovers_both_exact_command_receipts(self):
        detail = self.waiting()
        task = detail["job"]["id"]
        remote = detail["snapshot"]["remoteHandoff"]["remoteTaskId"]
        command = self.command(detail)
        loss = fixture.ControlledDispatchLoss(self.receiver_app, suffix="/commands")
        self.install_transport(loss)
        first = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
        self.assertTrue(first["decisionRecorded"], first)
        self.assertEqual(first["evidence"]["kind"], "receiver-command")
        second = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
        self.assertEqual(second["fingerprint"], first["fingerprint"])
        self.assertEqual(loss.attempts, 1)
        rows = self.receiver["store"].sql("SELECT * FROM af_control_commands WHERE command_id=:id", id=command["commandId"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_ref"], remote)
        self.assertEqual(rows[0]["body"]["binding"]["upstream"]["sourceFingerprint"], first["fingerprint"])
        self.assertEqual(self.ticket_count(self.receiver, remote), 1)
        self.assertEqual(self.ticket_count(self.origin, task), 0)
        self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}', owner="bob", expected=404)

    def test_remote_child_command_is_bound_to_exact_tree_member_and_cancel_receipt(self):
        parent = self.waiting()
        root = parent["job"]["id"]
        child = self.request("POST", f"/jobs/{root}/children", expected=202,
            json={"goal": "sort", "mode": "literature", "requestId": str(uuid4())}).json()["job"]["id"]
        detail = self.wait(child, {"waiting_input"})
        command = self.command(detail)
        receipt = self.request("POST", f"/jobs/{child}/commands", expected=202, json=command).json()
        self.assertTrue(receipt["decisionRecorded"], receipt)
        self.assertEqual(receipt["binding"]["remoteChildId"], child.split("~", 1)[1])
        self.request("GET", f'/jobs/{root}/commands/{command["commandId"]}', expected=404)
        self.request("POST", f"/jobs/{root}/commands", expected=409, json=command)
        child_cancel = {"commandId": str(uuid4()), "action": "cancel"}
        child_receipt = self.request("POST", f"/jobs/{child}/commands", expected=202, json=child_cancel).json()
        self.assertTrue(child_receipt["decisionRecorded"], child_receipt)
        self.assertEqual(child_receipt["binding"]["remoteChildId"], child.split("~", 1)[1])
        self.assertFalse(self.origin["store"].task(root)["cancel_requested"])
        # Root cancellation is independently scoped and persisted on both sides.
        cancel = {"commandId": str(uuid4()), "action": "cancel"}
        loss = fixture.ControlledDispatchLoss(self.receiver_app, suffix="/commands")
        self.install_transport(loss)
        value = self.request("POST", f"/jobs/{root}/commands", expected=202, json=cancel).json()
        self.assertTrue(value["decisionRecorded"], value)
        self.request("POST", f"/jobs/{root}/commands", expected=202, json=cancel)
        self.assertEqual(loss.attempts, 1)
        self.assertEqual(len(self.receiver["store"].sql("SELECT 1 FROM af_control_commands WHERE command_id=:id", id=cancel["commandId"])), 1)

    def test_missing_receiver_command_is_unknown_and_never_reposted_by_recovery(self):
        detail = self.waiting()
        task, command = detail["job"]["id"], self.command(detail)
        loss = fixture.ControlledDispatchLoss(self.receiver_app, before_delivery=True, suffix="/commands")
        self.install_transport(loss)
        value = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
        self.assertEqual(value["state"], "UNKNOWN")
        with patch.object(self.handoff, "control_command", side_effect=AssertionError("Read recovery must not dispatch")):
            for _ in range(2):
                value = self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}').json()
                self.assertEqual(value["state"], "UNKNOWN")
                self.request("POST", f"/jobs/{task}/commands", expected=202, json=command)
        self.assertEqual(loss.attempts, 1)
        self.assertEqual(self.receiver["store"].sql("SELECT 1 FROM af_control_commands WHERE command_id=:id", id=command["commandId"]), [])

    def test_changed_receiver_identity_proof_and_revoked_owner_refuse_command(self):
        detail = self.waiting()
        task, command = detail["job"]["id"], self.command(detail)
        original = self.handoff._request
        async def wrong(owner, target, method, path, **kwargs):
            value = await original(owner, target, method, path, **kwargs)
            if "/commands" in path and isinstance(value, dict):
                return {**value, "taskId": str(uuid4())}
            return value
        with patch.object(self.handoff, "_request", side_effect=wrong):
            value = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
            self.assertEqual(value["state"], "UNKNOWN")
        value = self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}').json()
        self.assertTrue(value["decisionRecorded"])
        headers = self.headers()
        self.origin["auth"].directory.set_disabled("alice", True)
        try:
            denied = disabled_member_request(self, self.origin, self.origin_client, 'POST', f'/api/factory/jobs/{task}/commands', headers=headers, json=command)
            self.assertEqual(denied.status_code, 403, denied.text)
            denied_read = disabled_member_request(self, self.origin, self.origin_client, 'GET', f'/api/factory/jobs/{task}/commands/{command["commandId"]}', headers=headers)
            self.assertEqual(denied_read.status_code, 403, denied_read.text)
        finally:
            self.origin["auth"].directory.set_disabled("alice", False)
        self.assertTrue(self.request("GET", f'/jobs/{task}/commands/{command["commandId"]}').json()["decisionRecorded"])

    def test_remote_approve_and_reject_lost_reply_preserve_exact_decision(self):
        for approved in (False, True):
            with self.subTest(approved=approved):
                job, _ = self.submit(self.plan("Run one controlled owned process", mode="experiment", application=APPROVAL_APP))
                task = job["id"]
                detail = self.wait(task, {"waiting_approval"})
                requirement = detail["job"]["approvalDetail"]
                command = {"commandId": str(uuid4()), "action": "approve", "requirementId": requirement["id"],
                           "version": requirement["version"], "approved": approved}
                loss = fixture.ControlledDispatchLoss(self.receiver_app, suffix="/commands")
                self.install_transport(loss)
                receipt = self.request("POST", f"/jobs/{task}/commands", expected=202, json=command).json()
                self.assertTrue(receipt["decisionRecorded"], receipt)
                self.assertEqual(receipt["approved"], approved)
                self.request("POST", f"/jobs/{task}/commands", expected=202, json=command)
                self.assertEqual(loss.attempts, 1)
                self.request("POST", f"/jobs/{task}/commands", expected=409, json={**command, "approved": not approved})
                self.request("POST", f"/jobs/{task}/cancel")
                stopped = self.wait(task, {"canceled", "failed", "completed"})
                self.assertTrue(stopped['snapshot']['remoteHandoff']['allStopped'])
                # This fixture has no pool lease. Its native effect records
                # positive stop of the original subprocess independently.
                effects = stopped['snapshot']['effects']
                self.assertTrue(all(effect['status'] in {'DONE', 'CANCELLED'} and
                                    effect['result']['allStopped'] for effect in effects))
                if not approved:
                    self.assertEqual(effects, [])
