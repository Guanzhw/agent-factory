"""Origin receipt admission with real validators; synthetic transport/SQL only."""
from contextvars import ContextVar
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.remote_handoff import TrustedHandoffClient
from agent_factory.remote_scientific_evidence import project_scientific_evidence
from agent_factory.store import Store, digest
from test_remote_scientific_evidence import scope


class ScientificHandoffPolicyTests(unittest.TestCase):
    def setUp(self):
        self.scope = scope('preparation')
        self.target = SimpleNamespace(origin_ref='origin', identity_map={'alice': 'receiver-alice'},
                                      configuration_revision='1', fingerprint='a' * 64)
        self.plan = {'executionBindings': {}, 'tools': ['research_preparation_verify']}
        self.row = {'owner_id': 'alice', 'task_id': self.scope['originChildTaskId'],
            'request_id': 'original-request', 'manifest_hash': self.scope['sourceManifestSha256'],
            'body': {'manifest': {'plan': self.plan}, 'scientificEnvelope': {'scope': self.scope}}}
        self.receipt = {'id': str(uuid4()), 'originRef': 'origin', 'originOwnerId': 'alice',
            'originTaskId': self.row['task_id'], 'remoteOwnerId': 'receiver-alice',
            'requestId': 'original-request', 'manifestHash': self.row['manifest_hash'],
            'remotePlanId': str(uuid4()), 'remoteTaskId': str(uuid4()), 'remoteRunId': 'original-run',
            'state': 'DISPATCHED', 'allStopped': True}
        self.receipt['native'] = {'run_id': 'original-run', 'session_id': self.receipt['remoteTaskId'],
            'user_id': 'receiver-alice', 'agent_id': 'factory-executor', 'status': 'completed',
            'queue': {'id': 'original-run', 'session_id': self.receipt['remoteTaskId'],
                      'user_id': 'receiver-alice', 'component_id': 'factory-executor',
                      'component_type': 'agent', 'status': 'completed'}}
        proof = {'schema': 1, 'originRef': 'origin', 'receiptId': self.receipt['id'],
            'originTaskId': self.row['task_id'], 'originOwner': 'alice', 'receiverOwner': 'receiver-alice',
            'receiverPlanId': self.receipt['remotePlanId'], 'manifestHash': self.row['manifest_hash'],
            'sourceConfiguration': {'revision': '1', 'sha256': 'a' * 64},
            'receiverConfiguration': {}, 'entries': []}
        proof['sha256'] = digest(proof | {'sourcePlan': self.plan, 'sourceBindings': {}})
        self.receipt['receiverBindingProof'] = proof
        self.receipt['scientificEvidence'] = project_scientific_evidence(self.receipt, scope=self.scope)
        self.conn = Mock()
        self.conn.execute.return_value.mappings.return_value.first.side_effect = lambda: deepcopy(self.row)
        self.store = SimpleNamespace(_connection=ContextVar('receipt-connection', default=None), engine=Mock(),
            remote_scientific=SimpleNamespace(validate_received_native=Mock()), observed=Mock(), task=Mock())
        self.store.engine.begin.return_value.__enter__ = Mock(return_value=self.conn)
        self.store.engine.begin.return_value.__exit__ = Mock(return_value=False)
        self.store.transaction = lambda: Store.transaction(self.store)
        self.client = object.__new__(TrustedHandoffClient)
        self.client.store = self.store

    def save(self):
        return self.client._save_receipt(self.row, self.target, self.receipt)

    def test_terminal_original_queue_id_releases_with_same_borrowed_transaction(self):
        def check(*args):
            with self.store.transaction() as borrowed:
                self.assertIs(borrowed, self.conn)
        self.store.remote_scientific.validate_received_native.side_effect = check
        self.save()
        self.store.engine.begin.assert_called_once()
        self.store.observed.assert_called_once()
        self.assertIs(self.store.observed.call_args.args[2], True)
        self.assertIsNone(self.store._connection.get())

    def test_run_id_alias_or_other_queue_identity_cannot_release(self):
        for mutation in ('alias', 'foreign', 'running', 'missing'):
            with self.subTest(mutation=mutation):
                value = deepcopy(self.receipt)
                queue = self.receipt['native']['queue']
                if mutation == 'alias': queue['run_id'] = queue.pop('id')
                elif mutation == 'foreign': queue['id'] = 'other-run'
                elif mutation == 'running': queue['status'] = 'running'
                else: self.receipt['native']['detailUnavailable'] = True
                with self.assertRaises(HTTPException): self.save()
                self.store.observed.assert_not_called()
                self.receipt = value

    def test_no_dispatch_cannot_erase_current_or_previous_native_ticket(self):
        self.receipt['state'] = 'CANCELLED_NO_DISPATCH'
        with self.assertRaises(HTTPException): self.save()
        self.row['body']['receipt'] = deepcopy(self.receipt)
        self.receipt['remoteRunId'] = None
        with self.assertRaises(HTTPException): self.save()
        self.store.observed.assert_not_called()

    def test_scientific_evidence_outside_selected_envelope_denies(self):
        self.row['body'].pop('scientificEnvelope')
        with self.assertRaises(HTTPException): self.save()
        self.store.observed.assert_not_called()

    def test_native_pin_denial_restores_connection_and_never_observes_release(self):
        self.store.remote_scientific.validate_received_native.side_effect = HTTPException(409, 'PIN_CHANGED')
        with self.assertRaises(HTTPException): self.save()
        self.assertIsNone(self.store._connection.get())
        self.store.observed.assert_not_called()

    def test_training_terminal_alone_is_not_stop_proof_but_bound_no_dispatch_is(self):
        self.scope['phase'] = 'training'
        self.receipt['scientificEvidence'] = project_scientific_evidence(self.receipt, scope=self.scope)
        self.receipt['native']['status'] = 'cancelled'
        self.receipt['native']['queue']['status'] = 'cancelled'
        with self.assertRaises(HTTPException): self.save()
        self.store.observed.assert_not_called()
        self.receipt['scientificNoDispatch'] = {'schema': 1, 'scopeSha256': digest(self.scope),
            'receiverTaskId': self.receipt['remoteTaskId'], 'receiverPlanId': self.receipt['remotePlanId'],
            'receiverNativeRunId': self.receipt['remoteRunId']}
        self.save()
        self.assertIs(self.store.observed.call_args.args[2], True)

    def test_retained_claim_marker_requires_exact_boolean(self):
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=value):
                self.receipt['scientificClaimsRetained'] = value
                with self.assertRaises(HTTPException): self.save()
                self.store.observed.assert_not_called()
        for value in (False, True):
            self.receipt['scientificClaimsRetained'] = value
            self.save()

    def test_retained_claim_marker_alone_outside_scientific_placement_denies(self):
        self.row['body'].pop('scientificEnvelope')
        self.receipt.pop('scientificEvidence')
        self.receipt['scientificClaimsRetained'] = True
        with self.assertRaises(HTTPException): self.save()
        self.store.observed.assert_not_called()

    def test_retained_true_never_replaces_native_or_process_gpu_stop_proof(self):
        self.receipt['scientificClaimsRetained'] = True
        self.receipt['native']['queue']['id'] = 'other-run'
        with self.assertRaises(HTTPException): self.save()
        self.receipt['native']['queue']['id'] = self.receipt['remoteRunId']
        self.scope['phase'] = 'training'
        self.receipt['scientificEvidence'] = project_scientific_evidence(self.receipt, scope=self.scope)
        with self.assertRaises(HTTPException): self.save()
        self.store.observed.assert_not_called()
