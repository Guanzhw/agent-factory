"""Static application ownership and teardown preserve the shared runtime lifetime."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_factory.config import Settings
from agent_factory_research.assembly import abort_research_install, research_shutdown
from agent_factory_research.services import ResearchServices


class ApplicationAssemblyTests(unittest.TestCase):
    def test_failed_install_closes_every_local_constructor_and_releases_graph(self):
        store = SimpleNamespace(application_environments=Mock(), personal_ssh=Mock(),
            dispose_root_locks=Mock(), engine=Mock())
        store.application_environments.close.side_effect = ValueError('synthetic close failure')
        original = ResearchServices(store, installed=True)
        other_store = SimpleNamespace()
        other = ResearchServices(other_store, installed=True)
        abort_research_install({'store': store, 'research': original})
        store.application_environments.close.assert_called_once_with()
        store.personal_ssh.close.assert_called_once_with()
        store.engine.dispose.assert_called_once_with()
        store.dispose_root_locks.assert_called_once_with()
        self.assertTrue(original.closed)
        self.assertFalse(original.installed)
        self.assertIs(other.require_store(other_store, ready=True), other)

    def test_graph_is_retained_until_explicit_native_shutdown_completion(self):
        store = SimpleNamespace()
        original = ResearchServices(store, installed=True)
        other_store = SimpleNamespace()
        other = ResearchServices(other_store, installed=True)
        original.research_runtime = object()
        self.assertIs(original.require_store(store, ready=True), original)
        research_shutdown({'store': store, 'research': original})
        self.assertTrue(original.closed)
        self.assertFalse(original.installed)
        with self.assertRaisesRegex(ValueError, 'RESEARCH_STORE_MISMATCH'):
            original.require_store(store, ready=True)
        self.assertIs(other.require_store(other_store, ready=True), other)

    def test_production_and_normal_environment_defaults_are_member_self_service(self):
        settings = Settings(db_url='postgresql://unused', demo=False, jwt_key='synthetic-key-' * 4)
        self.assertEqual(settings.temporary_policy, 'member-self-service')
        self.assertEqual(settings.policy_revision, 'department-member-v1')
        self.assertEqual(settings.material_review_mode, 'member-self-service')
        self.assertEqual(settings.material_policy_revision, 'material-department-v1')
        with patch.dict('os.environ', {'FACTORY_DATABASE_URL': 'postgresql://unused'}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.temporary_policy, 'member-self-service')
        self.assertEqual(settings.material_review_mode, 'member-self-service')
        self.assertEqual(settings.web_directory, Path('dist').resolve())


if __name__ == '__main__':
    unittest.main()
