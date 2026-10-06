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
