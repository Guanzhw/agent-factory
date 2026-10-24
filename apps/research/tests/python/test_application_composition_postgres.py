"""Two applications in one real PostgreSQL/HTTP/native lifecycle, both orders.

TestClient uses the real ASGI lifespan and Agno queue, matching the existing
application assembly fixture. This is not TCP/Uvicorn or live provider evidence.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient

from agent_factory_research.services import services_for
from agent_factory_server.main import create_app, factory_state, research_application
from application_composition_fixture import (APPLICATION, EFFECT, SecondApplication,
    ResearchRuntime, research_settings)
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ApplicationCompositionPostgresTests(unittest.TestCase):
    def wait_for(self, predicate, *, seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(.03)
        self.fail('Controlled application composition did not reach the required state')

    def request(self, client, method, path, body=None, expected=200):
        response = client.request(method, '/api/factory' + path, json=body)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def exercise_order(self, research_first):
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, \
                TemporaryDirectory(prefix='application-composition-') as directory:
            second, runtime = SecondApplication(), ResearchRuntime()
            settings, preset, bootstrap = research_settings(database.url, Path(directory), runtime, second)
            research = research_application()
            applications = ((research, second.assembly()) if research_first
                            else (second.assembly(), research))
            app = create_app(settings, applications=applications)
            state = factory_state(app)
            store = state['store']
            try:
                # Install/publication is inert; neither model nor tool is eager.
                self.assertEqual(second.calls, [])
                self.assertEqual(runtime.counters(), (0, 0, 0))
                preset = bootstrap.publish_application(state, preset, author='alice')
                state['settings'].autoresearch_presets[preset.id] = preset
                services_for(store).autoresearch.presets[preset.id] = preset
                second.publish(state)
                self.assertEqual(second.model_builds, 0)
                self.assertEqual(second.calls, [])
                self.assertEqual(runtime.counters(), (0, 0, 0))
                with TestClient(app) as client:
                    try:
                        self.request(client, 'POST', '/demo/login', {'persona': 'alice'})
                        started_research = self.request(client, 'POST', '/autoresearch/runs', {
                            'presetId': preset.id, 'requestId': 'composition-research-original'}, 202)
                        body = {'application': APPLICATION, 'mode': 'execute',
                            'goal': 'Run the original controlled second application operation.',
                            'requestId': 'composition-second-original'}
                        started_second = self.request(client, 'POST', '/application-interface/v1/starts', body, 202)
                        research_id, second_id = started_research['id'], started_second['job']['id']
                        self.wait_for(lambda: runtime.started.is_set() and second_id in second.operations)
                        research_task = store.task(research_id, 'alice')
                        second_task = store.task(second_id, 'alice')
                        original_research_effects = store.effects(research_id)
                        original_second_effects = store.effects(second_id)
                        original_research_binding = store.lifecycle_observer._binding(research_task)
                        self.assertEqual(original_research_binding['status'], 'running')
                        self.assertEqual(runtime.counters(), (1, 0, 0))
                        self.assertEqual(len(second.calls), 1)
                        self.assertGreater(second.model_builds, 0)
                        self.assertEqual(original_second_effects, [{
                            'effect_key': second_task['run_id'] + ':' + EFFECT,
                            'status': 'UNKNOWN', 'result': None}])
                        research_owners = store.application_runtime.owners(research_task)
                        self.assertEqual([owner.identifier for owner in research_owners], ['research'])
                        self.assertEqual([owner.identifier for owner in store.application_runtime.owners(second_task)],
                                         [APPLICATION])

                        # Observe this installed instance only, delegating every
                        # callback to its real implementation; no class patch.
                        hooks = research_owners[0].hooks
                        original_mark, original_cancel = hooks.mark_cancel, hooks.cancel
                        research_marks, research_cancels = [], []

                        def marked(owner_store, task_id):
                            research_marks.append(task_id)
                            return original_mark(owner_store, task_id)

                        async def cancelled(owner_store, task):
                            research_cancels.append(task['id'])
                            return await original_cancel(owner_store, task)

                        hooks.mark_cancel, hooks.cancel = marked, cancelled
                        calls_before = list(second.project_calls)
                        detail = self.request(client, 'GET', '/jobs/' + research_id)
                        self.assertNotIn('compositionFixture', detail)
                        self.assertEqual(second.project_calls, calls_before)
                        second_detail = self.request(client, 'GET', '/jobs/' + second_id)
                        self.assertEqual(second_detail['compositionFixture']['runId'], second_task['run_id'])
                        self.assertNotIn('orxExperiment', second_detail)

                        self.request(client, 'POST', '/jobs/' + second_id + '/cancel',
                                     {'commandId': 'composition-second-cancel'})
                        self.wait_for(lambda: bool(second.cancel_calls))
                        held = store.task(second_id, 'alice')
                        self.assertTrue(held['cancel_requested'])
                        self.assertFalse(held['terminal'])
                        self.assertTrue(store.application_runtime.task_held(held))
                        self.assertEqual(store.effects(second_id), original_second_effects)
                        self.assertEqual(set(second.mark_calls), {second_id})
                        self.assertEqual(set(second.cancel_calls), {(second_id, second_task['run_id'])})
                        self.assertEqual(research_marks, [])
                        self.assertEqual(research_cancels, [])
                        self.assertEqual(runtime.counters(), (1, 0, 0))
                        current_research = store.task(research_id, 'alice')
                        for field in ('id', 'run_id', 'plan_id', 'owner_id', 'cancel_requested', 'terminal'):
                            self.assertEqual(current_research[field], research_task[field])
                        self.assertEqual(store.effects(research_id), original_research_effects)
                        self.assertEqual(store.lifecycle_observer._binding(current_research)['status'],
                                         original_research_binding['status'])
                        # An acknowledged cancellation leaves both occupied task
                        # slots held until the original provider actually stops.
                        self.request(client, 'POST', '/application-interface/v1/starts',
                            {**body, 'requestId': 'composition-held-capacity'}, 429)
                        repeated = self.request(client, 'POST', '/application-interface/v1/starts', body, 202)
                        self.assertEqual(repeated['job']['id'], second_id)
                        self.assertEqual(len(second.calls), 1)

                        second.operations[second_id]['allowStop'].set()
                        self.wait_for(lambda: second.operations[second_id]['stopped'].is_set())
                        self.wait_for(lambda: store.effects(second_id)[0]['status'] == 'CANCELLED')
                        self.request(client, 'POST', '/jobs/' + second_id + '/reconcile')
                        self.wait_for(lambda: store.task(second_id)['terminal'])
                        proof = store.effects(second_id)[0]
                        self.assertEqual(proof['effect_key'], original_second_effects[0]['effect_key'])
                        self.assertEqual(proof['result'], {**second.calls[0], 'allStopped': True, 'cancelled': True})
                        self.assertFalse(store.application_runtime.task_held(store.task(second_id)))
                        self.assertEqual(research_marks, [])
                        self.assertEqual(research_cancels, [])
                        self.assertEqual(runtime.counters(), (1, 0, 0))
                        runtime.finish.set()
                        self.wait_for(lambda: services_for(store).autoresearch.row('alice', research_id)['body']['status'] == 'completed')
                        self.assertEqual(runtime.counters(), (1, 1, 0))
                        self.assertEqual(len(second.calls), 1)
                    finally:
                        # Test failures still release only fixture-owned work,
                        # before the real application/native lifespan unwinds.
                        second.release_all()
                        runtime.finish.set()
            finally:
                store.engine.dispose()
                store.native_db.db_engine.dispose()

    def test_research_then_second_preserves_original_owner_on_cancel(self):
        self.exercise_order(research_first=True)

    def test_second_then_research_preserves_original_owner_on_cancel(self):
        self.exercise_order(research_first=False)


if __name__ == '__main__':
    unittest.main()
