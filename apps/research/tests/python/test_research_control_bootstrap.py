"""Offline launcher boundaries; no PostgreSQL connection, socket or subprocess."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('control_bootstrap', Path(__file__).parents[4] / 'scripts/bootstrap_research_control.py')
assert spec is not None and spec.loader is not None
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


@unittest.skipUnless(os.name == 'posix', 'Private nofollow launcher requires POSIX')
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.url = self.root / 'database-url'
        self.url.write_text('postgresql+psycopg://fixture:synthetic-only@127.0.0.1:65432/control_test')
        self.url.chmod(0o600)
        self.workspace = self.root / 'control'
        self.args = ['--database-url-file', str(self.url), '--workspace', str(self.workspace), '--port', '3101',
                     '--ack-local-development', '--ack-dedicated-database']

    def call(self, args=None, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bootstrap.main(self.args if args is None else args, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def test_trusted_factory_receives_native_settings_and_loopback_only(self):
        factory, serve = Mock(return_value=object()), Mock()
        self.assertEqual(self.call(build_application=factory, serve=serve), (0, '', ''))
        settings = factory.call_args.args[0]
        self.assertTrue(settings.demo)
        self.assertTrue(settings.db_url.endswith('?hostaddr=127.0.0.1&connect_timeout=5'))
        self.assertEqual(settings.temporary_policy, 'member-self-service')
        self.assertEqual(settings.material_review_mode, 'member-self-service')
        self.assertEqual((settings.max_workers, settings.max_user_tasks, settings.max_total_tasks), (1, 1, 1))
        self.assertEqual(settings.remote_targets, {})
        self.assertEqual(settings.research_evaluators, {})
        self.assertFalse(settings.development_live_validation)
        self.assertEqual(serve.call_args.kwargs, dict(host='127.0.0.1', port=3101, workers=1,
                                                    access_log=False, log_config=None))
        self.assertEqual(self.workspace.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.workspace.iterdir()), [])  # No credential or synthetic ID persisted by launcher.

    def test_check_is_not_connection_or_authorization_and_writes_nothing(self):
        factory, serve = Mock(), Mock()
        self.assertEqual(self.call(self.args + ['--check-config'], build_application=factory, serve=serve),
                         (0, 'RESEARCH_CONTROL_CONFIG_VALID_NOT_CONNECTED\n', ''))
        factory.assert_not_called(); serve.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_explicit_acknowledgements_and_no_arbitrary_factory_or_public_host(self):
        for args in (self.args[:-1], self.args + ['--host', '0.0.0.0'], self.args + ['--factory', 'evil.module']):
            with self.subTest(args=args[-2:]):
                factory = Mock()
                self.assertEqual(self.call(args, build_application=factory), (2, '', bootstrap.FAILURE + '\n'))
                factory.assert_not_called()

    def test_existing_workspace_is_never_reset_or_attached(self):
        self.workspace.mkdir()
        marker = self.workspace / 'original'
        marker.write_bytes(b'original')
        factory = Mock()
        self.assertEqual(self.call(build_application=factory), (2, '', bootstrap.FAILURE + '\n'))
        self.assertEqual(marker.read_bytes(), b'original')
        factory.assert_not_called()

    def test_database_no_external_host_query_multihost_or_service_override(self):
        for value in ('postgresql+psycopg://u:p@example.org:5432/db',
                      'postgresql+psycopg://u:p@localhost:5432/db',
                      'postgresql+psycopg://u:p@127.0.0.1:5432/db?host=outside',
                      'postgresql+psycopg://u:p@127.0.0.1,127.0.0.2:5432/db',
                      'postgresql+psycopg://u:p@127.0.0.1:5432/db\n'):
            with self.subTest(value=value):
                self.url.write_text(value)
                self.assertEqual(self.call(self.args + ['--check-config']), (2, '', bootstrap.FAILURE + '\n'))

    def test_private_regular_singlelink_bounded_file_and_capability_required(self):
        for mode in (0o644, 0o666):
            self.url.chmod(mode)
            self.assertEqual(self.call(self.args + ['--check-config'])[0], 2)
        self.url.chmod(0o600)
        alias = self.root / 'alias'
        alias.symlink_to(self.url)
        self.assertRaises((ValueError, OSError), bootstrap.read_database_url, str(alias))
        alias.unlink(); os.link(self.url, alias)
        self.assertRaises(ValueError, bootstrap.read_database_url, str(self.url))
        alias.unlink(); self.url.write_bytes(b'a' * 4097)
        self.assertRaises(ValueError, bootstrap.read_database_url, str(self.url))
        with patch.object(bootstrap.os, 'O_NOFOLLOW', 0):
            self.assertRaises(ValueError, bootstrap.read_database_url, str(self.url))

    def test_initialization_failure_sanitized_and_not_retried(self):
        factory = Mock(side_effect=RuntimeError('private DSN password or path must not leak'))
        serve = Mock()
        self.assertEqual(self.call(build_application=factory, serve=serve), (2, '', bootstrap.FAILURE + '\n'))
        factory.assert_called_once(); serve.assert_not_called()
        self.assertTrue(self.workspace.exists())  # Preserve partial state for investigation, no automatic reset.

    def test_database_file_replacement_during_read_is_rejected(self):
        original = bootstrap.os.read
        def swap(fd, count):
            data = original(fd, count)
            self.url.unlink()
            self.url.write_bytes(data)
            self.url.chmod(0o600)
            return data
        with patch.object(bootstrap.os, 'read', side_effect=swap):
            self.assertRaises(ValueError, bootstrap.read_database_url, str(self.url))
