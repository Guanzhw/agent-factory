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
from sqlalchemy import select
from agent_factory.delegated_operations import DELEGATED_OPERATION_PIN
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
    unknown = Path(configuration['workspace']) / 'unknown-original-stop'
    key = tuple(DELEGATED_OPERATION_PIN[field] for field in ('adapterId', 'revision', 'configFingerprint'))
    runtime = state['store'].workflow.runtimes[key]
    original_observe = runtime._observe
    async def stop_confirmation(body):
        observed = await original_observe(body)
        if unknown.exists():
            # Withhold only confirmation; original native child execution and identity stay real.
            observed.update(state='UNKNOWN', allStopped=False, output=None, failure=None)
        return observed
    runtime._observe = stop_confirmation

    @app.app.post('/__workflow_fixture/control')
    async def observe_again(request: Request):
        if request.headers.get('X-Fixture-Control') != configuration['controlKey']:
            raise HTTPException(403, 'FIXTURE_CONTROL_DENIED')
        value = await request.json()
        if set(value) != {'op', 'taskId'} or value['op'] != 'observe':
            raise HTTPException(400, 'FIXTURE_CONTROL_INVALID')
        await state['store'].lifecycle_observer.observe_root(value['taskId'])
        return {'ok': True}

    @app.app.get('/__workflow_fixture/facts')
    async def facts(request: Request, taskId: str | None = None):
        if request.headers.get('X-Fixture-Control') != configuration['controlKey']:
            raise HTTPException(403, 'FIXTURE_CONTROL_DENIED')
        store = state['store']
        task = store.task(taskId, 'alice') if taskId else None
        links = store.sql('SELECT child_id FROM af_delegation_links WHERE parent_id=:id', id=taskId) if task else []
        children = [store.task(link['child_id'], 'alice') for link in links if link['child_id']]
        with store.transaction() as conn:
            row = conn.execute(select(rounds.rounds).where(rounds.rounds.c.task_id == taskId)).mappings().first() if task else None
        custody = [store.workflow.read('alice', item['id']) for item in store.sql(
            'SELECT id FROM af_external_operations WHERE task_id=:id ORDER BY id', id=taskId)] if task else []
        disk = store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=taskId) if task else []
        return {'application': application, 'task': task, 'taskCount': len(store.tasks('alice')),
            'round': dict(row) if row else None, 'custody': custody,
            'workflowHeld': store.workflow.task_held(taskId) if task else False,
            'diskHold': disk[0]['state'] if disk else None,
            'scope': store.local_budget_scopes.inspect('alice', row['scope_id']) if row else None,
            'native': store.native_db.get_job(task['run_id']) if task and task['run_id'] else None,
            'children': [{'id': child['id'], 'runId': child['run_id'],
                'native': store.native_db.get_job(child['run_id']) if child['run_id'] else None} for child in children]}
    uvicorn.run(state["http_app"], host='127.0.0.1', port=configuration['port'], log_level='error', access_log=False)


