"""Real PostgreSQL/AgentOS startup and unchanged application data across restart."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import inspect
from pg_fixture import IsolatedPostgres
from agent_factory_research.config import ResearchSettings
from agent_factory_research.services import services_for, release_services
from agent_factory_server.main import create_app, factory_state


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ApplicationAssemblyPostgresTests(unittest.TestCase):
    def test_static_deployment_routes_schema_and_existing_project_survive_restart(self):
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, TemporaryDirectory() as directory:
            settings = ResearchSettings(db_url=database.url, workspace=Path(directory),
                temporary_policy='member-self-service', storage_low_water_bytes=1, max_workers=1)
            adapters, prices = list(settings.runtime_adapters), settings.usage_pricing
            original = None
            for restart in range(2):
                app = create_app(settings)
                state = factory_state(app)
                store = state['store']
                original_stop = state['lifecycle_observer'].stop

                async def observe_stop():
                    self.assertIs(services_for(store), state['research'])
                    await original_stop()

                state['lifecycle_observer'].stop = observe_stop
                try:
                    tables = set(inspect(store.engine).get_table_names())
                    self.assertTrue({'af_inference_waits', 'af_orx_task_experiments',
                        'af_openresearch_workspace_projects', 'af_autoresearch_runs'} <= tables)
                    self.assertFalse(hasattr(store, 'autoresearch'))
                    self.assertIs(state['research'].factory_store, store)
                    with TestClient(app) as client:
                        self.assertIsNotNone(state['http_app'].state.queue_worker)
                        client.post('/api/factory/demo/login', json={'persona': 'alice'}).raise_for_status()
                        for route in ('/api/health', '/api/factory/openresearch/capabilities',
                                      '/api/factory/autoresearch/presets'):
                            self.assertEqual(client.get(route).status_code, 200, route)
                        self.assertTrue(client.get('/api/factory/materials').json())
                        self.assertTrue(client.get('/api/factory/applications').json())
                        if restart == 0:
                            response = client.post('/api/factory/openresearch/projects', json={
                                'requestId': 'static-assembly-project', 'name': 'Synthetic retained project'})
                            self.assertEqual(response.status_code, 201, response.text)
                            original = response.json()
                        else:
                            response = client.get('/api/factory/openresearch/projects/' + original['id'])
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(response.json(), original)
                    self.assertIsNot(services_for(store), state['research'])
                    release_services(store)
                finally:
                    store.engine.dispose()
                    store.native_db.db_engine.dispose()
                self.assertEqual(settings.runtime_adapters, adapters)
                self.assertEqual(settings.usage_pricing, prices)


if __name__ == '__main__':
    unittest.main()
