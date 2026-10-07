"""Offline launcher/config/stop evidence tests; no containers or provider calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import sys

_spec = importlib.util.spec_from_file_location('orx_runtime_test', Path(__file__).resolve().parents[2] / 'scripts/orx_research_runtime.py')
assert _spec and _spec.loader
subject = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = subject
_spec.loader.exec_module(subject)


class OrxResearchRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        binary = self.root / 'public-binary'; binary.write_bytes(b'synthetic trusted bytes'); binary.chmod(0o700)
        pin = subject.BinaryPin(str(binary), hashlib.sha256(binary.read_bytes()).hexdigest())
        self.config = subject.RuntimeConfig(str(self.root), 'sha256:' + 'a' * 64, pin, pin)
        self.capability = 'synthetic-local-capability-12345'

    @unittest.skipUnless(sys.platform == 'linux', 'Launcher requires Linux UID and POSIX permission semantics')
    def test_command_is_networkless_bounded_and_has_no_host_home_or_secret_values(self):
        command = subject.build_command(self.config, 'factory-orx-' + 'b' * 32, self.capability)
        self.assertIn('none', command)
        for option in ('--read-only', '--cap-drop', '--pids-limit', '--cpus', '--memory', '--memory-swap'):
            self.assertIn(option, command)
        self.assertNotIn('--privileged', command)
        self.assertNotIn(self.capability, ' '.join(command))
        self.assertNotIn('docker.sock', ' '.join(command))
        self.assertNotIn('OPENCODE_GO', subject.environment(self.capability))
        self.assertEqual(subject.environment(self.capability)['HOME'], '/session/home')
        self.assertNotIn('--publish', command)

    def test_config_denies_orx_explicit_bash_grant_and_provider_fallback(self):
        config = subject.opencode_config(self.capability)
        self.assertTrue(subject.verify_effective_config(config, config)['factoryMcpOnly'])
        for mutate in (lambda v: v['permission'].update(bash='allow'),
                       lambda v: v['agent']['build']['permission'].update(bash='allow'),
                       lambda v: v.update(plugin=['unexpected']),
                       lambda v: v.update(enabled_providers=['factory', 'openai']),
                       lambda v: v['mcp'].update(other={'url': 'https://invalid'})):
            value = deepcopy(config); mutate(value)
            with self.assertRaises(ValueError):
                subject.verify_effective_config(value, config)

    def test_pinned_debug_redaction_and_output_bound(self):
        expected = subject.opencode_config(self.capability, 64)
        config = deepcopy(expected)
        config['provider']['factory']['options']['apiKey'] = '***'
        config['mcp']['factory']['headers']['Authorization'] = '***'
        self.assertTrue(subject.verify_effective_config(config, expected)['effectiveConfigVerified'])
        value = json.loads(subject.environment(self.capability, 64)['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(value['provider']['factory']['models']['deepseek-flash']['limit']['output'], 64)
        for cap in (0, 4097, True):
            with self.assertRaises(ValueError):
                subject.opencode_config(self.capability, cap)

    def test_title_agent_explicit_disable_required_even_with_safe_tool_permissions(self):
        expected = subject.opencode_config(self.capability)
        self.assertEqual(expected['agent']['title'], {'disable': True})
        self.assertTrue(subject.verify_effective_config(expected, expected)['titleAgentDisabled'])
        for title in (None, {}, {'disable': False}, {'disable': 1}, {'disable': 'true'},
                      deepcopy(expected['agent']['build'])):
            with self.subTest(title=title):
                config = deepcopy(expected)
                if title is None:
                    del config['agent']['title']
                else:
                    config['agent']['title'] = title
                with self.assertRaises(ValueError):
                    subject.verify_effective_config(config, expected)

    @unittest.skipUnless(sys.platform == 'linux', 'Launcher requires Linux UID and POSIX permission semantics')
    def test_changed_binary_and_mutable_image_denied(self):
        Path(self.config.orx.path).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.config.validate()
        with self.assertRaises(ValueError):
            subject.RuntimeConfig(str(self.root), 'python:latest', self.config.orx, self.config.opencode).validate()

    def test_stop_requires_exact_container_positive_exited_state_not_pid_absence(self):
        runtime = subject.Runtime(self.config); runtime.container_id = 'c' * 64
        record = {'Id': runtime.container_id, 'Config': {'Labels': {'factory.orx.runtime': runtime.name}},
                  'State': {'Running': False, 'Paused': False, 'Dead': False, 'Pid': 0,
                            'Status': 'exited', 'ExitCode': 0, 'FinishedAt': '2026-10-07T12:00:00Z'}}
        def run(args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps([record]).encode())
        with patch.object(subject.subprocess, 'run', side_effect=run):
            self.assertTrue(runtime.stop()['stopped'])
            record['State']['Status'] = 'dead'
            self.assertFalse(runtime.stop()['stopped'])
            record['State']['Status'] = 'exited'; record['Id'] = 'd' * 64
            self.assertFalse(runtime.stop()['stopped'])

    @unittest.skipUnless(sys.platform == 'linux', 'Project bootstrap requires Linux private-directory semantics')
    def test_fresh_project_bootstrap_without_http_or_model_call(self):
        for name in ('orx', 'work'):
            (self.root / name).mkdir(mode=0o700)
        columns = [('id', 'TEXT'), ('name', 'TEXT'), ('slug', 'TEXT'), ('github_owner', 'TEXT'),
                   ('github_repo', 'TEXT'), ('github_sync_enabled', 'INTEGER'),
                   ('baseline_branch', 'TEXT'), ('repo_path', 'TEXT'), ('run_command', 'TEXT'),
                   ('paper_id', 'TEXT'), ('created_at', 'INTEGER'), ('updated_at', 'INTEGER'),
                   ('workspace_state_json', 'TEXT')]
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command == ['/trusted/orx', 'projects', '--json']:
                with sqlite3.connect(self.root / 'orx/orx.db') as database:
                    database.execute('CREATE TABLE local_projects (' + ','.join(n + ' ' + t for n, t in columns) + ')')
                    database.execute('CREATE TABLE local_experiments (id TEXT)')
            return SimpleNamespace(returncode=0, stdout=b'[]')
        with patch.object(subject.subprocess, 'run', side_effect=run):
            self.assertEqual(subject.bootstrap_project(self.root, self.config.project_id), self.config.project_id)
            with self.assertRaises(ValueError):
                subject.bootstrap_project(self.root, self.config.project_id)
        self.assertEqual(len(calls), 3)
        with sqlite3.connect(self.root / 'orx/orx.db') as database:
            row = database.execute('SELECT id, github_sync_enabled, repo_path, run_command FROM local_projects').fetchone()
        self.assertEqual(row, (self.config.project_id, 0, str(self.root / 'work'), None))
        self.assertEqual(subject.opencode_config(self.capability)['model'], 'factory/deepseek-flash')

    def test_reclaim_never_removes_active_or_mismatched_container(self):
        runtime = subject.Runtime(self.config); runtime.container_id = 'c' * 64
        record = {'Id': runtime.container_id, 'Config': {'Labels': {'factory.orx.runtime': runtime.name}},
                  'State': {'Running': True, 'Paused': False, 'Dead': False,
                            'Status': 'running', 'ExitCode': 0, 'FinishedAt': '0001-01-01T00:00:00Z'}}
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout=(json.dumps([record]).encode() if args[1] == 'inspect'
                                                        else runtime.container_id.encode()))
        with patch.object(subject.subprocess, 'run', side_effect=run):
            self.assertFalse(runtime.reclaim()['reclaimed'])
            self.assertFalse(any(args[1] == 'rm' for args in calls))
            record['State'].update(Running=False, Status='exited', FinishedAt='2026-10-07T12:00:00Z')
            record['Config']['Labels']['factory.orx.runtime'] = 'other-owner'
            self.assertFalse(runtime.reclaim()['reclaimed'])
            self.assertFalse(any(args[1] == 'rm' for args in calls))
            record['Config']['Labels']['factory.orx.runtime'] = runtime.name
            self.assertTrue(runtime.reclaim()['reclaimed'])
            self.assertTrue(runtime.reclaim()['reclaimed'])
            self.assertEqual([args for args in calls if args[1] == 'rm'], [['docker', 'rm', runtime.container_id]])

    def test_reclaim_created_requires_positive_never_started_state(self):
        runtime = subject.Runtime(self.config); runtime.container_id = 'c' * 64
        record = {'Id': runtime.container_id, 'Config': {'Labels': {'factory.orx.runtime': runtime.name}},
                  'State': {'Running': False, 'Paused': False, 'Dead': False, 'Status': 'created',
                            'StartedAt': '2026-10-07T12:00:00Z', 'FinishedAt': '0001-01-01T00:00:00Z'}}
        removed = []
        def run(args, **kwargs):
            if args[1] == 'rm':
                removed.append(args)
                return SimpleNamespace(returncode=0, stdout=runtime.container_id.encode())
            return SimpleNamespace(returncode=0, stdout=json.dumps([record]).encode())
        with patch.object(subject.subprocess, 'run', side_effect=run):
            self.assertFalse(runtime.reclaim()['reclaimed'])
            self.assertFalse(removed)
            record['State']['StartedAt'] = '0001-01-01T00:00:00Z'
            self.assertTrue(runtime.reclaim()['reclaimed'])
        self.assertEqual(removed, [['docker', 'rm', runtime.container_id]])

    def test_debug_config_failure_never_executes_server(self):
        with patch.dict(subject.os.environ, {'OPENCODE_CONFIG_CONTENT': json.dumps(subject.opencode_config(self.capability))}), \
                patch.object(subject.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout=b'')), \
                patch.object(subject.os, 'execv') as execute:
            with self.assertRaises(ValueError):
                subject.opencode_wrapper(['serve'])
            execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
