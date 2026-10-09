"""Controlled-clock unchanged-scope renewal; no live services or model calls."""
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.personal_orx_lease import PersonalOrxLease
from agent_factory.personal_orx_transport import PERSONAL_ORX_PROVIDER_ID
import test_personal_orx_transport as native
from agent_factory.personal_command_api import PersonalCommandAPI, PrepareCommand


class LeaseIngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_exact_pre_admission_lease_refusals_are_explicitly_coded(self):
        for code in ('ORX_LEASE_EXPLICIT_SELECTION_REQUIRED', 'REMOTE_CREDENTIAL_UNAVAILABLE'):
            api = Mock()
            api.prepare = Mock(side_effect=HTTPException(409, code))
            api.start = AsyncMock()
            with self.assertRaises(HTTPException) as caught:
                await PersonalCommandAPI.submit(api, 'alice', object())
            self.assertEqual(caught.exception.detail['code'], code)
            api.start.assert_not_called()
        for detail in ('IDEMPOTENCY_CONFLICT', {'code': 'IDEMPOTENCY_CONFLICT'}):
            error = HTTPException(409, detail)
            api.prepare = Mock(side_effect=error)
            with self.assertRaises(HTTPException) as caught:
                await PersonalCommandAPI.submit(api, 'alice', object())
            self.assertIs(caught.exception, error)

    async def test_post_admission_start_error_is_never_reclassified_as_nonexecution(self):
        for code in ('REMOTE_CREDENTIAL_UNAVAILABLE', 'REMOTE_VERIFICATION_FAILED'):
            api = Mock()
            api.prepare = Mock(return_value={'plan': {'id': 'already-admitted-plan'}})
            error = HTTPException(409, code)
            api.start = AsyncMock(side_effect=error)
            with self.assertRaises(HTTPException) as caught:
                await PersonalCommandAPI.submit(api, 'alice', object())
            self.assertIs(caught.exception, error)
            api.start.assert_awaited_once_with('alice', 'already-admitted-plan')

    def test_health_failure_is_coded_only_during_pre_admission_lease_checks(self):
        for action in ('create', 'prompt'):
            api = Mock()
            api.store.sql.return_value = []
            api.store.connections.inspect.return_value = {
                'kind': 'orx', 'available': False, 'ref': 'old-connection', 'fingerprint': 'a' * 64}
            api.sessions.inspect.return_value = {'namespace': 'native-openresearch', 'bindingStatus': 'expired',
                'id': 'original-session', 'connectionPin': {'fingerprint': 'a' * 64}}
            api.leases.refresh.side_effect = HTTPException(409, 'REMOTE_VERIFICATION_FAILED')
            api.leases.continue_session.side_effect = HTTPException(409, 'REMOTE_VERIFICATION_FAILED')
            body = PrepareCommand(requestId='health-refusal-' + action, action=action,
                **({'connectionRef': 'old-connection', 'nativeProjectId': 'native-project'} if action == 'create'
                    else {'sessionId': 'original-session', 'text': 'Preserve original goal'}))
            with self.assertRaises(HTTPException) as caught:
                PersonalCommandAPI.prepare(api, 'alice', body, refresh_lease=True)
            self.assertEqual(caught.exception.detail['code'], 'REMOTE_VERIFICATION_FAILED')
            api.store.admit_plan.assert_not_called()

    def test_same_health_code_after_admission_retains_its_original_error(self):
        api = Mock()
        api.store.sql.return_value = []
        api.store.connections.inspect.return_value = {'kind': 'orx', 'available': True}
        api.sessions.project.return_value = {'nativeProjectId': 'native-project', 'connectionPin': {}}
        error = HTTPException(409, 'REMOTE_VERIFICATION_FAILED')
        api._prepared.side_effect = error
        body = PrepareCommand(requestId='health-after-admission', action='create',
            connectionRef='active-connection', nativeProjectId='native-project')
        with self.assertRaises(HTTPException) as caught:
            PersonalCommandAPI.prepare(api, 'alice', body, refresh_lease=True)
        self.assertIs(caught.exception, error)
        api.store.admit_plan.assert_called_once()


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.fx = native.PersonalOrxTests('test_true_native_existing_attach_multiturn_tool_transcript_and_interrupt')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.connections, self.service = self.fx.connections, self.fx.service
        self.lease = PersonalOrxLease(self.service)
        self.original_time = self.connections._at()
        self.session = self.service.attach('alice', self.fx.bound['ref'], 'native-project', 'chat_original',
            'original-attach')['session']

    def advance(self, minutes=16):
        self.connections.clock = lambda: self.original_time + timedelta(minutes=minutes)

    def refresh(self):
        return self.lease.refresh('alice', self.fx.bound['ref'], self.fx.bound['fingerprint'])

    def posts(self):
        return [x for x in self.fx.wire.calls if x[0] == 'POST']

    def test_unchanged_expiry_health_and_narrow_binding_reuse_without_remote_posts(self):
        old = deepcopy(self.fx.bound)
        self.advance()
        fresh = self.refresh()
        self.assertNotEqual(fresh['ref'], old['ref'])
        self.assertEqual(fresh['capabilities'], old['capabilities'])
        self.assertEqual(fresh['expiresAt'], (self.connections._at() + timedelta(minutes=15)).isoformat())
        self.assertEqual(self.posts(), [])
        calls = len(self.fx.wire.calls)
        self.assertEqual(self.refresh(), fresh)
        self.assertEqual(len(self.fx.wire.calls), calls)
        self.assertEqual(self.fx.bound, old)
        self.assertFalse(self.connections.inspect('alice', old['ref'])['available'])

    def test_expired_continue_preserves_native_session_snapshots_and_recovers_lost_response(self):
        original = deepcopy(self.service._command('alice', 'original-attach'))
        self.advance()
        continued = self.lease.continue_session('alice', self.session['id'], self.session['connectionPin']['fingerprint'])
        self.assertEqual(continued['state'], 'ready')
        current = continued['session']
        for key in ('id', 'namespace', 'nativeProjectId', 'nativeSessionId', 'factoryIdentity'):
            self.assertEqual(current[key], self.session[key])
        self.assertEqual(self.service._command('alice', 'original-attach'), original)
        self.assertEqual(len(current['bindingHistory']), 1)
        replay = self.lease.continue_session('alice', self.session['id'], self.session['connectionPin']['fingerprint'])
        self.assertEqual(replay, continued)
        self.assertEqual(self.posts(), [])
        self.advance(32)
        again = self.lease.continue_session('alice', current['id'], current['connectionPin']['fingerprint'])
        self.assertEqual(again['state'], 'ready')
        self.assertEqual(len(again['session']['bindingHistory']), 2)
        self.assertEqual(again['session']['nativeSessionId'], 'chat_original')
        self.assertEqual(self.service._command('alice', 'original-attach'), original)
        self.assertEqual(self.posts(), [])

    def test_old_selected_connection_follows_only_its_proven_local_renewal_chain(self):
        self.advance(); first = self.refresh()
        self.advance(32); second = self.refresh()
        self.assertNotEqual(first['ref'], second['ref'])
        self.assertEqual(second['capabilities'], self.fx.bound['capabilities'])
        self.assertEqual(self.posts(), [])

    def test_narrow_original_scope_never_gains_provider_capabilities(self):
        narrowed = self.connections.bind('alice', self.fx.bound['registrationRef'], 'narrowed',
            capabilities=['project:read', 'session:read'])
        self.advance()
        renewed = self.lease.refresh('alice', narrowed['ref'], narrowed['fingerprint'])
        self.assertEqual(renewed['capabilities'], ['project:read', 'session:read'])
        self.assertEqual(self.posts(), [])

    def test_owner_grant_revoke_and_stale_fingerprint_fail_before_probe(self):
        self.advance()
        count = len(self.fx.wire.calls)
        with self.assertRaises(HTTPException):
            self.lease.refresh('bob', self.fx.bound['ref'], self.fx.bound['fingerprint'])
        with self.assertRaises(HTTPException):
            self.lease.refresh('alice', self.fx.bound['ref'], '0' * 64)
        original_require = self.fx.auth.require
        def denied(owner, action):
            if action == 'run': raise HTTPException(403, 'grant revoked')
            return original_require(owner, action)
        self.fx.auth.require = denied
        with self.assertRaises(HTTPException): self.refresh()
        self.fx.auth.require = original_require
        self.connections.revoke('alice', self.fx.bound['ref'], 'revoke-original')
        with self.assertRaises(HTTPException): self.refresh()
        self.assertEqual(len(self.fx.wire.calls), count)

    def test_rotation_target_policy_capability_change_requires_explicit_choice(self):
        self.advance()
        count = len(self.fx.wire.calls)
        self.fx.secrets.authorize = lambda **scope: False
        with self.assertRaises(HTTPException): self.refresh()
        self.fx.secrets.authorize = lambda **scope: True
        old_policy = self.fx.provider.policy_revision
        self.fx.provider.policy_revision = 'changed-policy'
        with self.assertRaises(HTTPException): self.refresh()
        self.fx.provider.policy_revision = old_policy
        old_caps = self.fx.provider.effective_capabilities
        self.fx.provider.effective_capabilities = lambda config: old_caps(config) - {'session:interrupt'}
        with self.assertRaises(HTTPException): self.refresh()
        self.fx.provider.effective_capabilities = old_caps
        for key, value in [('credentialRevision', 'r2'), ('projectId', 'other-project'), ('origin', 'https://other.example.com')]:
            self.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID, {**self.fx.config, key: value},
                'reconfigure-' + key, reference=self.fx.bound['registrationRef'])
            with self.assertRaises(HTTPException): self.refresh()
        self.assertEqual(len(self.fx.wire.calls), count)
        self.assertEqual(self.service.inspect('alice', self.session['id'])['connectionPin'], self.session['connectionPin'])

    def test_resource_revoke_and_reverification_without_original_proof_are_not_renewed(self):
        self.advance()
        self.connections.personal.verify('alice', self.fx.bound['registrationRef'], 'explicit-new-proof')
        count = len(self.fx.wire.calls)
        with self.assertRaises(HTTPException): self.refresh()
        self.connections.personal.revoke('alice', self.fx.bound['registrationRef'], 'revoke-resource')
        with self.assertRaises(HTTPException): self.refresh()
        self.assertEqual(len(self.fx.wire.calls), count)

    def test_config_race_during_health_never_binds_changed_configuration(self):
        self.advance()
        def rotate():
            self.fx.wire.before_address = None
            self.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID,
                {**self.fx.config, 'credentialRevision': 'r2'}, 'rotate-during-probe',
                reference=self.fx.bound['registrationRef'])
        self.fx.wire.before_address = rotate
        with self.assertRaises(HTTPException): self.refresh()
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.service.inspect('alice', self.session['id'])['connectionPin'], self.session['connectionPin'])

    def test_same_url_with_changed_upstream_instance_does_not_refresh_authority(self):
        self.advance()
        verify = self.fx.provider.verify
        self.fx.provider.verify = lambda owner, config: {**verify(owner, config), 'instanceId': 'different-instance'}
        with self.assertRaisesRegex(HTTPException, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED'): self.refresh()
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.service.inspect('alice', self.session['id'])['connectionPin'], self.session['connectionPin'])

    def test_checked_proof_rollover_before_bind_cannot_create_a_binding_for_new_identity(self):
        self.advance()
        with self.connections._read() as conn:
            before = list(conn.execute(select(self.connections.references.c.ref)).scalars())
        original = deepcopy(self.service._command('alice', 'original-attach'))
        bind, verify = self.connections.bind, self.fx.provider.verify
        def swap_before_bind(*args, **kwargs):
            self.assertIsNotNone(kwargs['expected_trusted_revision'])
            self.assertEqual(len(kwargs['expected_trusted_fingerprint']), 64)
            self.fx.provider.verify = lambda owner, config: {**verify(owner, config), 'instanceId': 'replacement-instance'}
            self.connections.personal.verify('alice', self.fx.bound['registrationRef'], 'verify-between-proof-and-bind')
            return bind(*args, **kwargs)
        self.connections.bind = swap_before_bind
        with self.assertRaisesRegex(HTTPException, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED'):
            self.refresh()
        with self.connections._read() as conn:
            self.assertEqual(list(conn.execute(select(self.connections.references.c.ref)).scalars()), before)
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.service._command('alice', 'original-attach'), original)
        self.assertEqual(self.service.inspect('alice', self.session['id'])['connectionPin'], self.session['connectionPin'])

    def test_identity_rollover_after_bind_is_denied_before_refresh_receipt_commit(self):
        self.advance()
        bind, verify = self.connections.bind, self.fx.provider.verify
        def swap_after_bind(*args, **kwargs):
            candidate = bind(*args, **kwargs)
            self.fx.provider.verify = lambda owner, config: {**verify(owner, config), 'instanceId': 'replacement-instance'}
            self.connections.personal.verify('alice', self.fx.bound['registrationRef'], 'verify-between-bind-and-refresh-commit')
            return candidate
        self.connections.bind = swap_after_bind
        with self.assertRaisesRegex(HTTPException, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED'):
            self.refresh()
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.service.inspect('alice', self.session['id'])['connectionPin'], self.session['connectionPin'])
        with self.connections._read() as conn:
            row = conn.execute(select(self.connections.commands).where(
                self.connections.commands.c.action == 'orx.lease-refresh')).mappings().one()
            self.assertEqual(row['result_ref'], self.fx.bound['ref'])

    def test_lost_local_bind_response_does_not_replay_research_or_destroy_old_evidence(self):
        self.advance()
        original_bind = self.connections.bind
        def lost(*args, **kwargs):
            original_bind(*args, **kwargs)
            raise RuntimeError('controlled local response loss')
        self.connections.bind = lost
        with self.assertRaises(RuntimeError): self.refresh()
        self.connections.bind = original_bind
        result = self.refresh()
        self.assertTrue(result['available'])
        self.assertEqual(self.posts(), [])
        self.assertEqual(self.service.inspect('alice', self.session['id'])['connectionPin'], self.session['connectionPin'])

    def test_failed_health_retries_only_proven_same_scope_without_configuration_steps(self):
        self.advance()
        verify = self.fx.provider.verify
        self.fx.provider.verify = lambda *_: (_ for _ in ()).throw(RuntimeError('temporary health failure'))
        with self.assertRaises(HTTPException): self.refresh()
        self.fx.provider.verify = verify
        result = self.refresh()
        self.assertTrue(result['available'])
        self.assertEqual(self.posts(), [])

    def test_unknown_native_prompt_and_interrupt_keep_original_intents_and_pin(self):
        sid = self.session['id']
        self.fx.wire.drop = '/api/chat/sessions/chat_original/message'
        result = self.service.prompt('alice', sid, 'Original only once', 'original-unknown')
        self.assertEqual(result['state'], 'ack_unknown')
        original = deepcopy(self.service._command('alice', 'original-unknown'))
        posts = deepcopy(self.posts()); self.advance()
        continued = self.lease.continue_session('alice', sid, self.session['connectionPin']['fingerprint'])
        self.assertEqual(continued['state'], 'waiting')
        self.assertEqual(continued['session']['connectionRef'], self.session['connectionRef'])
        self.assertEqual(self.service._command('alice', 'original-unknown'), original)
        self.assertEqual(self.posts(), posts)

    def test_unknown_interrupt_durable_fence_blocks_even_with_no_active_prompt(self):
        sid = self.session['id']
        self.fx.wire.drop = '/api/chat/sessions/chat_original/interrupt'
        self.service.interrupt('alice', sid, 'lost-original-interrupt')
        original = deepcopy(self.service._command('alice', 'lost-original-interrupt'))
        posts = deepcopy(self.posts()); self.advance()
        continued = self.lease.continue_session('alice', sid, self.session['connectionPin']['fingerprint'])
        self.assertEqual(continued['state'], 'waiting')
        self.assertEqual(continued['blocker'], 'PERSONAL_INTERRUPT_ACK_UNKNOWN')
        self.assertEqual(continued['session']['connectionRef'], self.session['connectionRef'])
        self.assertEqual(self.service._command('alice', 'lost-original-interrupt'), original)
        self.assertEqual(self.posts(), posts)
