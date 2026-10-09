"""Required real-PG/native-queue creation boundaries with a controlled ORX peer.

No real endpoint, clone or provider inference. CI rejects every skipped case.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.personal_command_profile import publish_application, PROJECT_APPLICATION_ID
from agent_factory.personal_orx_projects import PersonalOrxProjects
from agent_factory.personal_command_api import deny_direct_admission
from agent_factory.personal_orx_transport import PERSONAL_ORX_PROVIDER_ID
from pg_fixture import IsolatedPostgres
import test_personal_orx_projects as project_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL; required CI rejects skips')
class OrxProjectPostgresTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        fixture = project_fixture.ProjectTests('test_preview_consent_sync_false_and_existing_session_research_chain')
        fixture.setUp()
        try:
            with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, TemporaryDirectory() as folder:
                app = create_app(Settings(db_url=database.url, workspace=Path(folder), max_workers=1,
                    personal_agent_commands_enabled=True, temporary_policy='admin-review',
                    policy_revision='project-create-ci-v1', material_policy_revision='project-create-ci-v1',
                    personal_connection_providers={PERSONAL_ORX_PROVIDER_ID: fixture.fx.provider}))
                state = app.app.state.factory; self.store, self.auth = state['store'], state['auth']
                self.auth.directory.upsert('project-reviewer', name='Synthetic project reviewer')
                self.auth.authorization.assign('project-reviewer', 'factory-manager')
                publish_application(state, author='manager', reviewer='project-reviewer')
                publish_application(state, author='manager', reviewer='project-reviewer', project_creation=True)
                remote = self.store.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID,
                    fixture.config, 'project-native-config')
                self.store.connections.personal.verify('alice', remote['registrationRef'], 'project-native-verify')
                self.bound = self.store.connections.bind('alice', remote['registrationRef'], 'project-native-bind')
                self.wire = fixture.wire
                try:
                    with TestClient(app) as self.client: yield fixture
                finally:
                    self.store.engine.dispose(); self.store.native_db.db_engine.dispose()
        finally:
            fixture.doCleanups()

    def request(self, method, path, body=None, *, owner='alice', expected=200):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner)})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def test_personal_orx_registration_uses_shared_contract_without_remote_probe(self):
        with self.fixture():
            before = list(self.wire.calls)
            rows = self.request('GET', '/user-connections/registrations')
            row = next(item for item in rows if item['registrationRef'] == self.bound['registrationRef'])
            self.assertEqual(row['status'], 'available')
            self.assertTrue(row['available'])
            self.assertEqual(row['kind'], 'orx')
            self.assertEqual(row['allowedActions'], ['inspect', 'bind'])
            self.assertEqual(set(row), {'registrationRef', 'kind', 'revision', 'capabilities', 'expiresAt', 'status', 'available', 'allowedActions'})
            self.assertEqual(self.wire.calls, before)
            self.assertEqual(self.request('GET', '/user-connections/registrations', owner='bob'), [])

    def prepare(self, values):
        key = 'project-' + uuid4().hex
        result = self.request('POST', '/personal-agent/project-commands/prepare', {
            'requestId': key, 'connectionRef': self.bound['ref'], 'project': values})
        self.assertEqual(result['plan']['status'], 'ready', result['plan'])
        self.assertFalse(result['authorization']['reviewRequired'])
        self.assertTrue(result['authorization']['ownerSubmissionSupported'])
        self.assertEqual(self.wire.creation_posts, 0)
        return key, result

    def review(self, plan):
        review = self.request('POST', '/plan-reviews', {'planId': plan['id'], 'requestId': uuid4().hex}, expected=201)
        original = self.store.plan(plan['id'], 'alice')
        project = review['planSummary'].get('projectCreation')
        if original.get('application') == PROJECT_APPLICATION_ID: self.assertIsNotNone(project)
        if project is not None:
            bundle = json.loads(original['inputValues']['text'])
            self.assertEqual(project['project']['name'], bundle['request']['name'])
            self.assertEqual(project['project']['path'], bundle['request']['path'])
            self.assertEqual(project['project']['source'], 'clone')
            self.assertEqual(project['project']['cloneUrl'], bundle['request']['cloneUrl'])
            self.assertEqual(project['effects'], bundle['disclosure'])
            self.assertEqual(project['previewHash'], bundle['previewHash'])
            self.assertNotIn('usageBudget', original)
            self.assertIsNone(review['planSummary']['usageBudget'])
            self.assertEqual(project['billing']['remoteCostStatus'], 'unknown')
            self.assertEqual(project['billing']['controllerLedgerScope'], 'local-controller-only')
            self.assertFalse(project['billing']['remoteCostIncludedInUsageBudget'])
            self.assertNotIn('synthetic-test-password', json.dumps(review))
            self.assertNotIn('credentialRef', json.dumps(project))
            inspected = self.request('GET', '/plan-reviews/' + review['id'], owner='manager')
            listed = self.request('GET', '/plan-reviews?allOwners=true', owner='manager')
            self.assertEqual(inspected['planSummary']['projectCreation'], project)
            self.assertEqual(next(r for r in listed if r['id'] == review['id'])['planSummary']['projectCreation'], project)
            self.request('GET', '/plan-reviews/' + review['id'], owner='bob', expected=404)
        saved = self.request('POST', '/plan-reviews/' + review['id'] + '/decision',
            {'approved': True, 'requestId': uuid4().hex}, owner='manager')
        if project is not None: self.assertEqual(saved['planSummary']['projectCreation'], project)

    def approve(self, key, result):
        return self.request('POST', '/personal-agent/project-commands/' + key + '/decision',
            {'previewHash': result['receipt']['preview']['previewHash'], 'approved': True})

    def until(self, task, status):
        end = time.monotonic() + 30
        while time.monotonic() < end:
            last = self.request('GET', '/jobs/' + task['id'])['job']
            if last['status'] == status: return last
            if last['status'] == 'failed': self.fail(str(last))
            time.sleep(.05)
        self.fail('Native project command did not reach ' + status + ': ' + str(last))

    def session_command(self, action, **values):
        key = 'session-' + uuid4().hex
        task = self.request('POST', '/personal-agent/commands/submit',
            {'requestId': key, 'action': action, **values}, expected=202)
        self.until(task, 'completed')
        return self.request('GET', '/personal-agent/requests/' + key), task

    def test_create_approve_cancel_owner_scope_session_research_result_chain(self):
        with self.fixture() as fixture:
            key, prepared = self.prepare(fixture.values)
            self.request('POST', '/personal-agent/commands/start', {'planId': prepared['plan']['id']}, expected=409)
            self.request('GET', '/personal-agent/project-commands/' + key, owner='bob', expected=404)
            self.request('POST', '/personal-agent/project-commands/' + key + '/decision',
                {'previewHash': prepared['receipt']['preview']['previewHash'], 'approved': True}, owner='bob', expected=404)
            with self.store.engine.begin() as conn:
                conn.execute(text('DELETE FROM af_personal_orx_project_consents WHERE owner_id=:owner AND request_id=:request'),
                    {'owner': 'alice', 'request': key})
            recovered_preview = self.request('GET', '/personal-agent/commands/requests/' + key)
            self.assertEqual(recovered_preview['receipt']['preview'], prepared['receipt']['preview'])
            self.assertEqual(recovered_preview['receipt']['consentState'], 'awaiting')
            self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_personal_orx_project_consents')[0]['n'], 0)
            self.assertEqual(self.wire.creation_posts, 0)
            submit_path = '/personal-agent/project-commands/' + key + '/submit'
            submit_body = {'previewHash': prepared['receipt']['preview']['previewHash'], 'approved': True}
            self.request('POST', submit_path, submit_body, owner='bob', expected=404)
            self.request('POST', submit_path, {**submit_body, 'approved': False}, expected=422)
            self.request('POST', submit_path, {**submit_body, 'previewHash': '0' * 64}, expected=409)
            task = self.request('POST', submit_path, submit_body, expected=202)
            self.until(task, 'completed')
            receipt = self.request('GET', '/personal-agent/project-commands/' + key)
            self.assertEqual(receipt['state'], 'acknowledged')
            self.assertEqual(receipt['factoryIdentity']['taskId'], task['id'])
            self.assertEqual(self.wire.creation_posts, 1)
            replay = self.request('POST', submit_path, submit_body, expected=202)
            self.assertEqual(replay['id'], task['id'])
            self.assertEqual(self.wire.creation_posts, 1)
            create = next(c for c in self.wire.calls if c[:2] == ('POST', '/api/projects'))
            self.assertIs(create[2]['githubSyncEnabled'], False)
            self.assertIs(create[2]['github_sync_enabled'], False)
            self.assertNotIn('idempotencyKey', create[2])
            self.assertNotIn('synthetic-test-password', str(self.store.plan(task['planId'], 'alice')) + str(receipt))
            bound = self.request('POST', '/personal-agent/project-commands/' + key + '/connect',
                {'harness': 'opencode', 'model': 'owner/model'})
            self.assertNotIn('project:create', bound['capabilities'])
            project = self.request('GET', '/personal-agent/projects?connectionRef=' + bound['ref'])
            self.assertTrue(project['sessionCreationSupported'])
            created, session_task = self.session_command('create', connectionRef=bound['ref'],
                nativeProjectId=receipt['result']['nativeProjectId'], title='Synthetic native research')
            sid = created['session']['id']
            choices = self.request('GET', '/personal-agent/native-sessions?connectionRef=' + bound['ref'])
            self.assertEqual(choices['sessions'][0]['nativeSessionId'], created['session']['nativeSessionId'])
            attached = self.request('POST', '/personal-agent/sessions/attach', {'requestId': 'attach-new-native-chat',
                'connectionRef': bound['ref'], 'nativeProjectId': project['nativeProjectId'],
                'nativeSessionId': choices['sessions'][0]['nativeSessionId']})
            self.assertEqual(attached['session']['id'], sid)
            prompted, research_task = self.session_command('prompt', sessionId=sid, text='Synthetic native research')
            result = self.request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
            self.assertEqual(result['observation']['messages'][-1]['events'][-1]['text'], 'Native answer 1')
            self.assertEqual(result['nativeProjectId'], receipt['result']['nativeProjectId'])
            self.assertFalse(result['liveEndToEndVerified'])
            self.assertEqual(self.wire.prompts, 1)
            self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
            for native_task in (task, session_task, research_task):
                actual = self.store.task(native_task['id'], 'alice')
                self.assertIsNotNone(self.store.native_db.get_job(actual['run_id'], strict=True))
                self.assertIsNone(self.store.usage_ledger)
            # A separate cancelled request never dispatches, despite plan review.
            cancelled_key = 'project-' + uuid4().hex
            cancelled = self.request('POST', '/personal-agent/project-commands/prepare', {
                'requestId': cancelled_key, 'connectionRef': self.bound['ref'],
                'project': {**fixture.values, 'path': '/synthetic/cancelled'}})
            self.review(cancelled['plan'])
            self.request('POST', '/personal-agent/project-commands/' + cancelled_key + '/decision',
                {'previewHash': cancelled['receipt']['preview']['previewHash'], 'approved': False})
            self.request('POST', '/personal-agent/commands/start', {'planId': cancelled['plan']['id']}, expected=409)
            self.request('POST', '/personal-agent/project-commands/' + cancelled_key + '/submit',
                {'previewHash': cancelled['receipt']['preview']['previewHash'], 'approved': True}, expected=409)
            self.request('POST', '/instances', {'planId': cancelled['plan']['id'],
                'requestId': 'cancelled-generic-instance'}, expected=409)
            self.assertEqual(self.wire.creation_posts, 1)

    def test_cancellation_cannot_overwrite_dispatch_claim_after_reading_approved(self):
        with self.fixture() as fixture:
            key, prepared = self.prepare(fixture.values)
            self.review(prepared['plan']); self.approve(key, prepared)
            entered, release = threading.Event(), threading.Event()
            post_dns, release_dns = threading.Event(), threading.Event()
            addresses = []

            def pause_post_dns():
                addresses.append(True)
                if len(addresses) == 2:
                    post_dns.set()
                    self.assertTrue(release_dns.wait(30), 'Project POST DNS was not released')

            self.wire.before_address = pause_post_dns

            def pause_cancellation(conn, cursor, statement, parameters, context, executemany):
                if statement.startswith('UPDATE af_personal_orx_project_consents') and parameters.get('state') == 'cancelled':
                    entered.set()
                    self.assertTrue(release.wait(30), 'Cancellation update was not released')

            event.listen(self.store.engine, 'before_cursor_execute', pause_cancellation)
            try:
                task = self.request('POST', '/personal-agent/commands/start', {'planId': prepared['plan']['id']})
                self.assertTrue(post_dns.wait(5), 'Project command did not reserve before POST DNS')
                with ThreadPoolExecutor(max_workers=1) as pool:
                    cancellation = pool.submit(self.request, 'POST', '/personal-agent/project-commands/' + key + '/decision',
                        {'previewHash': prepared['receipt']['preview']['previewHash'], 'approved': False}, expected=409)
                    try:
                        self.assertTrue(entered.wait(5), 'Cancellation did not read approved consent')
                        release_dns.set()
                        self.until(task, 'completed')
                    finally:
                        release.set()
                    self.assertEqual(cancellation.result()['message'], 'PERSONAL_PROJECT_DECISION_FROZEN')
            finally:
                release.set()
                release_dns.set()
                event.remove(self.store.engine, 'before_cursor_execute', pause_cancellation)
            receipt = self.request('GET', '/personal-agent/project-commands/' + key)
            self.assertEqual(receipt['consentState'], 'dispatch_started')
            self.assertEqual(receipt['state'], 'acknowledged')
            self.assertEqual(self.wire.creation_posts, 1)

    def test_pg_concurrent_double_click_loss_restart_expiry_and_permission_recheck(self):
        with self.fixture() as fixture:
            key = 'race-' + uuid4().hex
            body = {'requestId': key, 'connectionRef': self.bound['ref'], 'project': fixture.values}
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.request('POST', '/personal-agent/project-commands/prepare', body), range(2)))
            self.assertEqual(results[0]['plan']['id'], results[1]['plan']['id'])
            prepared = results[0]
            entered, release = threading.Event(), threading.Event()
            original_request = self.wire.request
            def drop_response(*args, **kwargs):
                if args[2:4] == ('POST', '/api/projects'):
                    entered.set(); release.wait(5)
                return original_request(*args, **kwargs)
            self.wire.request = drop_response; self.wire.drop = '/api/projects'
            with ThreadPoolExecutor(max_workers=2) as pool:
                tasks = list(pool.map(lambda _: self.request('POST', '/personal-agent/project-commands/' + key + '/submit',
                    {'previewHash': prepared['receipt']['preview']['previewHash'], 'approved': True}, expected=202), range(2)))
            self.assertEqual(tasks[0]['id'], tasks[1]['id'])
            self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
            self.assertTrue(entered.wait(5)); release.set()
            self.until(tasks[0], 'unknown')
            restarted = PersonalOrxProjects(self.store.connections, admission=deny_direct_admission)
            recovered = restarted.request_result('alice', key, refresh=True)
            self.assertEqual(recovered['state'], 'ack_unknown')
            self.assertEqual(recovered['candidates'][0]['nativeProjectId'], 'native-created-1')
            self.assertEqual(recovered['factoryIdentity']['taskId'], tasks[0]['id'])
            original = self.request('GET', '/personal-agent/commands/requests/' + key)
            self.assertEqual(original['job']['id'], tasks[0]['id'])
            self.request('POST', '/personal-agent/project-commands/' + key + '/submit',
                {'previewHash': prepared['receipt']['preview']['previewHash'], 'approved': True}, expected=202)
            self.assertEqual(self.wire.creation_posts, 1)
            self.request('POST', '/personal-agent/project-commands/' + key + '/connect',
                {'harness': 'opencode', 'model': 'owner/model'}, expected=409)
            self.request('GET', '/personal-agent/project-commands/' + key, owner='bob', expected=404)
            self.wire.request = original_request
            # Binding expires after approval. The native tool must fail closed;
            # original UNKNOWN recovery metadata still remains readable.
            expired_key = 'expire-' + uuid4().hex
            expired = self.request('POST', '/personal-agent/project-commands/prepare', {
                **body, 'requestId': expired_key, 'project': {**fixture.values, 'path': '/synthetic/expired'}})
            self.review(expired['plan']); self.approve(expired_key, expired)
            at = self.store.connections._at()
            self.store.connections.clock = lambda: at + timedelta(minutes=16)
            self.request('POST', '/personal-agent/commands/start', {'planId': expired['plan']['id']}, expected=409)
            self.assertEqual(self.wire.creation_posts, 1)
            self.request('GET', '/personal-agent/project-commands/' + key)
            self.request('GET', '/personal-agent/project-commands/' + key + '?refresh=true', expected=409)
            self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_leases')[0]['n'], 0)
            self.store.connections.clock = lambda: at
            revoked_key = 'revoke-' + uuid4().hex
            revoked = self.request('POST', '/personal-agent/project-commands/prepare', {
                **body, 'requestId': revoked_key, 'project': {**fixture.values, 'path': '/synthetic/revoked'}})
            self.review(revoked['plan']); self.approve(revoked_key, revoked)
            self.auth.authorization.unassign('alice', 'factory-user')
            self.request('POST', '/personal-agent/commands/start', {'planId': revoked['plan']['id']}, expected=403)
            self.assertEqual(self.wire.creation_posts, 1)
