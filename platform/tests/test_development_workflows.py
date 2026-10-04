"""Explicit profile wiring/bootstrap tests, without PostgreSQL or subprocesses."""
import asyncio
from contextlib import contextmanager
import importlib.util
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_factory import development_workflows as workflows
from agent_factory.config import Settings
from agent_factory.store import digest

ORIGIN = 'https://127.0.0.1:3443'
DATABASE = 'postgresql+psycopg://fixture:synthetic-not-a-key@127.0.0.1/development'


class DevelopmentWorkflowTests(unittest.TestCase):
    def settings(self, directory):
        return Settings(db_url=DATABASE, workspace=Path(directory), demo=True, development_mock_login=True,
            development_public_origin=ORIGIN, temporary_policy='admin-review', max_workers=1)

    def test_explicit_settings_install_only_controlled_owned_resources_and_close_bootstrap(self):
        store = SimpleNamespace(engine=SimpleNamespace(dispose=Mock()))
        with TemporaryDirectory() as directory, patch.object(workflows, 'Store', return_value=store), \
                patch.object(workflows, 'ProcessResourceProvider') as providers, patch.object(workflows.sys, 'platform', 'linux'), \
                patch.object(workflows.stat, 'S_IMODE', return_value=0o700):
            base = self.settings(directory)
            with workflows.controlled_workflow_settings(base) as settings:
                self.assertIs(settings.demo, True)
                self.assertIs(settings.source_synthesis_enabled, True)
                self.assertEqual(settings.runtime_tool_contract, workflows.PROFILE)
                self.assertEqual(settings.temporary_policy, 'admin-review')
                self.assertEqual(len(settings.remote_targets), 5)
                self.assertEqual(len(settings.trusted_connections), 4)
                self.assertEqual(settings.development_profile, 'disabled')
                self.assertEqual(settings.handoff_targets, {})
                self.assertEqual(providers.call_count, 5)
                self.assertEqual({target.capacity_pool.pool_id for target in settings.remote_targets.values()}, {'development-comparison-pool'})
                self.assertTrue(all(target.owners == frozenset({'alice', 'bob'}) for target in settings.remote_targets.values()))
                self.assertFalse(base.source_synthesis_enabled)
                self.assertEqual(base.remote_targets, {})
                store.engine.dispose.assert_not_called()
            store.engine.dispose.assert_called_once()
            self.assertTrue((Path(directory) / 'controlled-workflows').is_dir())

    def test_profile_failure_disposes_engine_and_never_falls_back(self):
        store = SimpleNamespace(engine=SimpleNamespace(dispose=Mock()))
        with TemporaryDirectory() as directory, patch.object(workflows, 'Store', return_value=store), \
                patch.object(workflows, 'ProcessResourceProvider', side_effect=RuntimeError('synthetic failure')), \
                patch.object(workflows.sys, 'platform', 'linux'), \
                patch.object(workflows.stat, 'S_IMODE', return_value=0o700):
            with self.assertRaises(RuntimeError):
                with workflows.controlled_workflow_settings(self.settings(directory)):
                    self.fail('No fallback profile')
            store.engine.dispose.assert_called_once()

    def test_profile_rejects_implicit_nonlinux_or_existing_external_configuration(self):
        with TemporaryDirectory() as directory, patch.object(workflows, 'Store') as store:
            for update in ({'demo': False}, {'development_mock_login': False}, {'temporary_policy': 'read-only-auto'},
                           {'remote_targets': {'external': object()}}, {'handoff_targets': {'external': object()}},
                           {'development_profile': 'opencode-go'}):
                settings = self.settings(directory)
                for key, value in update.items():
                    setattr(settings, key, value)
                with self.assertRaises(ValueError):
                    with workflows.controlled_workflow_settings(settings):
                        self.fail('Invalid profile accepted')
            with patch.object(workflows.sys, 'platform', 'win32'), self.assertRaises(ValueError):
                with workflows.controlled_workflow_settings(self.settings(directory)):
                    self.fail('Unsupported platform accepted')
            store.assert_not_called()

    def test_synthetic_retrieval_has_no_network_or_real_source_claim(self):
        async def retrieve():
            provider = workflows.pubmed_profile.PubMedProvider('alice', workflows.httpx.MockTransport(workflows._synthetic_request))
            return await provider.retrieve(before_dispatch=lambda: None)
        result = asyncio.run(retrieve())
        self.assertEqual(result['evidenceMode'], 'controlled-fixture')
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['evidenceKind'], 'controlled_literature_fixture')
        self.assertIn('not a real paper', result['sources'][0]['title'])
        with self.assertRaises(ValueError):
            workflows._synthetic_request(workflows.httpx.Request('GET', 'https://example.invalid/'))

    def state(self, directory):
        settings = self.settings(directory)
        settings.runtime_tool_contract = workflows.PROFILE
        settings.source_synthesis_enabled = True
        definitions = {}
        applications = {}
        def draft(owner, definition, request):
            row = {**definition, 'version': 1, 'sha256': digest(definition), 'published': True}
            definitions[(row['id'], 1)] = row
            return row
        governance = SimpleNamespace(create_draft=Mock(side_effect=draft),
            request_publication=Mock(side_effect=lambda owner, identifier, version, request: {'id': identifier + '-review'}),
            decide_publication=Mock(), inspect_version=Mock(side_effect=lambda owner, identifier, version:
                {'material': definitions[(identifier, version)], 'governance': {'state': 'published'}}))
        def application(owner, definition, request):
            row = {**definition, 'version': 1, 'sha256': digest(definition)}
            applications[(row['id'], 1)] = row
            return row
        app = SimpleNamespace(create_draft=Mock(side_effect=application),
            request_publication=Mock(side_effect=lambda owner, identifier, version, request: {'id': identifier + '-review'}),
            decide_publication=Mock(), inspect=Mock(side_effect=lambda owner, identifier, version:
                {'application': applications[(identifier, version)], 'governance': {'state': 'published'}}))
        return {'store': SimpleNamespace(settings=settings), 'auth': SimpleNamespace(require=Mock()),
                'material_governance': governance, 'applications': app,
                'connections': SimpleNamespace(bind=Mock(return_value={'status': 'revoked'}))}

    def test_explicit_bootstrap_uses_separate_review_and_stable_connection_commands(self):
        with TemporaryDirectory() as directory:
            state = self.state(directory)
            result = workflows.initialize_controlled_fixtures(state)
            self.assertEqual(len(result['applications']), 3)
            self.assertFalse(result['planApprovalGranted'])
            self.assertTrue(result['syntheticOnly'])
            for service in ('material_governance', 'applications'):
                self.assertTrue(all(call.args[0] == 'manager' for call in state[service].create_draft.call_args_list))
                self.assertTrue(all(call.args[0] == 'manager2' and call.args[2] is True
                                    for call in state[service].decide_publication.call_args_list))
            first = list(state['connections'].bind.call_args_list)
            workflows.initialize_controlled_fixtures(state)
            self.assertEqual(first, state['connections'].bind.call_args_list[4:])
            self.assertEqual({call.args[0] for call in first}, {'alice', 'bob'})

    def test_revoked_manager_and_withdrawn_material_stop_bootstrap(self):
        with TemporaryDirectory() as directory:
            state = self.state(directory)
            state['auth'].require.side_effect = PermissionError('synthetic revoked')
            with self.assertRaises(PermissionError):
                workflows.initialize_controlled_fixtures(state)
            state['material_governance'].create_draft.assert_not_called()
            state = self.state(directory)
            state['material_governance'].inspect_version.side_effect = None
            state['material_governance'].inspect_version.return_value = {'material': {'published': False}, 'governance': {'state': 'withdrawn'}}
            with self.assertRaises(ValueError):
                workflows.initialize_controlled_fixtures(state)
            state['connections'].bind.assert_not_called()


class ControlledLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / 'scripts' / 'run_development_factory.py'
        spec = importlib.util.spec_from_file_location('controlled_launcher_fixture', path)
        assert spec is not None and spec.loader is not None
        cls.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.launcher)

    def test_explicit_controlled_bootstrap_precedes_serve_and_closes_owned_engines(self):
        order = []
        @contextmanager
        def profile(settings):
            order.append('profile')
            yield settings
            order.append('profile-close')
        @contextmanager
        def tls(origin):
            yield Path('synthetic-cert'), Path('synthetic-key')
        store = SimpleNamespace(engine=SimpleNamespace(dispose=Mock()),
            native_db=SimpleNamespace(db_engine=SimpleNamespace(dispose=Mock())))
        state = {'store': store}
        app = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(factory=state)))
        with TemporaryDirectory() as directory, patch.object(self.launcher, 'controlled_workflow_settings', profile), \
                patch.object(self.launcher, 'create_app', return_value=app), \
                patch.object(self.launcher, 'initialize_controlled_fixtures', side_effect=lambda value: order.append('initialize')) as initialize, \
                patch.object(self.launcher, 'temporary_development_tls', tls), \
                patch.object(self.launcher.uvicorn, 'run', side_effect=lambda *args, **kwargs: order.append('serve')), \
                patch.object(self.launcher.os, 'getenv', side_effect=AssertionError('No environment reads')), \
                patch('sys.stdout', new_callable=io.StringIO):
            result = self.launcher.main(['--public-origin', ORIGIN, '--workspace', directory, '--database-url', DATABASE,
                '--profile', 'controlled-workflows', '--initialize-controlled-fixtures'])
        self.assertEqual(result, 0)
        self.assertEqual(order, ['profile', 'initialize', 'serve', 'profile-close'])
        initialize.assert_called_once_with(state)
        store.engine.dispose.assert_called_once()
        store.native_db.db_engine.dispose.assert_called_once()

    def test_controlled_restart_without_bootstrap_does_not_publish_or_bind(self):
        @contextmanager
        def profile(settings):
            yield settings
        @contextmanager
        def tls(origin):
            yield Path('synthetic-cert'), Path('synthetic-key')
        store = SimpleNamespace(engine=SimpleNamespace(dispose=Mock()),
            native_db=SimpleNamespace(db_engine=SimpleNamespace(dispose=Mock())))
        app = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(factory={'store': store})))
        with TemporaryDirectory() as directory, patch.object(self.launcher, 'controlled_workflow_settings', profile), \
                patch.object(self.launcher, 'create_app', return_value=app), \
                patch.object(self.launcher, 'initialize_controlled_fixtures') as initialize, \
                patch.object(self.launcher, 'temporary_development_tls', tls), \
                patch.object(self.launcher.uvicorn, 'run') as run, patch('sys.stdout', new_callable=io.StringIO):
            result = self.launcher.main(['--public-origin', ORIGIN, '--workspace', directory,
                '--database-url', DATABASE, '--profile', 'controlled-workflows'])
        self.assertEqual(result, 0)
        initialize.assert_not_called()
        run.assert_called_once()

    def test_initialization_requires_selected_profile_and_sanitizes_failure(self):
        with TemporaryDirectory() as directory, patch.object(self.launcher, 'create_app') as create, \
                patch('sys.stderr', new_callable=io.StringIO) as errors:
            result = self.launcher.main(['--public-origin', ORIGIN, '--workspace', directory,
                '--database-url', DATABASE, '--initialize-controlled-fixtures'])
        self.assertEqual(result, 1)
        create.assert_not_called()
        self.assertEqual(errors.getvalue(), 'DEVELOPMENT_LAUNCH_FAILED\n')


if __name__ == '__main__':
    unittest.main()
