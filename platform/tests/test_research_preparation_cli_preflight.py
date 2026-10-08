"""Canonical CLI preflight reads synthetic config/tokenizer only; never execution."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_research_baseline_runner as fixture
from test_research_preparation_validation import synthetic_tokenizer

runner = fixture.runner
CANARY = 'synthetic-private-dsn-request'


@unittest.skipUnless(sys.platform == 'linux', 'Canonical preparation preflight requires Linux/POSIX')
class PreparationCliPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = fixture.config(self.root)
        self.config['requestId'] = CANARY
        self.path = self.root / 'config.json'
        self.tokenizer = self.root / 'inputs/tokenizer.json'
        self.tokenizer.parent.mkdir(mode=0o700)
        self.tokenizer.write_bytes(synthetic_tokenizer(8192)); self.tokenizer.chmod(0o600)
        self.dsn = Path(self.config['databaseUrlFile'])
        self.dsn.write_text(CANARY); self.dsn.chmod(0o600)

    def invoke(self):
        self.path.write_bytes(runner.canonical(self.config)); self.path.chmod(0o600)
        import agent_factory
        from agent_factory.research_preparation_driver import _FILES
        sources = {Path(agent_factory.__file__).parent / name for name in _FILES}
        reads, original_read = [], runner.read_private
        def read(path, *args, **kwargs):
            path = Path(path)
            self.assertIn(path, {self.path, self.tokenizer, *sources}, 'Only config/tokenizer and fixed platform source reads are permitted')
            reads.append(path)
            return original_read(path, *args, **kwargs)
        out, err = io.StringIO(), io.StringIO()
        before = (self.dsn.stat().st_size, self.dsn.stat().st_mtime_ns)
        with ExitStack() as patches:
            patches.enter_context(patch.object(sys, 'path', [str(fixture.SCRIPTS), *sys.path]))
            bootstrap = importlib.import_module('bootstrap_research_control')
            from agent_factory import research_bootstrap_assembly, research_device_observer, store
            forbidden = []
            for module, name in ((bootstrap, 'read_database_url'), (bootstrap, '_workspace'),
                (research_bootstrap_assembly, 'Store'), (research_bootstrap_assembly, 'create_app'),
                (research_bootstrap_assembly, 'prepare_application'), (store, 'Store'), (store, 'create_engine'),
                (research_device_observer, 'NvidiaSmiObserver')):
                forbidden.append(patches.enter_context(patch.object(module, name,
                    side_effect=AssertionError('Preflight must not execute or connect'))))
            forbidden.append(patches.enter_context(patch('subprocess.Popen', side_effect=AssertionError('No process'))))
            patches.enter_context(patch.object(runner, 'read_private', side_effect=read))
            execute = Mock(side_effect=AssertionError('No baseline execution'))
            with redirect_stdout(out), redirect_stderr(err):
                code = runner.main(['--preflight', '--config', str(self.path)], run=execute)
            execute.assert_not_called()
            for operation in forbidden: operation.assert_not_called()
        self.assertEqual(err.getvalue(), '')
        self.assertEqual(reads[:2], [self.path, self.tokenizer])
        self.assertEqual(set(reads[2:]), sources)
        self.assertEqual(len(reads), 2 + len(sources))
        self.assertEqual((self.dsn.stat().st_size, self.dsn.stat().st_mtime_ns), before)
        self.assertNotIn(CANARY, out.getvalue())
        self.assertNotIn(str(self.root), out.getvalue())
        value = json.loads(out.getvalue())
        self.assertEqual(value['kind'], 'RESEARCH_PREPARATION_PREFLIGHT')
        checks = {row['field']: row for row in value['checks']}
        self.assertEqual(checks['DATABASE_AND_APPLICATION']['status'], 'NOT_CHECKED')
        self.assertEqual(checks['RUNTIME_ADMISSION']['status'], 'NOT_CHECKED')
        return code, value, checks

    def test_valid_tokenizer_has_no_workspace_or_execution_side_effect(self):
        code, value, checks = self.invoke()
        self.assertEqual((code, value['status']), (0, 'CHECKED_FIELDS_PASS'))
        self.assertEqual(checks['payload_authority']['status'], 'PASS')
        self.assertEqual(checks['PROGRAM_DIRECTORY']['code'], 'NOT_CREATED')
        self.assertFalse(Path(self.config['workspace']).exists())

    def test_independent_bad_limits_and_tokenizer_are_all_reported(self):
        self.config['limits'].update(cpu_seconds=999999, wall_seconds=300, address_space_mb=1, file_size_bytes=1024,
                                     output_bytes=1025, disk_bytes=1024)
        bad = json.loads(synthetic_tokenizer(8192))
        bad.update(pat_str='', private_extra=CANARY)
        bad['special_tokens'] = {CANARY: 0}
        self.tokenizer.write_bytes(json.dumps(bad).encode())
        code, value, checks = self.invoke()
        self.assertEqual((code, value['status']), (2, 'BLOCKED'))
        for field in ('pattern', 'object_keys', 'special_ids', 'reserved_token',
                      'limits.cpu_seconds', 'limits.wall_seconds', 'limits.address_space_mb',
                      'limits.diskReservation', 'limits.outputBound'):
            self.assertEqual(checks[field]['status'], 'BLOCKED', field)
        self.assertFalse(Path(self.config['workspace']).exists())

    def test_existing_workspace_is_checked_without_writing_or_restarting(self):
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        program, custody = workspace / 'preparation-program', workspace / 'preparation-custody'
        program.mkdir(mode=0o700); custody.mkdir(mode=0o700)
        marker = program / 'original'; marker.write_bytes(b'original synthetic evidence'); marker.chmod(0o600)
        before = {str(p.relative_to(workspace)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                  for p in (workspace, program, custody, marker)}
        code, value, checks = self.invoke()
        self.assertEqual((code, value['status']), (0, 'CHECKED_FIELDS_PASS'))
        self.assertEqual(checks['PROGRAM_DIRECTORY']['status'], 'PASS')
        self.assertEqual(checks['CUSTODY_DIRECTORY']['status'], 'PASS')
        after = {str(p.relative_to(workspace)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                 for p in (workspace, program, custody, marker)}
        self.assertEqual(before, after)
        self.assertEqual(set(workspace.rglob('*')), {program, custody, marker})
