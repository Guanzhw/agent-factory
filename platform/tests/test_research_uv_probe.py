"""Only synthetic metadata and inert package bytes; no target Python or ML launch."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import call, patch


PROBE = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/probe_research_uv.py'))


class ResearchUVProbeTests(unittest.TestCase):
    def runtime(self, root):
        return {'prefix': str(root), 'execPrefix': str(root), 'basePrefix': str(root),
            'baseExecPrefix': str(root), 'executable': str(root / 'bin/python'),
            'sysPath': [str(root)], 'flags': {'no_user_site': 1, 'no_site': 1, 'dont_write_bytecode': 1}}

    def packages(self, root):
        return {name: {'candidates': [{'origin': str(root / name / '__init__.py'), 'locations': []}]}
            for name in PROBE['PACKAGES']}

    def test_expected_prefix_exec_prefix_and_executable_are_independent(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = self.runtime(root)
            self.assertEqual(PROBE['assess'](runtime, self.packages(root), str(root)), [])
            runtime['execPrefix'] = str(root / 'other')
            runtime['executable'] = str(root.parent / 'other/python')
            issues = PROBE['assess'](runtime, self.packages(root), str(root))
            self.assertIn('PREFIX_MISMATCH', issues)
            self.assertIn('EXECUTABLE_OUTSIDE_EXPECTED_VENV', issues)

    def test_site_relative_and_external_import_paths_are_not_silently_accepted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = self.runtime(root)
            runtime['flags'] = {'no_user_site': 0, 'no_site': 0, 'dont_write_bytecode': 0}
            runtime['sysPath'] = ['', str(root.parent / 'outside')]
            issues = PROBE['assess'](runtime, self.packages(root), str(root))
            for code in ('USER_SITE_NOT_DISABLED', 'STARTUP_SITE_ALREADY_RAN',
                         'BYTECODE_WRITES_NOT_DISABLED', 'RELATIVE_IMPORT_PATH',
                         'IMPORT_PATH_OUTSIDE_EXPECTED_ROOTS'):
                self.assertIn(code, issues)

    def test_filefinder_never_imports_inert_packages_or_uses_global_hooks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in PROBE['PACKAGES']:
                package = root / name
                package.mkdir()
                (package / '__init__.py').write_text('raise RuntimeError("MUST_NOT_IMPORT")\n')
            before = set(sys.modules)
            with patch.object(sys, 'meta_path', []), patch.object(sys, 'path_hooks', []):
                result = PROBE['package_specs']([str(root)])
            self.assertEqual(set(sys.modules), before)
            for name in PROBE['PACKAGES']:
                self.assertEqual(result[name]['candidates'][0]['origin'], str(root / name / '__init__.py'))
                self.assertFalse(result[name]['importedByProbe'])
            self.assertFalse(any(root.rglob('__pycache__')))

    def test_shadow_and_namespace_are_observations_not_import_proof(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'first', root / 'second'
            first.mkdir(); second.mkdir()
            for path in (first, second):
                (path / 'torch.py').write_text('raise RuntimeError("INERT")\n')
            (first / 'agent_factory').mkdir()
            packages = PROBE['package_specs']([str(first), str(second)])
            issues = PROBE['assess'](self.runtime(first), packages, str(first))
            self.assertIn('PACKAGE_SHADOW_TORCH', issues)
            self.assertIn('PACKAGE_OUTSIDE_EXPECTED_VENV_TORCH', issues)
            self.assertIn('PACKAGE_OUTSIDE_EXPECTED_VENV_AGENT_FACTORY', issues)

    def test_absent_expected_venv_has_no_passing_status(self):
        with patch.object(sys, 'path', []):
            report = PROBE['observe']()
        self.assertIn('EXPECTED_VENV_UNSPECIFIED', report['issues'])
        self.assertEqual(report['status'], 'DIAGNOSTIC_ONLY')
        self.assertTrue(all(value is False for value in report['capabilities'].values()))

    def test_changed_prefix_and_even_clean_profile_never_grant_capability(self):
        with TemporaryDirectory() as directory, patch.object(sys, 'path', []):
            with patch.object(sys, 'prefix', directory + '-other'):
                report = PROBE['observe'](expected_venv=directory)
            self.assertIn('PREFIX_MISMATCH', report['issues'])
            self.assertFalse(report['capabilities']['startupSafetyVerified'])
            self.assertFalse(report['capabilities']['scientificExecutionVerified'])

    def test_original_argv_and_binary_paths_are_bounded_diagnostic_metadata(self):
        argv = ['/public/venv/bin/python', '-B', '/public/probe_research_uv.py']
        with patch.object(sys, 'path', []), patch.object(sys, 'orig_argv', argv), \
                patch.object(sys, '_base_executable', '/public/base/python', create=True), \
                patch.object(sys, 'platform', 'linux'), \
                patch.object(os, 'readlink', return_value='/public/base/python') as readlink:
            report = PROBE['observe']()
        self.assertEqual(report['runtime']['origArgv'], argv)
        self.assertEqual(report['runtime']['baseExecutable'], '/public/base/python')
        self.assertEqual(report['runtime']['executedBinaryLink'], '/public/base/python')
        self.assertIn(call('/proc/self/exe'), readlink.call_args_list)
        self.assertFalse(report['capabilities']['fdLaunchVerified'])
        for invalid in (['x'] * 33, ['x' * 4097], [False]):
            with patch.object(sys, 'orig_argv', invalid), self.assertRaises(ValueError):
                PROBE['observe']()

    def test_binary_link_missing_or_nonlinux_and_nonstring_base_are_unknown(self):
        with patch.object(sys, 'path', []), patch.object(sys, '_base_executable', False, create=True), \
                patch.object(sys, 'platform', 'linux'), patch.object(os, 'readlink', side_effect=OSError):
            report = PROBE['observe']()
        self.assertIsNone(report['runtime']['baseExecutable'])
        self.assertIsNone(report['runtime']['executedBinaryLink'])
        with patch.object(sys, 'path', []), patch.object(sys, 'platform', 'win32'), \
                patch.object(sys, 'executable', ''), patch.object(os, 'readlink') as readlink:
            self.assertIsNone(PROBE['observe']()['runtime']['executedBinaryLink'])
        readlink.assert_not_called()

    def test_bounded_metadata_hash_and_no_content_echo(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'uv.lock'
            content = b'synthetic public metadata only'
            path.write_bytes(content)
            result = PROBE['passive_file'](path)
            if os.name == 'posix':
                self.assertEqual(result['status'], 'OBSERVED_REGULAR_FILE')
                self.assertEqual(result['sha256'], hashlib.sha256(content).hexdigest())
            else:
                self.assertEqual(result['status'], 'READ_IDENTITY_UNSUPPORTED')
            self.assertNotIn(content.decode(), json.dumps(result))
            path.write_bytes(b'x' * (PROBE['MAX_FILE_BYTES'] + 1))
            self.assertEqual(PROBE['passive_file'](path)['status'], 'SIZE_LIMIT')

    @unittest.skipUnless(os.name == 'posix', 'Synthetic POSIX links')
    def test_symlink_and_hardlink_are_not_hashed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'public.txt'; source.write_bytes(b'public')
            link = root / 'symlink'; link.symlink_to(source)
            self.assertEqual(PROBE['passive_file'](link)['status'], 'SYMLINK')
            self.assertNotIn('sha256', PROBE['passive_file'](link))
            os.link(source, root / 'hardlink')
            self.assertEqual(PROBE['passive_file'](source)['status'], 'NOT_SINGLE_REGULAR_FILE')

    def test_invalid_input_and_path_limit_have_sanitized_bounded_output(self):
        for arguments in (['--expected-venv', 'relative-private-value'],
                          ['--project-lock', 'invalid\nprivate-value']):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(PROBE['main'](arguments), 2)
            self.assertEqual(json.loads(output.getvalue())['error'], 'PROBE_OBSERVATION_FAILED')
            self.assertNotIn('private-value', output.getvalue())
        with patch.object(sys, 'path', [''] * 65), self.assertRaisesRegex(ValueError, 'PROBE_PATH_LIMIT'):
            PROBE['observe']()


if __name__ == '__main__':
    unittest.main()
