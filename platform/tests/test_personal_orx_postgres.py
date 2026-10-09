"""Required first-app control path: native queue + PG + controlled ORX wire.

The peer is a native-ORX-shaped fixture, never a live server/model, binary
compatibility proof or scientific result. Original native IDs and tool transcripts
remain distinct from the real Factory plan/task/run admission identities.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.personal_agent_sessions import PersonalAgentSessions
from agent_factory.personal_command_api import deny_direct_admission
from agent_factory.personal_command_profile import publish_application
from agent_factory.personal_orx_transport import PERSONAL_ORX_PROVIDER_ID
from pg_fixture import IsolatedPostgres
import test_personal_orx_transport as native_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL; required CI rejects skips')
class PersonalOrxPostgresTests(unittest.TestCase):
    def test_native_orx_attach_governed_multiturn_interrupt_and_unknown_restart(self):
        fixture = native_fixture.PersonalOrxTests('test_true_native_existing_attach_multiturn_tool_transcript_and_interrupt')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, TemporaryDirectory() as folder:
            settings = Settings(db_url=database.url, workspace=Path(folder), max_workers=1,
                personal_agent_commands_enabled=True, temporary_policy='admin-review',
                policy_revision='native-orx-personal-ci-v1', material_policy_revision='native-orx-personal-ci-v1',
                personal_connection_providers={PERSONAL_ORX_PROVIDER_ID: fixture.provider})
            app = create_app(settings)
            state = app.app.state.factory; store, auth = state['store'], state['auth']
            self.addCleanup(store.engine.dispose); self.addCleanup(store.native_db.db_engine.dispose)
            auth.directory.upsert('orx-personal-reviewer', name='Controlled ORX reviewer')
            auth.authorization.assign('orx-personal-reviewer', 'factory-manager')
            publish_application(state, author='manager', reviewer='orx-personal-reviewer')
            remote = store.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID,
                fixture.config, 'native-orx-configure')
            store.connections.personal.verify('alice', remote['registrationRef'], 'native-orx-verify')
            bound = store.connections.bind('alice', remote['registrationRef'], 'native-orx-bind')
            with TestClient(app) as client:
                def request(method, path, body=None, owner='alice', expected=200):
                    response = client.request(method, '/api/factory' + path, json=body,
                        headers={'Authorization': 'Bearer ' + auth._issue_native_token(owner)})
                    self.assertEqual(response.status_code, expected, response.text)
                    return response.json()
                intents = {}
                def prepare(action, **values):
                    key = 'orx-native-' + uuid4().hex
                    body = {'requestId': key, 'action': action, **values}
                    intents[key] = body
                    task = request('POST', '/personal-agent/commands/submit', body, expected=202)
                    prepared = request('GET', '/personal-agent/commands/requests/' + key)
                    plan = prepared['plan']; self.assertEqual(plan['status'], 'ready', plan)
                    self.assertFalse(prepared['authorization']['reviewRequired'])
                    self.assertTrue(prepared['authorization']['ownerSubmissionSupported'])
                    self.assertEqual(task['planId'], plan['id'])
                    return key, task
                def until(task, status):
                    end = time.monotonic() + 30
                    last = None
                    while time.monotonic() < end:
                        last = request('GET', '/jobs/' + task['id'])['job']
                        if last['status'] == status: return last
                        if last['status'] == 'failed': self.fail(str(last))
                        time.sleep(.05)
                    self.fail('Native ORX command failed to reach ' + status + ': ' + str(last))
                choices = request('GET', '/personal-agent/native-sessions?connectionRef=' + bound['ref'])
                self.assertEqual(choices['namespace'], 'native-openresearch')
                self.assertEqual(choices['sessions'][0]['nativeSessionId'], 'chat_original')
                capabilities = request('GET', '/personal-agent/capabilities')
                self.assertEqual(capabilities['modelConfiguration'], 'remote-configured-model')
                self.assertFalse(capabilities['factoryBYOKForwarded'])
                # A trusted/shared registration does not become an owner-owned
                # registration simply because it grants this owner a handle.
                with store.connections._read() as conn:
                    shared = store.connections.personal.binding(conn, 'alice', remote['registrationRef'])
                shared = replace(shared, opaque_handle=store.connections.resolve('alice', bound['ref'], 'orx'))
                store.connections.trusted_bindings['shared-orx-fixture'] = shared
                with store.engine.begin() as conn:
                    store.connections._register(conn, 'shared-orx-fixture', shared)
                shared_bound = store.connections.bind('alice', 'shared-orx-fixture', 'bind-shared-orx-fixture')
                shared_body = {'requestId': 'shared-orx-create', 'action': 'create',
                    'connectionRef': shared_bound['ref'], 'nativeProjectId': 'native-project'}
                shared_plan = request('POST', '/personal-agent/commands/prepare', shared_body)
                self.assertTrue(shared_plan['authorization']['reviewRequired'])
                self.assertFalse(shared_plan['authorization']['ownerSubmissionSupported'])
                shared_posts = len(fixture.posts())
                request('POST', '/personal-agent/commands/submit', shared_body, expected=409)
                self.assertEqual(len(fixture.posts()), shared_posts)
                count = len(fixture.posts())
                attached = request('POST', '/personal-agent/sessions/attach', {
                    'connectionRef': bound['ref'], 'nativeProjectId': 'native-project',
                    'nativeSessionId': 'chat_original', 'requestId': 'attach-existing-native-orx'})
                sid = attached['session']['id']
                self.assertEqual(attached['session']['upstreamOrxProjectId'], 'native-project')
                self.assertEqual(len(fixture.posts()), count)  # Read-only native attachment.
                request('GET', '/personal-agent/sessions/' + sid, owner='bob', expected=404)
                request('POST', '/personal-agent/commands/submit', {
                    'requestId': 'foreign-orx-submit', 'action': 'prompt', 'sessionId': sid, 'text': 'Forbidden'},
                    owner='bob', expected=404)
                first_key, first_task = prepare('prompt', sessionId=sid, text='Use the original native research tools')
                until(first_task, 'completed')
                first = request('GET', '/personal-agent/requests/' + first_key)
                same = request('POST', '/personal-agent/commands/submit', intents[first_key], expected=202)
                self.assertEqual(same['id'], first_task['id'])
                request('POST', '/personal-agent/commands/submit', {**intents[first_key], 'text': 'Changed intent'}, expected=409)
                self.assertEqual(first['factoryIdentity']['taskId'], first_task['id'])
                self.assertEqual(first['result']['nativeTurnId'], 'turn_native_1')
                self.assertIsNone(first['result']['nativeMessageId'])
                observed = request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
                self.assertEqual(observed['namespace'], 'native-openresearch')
                self.assertEqual(observed['observation']['correlationSource'], 'inferred-transcript-delta')
                self.assertFalse(observed['observation']['exactTurnVerified'])
                self.assertFalse(observed['observation']['trustedMetering'])
                self.assertEqual(observed['observation']['messages'][-1]['events'][0]['tool'], 'owner-tool')
                self.assertEqual(observed['observation']['messages'][-1]['events'][-1]['text'], 'Native answer 1')
                self.assertEqual(observed['nativeSessionId'], 'chat_original')
                second_key, second_task = prepare('prompt', sessionId=sid, text='Continue that original project and transcript')
                until(second_task, 'completed')
                request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
                self.assertEqual(fixture.wire.prompts, 2)
                self.assertEqual(len(fixture.wire.rows), 1)  # No replacement session/project.
                # Connection verification expiry and then explicit credential
                # rotation require deliberate metadata rebind, not a new native
                # session or silent rewriting of original approved commands.
                original_plans = {task['planId']: deepcopy(store.plan(task['planId'], 'alice'))
                                  for task in (first_task, second_task)}
                original_commands = {key: store.sql('''SELECT intent,fingerprint,identity,identity_hash
                    FROM af_personal_agent_commands WHERE owner_id=:owner AND request_id=:request''',
                    owner='alice', request=key)[0] for key in (first_key, second_key)}
                native_history = deepcopy(fixture.wire.messages['chat_original'])
                current = request('GET', '/personal-agent/sessions/' + sid)
                for index, credential_revision in enumerate((None, 'r2'), start=1):
                    old_pin = deepcopy(current['connectionPin'])
                    at = store.connections._at()
                    store.connections.clock = lambda at=at: at + timedelta(minutes=16)
                    request('GET', '/personal-agent/sessions/' + sid + '?refresh=true', expected=409)
                    count_before_rebind = len(fixture.posts())
                    if credential_revision is not None:
                        fixture.secrets.authorize = lambda **scope: scope == {
                            'owner': 'alice', 'reference': 'synthetic-reference', 'revision': 'r2',
                            'destination': 'https://runtime.example.com'}
                        store.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID,
                            {**fixture.config, 'credentialRevision': credential_revision},
                            'native-orx-rotate-config', reference=remote['registrationRef'])
                    store.connections.personal.verify('alice', remote['registrationRef'],
                        'native-orx-renew-verify-' + str(index))
                    renewed = store.connections.bind('alice', remote['registrationRef'],
                        'native-orx-renew-bind-' + str(index))
                    self.assertNotEqual(renewed['fingerprint'], old_pin['fingerprint'])
                    preview = request('GET', '/personal-agent/sessions/' + sid + '/rebind-preview?connectionRef='
                        + renewed['ref'] + '&expectedOldFingerprint=' + old_pin['fingerprint'])
                    self.assertTrue(preview['canRebind'])
                    self.assertIsNone(preview['activeRequestId'])
                    self.assertEqual(preview['oldConnectionPin'], old_pin)
                    self.assertEqual(request('GET', '/personal-agent/sessions/' + sid)['connectionPin'], old_pin)
                    rebind_body = {'requestId': 'native-orx-explicit-rebind-' + str(index),
                        'connectionRef': renewed['ref'], 'expectedOldFingerprint': old_pin['fingerprint'],
                        'expectedNewFingerprint': renewed['fingerprint']}
                    receipt = request('POST', '/personal-agent/sessions/' + sid + '/rebind', rebind_body)
                    current = receipt['session']
                    self.assertIsNone(receipt['factoryIdentity'])
                    self.assertEqual(receipt['result']['status'], 'rebound')
                    self.assertEqual(current['id'], sid)
                    self.assertEqual(current['nativeProjectId'], 'native-project')
                    self.assertEqual(current['nativeSessionId'], 'chat_original')
                    self.assertEqual(current['namespace'], 'native-openresearch')
                    self.assertEqual(current['connectionPin'], renewed)
                    self.assertEqual(len(current['bindingHistory']), index)
                    self.assertEqual(current['bindingHistory'][-1]['oldConnectionPin'], old_pin)
                    self.assertEqual(current['bindingHistory'][-1]['newConnectionPin'], renewed)
                    replay = request('POST', '/personal-agent/sessions/' + sid + '/rebind', rebind_body)
                    self.assertEqual(replay['result'], receipt['result'])
                    self.assertEqual(len(replay['session']['bindingHistory']), index)
                    self.assertEqual(len(fixture.posts()), count_before_rebind)
                    self.assertEqual(fixture.wire.messages['chat_original'], native_history)
                    for plan_id, original in original_plans.items():
                        self.assertEqual(store.plan(plan_id, 'alice'), original)
                    for key, original in original_commands.items():
                        self.assertEqual(store.sql('''SELECT intent,fingerprint,identity,identity_hash
                            FROM af_personal_agent_commands WHERE owner_id=:owner AND request_id=:request''',
                            owner='alice', request=key)[0], original)
                final_pin = deepcopy(current['connectionPin'])
                # Do not renew again while an unknown turn is outstanding.
                fixture.wire.drop = '/api/chat/sessions/chat_original/message'
                lost_key, lost_task = prepare('prompt', sessionId=sid, text='One uncertain original turn')
                until(lost_task, 'unknown')
                self.assertEqual(json.loads(store.plan(lost_task['planId'], 'alice')['inputValues']['connectionPin']), final_pin)
                count = len(fixture.posts())
                recovered = request('GET', '/personal-agent/commands/requests/' + lost_key)
                self.assertEqual(recovered['receipt']['state'], 'ack_unknown')
                self.assertEqual(recovered['job']['id'], lost_task['id'])
                same = request('POST', '/personal-agent/commands/submit', intents[lost_key], expected=202)
                self.assertEqual(same['id'], lost_task['id'])
                restarted = PersonalAgentSessions(store.connections, admission=deny_direct_admission)
                original = restarted.inspect('alice', sid, refresh=True)
                self.assertEqual(original['activeRequestId'], lost_key)
                self.assertEqual(original['connectionPin'], final_pin)
                self.assertEqual(len(original['bindingHistory']), 2)
                self.assertEqual(restarted.request_result('alice', lost_key)['state'], 'ack_unknown')
                request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
                until(lost_task, 'unknown')  # Similar result does not recover an ORX unknown ACK.
                self.assertEqual(len(fixture.posts()), count)
                interrupt_key, interrupt_task = prepare('interrupt', sessionId=sid)
                until(interrupt_task, 'completed')
                self.assertEqual(json.loads(store.plan(interrupt_task['planId'], 'alice')['inputValues']['connectionPin']), final_pin)
                interrupted = request('GET', '/personal-agent/requests/' + interrupt_key)
                self.assertFalse(interrupted['session']['stopVerified'])
                self.assertEqual(interrupted['session']['nativeSessionId'], 'chat_original')
                self.assertEqual(store.sql('SELECT COUNT(*) AS n FROM af_leases')[0]['n'], 0)
                self.assertEqual(fixture.wire.prompts, 3)
                self.assertEqual(store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
                for task in (first_task, second_task, lost_task, interrupt_task):
                    native_task = store.task(task['id'], 'alice')
                    self.assertTrue(native_task['run_id'])
                    self.assertIsNotNone(store.native_db.get_job(native_task['run_id'], strict=True))
                    self.assertIsNone(store.usage_ledger)
