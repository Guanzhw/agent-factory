"""Metadata-only rebind ingress does not create or replay native commands."""
import asyncio
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from agent_factory.personal_command_api import PersonalCommandAPI
from agent_factory.factory_api import FactoryAPI


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

    def test_original_request_authorization_does_not_block_asgi_loop(self):
        entered, release = threading.Event(), threading.Event()
        def bounded_health_check(owner, request_id):
            self.assertEqual((owner, request_id), ('alice', 'original'))
            entered.set()
            self.assertTrue(release.wait(timeout=2))
            return {'requestId': request_id, 'receipt': None}, None
        self.api._prepared_request_metadata = bounded_health_check
        async def observe():
            pending = asyncio.create_task(self.api.prepared_request('alice', 'original'))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                self.assertFalse(pending.done())
                # This loop remains able to serve another request while SSH
                # checks current authority; it never skips or replays a check.
                await asyncio.wait_for(asyncio.sleep(0), timeout=.2)
            finally:
                release.set()
            self.assertEqual(await pending, {'requestId': 'original', 'receipt': None})
        asyncio.run(observe())

    def test_explicit_start_keeps_fresh_authorization_off_loop_before_native_admission(self):
        from agent_factory.personal_command_profile import APPLICATION_ID
        plan = {'id': 'plan-original', 'application': APPLICATION_ID, 'mode': 'personal-command',
            'status': 'ready'}
        self.api.store.plan.return_value = plan
        factory = FactoryAPI.__new__(FactoryAPI)
        factory.auth, factory.store, factory.remote = self.auth, self.api.store, None
        factory.bridge = SimpleNamespace(submit=AsyncMock(return_value={'run_id': 'native-original'}))
        factory.detail = AsyncMock(return_value={'job': {'id': 'task-original'}})
        factory.store.reserve_task.return_value = ({'id': 'task-original'}, True)
        self.api.factory = factory
        entered, release = threading.Event(), threading.Event()
        def current_authority(owner, current_plan):
            self.assertEqual((owner, current_plan), ('alice', plan))
            entered.set()
            self.assertTrue(release.wait(timeout=2))
        factory.store.require_plan_execution.side_effect = current_authority
        async def observe():
            pending = asyncio.create_task(self.api.start('alice', 'plan-original'))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                await asyncio.wait_for(asyncio.sleep(0), timeout=.2)
                factory.bridge.submit.assert_not_awaited()
                factory.store.reserve_task.assert_not_called()
            finally:
                release.set()
            self.assertEqual(await pending, {'id': 'task-original'})
            factory.bridge.submit.assert_awaited_once()
            factory.store.require_plan_execution.assert_called_once_with('alice', plan)
        asyncio.run(observe())
