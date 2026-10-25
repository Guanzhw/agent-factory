"""A01 same-database research installation/removal, actual two-process lifecycle."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from sqlalchemy import create_engine, text

from pg_fixture import IsolatedPostgres
from test_research_workflow_restart_postgres import ResearchServer


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires isolated PostgreSQL')
class ResearchRemovalPostgresTests(unittest.TestCase):
    def test_original_task_stops_without_replay_or_research_completion_after_app_removal(self):
        database = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        directory = self.enterContext(TemporaryDirectory(prefix='research-removal-'))
        server = ResearchServer(database.url, directory)
        self.addCleanup(server.stop)
        engine = create_engine(database.url)
        self.addCleanup(engine.dispose)

        def domain_state():
            with engine.connect() as conn:
                return {table: [dict(row) for row in conn.execute(text('SELECT * FROM ' + table + ' ORDER BY id')).mappings()]
                        for table in ('research_rounds', 'research_projects',
                                      'af_assistant_events', 'af_application_content')}

        server.start()
        reference = server.facts()['application']
        created = server.request('POST', '/api/factory/research/projects',
            {'requestId': 'removal-project-create', 'title': 'Unfinished original research'})
        self.assertEqual(created.status_code, 201, created.text)
        url = '/api/factory/research/projects/' + created.json()['id']
        agreement = {'objective': 'Compute the actual agreed bytes once',
            'evaluation': 'Compare actual UTF-8 checksum evidence', 'stopConditions': 'Stop on evidenced result',
            'budget': {'rounds': 1, 'toolCalls': 32}, 'execution': {'applicationRef': reference,
                'mode': 'research', 'deadline': time.time() + 180, 'perRoundCaps': {'rounds': 1, 'toolCalls': 32}}}
        for path, body in (('/goals', {'requestId': 'removal-goal', 'expectedVersion': 0, 'agreement': agreement}),
                           ('/confirm', {'requestId': 'removal-confirm', 'expectedVersion': 1}),
                           ('/start', {'requestId': 'removal-original-start', 'expectedVersion': 1})):
            result = server.request('POST', url + path, body)
            self.assertIn(result.status_code, {200, 202}, result.text)
        receipt = result.json()
        task_id = receipt['execution']['taskId']
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            before = server.facts(task_id)
            if (before['native']['status'] == 'paused' and len(before['children']) == 1
                    and (before['children'][0]['native'] or {}).get('status') == 'completed'):
                break
            time.sleep(.05)
        self.assertEqual(before['native']['status'], 'paused', before)
        self.assertFalse(before['task']['terminal'], before)
        self.assertEqual(before['children'][0]['native']['status'], 'completed', before)
        with engine.connect() as conn:
            original_ops = conn.execute(text('SELECT id,closed FROM af_external_operations WHERE task_id=:task'),
                                        {'task': task_id}).mappings().all()
            original_holds = conn.execute(text('SELECT held_tools FROM af_local_budget_scopes WHERE id=:id'),
                                          {'id': receipt['scopeId']}).scalar_one()
        self.assertEqual(len(original_ops), 1)
        self.assertFalse(original_ops[0]['closed'])
        self.assertGreater(original_holds, 0)
        original_domain = domain_state()
        self.assertEqual(len(original_domain['research_rounds']), 1)
        for field in ('decision', 'terminal', 'terminal_record'):
            self.assertIsNone(original_domain['research_rounds'][0][field])
        self.assertIsNone(original_domain['research_projects'][0]['ending'])
        catalog = server.request('GET', '/api/factory/applications').json()
        original_pids = list(server.pids)
        server.process.kill()
        server.process.wait(5)
        server.log.close()
        server.module = 'app_removal_core_server'
        server.start()
        self.assertNotEqual(server.process.pid, original_pids[-1])
        query = '?taskId=' + task_id + '&scopeId=' + receipt['scopeId']
        response = server.request('GET', '/__workflow_fixture/facts' + query, fixture=True)
        self.assertEqual(response.status_code, 200, response.text)
        after = response.json()
        observed = server.request('POST', '/__workflow_fixture/observe?taskId=' + task_id, fixture=True)
        self.assertEqual(observed.status_code, 200, observed.text)
        final = server.request('GET', '/__workflow_fixture/facts' + query, fixture=True).json()
        evidence = {'before': before, 'after': after, 'observation': observed.json(), 'final': final}
        # Persist only public/synthetic state; never the server config or fixture tokens.
        import json
        Path('/tmp/research-removal-original-evidence.json').write_text(json.dumps(evidence, indent=2, default=str))
        for phase in (after, final):
            self.assertFalse(phase['researchImported'])
            self.assertFalse(phase['deploymentImported'])
            self.assertFalse(phase['applicationOwners'])
            self.assertEqual(phase['configuredWorkflows'], 0)
            self.assertEqual(phase['configuredAdapters'], 0)
            self.assertEqual(phase['task']['id'], task_id)
            self.assertEqual(phase['task']['run_id'], before['task']['run_id'])
            self.assertEqual(set(phase['taskIds']), {task_id, before['children'][0]['id']})
            self.assertEqual([item['id'] for item in phase['operations']], [original_ops[0]['id']])
        self.assertFalse(after['task']['terminal'], evidence)
        self.assertFalse(after['operations'][0]['closed'], evidence)
        self.assertEqual(after['scope']['heldToolCalls'], original_holds)
        self.assertEqual(after['scope']['allocations'][0]['state'], 'BOUND')
        self.assertEqual(final['native']['status'], 'cancelled')
        self.assertTrue(final['task']['terminal'])
        self.assertEqual(final['task']['body']['lastStatus'], 'failed')
        self.assertTrue(final['operations'][0]['closed'])
        self.assertEqual(final['operations'][0]['observation']['state'], 'FAILED')
        self.assertTrue(final['operations'][0]['observation']['allStopped'])
        self.assertTrue(observed.json()['allStopped'], observed.json())
        self.assertTrue(all(fact['stopped'] and not fact['unknown'] for fact in observed.json()['facts']))
        self.assertEqual(final['scope']['allocations'][0]['state'], 'SETTLED')
        self.assertEqual(final['scope']['heldToolCalls'], 0)
        self.assertEqual(domain_state(), original_domain)
        self.assertEqual(server.request('GET', '/api/health').status_code, 200)
        self.assertEqual(server.request('GET', '/api/factory/jobs/' + task_id).status_code, 200)
        self.assertEqual(server.request('GET', '/api/factory/research/projects').status_code, 404)
        self.assertEqual(server.request('GET', '/api/factory/research/assistants').status_code, 404)
        self.assertEqual(server.request('GET', '/api/factory/applications').json(), catalog)
        for path in ('personal-credentials/capabilities', 'personal-models/capabilities',
                     'personal-remotes/providers', 'personal-tools/descriptors', 'personal-ssh/capabilities'):
            self.assertEqual(server.request('GET', '/api/factory/' + path).status_code, 200, path)
