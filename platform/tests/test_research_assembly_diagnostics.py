"""Offline canonical assembly diagnostics: construction only, no lifespan or DB."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_research_baseline_runner as fixture

runner = fixture.runner


@unittest.skipUnless(os.name == 'posix', 'Canonical private workspace is POSIX only')
class AssemblyDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.config = fixture.config(self.root)
        self.path = self.root / 'config.json'
        self.path.write_bytes(runner.canonical(self.config)); self.path.chmod(0o600)
        self.tokenizer = self.root / 'inputs/tokenizer.json'
        self.tokenizer.parent.mkdir(mode=0o700); self.tokenizer.write_bytes(b'synthetic tokenizer')
        self.tokenizer.chmod(0o600)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(sys, 'path', [str(fixture.SCRIPTS), *sys.path]))
        self.bootstrap = importlib.import_module('bootstrap_research_control')
        from agent_factory import research_bootstrap_assembly as assembly
        self.assembly = assembly
        self.runtime_identity = self.stack.enter_context(patch.object(runner, 'runtime_identity'))
        self.dsn = self.stack.enter_context(patch.object(self.bootstrap, 'read_database_url',
            return_value='postgresql+psycopg://synthetic:synthetic@127.0.0.1:1/synthetic'))
        self.forbidden = [self.stack.enter_context(patch(target, side_effect=AssertionError('Execution forbidden')))
            for target in ('subprocess.Popen', 'fastapi.testclient.TestClient',
                           'agent_factory.lifecycle_observer.FactoryLifecycleObserver.tick')]
        self.operations = [Mock() for _ in range(9)]
        def store(offset):
            return SimpleNamespace(dispose_root_locks=self.operations[offset],
                engine=SimpleNamespace(dispose=self.operations[offset+1]),
                native_db=SimpleNamespace(db_engine=SimpleNamespace(dispose=self.operations[offset+2])))
        self.bundle = {'state': {'store': store(0),
            'schedules': SimpleNamespace(lock_engine=SimpleNamespace(dispose=self.operations[6]),
                manager=SimpleNamespace(close=self.operations[7]),
                diagnostics=SimpleNamespace(engine=SimpleNamespace(dispose=self.operations[8])))},
            'providerStore': store(3)}
        self.prepare = self.stack.enter_context(patch.object(assembly, 'prepare_application', return_value=self.bundle))
        self.executor = Mock(side_effect=AssertionError('Full run forbidden'))

    def call(self, mode='--assembly-only'):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = runner.main([mode, '--config', str(self.path)], run=self.executor)
        self.executor.assert_not_called()
        for operation in self.forbidden: operation.assert_not_called()
        self.assertNotIn(str(self.root), out.getvalue() + err.getvalue())
        return result, out.getvalue(), err.getvalue()

    def test_assemble_once_without_lifespan_then_dispose_all_original_pools(self):
        self.assertEqual(self.call(), (0, 'RESEARCH_PREPARATION_ASSEMBLED_NO_EXECUTION\n', ''))
        self.prepare.assert_called_once(); self.dsn.assert_called_once()
        for operation in self.operations: operation.assert_called_once_with()
        evidence = sorted(Path(self.config['workspace']).glob('progress-*.json'))
        self.assertEqual(json.loads(evidence[-1].read_bytes())['progress'],
                         {'phase': 'ASSEMBLY_CHECKED', 'executionVerified': False})

    def test_runtime_identity_failure_precedes_any_workspace_creation(self):
        self.runtime_identity.side_effect = ValueError('private-runtime-identity')
        code, out, err = self.call()
        self.assertEqual((code, out), (2, ''))
        result = json.loads(err.splitlines()[1])
        self.assertEqual((result['stage'], result['errorCode']), ('EXECUTION_IDENTITY', 'VALIDATION_REJECTED'))
        self.assertFalse(Path(self.config['workspace']).exists())
        self.prepare.assert_not_called(); self.dsn.assert_not_called()
        for operation in self.operations: operation.assert_not_called()

    def test_existing_workspace_rejected_without_construct_or_mutation(self):
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        marker = workspace / 'original'; marker.write_bytes(b'original')
        before = (workspace.stat().st_mtime_ns, marker.stat().st_mtime_ns)
        code, out, err = self.call()
        self.assertEqual((code, out), (2, ''))
        self.assertEqual(json.loads(err.splitlines()[1])['stage'], 'WORKSPACE_INSPECT')
        self.prepare.assert_not_called(); self.dsn.assert_not_called()
        self.assertEqual(before, (workspace.stat().st_mtime_ns, marker.stat().st_mtime_ns))
        self.assertEqual(list(workspace.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b'original')

    def test_dispose_failure_attempts_every_resource_and_preserves_first_error(self):
        self.operations[0].side_effect = ValueError('private-first')
        self.operations[2].side_effect = OSError('private-second')
        code, out, err = self.call()
        self.assertEqual((code, out), (2, ''))
        result = json.loads(err.splitlines()[1])
        self.assertEqual((result['stage'], result['errorCode']), ('ASSEMBLY_DISPOSE', 'VALIDATION_REJECTED'))
        self.assertNotIn('private-', err)
        for operation in self.operations: operation.assert_called_once_with()

    def test_precise_primary_assembly_stage_survives_failed_stop_journal(self):
        def fail(**kwargs):
            kwargs['diagnostics'].at('PREPARATION_CREATE_APP')
            raise ValueError('private-primary')
        self.prepare.side_effect = fail
        original = runner.Progress.record
        def record(progress, stage, value):
            if value['phase'] == 'STOPPED': raise OSError('private-stop-journal')
            return original(progress, stage, value)
        self.stack.enter_context(patch.object(runner.Progress, 'record', record))
        code, out, err = self.call()
        self.assertEqual((code, out), (2, ''))
        result = json.loads(err.splitlines()[1])
        self.assertEqual((result['stage'], result['errorCode']), ('PREPARATION_CREATE_APP', 'VALIDATION_REJECTED'))
        self.assertEqual(result['secondaryStage'], 'PROGRESS_STOPPED')
        self.assertNotIn('private-', err)
        self.prepare.assert_called_once()

    def test_database_report_cli_never_creates_workspace_or_store(self):
        report = {'schema': 1, 'status': 'CHECKED_FIELDS_PASS', 'checks': []}
        database = importlib.import_module('agent_factory.research_bootstrap_database_preflight')
        engine = Mock()
        self.stack.enter_context(patch('sqlalchemy.create_engine', return_value=engine))
        inspect = self.stack.enter_context(patch.object(database, 'database_preflight', return_value=report))
        forbidden_store = self.stack.enter_context(patch.object(self.assembly, 'Store', side_effect=AssertionError('No Store')))
        workspace = self.stack.enter_context(patch.object(self.bootstrap, '_workspace', side_effect=AssertionError('No workspace')))
        code, out, err = self.call('--database-preflight')
        self.assertEqual((code, json.loads(out), err), (0, report, ''))
        inspect.assert_called_once(); engine.dispose.assert_called_once_with()
        self.prepare.assert_not_called(); forbidden_store.assert_not_called(); workspace.assert_not_called()
        self.assertFalse(Path(self.config['workspace']).exists())
