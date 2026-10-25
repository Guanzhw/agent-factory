"""Independent research graphs in two simultaneous PostgreSQL/native servers.

Both TestClients run actual ASGI lifespans and Agno workers in this process.
Provider work is deterministic and inert; no TCP or live model claim is made.
"""
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import time
import unittest

from fastapi.testclient import TestClient

from agent_factory_research.autoresearch_profile import MODEL_ADAPTER_ID
from agent_factory_research.services import ResearchFactory
from agent_factory_server.main import create_app, factory_state
from application_composition_fixture import ResearchRuntime, research_settings
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ApplicationInstancePostgresTests(unittest.TestCase):
    def wait_for(self, predicate, *, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(.03)
        self.fail('Independent native research instance did not reach the expected state')

    def request(self, client, method, path, body=None, expected=200):
        response = client.request(method, '/api/factory' + path, json=body)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def model_factory(self, settings):
        return next(entry.factory for entry in settings.runtime_adapters
                    if entry.kind == 'model' and entry.adapter_id == MODEL_ADAPTER_ID)

    def publish(self, state, preset, bootstrap):
        published = bootstrap.publish_application(state, preset, author='alice')
        state['settings'].autoresearch_presets[published.id] = published
        state['research'].autoresearch.presets[published.id] = published
        return published

    def exercise_instances(self, *, reuse_bound_settings):
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database_a, \
                IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database_b, \
                TemporaryDirectory(prefix='research-instance-a-') as directory_a, \
                TemporaryDirectory(prefix='research-instance-b-') as directory_b:
            runtime_a, runtime_b = ResearchRuntime(), ResearchRuntime()
            settings_a, preset_a, bootstrap_a = research_settings(database_a.url, Path(directory_a), runtime_a)
            settings_b, preset_b, bootstrap_b = research_settings(database_b.url, Path(directory_b), runtime_b)
            original_registrations = settings_a.runtime_adapters
            settings_b.runtime_adapters = original_registrations
            unbound = self.model_factory(settings_a)
            self.assertIsInstance(unbound, ResearchFactory)
            self.assertIsNone(unbound.research)
            states, clients = [], []
            try:
                app_a = create_app(settings_a)
                state_a = factory_state(app_a)
                states.append(state_a)
                preset_a = self.publish(state_a, preset_a, bootstrap_a)
                factory_a = self.model_factory(state_a['settings'])
                graph_a = state_a['research']
                self.assertIs(factory_a.research, graph_a)
                if reuse_bound_settings:
                    # Explicitly reuse the first server's already-bound entries;
                    # only the second server's DB/workspace/preset differ.
                    settings_b = replace(state_a['settings'], db_url=database_b.url,
                        workspace=Path(directory_b), autoresearch_presets={preset_b.id: preset_b})
                    self.assertIs(self.model_factory(settings_b), factory_a)
                else:
                    self.assertIs(settings_b.runtime_adapters, original_registrations)
                    self.assertIs(self.model_factory(settings_b), unbound)
                app_b = create_app(settings_b)
                state_b = factory_state(app_b)
                states.append(state_b)
                preset_b = self.publish(state_b, preset_b, bootstrap_b)
                graph_b = state_b['research']
                factory_b = self.model_factory(state_b['settings'])
                self.assertIsNot(graph_a, graph_b)
                self.assertIsNot(factory_a, factory_b)
                self.assertIs(factory_b.research, graph_b)
                self.assertIs(factory_a.research, graph_a)
                self.assertIsNone(unbound.research, 'Original registration specifications stay unbound')
                for app in (app_a, app_b):
                    client = TestClient(app).__enter__()
                    clients.append(client)
                    self.request(client, 'POST', '/demo/login', {'persona': 'alice'})
                client_a, client_b = clients
                body = {'presetId': preset_a.id, 'requestId': 'independent-original-research'}
                started_a = self.request(client_a, 'POST', '/autoresearch/runs', body, 202)
                started_b = self.request(client_b, 'POST', '/autoresearch/runs', body, 202)
                self.wait_for(lambda: runtime_a.started.is_set() and runtime_b.started.is_set())
                store_a, store_b = state_a['store'], state_b['store']
                task_a = store_a.task(started_a['id'], 'alice')
                task_b = store_b.task(started_b['id'], 'alice')
                self.assertNotEqual(task_a['id'], task_b['id'])
                self.assertNotEqual(task_a['run_id'], task_b['run_id'])
                effects_b = store_b.effects(task_b['id'])
                native_b = store_b.lifecycle_observer._binding(task_b)
                self.assertEqual(native_b['status'], 'running')
                self.assertEqual(runtime_b.counters(), (1, 0, 0))
                self.assertIs(graph_a.require_store(store_a, ready=True), graph_a)
                self.assertIs(graph_b.require_store(store_b, ready=True), graph_b)

                # Shut A down while both original native runs are still active.
                # A's graph and bound factories must not redirect into B.
                clients.remove(client_a)
                client_a.__exit__(None, None, None)
                self.assertTrue(graph_a.closed)
                self.assertFalse(graph_a.installed)
                self.assertIs(state_a['research'], graph_a)
                with self.assertRaisesRegex(ValueError, 'RESEARCH_STORE_MISMATCH'):
                    factory_a(SimpleNamespace(store=store_a))
                with self.assertRaisesRegex(ValueError, 'RESEARCH_STORE_MISMATCH'):
                    factory_a(SimpleNamespace(store=store_b))
                self.assertFalse(graph_b.closed)
                self.assertIs(graph_b.require_store(store_b, ready=True), graph_b)
                self.assertIs(factory_b.research, graph_b)
                self.assertEqual(runtime_b.counters(), (1, 0, 0))
                current_b = store_b.task(task_b['id'], 'alice')
                for field in ('id', 'run_id', 'plan_id', 'owner_id', 'cancel_requested', 'terminal'):
                    self.assertEqual(current_b[field], task_b[field])
                self.assertEqual(store_b.effects(task_b['id']), effects_b)
                self.assertEqual(store_b.lifecycle_observer._binding(current_b)['status'], native_b['status'])
                detail = self.request(client_b, 'GET', '/jobs/' + task_b['id'])
                self.assertEqual(detail['job']['id'], task_b['id'])
                # Explicit original-operation control remains usable after A
                # closes; reconcile inspects original custody without replay.
                reconciled = self.request(client_b, 'POST', '/jobs/' + task_b['id'] + '/reconcile')
                self.assertEqual(reconciled['id'], task_b['id'])
                self.assertEqual(self.request(client_b, 'POST', '/autoresearch/runs', body, 202)['id'], task_b['id'])
                self.assertEqual(runtime_b.counters(), (1, 0, 0))
                runtime_b.finish.set()
                self.wait_for(lambda: graph_b.autoresearch.row('alice', task_b['id'])['body']['status'] == 'completed')
                self.wait_for(lambda: store_b.lifecycle_observer._binding(store_b.task(task_b['id']))['status'] == 'completed')
                final = store_b.effects(task_b['id'])
                self.assertEqual([effect['effect_key'] for effect in final], [effect['effect_key'] for effect in effects_b])
                self.assertEqual([effect['status'] for effect in final], ['DONE'])
                self.assertEqual(runtime_b.counters(), (1, 1, 0))
                self.assertEqual(runtime_b.identity['runId'], task_b['run_id'])
                self.assertTrue(graph_a.closed)
            finally:
                runtime_a.finish.set()
                runtime_b.finish.set()
                for client in reversed(clients):
                    client.__exit__(None, None, None)
                for state in reversed(states):
                    state['store'].engine.dispose()
                    state['store'].native_db.db_engine.dispose()
            self.assertTrue(graph_b.closed)
            self.assertFalse(graph_b.installed)

    def test_original_registration_specs_create_independent_native_instances(self):
        self.exercise_instances(reuse_bound_settings=False)

    def test_first_server_bound_settings_rebind_to_second_graph(self):
        self.exercise_instances(reuse_bound_settings=True)


if __name__ == '__main__':
    unittest.main()