class ResearchServer(WorkflowServer):
    module = 'applications.tests.test_research_workflow_restart_postgres'


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class ResearchWorkflowRestartTests(unittest.TestCase):
    def test_cancel_unknown_keeps_original_research_across_restart_until_stop_confirmed(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        server = ResearchServer(database.url, directory.name)
        self.addCleanup(server.stop)
        unknown = Path(server.configuration['workspace']) / 'unknown-original-stop'
        unknown.touch()
        server.start()
        reference = server.facts()['application']
        result = server.request('POST', '/api/factory/research/projects',
            {'requestId': 'cancel-project-create', 'title': 'Original research cancellation'})
        self.assertEqual(result.status_code, 201, result.text)
        url = '/api/factory/research/projects/' + result.json()['id']
        agreement = {'objective': 'Compute the actual agreed bytes once',
            'evaluation': 'Compare actual UTF-8 checksum evidence', 'stopConditions': 'Stop on evidenced result',
            'budget': {'rounds': 1, 'toolCalls': 32}, 'execution': {'applicationRef': reference,
                'mode': 'research', 'deadline': time.time() + 180, 'perRoundCaps': {'rounds': 1, 'toolCalls': 32}}}
        for path, body in (('/goals', {'requestId': 'cancel-goal-create', 'expectedVersion': 0, 'agreement': agreement}),
                           ('/confirm', {'requestId': 'cancel-goal-confirm', 'expectedVersion': 1}),
                           ('/start', {'requestId': 'cancel-root-start', 'expectedVersion': 1})):
            result = server.request('POST', url + path, body)
            self.assertIn(result.status_code, {200, 202}, result.text)
        task_id = result.json()['execution']['taskId']
        def until(predicate):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                facts = server.facts(task_id)
                if predicate(facts):
                    return facts
                time.sleep(.05)
            self.fail('Original research condition not reached: ' + str(facts))
        before = until(lambda facts: facts['native']['status'] == 'paused'
            and len(facts['children']) == 1 and facts['children'][0]['native']['status'] == 'completed')
        identities = [(child['id'], child['runId']) for child in before['children']]
        operations = [(item['id'], item['handle']) for item in before['custody']]
        self.assertTrue(operations)
        ended = server.request('POST', url + '/end', {'requestId': 'cancel-project-end', 'expectedVersion': 1,
            'outcome': 'cancelled', 'reason': 'User stopped the original research'})
        self.assertEqual(ended.status_code, 200, ended.text)
        cancelled = server.request('POST', '/api/factory/jobs/' + task_id + '/cancel')
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        def assert_held(facts):
            self.assertEqual(facts['task']['run_id'], before['task']['run_id'])
            self.assertEqual([(child['id'], child['runId']) for child in facts['children']], identities)
            self.assertEqual([(item['id'], item['handle']) for item in facts['custody']], operations)
            self.assertEqual(facts['taskCount'], 2)
            self.assertTrue(facts['task']['cancel_requested'])
            self.assertFalse(facts['task']['terminal'])
            self.assertTrue(facts['workflowHeld'])
            self.assertEqual(facts['diskHold'], 'HELD')
            self.assertEqual(facts['scope']['heldToolCalls'], 32)
            self.assertIsNone(facts['round']['terminal'])
            self.assertIsNone(facts['round']['terminal_record'])
            self.assertTrue(all(not item['closed'] and item['observation']['state'] == 'UNKNOWN'
                for item in facts['custody']))
        assert_held(server.facts(task_id))
        server.process.kill(); server.process.wait(5); server.log.close()
        server.start()
        observed = server.request('POST', '/__workflow_fixture/control',
            {'op': 'observe', 'taskId': task_id}, fixture=True)
        self.assertEqual(observed.status_code, 200, observed.text)
        assert_held(server.facts(task_id))
        unknown.unlink()
        final = until(lambda facts: facts['task']['terminal'])
        self.assertEqual(final['taskCount'], 2)
        self.assertEqual([(child['id'], child['runId']) for child in final['children']], identities)
        self.assertEqual(final['native']['status'], 'cancelled')
        self.assertFalse(final['workflowHeld'])
        self.assertEqual(final['diskHold'], 'RELEASED')
        self.assertEqual(final['scope']['heldToolCalls'], 0)
        self.assertTrue(all(item['closed'] and item['observation']['allStopped'] for item in final['custody']))
        self.assertIsNone(final['round']['decision'])
        self.assertIsNotNone(final['round']['terminal_record'])
        listing = server.request('GET', url + '/experiments').json()
        self.assertEqual(len(listing['rounds']), 1)
        self.assertEqual(listing['rounds'][0]['continuations'], [])
        self.assertEqual(server.request('GET', url).json()['ending']['outcome'], 'cancelled')
        for _ in range(2):
            observed = server.request('POST', '/__workflow_fixture/control',
                {'op': 'observe', 'taskId': task_id}, fixture=True)
            self.assertEqual(observed.status_code, 200, observed.text)
        replay = server.facts(task_id)
        self.assertEqual(replay['round']['terminal_record'], final['round']['terminal_record'])
        self.assertEqual(replay['round']['terminal'], final['round']['terminal'])
        self.assertEqual(replay['scope'], final['scope'])
        self.assertEqual(replay['taskCount'], 2)

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
