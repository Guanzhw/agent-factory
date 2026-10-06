"""Synthetic read-only CLI tests. No interpreter, subprocess, network or ML calls."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_RUNNER = Path(__file__).resolve().parents[2] / 'scripts' / 'capture_research_uv_contract.py'
spec = importlib.util.spec_from_file_location('capture_research_uv_contract_cli', _RUNNER)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def run(args):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = runner.main(args)
    return result, stdout.getvalue(), stderr.getvalue()


class ContractArgumentsTests(unittest.TestCase):
    def test_missing_agent_module_is_sanitized_before_capture(self):
        import builtins
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == 'agent_factory.research_interpreter':
                raise ImportError('/private/operator/path missing local module')
            return original(name, *args, **kwargs)
        with patch.object(builtins, '__import__', side_effect=missing):
            self.assertEqual(run(['--config', '/private/config']), (2, '', 'RESEARCH_UV_CONTRACT_CAPTURE_FAILED\n'))

    def test_unsupported_flags_never_echo_private_arguments(self):
        for args in ([], ['--help'], ['--config'], ['--execute', '/private/detail'],
                     ['--config', '/private/config', '--force'], ['--config', 'relative.json']):
            with self.subTest(args=args), patch.object(runner, 'capture_interpreter_contract', side_effect=AssertionError('NO_CAPTURE')):
                self.assertEqual(run(args), (2, '', 'RESEARCH_UV_CONTRACT_CAPTURE_FAILED\n'))

    def test_non_posix_and_missing_capability_fail_before_open(self):
        with patch.object(os, 'name', 'nt'), patch.object(os, 'open', side_effect=AssertionError('NO_OPEN')):
            self.assertEqual(run(['--config', '/private/config']), (2, '', 'RESEARCH_UV_CONTRACT_CAPTURE_FAILED\n'))
        for flag in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'):
            with patch.object(os, flag, 0, create=True), patch.object(os, 'open', side_effect=AssertionError('NO_OPEN')):
                self.assertEqual(run(['--config', '/private/config']), (2, '', 'RESEARCH_UV_CONTRACT_CAPTURE_FAILED\n'))


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'POSIX nofollow filesystem required')
class ContractCaptureCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        project = self.root / 'project'; project.mkdir()
        venv = project / '.venv'; venv.mkdir(); (venv / 'bin').mkdir()
        approved = self.root / 'approved'; approved.mkdir()
        target = approved / 'python'; target.write_bytes(b'inert never-executed interpreter bytes'); target.chmod(0o755)
        executable = venv / 'bin' / 'python'; executable.symlink_to(target)
        cfg = venv / 'pyvenv.cfg'; cfg.write_text('uv = 0.11.7\n')
        pyproject = project / 'pyproject.toml'; pyproject.write_text('[project]\nname="inert"\n')
        lock = project / 'uv.lock'; lock.write_text('version = 1\n')
        inventory = project / 'inventory.json'; inventory.write_text('{"synthetic":true}')
        package = venv / 'empty.py'; package.touch()
        self.config = {'executable': str(executable), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'project_root': str(project), 'venv_root': str(venv), 'approved_interpreter_roots': [str(approved)],
            'pyvenv_cfg': str(cfg), 'pyproject_toml': str(pyproject), 'uv_lock': str(lock),
            'package_inventory': str(inventory), 'package_files': [str(package)]}
        self.path = self.root / 'config.json'; self.write_config(self.config)

    def write_config(self, value):
        self.path.write_text(json.dumps(value))

    def failure(self):
        self.assertEqual(run(['--config', str(self.path)]), (2, '', 'RESEARCH_UV_CONTRACT_CAPTURE_FAILED\n'))

    def test_exact_helper_bytes_stdout_only_read_only_and_no_launch(self):
        expected = runner.capture_interpreter_contract(**self.config)
        paths = [path for path in self.root.rglob('*') if path.is_file() and not path.is_symlink()]
        before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in paths}
        with patch('subprocess.Popen', side_effect=AssertionError('NO_SUBPROCESS')), \
                patch('os.execve', side_effect=AssertionError('NO_EXEC')), \
                patch('socket.create_connection', side_effect=AssertionError('NO_NETWORK')):
            self.assertEqual(run(['--config', str(self.path)]), (0, expected, ''))
        after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in paths}
        self.assertEqual(before, after)
        self.assertEqual({str(path) for path in self.root.rglob('*') if path.is_file() and not path.is_symlink()}, set(before))

    def test_duplicate_unknown_missing_wrong_types_and_trailing_bytes_rejected(self):
        original = json.dumps(self.config)
        invalid = [original[:-1] + ',"sha256":"' + self.config['sha256'] + '"}',
                   json.dumps(self.config | {'execute': True}), original + '{}', original + 'private trailing text',
                   json.dumps({key: val for key, val in self.config.items() if key != 'package_files'}),
                   json.dumps(self.config | {'package_files': 'not-a-list'}),
                   json.dumps(self.config | {'approved_interpreter_roots': []}),
                   json.dumps(self.config | {'sha256': True}), original.replace('"package_files":', '"package_files":NaN,"ignored":')]
        for index, content in enumerate(invalid):
            with self.subTest(index=index), patch.object(runner, 'capture_interpreter_contract', side_effect=AssertionError('NO_CAPTURE')):
                self.path.write_text(content); self.failure()

    def test_oversized_config_rejected_before_helper(self):
        self.path.write_bytes(b' ' * (runner.MAX_CONFIG_BYTES + 1))
        with patch.object(runner, 'capture_interpreter_contract', side_effect=AssertionError('NO_CAPTURE')):
            self.failure()

    def test_config_symlink_hardlink_and_parent_symlink_fail_closed(self):
        original = self.root / 'original.json'; self.path.rename(original)
        self.path.symlink_to(original); self.failure(); self.path.unlink()
        os.link(original, self.path); self.failure(); self.path.unlink(); original.rename(self.path)
        alias = self.root / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(run(['--config', str(alias / 'config.json')]), (2, '', 'RESEARCH_UV_CONTRACT_CAPTURE_FAILED\n'))

    def test_config_changed_during_read_is_rejected(self):
        read = os.read; changed = False
        def change(fd, size):
            nonlocal changed
            data = read(fd, size)
            if not changed:
                changed = True; self.path.write_text(json.dumps(self.config) + ' ')
            return data
        with patch.object(os, 'read', side_effect=change), patch.object(runner, 'capture_interpreter_contract', side_effect=AssertionError('NO_CAPTURE')):
            self.failure()

    def test_config_replaced_during_capture_has_no_partial_stdout(self):
        capture = runner.capture_interpreter_contract
        def replace_config(**kwargs):
            result = capture(**kwargs)
            self.path.rename(self.root / 'old.json'); self.write_config(self.config)
            return result
        with patch.object(runner, 'capture_interpreter_contract', side_effect=replace_config):
            self.failure()

    def test_wrong_supplied_hash_and_helper_error_are_sanitized(self):
        self.write_config(self.config | {'sha256': '0' * 64}); self.failure()
        self.write_config(self.config)
        with patch.object(runner, 'capture_interpreter_contract', side_effect=ValueError('/private/path arbitrary secret-like text')):
            self.failure()

    def test_output_bound_rejects_helper_oversize_without_partial_stdout(self):
        with patch.object(runner, 'capture_interpreter_contract', return_value='x' * (runner.contract_limit() + 1)):
            self.failure()
