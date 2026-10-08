"""Metadata-only rebind ingress does not create or replay native commands."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from agent_factory.personal_command_api import PersonalCommandAPI


class PersonalCommandAPITests(unittest.TestCase):
    def setUp(self):
        self.api = PersonalCommandAPI.__new__(PersonalCommandAPI)
        self.auth = SimpleNamespace(user=Mock(return_value={'id': 'alice'}), require=Mock())
        self.api.auth, self.api.store, self.api.factory = self.auth, Mock(), Mock()
        self.receipt = {'requestId': 'original-rebind', 'action': 'rebind', 'state': 'acknowledged',
            'factoryIdentity': None, 'session': {'id': 'personal-original', 'nativeSessionId': 'chat_original'}}
        self.sessions = Mock()
        self.sessions.auth = self.auth
        self.sessions.preview_rebind.return_value = {'sessionId': 'personal-original', 'canRebind': True,
            'oldConnectionPin': {'fingerprint': 'a' * 64}, 'newConnectionPin': {'fingerprint': 'b' * 64},
            'nativeSessionId': 'chat_original', 'blocker': None}
        self.sessions.rebind.return_value = self.receipt
        self.sessions.request_result.return_value = self.receipt
        self.sessions._command.return_value = {'state': 'acknowledged', 'intent': {'action': 'rebind'}, 'identity': None}
        self.api.sessions = self.sessions
        self.api.router = APIRouter(prefix='/api/factory/personal-agent')
        self.api.routes()
        app = FastAPI(); app.include_router(self.api.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.base = '/api/factory/personal-agent'
        self.body = {'requestId': 'original-rebind', 'connectionRef': 'new-owner-ref',
            'expectedOldFingerprint': 'a' * 64, 'expectedNewFingerprint': 'b' * 64}

    def test_preview_and_explicit_rebind_preserve_authenticated_owner_and_exact_pins(self):
        preview = self.client.get(self.base + '/sessions/personal-original/rebind-preview', params={
            'connectionRef': 'new-owner-ref', 'expectedOldFingerprint': 'a' * 64})
        self.assertEqual(preview.status_code, 200)
        self.sessions.preview_rebind.assert_called_once_with('alice', 'personal-original', 'new-owner-ref', 'a' * 64)
        self.sessions.rebind.assert_not_called()
        result = self.client.post(self.base + '/sessions/personal-original/rebind', json=self.body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()['factoryIdentity'])
        self.sessions.rebind.assert_called_once_with('alice', 'personal-original', 'new-owner-ref', 'original-rebind',
            expected_old_fingerprint='a' * 64, expected_new_fingerprint='b' * 64)
        self.assertIn((('alice', 'read'), {}), self.auth.require.call_args_list)
        self.assertIn((('alice', 'run'), {}), self.auth.require.call_args_list)
        self.api.factory.assert_not_called(); self.assertEqual(self.api.factory.mock_calls, [])
        self.assertEqual(self.api.store.mock_calls, [])

    def test_original_rebind_request_recovery_never_admits_or_settles_a_task(self):
        result = self.client.get(self.base + '/requests/original-rebind')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), self.receipt)
        self.sessions.request_result.assert_called_once_with('alice', 'original-rebind')
        self.sessions.rebind.assert_not_called()
        self.assertEqual(self.api.factory.mock_calls, [])
        self.assertEqual(self.api.store.mock_calls, [])

    def test_extra_authority_missing_or_changed_pin_and_service_blocker_fail_closed(self):
        for body in ({**self.body, 'ownerId': 'bob'}, {**self.body, 'expectedOldFingerprint': 'invalid'},
                {k: v for k, v in self.body.items() if k != 'expectedNewFingerprint'}):
            result = self.client.post(self.base + '/sessions/personal-original/rebind', json=body)
            self.assertEqual(result.status_code, 422)
        self.sessions.rebind.assert_not_called()
        self.sessions.rebind.side_effect = HTTPException(409, 'PERSONAL_REBIND_PENDING_UNRESOLVED')
        result = self.client.post(self.base + '/sessions/personal-original/rebind', json=self.body)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()['detail'], 'PERSONAL_REBIND_PENDING_UNRESOLVED')
        self.assertEqual(self.api.factory.mock_calls, [])

    def test_current_auth_revocation_prevents_local_mapping_change(self):
        self.auth.require.side_effect = HTTPException(403, 'revoked')
        result = self.client.post(self.base + '/sessions/personal-original/rebind', json=self.body)
        self.assertEqual(result.status_code, 403)
        self.sessions.rebind.assert_not_called()
