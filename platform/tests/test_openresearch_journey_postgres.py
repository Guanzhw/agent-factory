"""First-app journey over controlled ORX HTTP and real PG/native queue only."""
import os
import unittest
from uuid import uuid4
import test_personal_orx_projects_postgres as native


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class ResearchJourneyPostgresTests(unittest.TestCase):
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
