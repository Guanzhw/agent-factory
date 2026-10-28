"""Research HTTPS factory respects explicit operator tool configuration."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_factory.config import Settings
from agent_factory_server import research


class ResearchSessionCompositionTests(unittest.TestCase):
    def settings(self):
        return Settings(db_url='postgresql://unused', jwt_key='synthetic-signing-key-at-least-32bytes')

    def installed_tools(self, settings=None):
        with patch.object(research.Settings, 'from_env', return_value=self.settings()), \
                patch.object(research, 'create_deployment') as deployment, \
                patch.object(research, 'install') as install:
            research.create_app(settings)
            deployment.call_args.kwargs['applications'][0].install(object())
            return install.call_args.kwargs['session_tools']

    @unittest.skipUnless(os.name == 'posix', 'Research host commands require POSIX')
    def test_no_argument_https_factory_uses_operator_environment(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
                'FACTORY_RESEARCH_WORKSPACE_ROOT': directory,
                'FACTORY_RESEARCH_HOST_COMMANDS': '1',
                'FACTORY_RESEARCH_COMMAND_PATH': '/usr/bin:/bin'}, clear=True):
            tools = self.installed_tools()
            self.assertEqual(tools.workspace_root, Path(directory))
            self.assertEqual(tools.command_path, '/usr/bin:/bin')
            self.assertIn('research_run', tools.available_tools)

    def test_explicit_settings_does_not_inherit_ambient_tool_opt_in(self):
        with patch.dict(os.environ, {'FACTORY_RESEARCH_HOST_COMMANDS': '1',
                'FACTORY_RESEARCH_WORKSPACE_ROOT': '/nonexistent'}, clear=True):
            tools = self.installed_tools(self.settings())
            self.assertIsNone(tools.workspace_root)
            self.assertNotIn('research_run', tools.available_tools)

    def test_normal_factory_loads_configured_timeouts_without_changing_defaults(self):
        environment = {'FACTORY_DATABASE_URL': 'postgresql://unused',
            'FACTORY_JWT_KEY': 'synthetic-signing-key-at-least-32bytes'}
        with patch.dict(os.environ, environment, clear=True):
            defaults = Settings.from_env()
        self.assertEqual((defaults.experiment_timeout_seconds, defaults.native_timeout_seconds), (8, 60))
        with patch.dict(os.environ, {**environment, 'FACTORY_OPERATION_TIMEOUT_SECONDS': '60',
                'FACTORY_NATIVE_TIMEOUT_SECONDS': '300'}, clear=True), \
                patch.object(research, 'create_deployment') as deployment:
            research.create_app()
        configured = deployment.call_args.args[0]
        self.assertEqual((configured.experiment_timeout_seconds, configured.native_timeout_seconds), (60, 300))

    def test_invalid_operation_timeout_is_rejected_at_startup(self):
        for value in ('0', '601', 'not-seconds'):
            with self.subTest(value=value), patch.dict(os.environ, {
                    'FACTORY_DATABASE_URL': 'postgresql://unused',
                    'FACTORY_JWT_KEY': 'synthetic-signing-key-at-least-32bytes',
                    'FACTORY_OPERATION_TIMEOUT_SECONDS': value}, clear=True), self.assertRaises(ValueError):
                research.create_app()

    def test_invalid_host_command_flag_rejects_factory_startup(self):
        with patch.dict(os.environ, {'FACTORY_RESEARCH_HOST_COMMANDS': 'true'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'FACTORY_RESEARCH_HOST_COMMANDS'):
                self.installed_tools()
