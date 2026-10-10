"""First-app journey over controlled ORX HTTP and real PG/native queue only."""
import os
import unittest
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from fastapi import HTTPException
from agent_factory.personal_orx_projects import PersonalOrxProjects
import test_personal_orx_projects_postgres as native


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class ResearchJourneyPostgresTests(unittest.TestCase):
    def test_controlled_expiry_continue_and_new_research_keep_native_queue_and_old_snapshots(self):
        fixture = native.OrxProjectPostgresTests('test_personal_orx_registration_uses_shared_contract_without_remote_probe')
        with fixture.fixture():
            request = fixture.request
            selected = request('POST', '/personal-agent/project-selection', {'requestId': 'lease-setup',
                'connectionRef': fixture.bound['ref'], 'nativeProjectId': 'native-project'})
            created, _ = fixture.session_command('create', connectionRef=selected['ref'],
                nativeProjectId='native-project', title='Controlled first research')
            sid = created['session']['id']
            fixture.session_command('prompt', sessionId=sid, text='Original controlled goal')
            first = request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
            original_plan = deepcopy(fixture.store.plan(created['factoryIdentity']['planId'], 'alice'))
            at = fixture.store.connections._at()
            fixture.store.connections.clock = lambda: at + timedelta(minutes=16)
            expired = request('GET', '/personal-agent/sessions/' + sid)
            self.assertEqual(expired['bindingStatus'], 'expired')
            posts = len([c for c in fixture.wire.calls if c[0] == 'POST'])
            continued = request('POST', '/personal-agent/sessions/' + sid + '/continue',
                {'expectedFingerprint': first['connectionPin']['fingerprint']})
            self.assertEqual(continued['state'], 'ready')
            self.assertEqual(len([c for c in fixture.wire.calls if c[0] == 'POST']), posts)
            self.assertEqual(continued['session']['nativeSessionId'], first['nativeSessionId'])
            fixture.session_command('prompt', sessionId=sid, text='New explicit followup after expiry')
            second = request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
            self.assertEqual(fixture.wire.prompts, 2)
            self.assertEqual(second['nativeSessionId'], first['nativeSessionId'])
            self.assertEqual(fixture.store.plan(created['factoryIdentity']['planId'], 'alice'), original_plan)
            # A later ordinary submit combines health/rebind internally with this
            # new explicit prompt only. The original request is never reissued.
            fixture.store.connections.clock = lambda: at + timedelta(minutes=32)
            fixture.session_command('prompt', sessionId=sid, text='Explicit next followup across second lease')
            self.assertEqual(fixture.wire.prompts, 3)
            third = request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
            self.assertEqual(third['nativeSessionId'], first['nativeSessionId'])
            self.assertEqual(len(third['bindingHistory']), 2)
            # Old selected project refs can refresh to the same proven scope for
            # an explicit distinct study, without a remote project creation.
            new, _ = fixture.session_command('create', connectionRef=selected['ref'],
                nativeProjectId='native-project', title='Explicit separate research after expiry')
            self.assertNotEqual(new['session']['nativeSessionId'], first['nativeSessionId'])
            self.assertEqual(fixture.wire.creation_posts, 0)
            self.assertEqual(fixture.store.plan(created['factoryIdentity']['planId'], 'alice'), original_plan)

    def test_configuration_failure_partial_unknown_and_explicit_reselection_recovery(self):
        fixture = native.OrxProjectPostgresTests('test_personal_orx_registration_uses_shared_contract_without_remote_probe')
        with fixture.fixture():
            request = fixture.request; route = '/personal-agent/project-selection'
            body = {'requestId': 'missing-selection', 'connectionRef': fixture.bound['ref'], 'nativeProjectId': 'missing-project'}
            request('POST', route, body, expected=404)
            status = request('GET', route + '/requests/missing-selection/status')
            self.assertEqual((status['state'], status['localConfiguration']), ('failed', 'none'))
            request('GET', route + '/requests/missing-selection/status', owner='bob', expected=404)
            body = {**body, 'requestId': 'partial-selection', 'nativeProjectId': 'native-project'}
            with patch.object(fixture.store.connections.personal, 'verify', side_effect=HTTPException(409, 'synthetic verify rejected')):
                request('POST', route, body, expected=409)
            status = request('GET', route + '/requests/partial-selection/status')
            self.assertEqual((status['state'], status['localConfiguration']), ('failed', 'partial'))
            service = PersonalOrxProjects(fixture.store.connections, admission=lambda *_: None)
            configure = fixture.store.connections.personal.configure
            def lost_configuration(*args, **kwargs):
                configure(*args, **kwargs)
                raise RuntimeError('Synthetic lost local reply after commit')
            with patch.object(fixture.store.connections.personal, 'configure', side_effect=lost_configuration):
                with self.assertRaises(RuntimeError):
                    service.select_existing('alice', fixture.bound['ref'], 'native-project', 'unknown-selection')
            calls = len(fixture.wire.calls)
            status = request('GET', route + '/requests/unknown-selection/status')
            self.assertEqual((status['state'], status['localConfiguration']), ('unknown', 'partial'))
            request('POST', route, {**body, 'requestId': 'unknown-selection'}, expected=409)
            self.assertEqual(len(fixture.wire.calls), calls)
            selected = request('POST', route, {**body, 'requestId': 'explicit-new-selection'})
            status = request('GET', route + '/requests/explicit-new-selection/status')
            self.assertEqual(status['connection']['ref'], selected['ref'])
            self.assertEqual(status['state'], 'complete')
            self.assertFalse(any(call[0] != 'GET' for call in fixture.wire.calls))
            self.assertEqual(fixture.wire.prompts, 0)
            self.assertEqual(fixture.wire.creation_posts, 0)

    def test_select_native_project_create_goal_result_continue_and_owner_isolation(self):
        fixture = native.OrxProjectPostgresTests('test_personal_orx_registration_uses_shared_contract_without_remote_probe')
        with fixture.fixture():
            request = fixture.request
            route = '/personal-agent/project-selection'
            listed = request('GET', route + '?connectionRef=' + fixture.bound['ref'])
            self.assertEqual(listed[0]['name'], 'Original native project')
            key = 'journey-setup-' + uuid4().hex
            selected = request('POST', route, {'requestId': key, 'connectionRef': fixture.bound['ref'], 'nativeProjectId': listed[0]['nativeProjectId']})
            self.assertEqual(selected['ownerId'], 'alice')
            self.assertEqual(request('GET', route + '/requests/' + key)['ref'], selected['ref'])
            request('GET', route + '/requests/' + key, owner='bob', expected=404)
            request('POST', route, {'requestId': 'foreign-project-selection', 'connectionRef': fixture.bound['ref'], 'nativeProjectId': listed[0]['nativeProjectId']}, owner='bob', expected=404)
            project = request('GET', '/personal-agent/projects?connectionRef=' + selected['ref'])
            self.assertTrue(project['sessionCreationSupported'])
            self.assertFalse(any(call[0] != 'GET' for call in fixture.wire.calls))
            created, task = fixture.session_command('create', connectionRef=selected['ref'], nativeProjectId=project['nativeProjectId'], title='Synthetic research goal')
            self.assertEqual(created['state'], 'acknowledged')
            sid = created['session']['id']
            request('POST', '/personal-agent/commands/submit', {'requestId': 'foreign-goal', 'action': 'prompt', 'sessionId': sid, 'text': 'Do not dispatch'}, owner='bob', expected=404)
            first, _ = fixture.session_command('prompt', sessionId=sid, text='Synthetic goal\n\nUser-supplied synthetic material')
            self.assertEqual(first['session']['id'], sid)
            observed = request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
            self.assertEqual(observed['observation']['messages'][-1]['events'][-1]['text'], 'Native answer 1')
            self.assertFalse(observed['observation']['exactTurnVerified'])
            fixture.session_command('prompt', sessionId=sid, text='Continue the same native research')
            request('GET', '/personal-agent/sessions/' + sid + '?refresh=true')
            self.assertEqual(fixture.wire.prompts, 2)
            self.assertEqual(len(fixture.wire.rows), 2)
            self.assertEqual(fixture.wire.creation_posts, 0)
            self.assertEqual(fixture.store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
            recovered = request('GET', '/personal-agent/commands/requests/' + created['requestId'])
            self.assertEqual(recovered['job']['id'], task['id'])
            self.assertEqual(recovered['nativeStatus'], 'completed')
