"""Synthetic prepare/check evidence; never installs wheels or invokes uv."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('repair_factory_wheel', SCRIPTS / 'repair_factory_wheel.py')
assert spec and spec.loader
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


@unittest.skipUnless(os.name == 'posix', 'POSIX no-follow filesystem contract')
class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'venv/lib/python3.12/site-packages'
        self.site.mkdir(parents=True)
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir(mode=0o700)
        self.args = SimpleNamespace(venv=self.root / 'venv', evidence=self.evidence,
            **{key: self.root / key for key in ('wheel', 'base_wheel', 'source', 'manifest', 'uv')})
        self.base = {}
        for number in range(135):
            name = repair.closure.PATH_FIX_FILE if number == 0 else f'agent_factory/file{number}.py'
            raw = f'# original {number}\n'.encode()
            path = self.site / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)
            self.base[name] = hashlib.sha256(raw).hexdigest()
        self.expected = {**self.base, repair.closure.PATH_FIX_FILE: hashlib.sha256(b'# patched\n').hexdigest()}
        for number in range(95):
            name = repair.DIST if number == 0 else f'fixture{number}-1.dist-info'
            path = self.site / name
            path.mkdir()
            package = 'department-agent-factory' if number == 0 else f'fixture{number}'
            version = '0.2.0' if number == 0 else '1'
            (path / 'METADATA').write_text(f'Name: {package}\nVersion: {version}\n')
        self.inputs = patch.object(repair, 'verified_inputs', return_value=(self.base, self.expected, {'controlledFixture': True}))
        self.inputs.start()
        self.addCleanup(self.inputs.stop)

    def prepare(self):
        self.assertEqual(repair.prepare(self.args)['status'], 'PREPARED')
        self.assertEqual((self.evidence / repair.PLAN).stat().st_mode & 0o777, 0o600)

    def patched(self):
        (self.site / repair.closure.PATH_FIX_FILE).write_bytes(b'# patched\n')

    def test_prepare_and_check_preserve_original_and_other_94(self):
        (self.evidence / 'wheel-verification.json').write_text('{}')
        self.prepare()
        original = (self.evidence / repair.closure.PATH_FIX_FILE).read_bytes()
        self.patched()
        self.assertEqual(repair.check(self.args)['status'], 'CHECKED')
        self.assertEqual((self.evidence / repair.closure.PATH_FIX_FILE).read_bytes(), original)
        plan = json.loads((self.evidence / repair.PLAN).read_bytes())
        self.assertEqual(len(plan['versions']), 95)
        self.assertIn('--offline', plan['installArgv'])
        self.assertFalse(plan['installationPerformed'])

    def test_non_factory_change_rejected(self):
        self.prepare(); self.patched()
        (self.site / 'fixture1-1.dist-info/METADATA').write_text('Name: fixture1\nVersion: 2\n')
        with self.assertRaises(ValueError): repair.check(self.args)

    def test_unexpected_factory_pyc_rejected(self):
        (self.site / 'agent_factory/extra.pyc').write_bytes(b'inert')
        with self.assertRaises(ValueError): repair.prepare(self.args)
        self.assertFalse((self.evidence / 'agent_factory').exists())

    def test_non_factory_symlink_or_hardlink_rejected(self):
        path = self.site / 'alias'
        source = self.site / 'fixture1-1.dist-info/METADATA'
        path.symlink_to(source)
        with self.assertRaises(Exception): repair.prepare(self.args)
        path.unlink(); os.link(source, path)
        with self.assertRaises(Exception): repair.prepare(self.args)

    def test_backup_tamper_rejected(self):
        self.prepare(); self.patched()
        (self.evidence / repair.closure.PATH_FIX_FILE).write_bytes(b'changed')
        with self.assertRaises(ValueError): repair.check(self.args)

    def test_existing_plan_is_never_overwritten(self):
        self.prepare()
        previous = (self.evidence / repair.PLAN).read_bytes()
        with self.assertRaises(ValueError): repair.prepare(self.args)
        self.assertEqual((self.evidence / repair.PLAN).read_bytes(), previous)

    def test_wrong_prior_versions_rejected(self):
        repair.save(self.evidence, 'old-versions.json', {})
        with self.assertRaises(ValueError): repair.prepare(self.args)
        self.assertFalse((self.evidence / 'agent_factory').exists())

    def test_mode_drift_rejected(self):
        (self.site / 'fixture1-1.dist-info/METADATA').chmod(0o644)
        self.prepare(); self.patched()
        (self.site / 'fixture1-1.dist-info/METADATA').chmod(0o600)
        with self.assertRaises(ValueError): repair.check(self.args)


class PrivateOutputTests(unittest.TestCase):
    def test_isolated_cli_resolves_reviewed_siblings(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for module in (repair, repair.copying, repair.closure):
                shutil.copyfile(module.__file__, folder / Path(module.__file__).name)
            result = subprocess.run([sys.executable, '-I', '-B', str(folder / 'repair_factory_wheel.py'), '--help'],
                capture_output=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b'prepare', result.stdout)
            self.assertEqual(result.stderr, b'')

    def test_bad_arguments_do_not_echo_private_values(self):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(repair.main(['prepare', '--private', '/private/target']), 2)
        self.assertNotIn('/private', output.getvalue() + errors.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'REJECTED')

    def test_fix_pin_mismatch_stops_before_any_file_read(self):
        with patch.object(repair.closure, 'PATH_FIX_SHA256', '0' * 64), patch.object(repair, 'file_identity') as reader:
            with self.assertRaises(ValueError): repair.verified_inputs(SimpleNamespace())
            reader.assert_not_called()
