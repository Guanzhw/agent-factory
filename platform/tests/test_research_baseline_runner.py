"""Offline bootstrap CLI tests; no training, Torch, PG connection or device query."""
from contextlib import redirect_stderr, redirect_stdout
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).parents[2] / 'scripts'
spec = importlib.util.spec_from_file_location('baseline_runner', SCRIPTS / 'run_research_baseline.py')
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


def config(root):
    return {'schema': 1, 'ackLocalDevelopment': True, 'ackTraining': True,
        'databaseUrlFile': str(root / 'dsn'), 'workspace': str(root / 'new-workspace'), 'requestId': 'operator-attempt',
        'inputRoot': str(root / 'inputs'), 'tokenizerBasename': 'tokenizer.json',
        'shards': [{'id': 'train', 'basename': 'train.parquet'}, {'id': 'val', 'basename': 'val.parquet'}],
        'validationIds': ['val'], 'upstreamRoot': str(root / 'upstream'), 'projectRoot': str(root / 'project'),
        'venvRoot': str(root / 'project/.venv'), 'interpreterTarget': str(root / 'python'),
        'interpreterSha256': 'a' * 64, 'approvedInterpreterRoots': [str(root)], 'deviceUuid': 'GPU-12345678',
        'receiverNamespaceSha256': 'b' * 64, 'nvidiaSmi': {'executable': str(root / 'nvidia-smi'), 'sha256': 'c' * 64},
        'limits': {'cpu_seconds': 600, 'address_space_mb': 65536, 'file_size_bytes': 2**30,
            'wall_seconds': 900, 'disk_bytes': 3 * 2**30, 'output_bytes': 2**20}, 'microbatch': 1}


