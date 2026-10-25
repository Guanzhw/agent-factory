"""Hard restart of the actual research consumer at its original native wait."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

# The shared subprocess harness starts modules from the repository root.
if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root / 'applications'), str(root / 'applications/tests'), str(root / 'deployment')]

from fastapi import HTTPException, Request
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from pg_fixture import IsolatedPostgres
from test_native_workflow_factory_postgres import WorkflowServer
from test_research_workflow_postgres import publish, settings_for


def serve(configuration):
    import uvicorn
    app = create_app(settings_for(configuration['dbUrl'], configuration['workspace'], jwt_key=configuration['jwtKey']))
    state = factory_state(app)
    application = publish(state)
    rounds = state['research_rounds']
    original = rounds.observe_waits
    release = Path(configuration['workspace']) / 'release-original-wait'
    async def gated(observer, task):
        if release.exists():
            await original(observer, task)
    rounds.observe_waits = gated

    @app.app.get('/__workflow_fixture/facts')
    async def facts(request: Request, taskId: str | None = None):
        if request.headers.get('X-Fixture-Control') != configuration['controlKey']:
            raise HTTPException(403, 'FIXTURE_CONTROL_DENIED')
        store = state['store']
        task = store.task(taskId, 'alice') if taskId else None
        links = store.sql('SELECT child_id FROM af_delegation_links WHERE parent_id=:id', id=taskId) if task else []
        children = [store.task(link['child_id'], 'alice') for link in links if link['child_id']]
        return {'application': application, 'task': task, 'taskCount': len(store.tasks('alice')),
            'native': store.native_db.get_job(task['run_id']) if task and task['run_id'] else None,
            'children': [{'id': child['id'], 'runId': child['run_id'],
                'native': store.native_db.get_job(child['run_id']) if child['run_id'] else None} for child in children]}
    uvicorn.run(app, host='127.0.0.1', port=configuration['port'], log_level='error', access_log=False)


class ResearchServer(WorkflowServer):
    module = 'applications.tests.test_research_workflow_restart_postgres'


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class ResearchWorkflowRestartTests(unittest.TestCase):
    def test_original_paused_research_survives_process_death_without_new_child(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        server = ResearchServer(database.url, directory.name)
        self.addCleanup(server.stop)
        server.start()
        reference = server.facts()['application']
        result = server.request('POST', '/api/factory/research/projects',
            {'requestId': 'restart-project-create', 'title': 'Original native research restart'})
        self.assertEqual(result.status_code, 201, result.text)
        url = '/api/factory/research/projects/' + result.json()['id']
        agreement = {'objective': 'Compute the actual agreed bytes once',
            'evaluation': 'Compare actual UTF-8 checksum evidence', 'stopConditions': 'Stop on evidenced result',
            'budget': {'rounds': 1, 'toolCalls': 32}, 'execution': {'applicationRef': reference,
                'mode': 'research', 'deadline': time.time() + 180, 'perRoundCaps': {'rounds': 1, 'toolCalls': 32}}}
        for path, body in (('/goals', {'requestId': 'restart-goal-create', 'expectedVersion': 0, 'agreement': agreement}),
                           ('/confirm', {'requestId': 'restart-goal-confirm', 'expectedVersion': 1}),
                           ('/start', {'requestId': 'restart-root-start', 'expectedVersion': 1})):
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
        self.assertEqual(before['children'][0]['native']['status'], 'completed', before)
        server.process.kill(); server.process.wait(5); server.log.close()
        (Path(server.configuration['workspace']) / 'release-original-wait').touch()
        server.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            after = server.facts(task_id)
            if after['task']['terminal']:
                break
            time.sleep(.05)
        self.assertTrue(after['task']['terminal'], after)
        self.assertEqual(after['native']['status'], 'completed', after)
        self.assertEqual(after['native']['id'], before['native']['id'])
        self.assertEqual([(c['id'], c['runId']) for c in after['children']],
                         [(c['id'], c['runId']) for c in before['children']])
        self.assertEqual(after['taskCount'], 2)
        listing = server.request('GET', url + '/experiments').json()
        self.assertEqual(listing['rounds'][0]['decision']['outcome'], 'met', listing)
        replay = server.request('POST', url + '/start', {'requestId': 'restart-root-start', 'expectedVersion': 1})
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(replay.json()['execution']['taskId'], task_id)
        self.assertEqual(server.facts(task_id)['taskCount'], 2)


if __name__ == '__main__':
    serve(json.loads(Path(sys.argv[2]).read_text()))
