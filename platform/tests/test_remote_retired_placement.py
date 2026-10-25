"""Retired application records remain inert; no reinterpretation or replay."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from agent_factory.remote_handoff import PrepareBody, PreparedHandoffService, TrustedHandoffClient, _manifest
from agent_factory.store import digest
from test_remote_contracts import _fixture


class RetiredPlacementTests(unittest.TestCase):
    def test_prepare_rejects_removed_envelope_even_when_null(self):
        body = dict(originRef='fixture-origin', originOwnerId='alice', originTaskId=uuid4(),
                    requestId='fixture-request', manifest={})
        PrepareBody.model_validate(body)
        for envelope in (None, {}, {'phase': 'old-application'}):
            with self.subTest(envelope=envelope), self.assertRaises(ValidationError):
                PrepareBody.model_validate({**body, 'scientificEnvelope': envelope})

    def test_legacy_child_manifest_cannot_be_admitted_as_root(self):
        _, original, _ = _fixture()
        for changes in ({'delegation': {}}, {'scientificEnvelope': {}},
                        {'budget': {**original['budget'], 'depth': 1}}):
            plan = {**deepcopy(original), **changes}
            plan['fingerprint'] = digest({k: v for k, v in plan.items() if k not in {'id', 'createdAt', 'fingerprint'}})
            with self.subTest(changes=changes), self.assertRaises(HTTPException) as denied:
                _manifest({'plan': plan, 'sha256': digest(plan)}, SimpleNamespace(), 'alice', receiver=True)
            self.assertIn(denied.exception.status_code, (409, 422))

    def test_both_original_row_paths_reject_old_records_without_mutation(self):
        for body in ({'scientificEnvelope': {}}, {'scientificEnvelope': None},
                     {'receipt': {'scientificEvidence': {}}}, {'receipt': {'scientificNoDispatch': True}},
                     {'receipt': {'scientificClaimsRetained': True}}):
            for cls in (PreparedHandoffService, TrustedHandoffClient):
                with self.subTest(body=body, service=cls.__name__):
                    row = {'body': deepcopy(body), 'state': 'DISPATCH_UNKNOWN'}
                    saved = deepcopy(row)
                    service = cls.__new__(cls)
                    service.store = Mock()
                    service.store.sql.return_value = [row]
                    with self.assertRaises(HTTPException) as denied:
                        service._row('fixture-first', 'fixture-second')
                    self.assertEqual(denied.exception.status_code, 409)
                    self.assertIn('REMOTE_CONTRACT_UNSUPPORTED', denied.exception.detail)
                    self.assertEqual(row, saved)
                    self.assertEqual(len(service.store.mock_calls), 1)
                    self.assertTrue(service.store.sql.call_args.args[0].startswith('SELECT '))

    def test_original_unknown_cannot_dispatch_or_cancel_after_application_removal(self):
        for cls, methods in ((TrustedHandoffClient, ('prepare', 'dispatch', 'cancel')),
                             (PreparedHandoffService, ('dispatch', 'cancel'))):
            for method in methods:
                with self.subTest(service=cls.__name__, method=method):
                    service = cls.__new__(cls)
                    service.store = Mock()
                    row = {'state': 'DISPATCH_UNKNOWN', 'body': {'scientificEnvelope': {}, 'dispatchAttempted': True}}
                    service.store.sql.return_value = [row]
                    service.auth = Mock()
                    with self.assertRaises(HTTPException) as denied:
                        asyncio.run(getattr(service, method)('alice', 'original-task'))
                    self.assertEqual(denied.exception.status_code, 409)
                    self.assertEqual(len(service.store.mock_calls), 1)
                    self.assertEqual(row['state'], 'DISPATCH_UNKNOWN')

    def test_scientific_receipt_cannot_release_root_capacity(self):
        client = TrustedHandoffClient.__new__(TrustedHandoffClient)
        client.store = Mock()
        row = {'body': {'receipt': None}, 'state': 'DISPATCH_UNKNOWN'}
        for field in ('scientificEvidence', 'scientificNoDispatch', 'scientificClaimsRetained'):
            with self.subTest(field=field), self.assertRaises(HTTPException) as denied:
                client._save_receipt(row, None, {'allStopped': True, field: {}})
            self.assertEqual(denied.exception.status_code, 409)
            self.assertEqual(client.store.mock_calls, [])
            self.assertEqual(row, {'body': {'receipt': None}, 'state': 'DISPATCH_UNKNOWN'})


if __name__ == '__main__':
    unittest.main()