@unittest.skipUnless(os.name == 'posix', 'Private operator filesystem requires POSIX')
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = config(self.root)
        self.path = self.root / 'config.json'
        self.path.write_bytes(runner.canonical(self.config)); self.path.chmod(0o600)
        self.patch = patch.object(sys, 'path', [str(SCRIPTS), *sys.path])
        self.patch.start(); self.addCleanup(self.patch.stop)

    def call(self, run):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = runner.main(['--config', str(self.path)], run=run)
        return code, out.getvalue(), err.getvalue()

    def test_explicit_acknowledged_fresh_run_only_mock_executor(self):
        execute = Mock()
        result = self.call(execute)
        self.assertEqual(result, (0, 'RESEARCH_BASELINE_COMPLETED_PRIVATE_EVIDENCE\n', ''))
        execute.assert_called_once()
        workspace = Path(self.config['workspace'])
        self.assertEqual(workspace.stat().st_mode & 0o777, 0o700)
        events = sorted(workspace.glob('progress-*.json'))
        self.assertEqual([json.loads(p.read_bytes())['progress']['phase'] for p in events], ['STARTED', 'COMPLETED'])
        self.assertNotIn(str(self.root), result[1])

    def test_existing_workspace_read_only_no_executor_or_evidence_mutation(self):
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        marker = workspace / 'progress-000001.json'; marker.write_bytes(b'original evidence'); marker.chmod(0o600)
        before = marker.stat()
        execute = Mock()
        self.assertEqual(self.call(execute), (0, 'RESEARCH_BASELINE_EXISTING_INSPECT_ONLY\n', ''))
        execute.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'original evidence')
        self.assertEqual(marker.stat().st_mtime_ns, before.st_mtime_ns)

    def test_failure_journal_fixed_stdout_no_exception_path_and_no_retry(self):
        execute = Mock(side_effect=RuntimeError('private path and password must not be echoed'))
        self.assertEqual(self.call(execute), (2, '', runner.ERROR + '\n'))
        execute.assert_called_once()
        files = sorted(Path(self.config['workspace']).glob('progress-*.json'))
        self.assertEqual(json.loads(files[-1].read_bytes())['progress'], {'phase': 'STOPPED', 'cleanupConfirmed': False})

    def test_strict_config_rejects_missing_ack_extra_identity_duplicate_keys_and_bool_budget(self):
        bad = [dict(self.config, ackTraining=False), dict(self.config, taskId='invented'),
               dict(self.config, schema=True), dict(self.config, limits={**self.config['limits'], 'wall_seconds': True})]
        for value in bad:
            with self.assertRaises(ValueError):
                runner.config_from_bytes(runner.canonical(value))
        with self.assertRaises(ValueError):
            runner.config_from_bytes(b'{"schema":1,"schema":1}')
        with self.assertRaises(ValueError):
            runner.config_from_bytes(b'a' * (2 * 1024**2 + 1))

    def test_private_read_symlink_hardlink_and_changed_file_fail_closed(self):
        alias = self.root / 'alias'; alias.symlink_to(self.path)
        with self.assertRaises(OSError): runner.read_private(alias)
        alias.unlink(); os.link(self.path, alias)
        with self.assertRaises(ValueError): runner.read_private(self.path)
        alias.unlink()
        original = runner.os.read
        def swap(fd, size):
            data = original(fd, size)
            self.path.unlink(); self.path.write_bytes(b'replaced'); self.path.chmod(0o600)
            return data
        with patch.object(runner.os, 'read', side_effect=swap):
            with self.assertRaises(ValueError): runner.read_private(self.path)

    def test_write_is_exclusive_private_and_never_overwrites(self):
        target = self.root / 'record'
        runner.write_private(target, b'first')
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError): runner.write_private(target, b'second')
        self.assertEqual(target.read_bytes(), b'first')

    def test_preparation_uses_ordinary_native_instance_and_imports_original(self):
        bootstrap = importlib.import_module('bootstrap_research_control')
        from agent_factory import process_runtime_profile
        lease = {'id': 'original-lease', 'state': 'RECLAIMED', 'executionStatus': 'COMPLETED',
                 'capacityHeld': False, 'stopEvidence': {'allStopped': True}, 'nativeRunId': 'original-run',
                 'providerJobId': 'original-process'}
        store = Mock()
        store.process_runtime._original.return_value = {'lease_id': 'original-lease'}
        store.process_runtime.resources.inspect.return_value = lease
        prep = Mock(); prep.import_completed.return_value = {'id': 'original-artifact'}
        prep.input_pin.return_value = {'binding': {'taskId': 'original-task'}}
        bundle = {'state': {'store': store}, 'preparation': prep}
        calls = []
        def request(method, path, body, *, owner):
            calls.append((method, path, body, owner))
            if path.endswith('/proposals'): return {'id': 'proposal'}
            if path.endswith('/accept'): return {'id': 'plan'}
            if path.endswith('/plan-reviews'): return {'id': 'review'}
            if path.endswith('/decision'): return {}
            if path.endswith('/instances'): return {'id': 'original-task'}
            if path.endswith('/jobs/original-task'): return {'job': {'status': 'completed'}}
            raise AssertionError('Unexpected request')
        progress = Mock()
        with patch.object(bootstrap, 'ensure_task_development_reviewer', return_value='task-dev-reviewer'), \
             patch.object(process_runtime_profile, 'publish_process_application', return_value={'id': 'app', 'version': 1, 'sha256': 'a'*64}), \
             patch.object(runner, 'request_client', return_value=request):
            result = runner.preparation_phase(bundle, object(), 'operator-attempt', progress)
        self.assertEqual(result[0:2], ('original-task', 'original-artifact'))
        self.assertEqual(sum(path.endswith('/instances') for _, path, _, _ in calls), 1)
        self.assertFalse(any(path.endswith('/approve') for _, path, _, _ in calls))
        prep.import_completed.assert_called_once_with('alice', 'original-lease')
        store.research_runtime.submit.assert_not_called()
        store.request_cancel.assert_not_called()


    def test_launch_environment_selects_exact_local_distutils_profile(self):
        env = runner.launch_environment(self.config, self.root / 'program', self.root / 'cache')
        self.assertEqual(env['SETUPTOOLS_USE_DISTUTILS'], 'local')
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], self.config['deviceUuid'])
        self.assertEqual(env['PYTHONPYCACHEPREFIX'], str(self.root / 'program'))

    def test_preparation_lost_ack_never_cancels_mismatched_original_plan(self):
        bootstrap = importlib.import_module('bootstrap_research_control')
        from agent_factory import process_runtime_profile, research_bootstrap_controller
        store = Mock()
        store.task.return_value = {'id': 'original-task', 'owner_id': 'alice', 'plan_id': 'different-plan'}
        calls = []
        def request(method, path, body, *, owner):
            calls.append(path)
            if path.endswith('/proposals'): return {'id': 'proposal'}
            if path.endswith('/accept'): return {'id': 'plan'}
            if path.endswith('/plan-reviews'): return {'id': 'review'}
            if path.endswith('/decision'): return {}
            if path.endswith('/instances'): raise RuntimeError('lost acknowledgement')
            if '/requests/' in path:
                return {'planId': 'plan', 'taskId': 'original-task', 'requestId': 'operator-attempt:prep:instance'}
            raise AssertionError('Unexpected request')
        with patch.object(bootstrap, 'ensure_task_development_reviewer', return_value='task-dev-reviewer'), \
             patch.object(process_runtime_profile, 'publish_process_application', return_value={'id': 'app', 'version': 1, 'sha256': 'a'*64}), \
             patch.object(runner, 'request_client', return_value=request), \
             patch.object(research_bootstrap_controller, 'cleanup_original') as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'lost acknowledgement'):
                runner.preparation_phase({'state': {'store': store}}, object(), 'operator-attempt', Mock())
        cleanup.assert_not_called()
        store.request_cancel.assert_not_called()
        self.assertFalse(any(path.endswith('/cancel') for path in calls))
        self.assertEqual(sum(path.endswith('/instances') for path in calls), 1)

    def test_installed_lock_pin_retains_original_project_root_and_inode(self):
        project = Path(self.config['projectRoot']); project.mkdir(mode=0o700)
        lock = project / 'uv.lock'; lock.write_bytes(b'version = 1\n'); lock.chmod(0o600)
        evidence = self.root / 'evidence'; evidence.mkdir(mode=0o700)
        pins = runner.environment_pins(self.config, evidence,
            {'inventoryBytes': b'{}', 'kernelBytes': b'{}'})
        pin = next(pin for pin in pins if pin.label == 'environment-lockfile')
        self.assertEqual(pin.root, str(project))
        self.assertEqual(pin.root_identity.device, project.stat().st_dev)
        self.assertEqual(pin.root_identity.inode, project.stat().st_ino)
        self.assertEqual(pin.file.basename, 'uv.lock')
        self.assertFalse((evidence / 'uv.lock').exists())
        lock.chmod(0o644)
        with self.assertRaises(ValueError):
            runner.environment_pins(self.config, evidence, {'inventoryBytes': b'{}', 'kernelBytes': b'{}'})
