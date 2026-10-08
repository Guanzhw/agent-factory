"""Explicit same-native-session binding migration; controlled fixtures, no live IO."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine

from agent_factory.personal_agent_transport import PERSONAL_PROVIDER_ID
from agent_factory.store import digest
import test_personal_agent_sessions as opencode_fixture
import test_personal_orx_transport as orx_fixture


class PersonalRebindTests(unittest.TestCase):
    def setUp(self):
        self.fx = opencode_fixture.Sessions('test_real_wire_multiturn_tool_result_unknown_restart_and_interrupt')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.service = self.fx.service

    def created(self):
        return self.fx.create()['session']

    def renewed(self, *, revision=None, capabilities=None):
        fx = self.fx
        current = fx.connections._at()
        fx.connections.clock = lambda: current + timedelta(minutes=16)
        if revision:
            fx.secrets.authorize = lambda **scope: scope == dict(owner='alice', reference='synthetic-reference',
                revision=revision, destination='https://runtime.example.com')
            fx.connections.personal.configure('alice', PERSONAL_PROVIDER_ID,
                {'origin': 'https://runtime.example.com', 'credentialRef': 'synthetic-reference',
                 'credentialRevision': revision, 'projectId': 'native-project'}, 'rotate-config-' + revision,
                reference=fx.registration)
        fx.connections.personal.verify('alice', fx.registration, 'renew-verify-' + str(revision))
        return fx.connections.bind('alice', fx.registration, 'renew-bind-' + str(revision), capabilities=capabilities)

    def preview(self, session, new):
        return self.service.preview_rebind('alice', session['id'], new['ref'], session['connectionPin']['fingerprint'])

    def commit(self, session, new, request='rebind-original'):
        return self.service.rebind('alice', session['id'], new['ref'], request,
            expected_old_fingerprint=session['connectionPin']['fingerprint'], expected_new_fingerprint=new['fingerprint'])

    def test_expiry_and_rotation_rebind_preserves_identity_history_and_old_intents(self):
        session = self.created()
        for revision in (None, 'r2'):
            with self.subTest(revision=revision):
                if revision:
                    session = self.service.inspect('alice', session['id'])
                before = deepcopy(self.service._command('alice', 'create'))
                new = self.renewed(revision=revision)
                count = len([x for x in self.fx.wire if x[0] == 'POST'])
                preview = self.preview(session, new)
                self.assertTrue(preview['canRebind'])
                self.assertEqual(self.service.inspect('alice', session['id'])['connectionRef'], session['connectionRef'])
                result = self.commit(session, new, 'rebind-' + str(revision))
                updated = result['session']
                self.assertIsNone(result['factoryIdentity'])
                for key in ('id', 'nativeProjectId', 'nativeSessionId', 'factoryIdentity', 'namespace'):
                    self.assertEqual(updated[key], session[key])
                self.assertEqual(updated['connectionRef'], new['ref'])
                self.assertEqual(updated['bindingHistory'][-1]['oldConnectionPin'], session['connectionPin'])
                self.assertEqual(updated['bindingHistory'][-1]['newConnectionPin'], new)
                self.assertEqual(self.service._command('alice', 'create'), before)
                self.assertEqual(len([x for x in self.fx.wire if x[0] == 'POST']), count)
                replay = self.commit(session, new, 'rebind-' + str(revision))
                self.assertEqual(replay['result'], result['result'])
                session = updated

    def test_pending_original_result_can_be_read_recovered_without_mutating_old_pin(self):
        session = self.created()
        self.fx.drop = '/session/' + session['nativeSessionId'] + '/prompt_async'
        self.service.prompt('alice', session['id'], 'Original before expiry', 'unknown-original')
        original = deepcopy(self.service._command('alice', 'unknown-original'))
        self.assertEqual(original['state'], 'ack_unknown')
        new = self.renewed(revision='r2')
        posts = len([x for x in self.fx.wire if x[0] == 'POST'])
        preview = self.preview(session, new)
        self.assertTrue(preview['canRebind'])
        recovered = self.service._command('alice', 'unknown-original')
        self.assertEqual(recovered['state'], 'result_observed')
        for key in ('intent', 'fingerprint', 'identity', 'identity_hash'):
            self.assertEqual(original[key], recovered[key])
        self.assertEqual(recovered['result']['observationEvidence']['observedViaConnectionPin'], new)
        self.assertEqual(self.service.inspect('alice', session['id'])['connectionRef'], session['connectionRef'])
        self.commit(session, new)
        self.assertEqual(len([x for x in self.fx.wire if x[0] == 'POST']), posts)

    def test_unfinished_turn_blocks_rebind_without_clearing_pending(self):
        session = self.created()
        self.service.prompt('alice', session['id'], 'Still running', 'running-original')
        self.fx.remote[session['nativeSessionId']].pop()  # Tool completion is not final turn.
        original = deepcopy(self.service._command('alice', 'running-original'))
        new = self.renewed()
        preview = self.preview(session, new)
        self.assertFalse(preview['canRebind'])
        self.assertEqual(preview['blocker'], 'PERSONAL_PREVIOUS_TURN_UNRESOLVED')
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_PREVIOUS_TURN_UNRESOLVED'):
            self.commit(session, new)
        self.assertEqual(self.service._command('alice', 'running-original'), original)
        self.assertEqual(self.service.inspect('alice', session['id'])['activeRequestId'], 'running-original')
        self.assertIsNone(self.service._command('alice', 'rebind-original'))

    def test_owner_caps_stale_pins_and_request_reuse_fail_closed(self):
        self.fx.remote['ses_original'] = []
        narrow = self.fx.connections.bind('alice', self.fx.registration, 'narrow-original',
            capabilities=['project:read', 'session:read'])
        session = self.service.attach('alice', narrow['ref'], 'native-project', 'ses_original', 'attach-narrow')['session']
        new = self.renewed()
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_REBIND_SCOPE_EXPANSION'): self.preview(session, new)
        with self.assertRaises(HTTPException):
            self.service.preview_rebind('bob', session['id'], new['ref'], narrow['fingerprint'])
        restricted = self.fx.connections.bind('alice', self.fx.registration, 'restricted-new',
            capabilities=['project:read', 'session:read'])
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_REBIND_STALE_OLD_PIN'):
            self.service.preview_rebind('alice', session['id'], restricted['ref'], 'wrong-old')
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_REBIND_STALE_NEW_PIN'):
            self.service.rebind('alice', session['id'], restricted['ref'], 'wrong-new',
                expected_old_fingerprint=narrow['fingerprint'], expected_new_fingerprint='wrong-new')
        self.commit(session, restricted)
        with self.assertRaisesRegex(HTTPException, 'IDEMPOTENCY_CONFLICT'):
            self.commit(session, new)
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_REBIND_STALE_OLD_PIN'):
            self.commit(session, restricted, 'different-request-old-pin')

    def test_alternate_origin_and_project_are_denied_before_remote_reads(self):
        session = self.created()
        self.fx.secrets.authorize = lambda **scope: scope['owner'] == 'alice'
        original_get = self.fx.provider.probe.get
        for suffix, destination, project in [('origin', 'https://other.example.com', 'native-project'),
                ('project', 'https://runtime.example.com', 'different-project')]:
            def probe(destination, address, path, lease=None, project=project):
                if lease is not None and path == '/project/current': return 200, {'id': project}
                return original_get(destination, address, path, lease)
            self.fx.provider.probe.get = probe
            remote = self.fx.connections.personal.configure('alice', PERSONAL_PROVIDER_ID,
                {'origin': destination, 'credentialRef': 'synthetic-reference', 'credentialRevision': 'r1',
                 'projectId': project}, 'configure-other-' + suffix)
            self.fx.connections.personal.verify('alice', remote['registrationRef'], 'verify-other-' + suffix)
            other = self.fx.connections.bind('alice', remote['registrationRef'], 'bind-other-' + suffix)
            calls = len(self.fx.wire)
            with self.assertRaisesRegex(HTTPException, 'PERSONAL_REBIND_IDENTITY_MISMATCH'):
                self.preview(session, other)
            self.assertEqual(len(self.fx.wire), calls)

    def test_alternate_native_provider_namespace_cannot_rebind(self):
        session = self.created()
        wire = orx_fixture.NativeOrxWire()
        provider = orx_fixture.PersonalOrxProvider(self.fx.secrets, transport=wire)
        self.fx.connections.personal.providers[orx_fixture.PERSONAL_ORX_PROVIDER_ID] = provider
        remote = self.fx.connections.personal.configure('alice', orx_fixture.PERSONAL_ORX_PROVIDER_ID,
            {'origin': 'https://runtime.example.com', 'credentialRef': 'synthetic-reference',
             'credentialRevision': 'r1', 'projectId': 'native-project', 'authMode': 'bearer'}, 'other-engine')
        self.fx.connections.personal.verify('alice', remote['registrationRef'], 'verify-other-engine')
        new = self.fx.connections.bind('alice', remote['registrationRef'], 'bind-other-engine')
        calls = len(wire.calls)
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_REBIND_IDENTITY_MISMATCH'): self.preview(session, new)
        self.assertEqual(len(wire.calls), calls)

    def test_cas_rejects_concurrent_mapping_change_without_recording_rebind(self):
        session = self.created(); new = self.renewed()
        original = self.service._rebind_target
        calls = [0]
        def racing(*args, **kwargs):
            result = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                row = result[0]; body = {**row['body'], 'concurrentMetadata': 'synthetic-only'}
                with self.fx.engine.begin() as conn:
                    conn.execute(self.service.sessions.update().where(self.service.sessions.c.id == session['id'])
                        .values(body=body, body_hash=digest(body)))
            return result
        self.service._rebind_target = racing
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_REBIND_STALE_MAPPING'): self.commit(session, new)
        self.assertIsNone(self.service._command('alice', 'rebind-original'))
        self.assertEqual(self.service.inspect('alice', session['id'])['connectionRef'], session['connectionRef'])

    def test_rebind_racing_prepared_prompt_cannot_use_superseded_mapping(self):
        session = self.created()
        new = self.fx.connections.bind('alice', self.fx.registration, 'parallel-binding')
        original_admission = self.service.admission
        fired = [False]
        def admission(owner, intent):
            if intent['action'] == 'prompt' and not fired[0]:
                fired[0] = True
                self.commit(session, new)
            return original_admission(owner, intent)
        self.service.admission = admission
        posts = len([x for x in self.fx.wire if x[0] == 'POST'])
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_EXECUTION_MAPPING_CHANGED'):
            self.service.prompt('alice', session['id'], 'Old prepared command', 'old-prompt')
        self.assertIsNone(self.service._command('alice', 'old-prompt'))
        self.assertEqual(len([x for x in self.fx.wire if x[0] == 'POST']), posts)

    def test_rebind_during_final_admission_is_blocked_by_interrupt_intent(self):
        session = self.created()
        new = self.fx.connections.bind('alice', self.fx.registration, 'parallel-binding')
        original_admission = self.service.admission
        calls = [0]
        def admission(owner, intent):
            calls[0] += 1
            if calls[0] == 3: self.commit(session, new)
            return original_admission(owner, intent)
        self.service.admission = admission
        posts = len([x for x in self.fx.wire if x[0] == 'POST'])
        receipt = self.service.interrupt('alice', session['id'], 'old-interrupt')
        self.assertEqual(receipt['state'], 'ack_unknown')
        self.assertEqual(receipt['session']['connectionRef'], session['connectionRef'])
        self.assertIsNone(self.service._command('alice', 'rebind-original'))
        self.assertEqual(len([x for x in self.fx.wire if x[0] == 'POST']), posts)

    def test_interrupt_paused_inside_transport_blocks_rebind_until_http_ack(self):
        session = self.created()
        new = self.fx.connections.bind('alice', self.fx.registration, 'parallel-binding')
        entered, release = Event(), Event()
        self.addCleanup(release.set)
        original = self.fx.provider.transport.request
        results = []
        def paused(destination, address, method, path, lease, payload=None):
            if method == 'POST' and path.endswith('/abort'):
                entered.set()
                if not release.wait(5): raise RuntimeError('Controlled test release missing')
            return original(destination, address, method, path, lease, payload)
        self.fx.provider.transport.request = paused
        thread = Thread(target=lambda: results.append(self.service.interrupt('alice', session['id'], 'paused-interrupt')))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            preview = self.preview(session, new)
            self.assertFalse(preview['canRebind'])
            self.assertIsNone(preview['activeRequestId'])
            self.assertEqual(preview['blocker'], 'PERSONAL_INTERRUPT_ACK_UNKNOWN')
            self.assertEqual(preview['blockers'], [{'requestId': 'paused-interrupt', 'action': 'interrupt',
                'state': 'ack_unknown', 'source': 'durable-command-ledger'}])
            with self.assertRaisesRegex(HTTPException, 'PERSONAL_INTERRUPT_ACK_UNKNOWN'): self.commit(session, new)
            self.assertEqual(self.service.inspect('alice', session['id'])['connectionRef'], session['connectionRef'])
        finally:
            release.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]['state'], 'acknowledged')
        self.assertFalse(results[0]['session']['stopVerified'])
        self.assertTrue(self.preview(session, new)['canRebind'])
        self.assertEqual(self.commit(session, new)['session']['connectionRef'], new['ref'])

    def test_unknown_interrupt_never_clears_from_idle_or_transcript(self):
        session = self.created()
        self.fx.drop = '/session/' + session['nativeSessionId'] + '/abort'
        self.assertEqual(self.service.interrupt('alice', session['id'], 'lost-interrupt')['state'], 'ack_unknown')
        original = deepcopy(self.service._command('alice', 'lost-interrupt'))
        new = self.renewed()
        preview = self.preview(session, new)
        self.assertEqual(preview['blocker'], 'PERSONAL_INTERRUPT_ACK_UNKNOWN')
        with self.assertRaisesRegex(HTTPException, 'PERSONAL_INTERRUPT_ACK_UNKNOWN'): self.commit(session, new)
        self.assertEqual(self.service._command('alice', 'lost-interrupt'), original)
        self.assertFalse(self.service.inspect('alice', session['id'])['stopVerified'])

    def test_pool_one_rebind_does_not_authorize_with_metadata_connection_held(self):
        session = self.created(); new = self.renewed()
        folder = TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'rebind.db'
        target = sqlite3.connect(path); source = self.fx.engine.raw_connection()
        try: source.driver_connection.backup(target)
        finally: source.close(); target.close()
        single = create_engine('sqlite:///' + str(path), pool_size=1, max_overflow=0, pool_timeout=.1)
        self.addCleanup(single.dispose)
        self.fx.connections.store.engine = single
        original = self.service._handle
        def checked(*args, **kwargs):
            self.assertEqual(single.pool.checkedout(), 0)
            return original(*args, **kwargs)
        self.service._handle = checked
        self.assertTrue(self.preview(session, new)['canRebind'])
        self.assertEqual(self.commit(session, new)['session']['connectionRef'], new['ref'])

    def test_orx_known_ack_can_reconcile_but_unknown_and_queued_never_can(self):
        for mode in ('known', 'unknown', 'queued'):
            with self.subTest(mode=mode):
                fx = orx_fixture.PersonalOrxTests('test_true_native_existing_attach_multiturn_tool_transcript_and_interrupt')
                fx.setUp(); self.addCleanup(fx.doCleanups)
                session = fx.attach()['session']
                if mode == 'unknown': fx.wire.drop = '/api/chat/sessions/chat_original/message'
                if mode == 'queued': fx.wire.queued_ack = True
                fx.service.prompt('alice', session['id'], 'Original native context', 'original-' + mode)
                original = deepcopy(fx.service._command('alice', 'original-' + mode))
                at = fx.connections._at(); fx.connections.clock = lambda: at + timedelta(minutes=16)
                fx.connections.personal.verify('alice', fx.bound['registrationRef'], 'renew-native')
                new = fx.connections.bind('alice', fx.bound['registrationRef'], 'renew-native-binding')
                posts = len(fx.posts())
                preview = fx.service.preview_rebind('alice', session['id'], new['ref'], session['connectionPin']['fingerprint'])
                self.assertEqual(preview['canRebind'], mode == 'known')
                if mode == 'known':
                    fx.service.rebind('alice', session['id'], new['ref'], 'native-rebind',
                        expected_old_fingerprint=session['connectionPin']['fingerprint'], expected_new_fingerprint=new['fingerprint'])
                    record = fx.service._command('alice', 'original-known')
                    self.assertEqual(record['result']['observationEvidence']['correlationSource'], 'inferred-transcript-delta')
                    self.assertEqual(record['intent'], original['intent'])
                else:
                    with self.assertRaisesRegex(HTTPException, 'PERSONAL_PREVIOUS_TURN_UNRESOLVED'):
                        fx.service.rebind('alice', session['id'], new['ref'], 'native-rebind',
                            expected_old_fingerprint=session['connectionPin']['fingerprint'], expected_new_fingerprint=new['fingerprint'])
                    self.assertEqual(fx.service._command('alice', 'original-' + mode), original)
                self.assertEqual(len(fx.posts()), posts)
                self.assertNotIn('synthetic-test-password', json.dumps(preview))
