"""Fixed public diagnostics only; synthetic mocks, no credential or DB access."""
from contextlib import redirect_stderr, redirect_stdout
import asyncio
import importlib
import io
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings

import httpx
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

import test_research_baseline_runner as fixture

runner = fixture.runner
SECRET = 'synthetic-private-path/postgresql://owner:password@loopback/request-id'


class HostileError(RuntimeError):
    def __str__(self):
        raise AssertionError('Exception string must not be accessed')

    @property
    def __class__(self):
        raise AssertionError('Exception class property must not be accessed')

    @property
    def __context__(self):
        raise AssertionError('Exception context must not be accessed')

    @property
    def args(self):
        raise AssertionError('Exception args must not be accessed')

    @property
    def __cause__(self):
        raise AssertionError('Exception cause must not be accessed')


class DiagnosticsTests(unittest.TestCase):
    def output(self, diagnostics):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            diagnostics.emit()
        self.assertLessEqual(len(stderr.getvalue().encode('utf-8')), 512)
        return json.loads(stderr.getvalue())

    def test_fixed_classes_do_not_disclose_payloads(self):
        cases = [(FileNotFoundError(SECRET), 'FILE_NOT_FOUND'), (PermissionError(SECRET), 'PERMISSION_DENIED'),
            (ModuleNotFoundError(SECRET), 'MODULE_NOT_FOUND'), (ImportError(SECRET), 'IMPORT_ERROR'),
            (ValueError(SECRET), 'VALIDATION_REJECTED'), (TypeError(SECRET), 'TYPE_INVALID'),
            (KeyError(SECRET), 'FIELD_MISSING'), (RuntimeError(SECRET), 'RUNTIME_ERROR'),
            (OSError(SECRET), 'OS_ERROR'), (TimeoutError(SECRET), 'TIMEOUT'),
            (KeyboardInterrupt(SECRET), 'INTERRUPTED'), (SystemExit(SECRET), 'SYSTEM_EXIT'),
            (asyncio.CancelledError(SECRET), 'CANCELLED'), (HTTPException(403, SECRET), 'HTTP_REJECTED'),
            (httpx.ReadTimeout(SECRET), 'HTTP_TIMEOUT'), (httpx.ConnectError(SECRET), 'HTTP_ERROR'),
            (OperationalError(SECRET, {}, RuntimeError(SECRET)), 'DATABASE_OPERATIONAL'),
            (IntegrityError(SECRET, {}, RuntimeError(SECRET)), 'DATABASE_INTEGRITY'),
            (json.JSONDecodeError(SECRET, SECRET, 0), 'CONFIG_JSON_INVALID'),
            (HostileError(SECRET), 'RUNTIME_ERROR'), (BaseException(SECRET), 'UNEXPECTED_ERROR')]
        for error, expected in cases:
            with self.subTest(expected=expected):
                diagnostics = runner.Diagnostics(); diagnostics.at('DATABASE_CONFIG'); diagnostics.capture(error)
                value = self.output(diagnostics)
                self.assertEqual(value, {'schema': 1, 'kind': 'RESEARCH_BASELINE_DIAGNOSTIC',
                    'stage': 'DATABASE_CONFIG', 'errorCode': expected})
                self.assertNotIn(SECRET, json.dumps(value))

    def test_first_failure_survives_stage_change_recapture_and_secondary_failure(self):
        diagnostics = runner.Diagnostics()
        original, secondary = HostileError(SECRET), PermissionError(SECRET)
        diagnostics.at('TRAINING_RUN'); diagnostics.capture(original)
        diagnostics.at('TRAINING_SHUTDOWN'); diagnostics.capture(original)
        self.assertNotIn('secondaryErrorCode', self.output(diagnostics))
        diagnostics.capture(secondary)
        diagnostics.at('CLEANUP'); diagnostics.capture(ValueError(SECRET))
        self.assertEqual(self.output(diagnostics), {'schema': 1, 'kind': 'RESEARCH_BASELINE_DIAGNOSTIC',
            'stage': 'TRAINING_RUN', 'errorCode': 'RUNTIME_ERROR',
            'secondaryStage': 'TRAINING_SHUTDOWN', 'secondaryErrorCode': 'PERMISSION_DENIED'})

    def test_stages_are_closed_and_progress_delegates_without_writing(self):
        diagnostics = runner.Diagnostics()
        progress = runner.Progress(Path('/synthetic-unused'), diagnostics)
        for stage in ('CONFIG_READ', 'CONFIG_VALIDATE', 'WORKSPACE_CREATE', 'EXECUTION_IMPORTS',
            'EXECUTION_IDENTITY', 'DATABASE_CONFIG', 'PREPARATION_ASSEMBLY', 'PREPARATION_STARTUP',
            'TRAINING_RUN', 'EVALUATION_RUN'):
            progress.at(stage)
        for invalid in (SECRET, True, None, [], 7):
            with self.assertRaises(ValueError): progress.at(invalid)
        progress.capture(ValueError(SECRET))
        self.assertEqual(self.output(diagnostics)['stage'], 'EVALUATION_RUN')


class MainDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.config = fixture.config(Path(self.temp.name))
        self.path_patch = patch.object(sys, 'path', [str(fixture.SCRIPTS), *sys.path])
        self.path_patch.start(); self.addCleanup(self.path_patch.stop)
        self.bootstrap = importlib.import_module('bootstrap_research_control')

    def call(self, execute, *, raw=None, read_error=None, workspace_error=None, write=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(runner, 'read_private', return_value=raw if raw is not None else runner.canonical(self.config),
                          side_effect=read_error), \
             patch.object(self.bootstrap, '_workspace', side_effect=workspace_error), \
             patch.object(runner, 'write_private', side_effect=write), redirect_stdout(out), redirect_stderr(err):
            code = runner.main(['--config', str(Path(self.temp.name) / 'synthetic-config')], run=execute)
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), '')
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], runner.ERROR)
        self.assertNotIn(SECRET, err.getvalue())
        self.assertNotIn(self.temp.name, err.getvalue())
        self.assertLessEqual(len(lines[1].encode('utf-8')), 512)
        value = json.loads(lines[1])
        self.assertEqual(value['kind'], 'RESEARCH_BASELINE_DIAGNOSTIC')
        return value

    def test_initial_read_validation_and_workspace_fail_before_executor(self):
        for options, stage, code in [({'read_error': PermissionError(SECRET)}, 'CONFIG_READ', 'PERMISSION_DENIED'),
            ({'raw': b'{invalid'}, 'CONFIG_VALIDATE', 'CONFIG_JSON_INVALID'),
            ({'workspace_error': OSError(SECRET)}, 'WORKSPACE_CREATE', 'OS_ERROR')]:
            with self.subTest(stage=stage):
                execute = Mock()
                value = self.call(execute, **options)
                self.assertEqual((value['stage'], value['errorCode']), (stage, code))
                execute.assert_not_called()

    def test_execution_print_warning_and_hostile_error_never_escape_or_replay(self):
        calls = []
        old_logging = logging.root.manager.disable
        def execute(config, workspace, progress):
            calls.append(config['requestId'])
            progress.at('EXECUTION_IDENTITY')
            print(SECRET); print(SECRET, file=sys.stderr); warnings.warn(SECRET)
            raise HostileError(SECRET)
        value = self.call(execute)
        self.assertEqual(value['stage'], 'EXECUTION_IDENTITY')
        self.assertEqual(value['errorCode'], 'RUNTIME_ERROR')
        self.assertEqual(calls, [self.config['requestId']])
        self.assertEqual(logging.root.manager.disable, old_logging)

    def test_stopped_journal_failure_does_not_replace_original_or_retry(self):
        writes = []
        def write(path, raw):
            phase = json.loads(raw)['progress']['phase']; writes.append(phase)
            if phase == 'STOPPED': raise PermissionError(SECRET)
        execute = Mock(side_effect=HostileError(SECRET))
        value = self.call(execute, write=write)
        self.assertEqual((value['stage'], value['errorCode']), ('EXECUTE', 'RUNTIME_ERROR'))
        self.assertEqual(value['secondaryErrorCode'], 'PERMISSION_DENIED')
        self.assertEqual(value['secondaryStage'], 'PROGRESS_STOPPED')
        self.assertEqual(writes, ['STARTED', 'STOPPED'])
        execute.assert_called_once()

    def execute_boundary(self, *, assembly_error=None, startup_error=None, body_error: BaseException | None = None,
                         shutdown_error=None, dispose_error=None):
        """Exercise real execute with inert preflight/provider/lifespan boundaries."""
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import agent_factory
        import fastapi.testclient
        from agent_factory import research_bootstrap_assembly, research_device_observer, research_profile

        self.config['interpreterTarget'] = str(Path(sys.executable).resolve())
        fake_module = Path(self.config['venvRoot']) / 'lib' / (
            f'python{sys.version_info.major}.{sys.version_info.minor}') / 'site-packages/agent_factory/__init__.py'
        stores = [SimpleNamespace(dispose_root_locks=Mock(), engine=SimpleNamespace(dispose=Mock(
            side_effect=dispose_error)), native_db=None),
            SimpleNamespace(dispose_root_locks=Mock(), engine=SimpleNamespace(dispose=Mock()), native_db=None)]
        bundle = {'app': object(), 'state': {'store': stores[0]}, 'providerStore': stores[1]}
        assembly = Mock(return_value=bundle, side_effect=assembly_error)
        context = MagicMock()
        context.__enter__.side_effect = startup_error
        context.__exit__.side_effect = shutdown_error
        context.__exit__.return_value = False

        def body(unused_bundle, unused_client, unused_request, progress):
            progress.at('PREPARATION_PUBLICATION')
            if body_error is None:
                raise AssertionError('Preparation body must not execute for earlier failure')
            raise body_error

        with ExitStack() as patches:
            patches.enter_context(patch.object(runner, 'identity', return_value={'device': 1, 'inode': 2}))
            patches.enter_context(patch.object(sys, 'dont_write_bytecode', True))
            patches.enter_context(patch.object(sys, 'prefix', self.config['venvRoot']))
            patches.enter_context(patch.object(agent_factory, '__file__', str(fake_module)))
            database = patches.enter_context(patch.object(self.bootstrap, 'read_database_url',
                return_value='postgresql+psycopg://synthetic-unused/unused'))
            patches.enter_context(patch.object(research_profile, 'verify_upstream_source'))
            device = patches.enter_context(patch.object(research_device_observer, 'NvidiaSmiObserver', return_value=object()))
            patches.enter_context(patch.object(research_bootstrap_assembly, 'prepare_application', assembly))
            research = patches.enter_context(patch.object(research_bootstrap_assembly, 'research_application',
                side_effect=AssertionError('No training/evaluation assembly after preparation failure')))
            client = patches.enter_context(patch.object(fastapi.testclient, 'TestClient', return_value=context))
            preparation = patches.enter_context(patch.object(runner, 'preparation_phase', side_effect=body))
            value = self.call(runner.execute,
                workspace_error=lambda path, create: Path(path).mkdir(mode=0o700))
        assembly.assert_called_once()
        database.assert_called_once_with(self.config['databaseUrlFile'])
        device.assert_called_once()
        research.assert_not_called()
        return value, client, context, preparation, stores

    def test_real_execute_assembly_failure_reports_original_boundary(self):
        value, client, _, preparation, _ = self.execute_boundary(assembly_error=RuntimeError(SECRET))
        self.assertEqual((value['stage'], value['errorCode']), ('PREPARATION_ASSEMBLY', 'RUNTIME_ERROR'))
        client.assert_not_called()
        preparation.assert_not_called()

    def test_real_execute_startup_failure_disposes_without_entering_preparation(self):
        value, client, context, preparation, stores = self.execute_boundary(startup_error=PermissionError(SECRET))
        self.assertEqual((value['stage'], value['errorCode']), ('PREPARATION_STARTUP', 'PERMISSION_DENIED'))
        client.assert_called_once()
        context.__enter__.assert_called_once()
        context.__exit__.assert_not_called()
        preparation.assert_not_called()
        for store in stores:
            store.dispose_root_locks.assert_called_once()
            store.engine.dispose.assert_called_once()

    def test_real_execute_body_failure_survives_shutdown_and_dispose_failures(self):
        value, client, context, preparation, stores = self.execute_boundary(body_error=ValueError(SECRET),
            shutdown_error=PermissionError(SECRET), dispose_error=RuntimeError(SECRET))
        self.assertEqual(value, {'schema': 1, 'kind': 'RESEARCH_BASELINE_DIAGNOSTIC',
            'stage': 'PREPARATION_PUBLICATION', 'errorCode': 'VALIDATION_REJECTED',
            'secondaryStage': 'PREPARATION_SHUTDOWN', 'secondaryErrorCode': 'PERMISSION_DENIED'})
        client.assert_called_once()
        preparation.assert_called_once()
        context.__exit__.assert_called_once()
        stores[0].engine.dispose.assert_called_once()
