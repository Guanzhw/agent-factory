"""Declarative operator gates; no database, model, receiver, or provider calls."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent_factory.config import Settings

_spec = importlib.util.spec_from_file_location('tested_autoresearch_operator',
    Path(__file__).resolve().parents[2] / 'scripts' / 'autoresearch_operator.py')
assert _spec and _spec.loader
operator = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = operator
_spec.loader.exec_module(operator)


def config():
    return {'schema': 1, 'role': 'controller', 'workspace': str(Path.cwd()), 'port': 3100,
        'databaseRef': 'EXISTING_DATABASE', 'jwtRef': 'EXISTING_JWT',
        'handoffBearerRef': 'EXISTING_HANDOFF', 'project': {'presetId': 'reviewed-science', 'applicationRef': {'id': 'existing'}},
        'publication': {'author': 'manager', 'reviewer': 'reviewer'}}


class OperatorTests(unittest.TestCase):
    def bindings(self):
        def describe(value, url):
            return Settings(db_url=url, workspace=Path(value['workspace']), host='127.0.0.1', port=value['port'])
        return operator.OperatorBindings(Mock(side_effect=describe), Mock(), Mock())

    def test_strict_json_and_fields(self):
        self.assertEqual(operator.configuration(json.dumps(config()).encode()), config())
        for raw in (b'{"schema":1,"schema":1}', b'{"x":NaN}', b'{}', b'[]'):
            with self.assertRaises(ValueError): operator.configuration(raw)
        for key, value in (('port', True), ('workspace', '../private'), ('jwtRef', 'secret=value'),
                ('role', 'execute'), ('publication', {'author': 'same', 'reviewer': 'same'})):
            changed = {**config(), key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                operator.configuration(json.dumps(changed).encode())
        with self.assertRaises(ValueError):
            operator.configuration(json.dumps({**config(), 'candidate': 'prescribed'}).encode())

    def test_sqlite_does_not_create_a_file_during_check(self):
        engine = Mock()
        with self.assertRaises(ValueError):
            operator.execute(config(), self.bindings(), 'check', resolve=lambda _: 'sqlite:///missing.db',
                engine_factory=engine)
        engine.assert_not_called()

    def test_check_reads_only_database_reference_and_never_constructs(self):
        bindings = self.bindings(); engine = Mock(); resolver = Mock(return_value='postgresql://unused')
        report = {'schema': 1, 'status': 'PASS', 'checks': [], 'executionVerified': False}
        check = Mock(return_value=report)
        self.assertEqual(operator.execute(config(), bindings, 'check', resolve=resolver,
            engine_factory=Mock(return_value=engine), preflight=check), report)
        resolver.assert_called_once_with('EXISTING_DATABASE')
        bindings.construct_application.assert_not_called(); bindings.prepare_publication.assert_not_called()
        engine.dispose.assert_called_once()

    def test_uninitialized_or_incompatible_database_blocks_all_effects(self):
        for status in ('BLOCKED', 'NOT_CHECKED'):
            bindings = self.bindings(); engine = Mock()
            operator.execute(config(), bindings, 'serve', resolve=lambda _: 'postgresql://unused',
                engine_factory=Mock(return_value=engine), preflight=lambda *_: {'status': status})
            bindings.construct_application.assert_not_called()
            bindings.prepare_publication.assert_not_called()
            engine.dispose.assert_called_once()

    def test_prepare_is_explicit_and_serve_is_loopback(self):
        for action in ('prepare', 'serve'):
            bindings = self.bindings(); server = Mock()
            operator.execute(config(), bindings, action, resolve=lambda _: 'postgresql://unused',
                engine_factory=Mock(return_value=Mock()), preflight=lambda *_: {'status': 'PASS'}, serve=server)
            bindings.construct_application.assert_called_once()
            if action == 'prepare':
                bindings.prepare_publication.assert_called_once_with(bindings.construct_application.return_value,
                    config()['publication']); server.assert_not_called()
            else:
                bindings.prepare_publication.assert_not_called()
                server.assert_called_once_with(bindings.construct_application.return_value,
                    host='127.0.0.1', port=3100, access_log=False)

    def test_cli_error_never_echoes_private_argument(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(operator.main(['--unknown', '/private/sensitive']), 2)
        self.assertNotIn('/private', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'BLOCKED')

    @unittest.skipUnless(os.name == 'posix', 'POSIX private file custody')
    def test_private_file_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as area:
            path = Path(area) / 'operator.json'; path.write_text(json.dumps(config())); path.chmod(0o600)
            self.assertEqual(operator.read_configuration(path), config())
            path.chmod(0o644)
            with self.assertRaises(ValueError): operator.read_configuration(path)
            path.chmod(0o600)
            link = Path(area) / 'linked'; link.symlink_to(path)
            with self.assertRaises(OSError): operator.read_configuration(link)

    def test_existing_environment_reference_resolves_lazily(self):
        with patch.dict(os.environ, {'TEST_OPERATOR_EXISTING': 'synthetic'}, clear=True):
            self.assertEqual(operator.environment_resolver('TEST_OPERATOR_EXISTING'), 'synthetic')
            with self.assertRaises(ValueError): operator.environment_resolver('MISSING')
