"""App-owned placement validation cannot replace core immutable proof checks."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table

from agent_factory.application_runtime import ApplicationRuntimeRegistry
from agent_factory.remote_bindings import RemoteBindingService
from agent_factory.remote_handoff import PreparedHandoffService
from agent_factory.store import digest


class RemoteBindingApplicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "id": "origin-plan", "ownerId": "origin-owner", "createdAt": "source-time",
            "fingerprint": "source-fingerprint", "tools": ["approved-tool"],
            "budget": {"depth": 1, "toolCalls": 2},
            "delegation": {"parentTaskId": "origin-parent"},
        }
        self.proof = {
            "receiverOwner": "receiver-owner", "receiverPlanId": "receiver-plan",
            "receiptId": "receipt", "originRef": "origin", "originTaskId": "origin-child",
            "manifestHash": digest(self.source), "sourcePlan": copy.deepcopy(self.source),
        }
        self.root = {
            **copy.deepcopy(self.source), "id": "receiver-plan", "ownerId": "receiver-owner",
            "createdAt": "receiver-time", "fingerprint": "receiver-fingerprint",
            "budget": {"depth": 0, "toolCalls": 2},
            "remoteHandoff": {
                "receiptId": "receipt", "originRef": "origin", "originTaskId": "origin-child",
                "manifestHash": digest(self.source), "bindingProofSha256": digest(self.proof),
            },
        }
        self.root.pop("delegation")
        self.service = object.__new__(RemoteBindingService)
        self.service.store = SimpleNamespace()
        self.service.delegated_root_validator = None
        self.service.proofs = Table("proofs", MetaData(),
            Column("receipt_id", String), Column("receiver_owner", String))
        self.conn = Mock()
        self.conn.execute.return_value.mappings.return_value.first.return_value = {
            "receiver_plan_id": self.root["id"], "sha": digest(self.proof), "body": self.proof,
        }

    def test_delegated_import_requires_explicit_trusted_validator(self):
        with self.assertRaisesRegex(HTTPException, "trusted receiver root validation is unavailable"):
            self.service._proof(self.conn, self.root)

    def test_validator_receives_original_proof_with_no_application_store_dependency(self):
        validator = Mock()
        self.service.delegated_root_validator = validator
        self.assertEqual(self.service._proof(self.conn, self.root), self.proof)
        validator.assert_called_once_with(self.conn, self.root, self.source)

    def test_identity_integrity_is_checked_before_application_validator(self):
        validator = Mock()
        self.service.delegated_root_validator = validator
        self.root["remoteHandoff"]["bindingProofSha256"] = "different-proof"
        with self.assertRaisesRegex(HTTPException, "REMOTE_BINDING_INTEGRITY"):
            self.service._proof(self.conn, self.root)
        validator.assert_not_called()

    def test_application_rejection_is_not_ignored(self):
        self.service.delegated_root_validator = Mock(side_effect=HTTPException(409, "Original app scope changed"))
        with self.assertRaisesRegex(HTTPException, "Original app scope changed"):
            self.service._proof(self.conn, self.root)

    def test_application_validator_cannot_rewrite_proof_or_restore_child_authority(self):
        for field, value, error in (
            ("tools", ["unapproved-tool"], "REMOTE_BINDING_SOURCE"),
            ("budget", {"depth": 0, "toolCalls": 3}, "REMOTE_BINDING_DELEGATION"),
            ("delegation", {"parentTaskId": "new-parent"}, "REMOTE_BINDING_DELEGATION"),
        ):
            with self.subTest(field=field):
                root = {**copy.deepcopy(self.root), field: value}
                original_proof = copy.deepcopy(self.proof)
                def mutate_arguments(conn, candidate, source):
                    source[field] = copy.deepcopy(value)
                    candidate.pop("delegation", None)
                    candidate["budget"] = {"depth": 0, "toolCalls": 2}
                self.service.delegated_root_validator = mutate_arguments
                with self.assertRaisesRegex(HTTPException, error):
                    self.service._proof(self.conn, root)
                self.assertEqual(self.proof, original_proof)
                self.assertEqual(root[field], value)

    def test_ordinary_root_does_not_require_application_validator(self):
        self.proof["sourcePlan"].pop("delegation")
        self.proof["sourcePlan"]["budget"]["depth"] = 0
        self.proof["manifestHash"] = digest(self.proof["sourcePlan"])
        self.root["remoteHandoff"].update(
            manifestHash=self.proof["manifestHash"], bindingProofSha256=digest(self.proof))
        self.conn.execute.return_value.mappings.return_value.first.return_value["sha"] = digest(self.proof)
        self.assertEqual(self.service._proof(self.conn, self.root), self.proof)


class RemoteReceiptApplicationBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_native_ticket_waits_for_registered_runtime_stop_proof(self):
        task = {'id': 'receiver-task', 'run_id': 'original-run', 'owner_id': 'receiver-owner', 'plan_id': 'receiver-plan',
            'admission': 'accepted', 'cancel_requested': False}
        row = {'id': 'receipt', 'state': 'ACCEPTED', 'body': {'remoteTaskId': task['id']}}
        effect = {'status': 'DONE', 'effect_key': 'original-run:external-adapter-work'}
        service = object.__new__(PreparedHandoffService)
        service.store = SimpleNamespace(task=Mock(return_value=task), sql=Mock(),
            effects=Mock(return_value=[effect]), events=Mock(return_value=[]), artifacts=Mock(return_value=[]),
            plan=Mock(return_value={}))
        effect_held = Mock(return_value=True)
        service.store.application_runtime = ApplicationRuntimeRegistry(service.store)
        service.store.application_runtime.register('fixture-owner', SimpleNamespace(effect_held=effect_held),
            effects=('external-adapter-work',))
        service.bridge = SimpleNamespace(find_run=AsyncMock(return_value={'run_id': 'original-run'}),
            detail=AsyncMock(return_value={'run_id': 'original-run', 'status': 'completed'}))
        service._row = Mock(return_value=row)
        service._check_row = Mock()
        service._public = Mock(side_effect=lambda *_: {'id': 'receipt'})
        receipt = await service.receipt('receiver-owner', 'receipt')
        self.assertIs(receipt['allStopped'], False)
        self.assertEqual(receipt['applicationStatus'], 'unknown')
        effect_held.assert_called_with(effect)
        effect_held.return_value = False
        receipt = await service.receipt('receiver-owner', 'receipt')
        self.assertIs(receipt['allStopped'], True)
        self.assertEqual(receipt['applicationStatus'], 'completed')


if __name__ == "__main__":
    unittest.main()
