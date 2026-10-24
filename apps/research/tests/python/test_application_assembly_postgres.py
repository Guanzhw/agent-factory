"""Real PostgreSQL/AgentOS startup and unchanged application data across restart."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from pg_fixture import IsolatedPostgres  # pyright: ignore[reportMissingImports]
from agent_factory.personal_ssh import SSHEnrollmentConfig
from agent_factory.ssh_credentials import PROVIDER_ID as SSH_CREDENTIAL_PROVIDER_ID
from agent_factory_research.config import ResearchSettings
from agent_factory_research.platform_openresearch import PlatformOpenResearchConfig
from agent_factory_research.services import services_for, release_services
from agent_factory_research.ssh_openresearch import SSHOpenResearchConfig, SSHOpenResearchPackage, SSHOrxProvider, SSHServer
from agent_factory_server.main import create_app, factory_state


class CatalogOnlySSHPackage(SSHOpenResearchPackage):
    """Keep real owner catalog projection without preparing binaries or SSH."""
    def __init__(self, config, root):
        self.config, self.root = config, root
        self.personal_servers = None
        self.provider = SSHOrxProvider(self)
        self.close = Mock()


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ApplicationAssemblyPostgresTests(unittest.TestCase):
    def test_static_ssh_catalog_remains_owner_scoped_with_and_without_self_service(self):
        runtime = PlatformOpenResearchConfig('/synthetic/orx', '/synthetic/opencode', 'sha256:' + 'a' * 64)
        credentials = Mock(side_effect=AssertionError('Catalog reads must not acquire SSH credentials'))
        host_key = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        servers = tuple(SSHServer(owner + '-server', owner, '1', owner + ' server', '127.0.0.1',
            2234, 'agent', host_key, '/synthetic/' + owner, owner + '-binding', '1')
            for owner in ('alice', 'bob'))
        config = SSHOpenResearchConfig(runtime, servers, credentials)
        for self_service in (False, True):
            with self.subTest(self_service=self_service), \
                    IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, \
                    TemporaryDirectory() as directory:
                vault = SimpleNamespace(capabilities=lambda: {'providerIds': [SSH_CREDENTIAL_PROVIDER_ID] if self_service else []},
                    authorize=Mock(side_effect=AssertionError('No credential authorization expected')),
                    resolve=Mock(side_effect=AssertionError('No credential resolution expected')))
                settings = ResearchSettings(db_url=database.url, workspace=Path(directory),
                    temporary_policy='member-self-service', storage_low_water_bytes=1, max_workers=1,
                    personal_agent_commands_enabled=True, ssh_openresearch=config,
                    ssh_self_service=SSHEnrollmentConfig() if self_service else None,
                    credential_vault_factory=lambda engine: vault)
                with patch('agent_factory_research.ssh_openresearch.SSHOpenResearchPackage', CatalogOnlySSHPackage):
                    app = create_app(settings)
                store = factory_state(app)['store']
                package = store.application_environments.packages['openresearch:ssh']
                try:
                    with TestClient(app) as client:
                        for owner in ('alice', 'bob'):
                            client.post('/api/factory/demo/login', json={'persona': owner}).raise_for_status()
                            response = client.get('/api/factory/application-environments/capabilities')
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(response.json(), {'locations': ['ssh'], 'applications': ['openresearch'],
                                'modelSetup': '/api/factory/personal-models', 'preparationSubmitsResearch': False,
                                'selfServiceSSH': self_service, 'platformBillingEnabled': False,
                                'hardExternalBudgetEnforced': False})
                            response = client.get('/api/factory/application-environments/servers')
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(response.json(), [{'reference': owner + '-server',
                                'name': owner + ' server', 'defaultDirectory': '/synthetic/' + owner + '/research'}])
                        self.assertIs(package.personal_servers, store.personal_ssh)
                        if self_service:
                            self.assertIs(store.personal_ssh.package, package)
                    package.close.assert_called_once_with()
                    credentials.assert_not_called()
                    vault.authorize.assert_not_called()
                    vault.resolve.assert_not_called()
                finally:
                    store.engine.dispose()
                    store.native_db.db_engine.dispose()

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
                            assert original is not None
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
