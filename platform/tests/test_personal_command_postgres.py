"""Native Agno queue/tool + real local HTTP wire; no live model or stop claim."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.personal_agent_transport import PERSONAL_PROVIDER_ID
from agent_factory.personal_command_profile import publish_application
from pg_fixture import IsolatedPostgres
import test_personal_agent_sessions as wire_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL; required CI runner rejects skips')
class PersonalCommandPostgresTests(unittest.TestCase):
    def test_native_queue_review_exact_remote_command_and_uncertain_ack(self):
        wire = wire_fixture.Sessions('test_real_wire_multiturn_tool_result_unknown_restart_and_interrupt')
        wire.setUp(); self.addCleanup(wire.doCleanups)
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, TemporaryDirectory() as folder:
            settings = Settings(db_url=database.url, workspace=Path(folder), max_workers=1,
                personal_agent_commands_enabled=True, temporary_policy='admin-review',
                policy_revision='personal-command-ci-v1', material_policy_revision='personal-command-ci-v1',
                personal_connection_providers={PERSONAL_PROVIDER_ID: wire.provider})
            app = create_app(settings)
            state = app.app.state.factory; store, auth = state['store'], state['auth']
            self.addCleanup(store.engine.dispose); self.addCleanup(store.native_db.db_engine.dispose)
            auth.directory.upsert('personal-reviewer', name='Synthetic personal reviewer')
            auth.authorization.assign('personal-reviewer', 'factory-manager')
            publish_application(state, author='manager', reviewer='personal-reviewer')
            connections = store.connections
            remote = connections.personal.configure('alice', PERSONAL_PROVIDER_ID,
                {'origin': 'https://runtime.example.com', 'credentialRef': 'synthetic-reference',
                 'credentialRevision': 'r1', 'projectId': 'native-project'}, 'personal-native-config')
            connections.personal.verify('alice', remote['registrationRef'], 'personal-native-verify')
            bound = connections.bind('alice', remote['registrationRef'], 'personal-native-bind')
            with TestClient(app) as client:
                def request(method, path, body=None, owner='alice', expected=200):
                    result = client.request(method, '/api/factory' + path, json=body,
                        headers={'Authorization': 'Bearer ' + auth._issue_native_token(owner)})
                    self.assertEqual(result.status_code, expected, result.text)
                    return result.json()
                def prepare(action, **values):
                    key = 'personal-' + uuid4().hex
                    result = request('POST', '/personal-agent/commands/prepare',
                        {'requestId': key, 'action': action, **values})
                    plan = result['plan']; self.assertEqual(plan['status'], 'ready', plan)
                    self.assertFalse(result['authorization']['reviewRequired'])
                    self.assertTrue(result['authorization']['ownerSubmissionSupported'])
                    # Starting this exact owner command is its business approval.
                    task = request('POST', '/personal-agent/commands/start', {'planId': plan['id']})
                    return key, task
                def terminal(task, status):
                    deadline = time.monotonic() + 25
                    while time.monotonic() < deadline:
                        value = request('GET', '/jobs/' + task['id'])['job']
                        if value['status'] == status: return value
                        if value['status'] == 'failed': self.fail(str(value))
                        time.sleep(.05)
                    self.fail('Native personal command did not reach ' + status + ': ' + str(value))
                create_key, create_task = prepare('create', connectionRef=bound['ref'], nativeProjectId='native-project')
                terminal(create_task, 'completed')
                receipt = request('GET', '/personal-agent/requests/' + create_key)
                sid, native = receipt['session']['id'], receipt['session']['nativeSessionId']
                self.assertEqual(receipt['factoryIdentity']['taskId'], create_task['id'])
                self.assertEqual(native, 'ses_1')
                first_key, first_task = prepare('prompt', sessionId=sid, text='Native exact approved first turn')
                terminal(first_task, 'completed')
                observed = request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
                self.assertEqual(observed['observation']['messages'][1]['usage']['cost'], .007)
                self.assertFalse(observed['observation']['trustedMetering'])
                wire.drop = '/session/' + native + '/prompt_async'
                lost_key, lost_task = prepare('prompt', sessionId=sid, text='Native second turn lost acknowledgement')
                terminal(lost_task, 'unknown')
                before = len([row for row in wire.wire if row[0] == 'POST'])
                recovered = request('GET', '/personal-agent/commands/requests/' + lost_key)
                self.assertEqual(recovered['job']['id'], lost_task['id'])
                self.assertEqual(recovered['receipt']['state'], 'ack_unknown')
                same = request('POST', '/personal-agent/commands/start', {'planId': lost_task['planId']})
                self.assertEqual(same['id'], lost_task['id'])
                self.assertEqual(before, len([row for row in wire.wire if row[0] == 'POST']))
                # GET observation of the exact original message settles only its
                # original native command, never resubmits or proves remote stop.
                request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
                terminal(lost_task, 'completed')
                recovered = request('GET', '/personal-agent/commands/requests/' + lost_key)
                self.assertEqual(recovered['receipt']['state'], 'result_observed')
                self.assertEqual(recovered['nativeRunId'], recovered['receipt']['factoryIdentity']['nativeRunId'])
                self.assertEqual(before, len([row for row in wire.wire if row[0] == 'POST']))
                interrupt_key, interrupt_task = prepare('interrupt', sessionId=sid)
                terminal(interrupt_task, 'completed')
                interrupted = request('GET', '/personal-agent/requests/' + interrupt_key)
                self.assertFalse(interrupted['session']['stopVerified'])
                self.assertEqual(interrupted['session']['nativeSessionId'], native)
                self.assertEqual(store.sql('SELECT COUNT(*) AS n FROM af_leases')[0]['n'], 0)
                self.assertIsNone(store.usage_ledger)
                self.assertEqual(store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
