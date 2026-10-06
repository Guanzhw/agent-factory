"""Public/synthetic temp files only; no startup execution or external programs."""
import importlib.util
import io
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location('uv_startup_probe', Path(__file__).resolve().parents[2] / 'scripts' / 'probe_research_uv_startup.py')
assert _SPEC is not None and _SPEC.loader is not None
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


class ConfigTests(unittest.TestCase):
    def test_allowlist_drops_private_values_without_normalization(self):
        self.assertEqual(probe.parse_config(b'home = /private/home\nexecutable = secret\nuv = 0.11.7\ninclude-system-site-packages = false\nversion_info = 3.12.13\n'),
            {'uv': '0.11.7', 'include-system-site-packages': 'false', 'version_info': '3.12.13'})
        for raw in (b'uv = 0.11.7\nuv = 0.12.19', b'uv = private/path', b'version_info = 3.12.13\x00'):
            with self.assertRaises(ValueError):
                probe.parse_config(raw)

    def test_minor_version_and_ignored_key_duplicates(self):
        self.assertEqual(probe.parse_config(b'uv=0.12.19\nversion_info=3.12')['version_info'], '3.12')
        for raw in (b'home=/private/one\nHOME=/private/two', b'custom=one\nCustom=two', b'uv=0.12'):
            with self.assertRaises(ValueError):
                probe.parse_config(raw)

    def test_unsupported_flags_fail_before_open(self):
        with patch.object(probe.os, 'O_NOFOLLOW', None, create=True), patch.object(probe.os, 'open') as opening:
            self.assertEqual(probe.probe('/synthetic')['status'], 'PLATFORM_UNSUPPORTED')
            opening.assert_not_called()

    def test_invalid_cli_never_echoes_private_arguments(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['probe', '--venv', '/private/venv', '/private/extra']), \
             redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(probe.main(), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'ARGUMENTS_INVALID')
        self.assertNotIn('/private', output.getvalue()+errors.getvalue())



@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'POSIX nofollow reads')
class StartupFilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.site = self.root / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        self.site.mkdir(parents=True)
        self.cfg = self.root / 'pyvenv.cfg'
        self.cfg.write_bytes(b'home = /never/report/this\nuv = 0.11.7\ninclude-system-site-packages = false\nversion_info = 3.12.13\n')
        self.py = self.site / '_virtualenv.py'
        self.py.write_bytes(b'raise AssertionError("MUST NOT EXECUTE")\n')
        self.pth = self.site / '_virtualenv.pth'
        self.pth.write_bytes(b'import _virtualenv')

    def test_fixed_files_observed_no_execution_or_private_paths(self):
        result = probe.probe(str(self.root))
        self.assertEqual(result['status'], 'OBSERVED')
        self.assertTrue(result['uv0117ConfigMatches'])
        self.assertFalse(any(result['startupProfileMatches'].values()))
        for key in ('factoryExecutionVerified', 'startupSafetyVerified', 'scientificConclusionVerified'):
            self.assertFalse(result[key])
        serialized = json.dumps(result)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn('/never/report', serialized)
        self.assertNotIn('MUST NOT EXECUTE', serialized)

    def test_missing_oversize_and_file_symlink_fail_closed(self):
        self.py.unlink()
        self.assertEqual(probe.probe(str(self.root))['files']['virtualenvPy']['status'], 'MISSING')
        self.py.write_bytes(b'x'*(probe.MAX_BYTES+1))
        self.assertEqual(probe.probe(str(self.root))['files']['virtualenvPy']['status'], 'UNCONFIRMED')
        self.py.unlink(); self.py.symlink_to(self.cfg)
        self.assertEqual(probe.probe(str(self.root))['files']['virtualenvPy']['status'], 'UNCONFIRMED')

    def test_root_symlink_and_noncanonical_paths_deny(self):
        alias = self.root / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        for root in (str(alias), str(self.root)+'/../'+self.root.name, str(self.root)+'/.'):
            self.assertEqual(probe.probe(root)['status'], 'UNCONFIRMED')

    def test_hardlink_and_identity_drift_are_unconfirmed(self):
        os.link(self.py, self.site / 'other')
        self.assertEqual(probe.probe(str(self.root))['files']['virtualenvPy']['status'], 'UNCONFIRMED')
        (self.site / 'other').unlink()
        original = probe.os.read
        changed = False
        def reading(fd, size):
            nonlocal changed
            raw = original(fd, size)
            if raw.startswith(b'raise') and not changed:
                changed = True
                self.py.write_bytes(b'changed file\n')
            return raw
        with patch.object(probe.os, 'read', side_effect=reading):
            self.assertEqual(probe.probe(str(self.root))['files']['virtualenvPy']['status'], 'UNCONFIRMED')

    def test_profile_match_needs_both_exact_startup_files_and_config(self):
        import hashlib
        fake_profiles = {'controlled-profile': ('0.11.7', hashlib.sha256(self.py.read_bytes()).hexdigest(), self.py.stat().st_size)}
        with patch.object(probe, 'PROFILES', fake_profiles):
            result = probe.probe(str(self.root))
            self.assertTrue(result['startupProfileMatches']['controlled-profile'])
            self.assertFalse(result['startupSafetyVerified'])
            self.pth.write_bytes(b'import _virtualenv\n')
            self.assertFalse(probe.probe(str(self.root))['startupProfileMatches']['controlled-profile'])
