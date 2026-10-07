"""PR50 delivery closure; synthetic artifacts only, no installer/database startup."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location('pr50_closure', ROOT / 'scripts/verify_pr50_closure.py')
assert SPEC and SPEC.loader
closure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(closure)


class Pr50InstallClosureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_public_manifest_pins_exact_pr50_and_135_payloads(self):
        path = ROOT / 'docs/evidence/pr50-source-manifest.json'
        self.assertEqual(closure.sha(path), closure.MANIFEST)
        manifest = json.loads(path.read_bytes())
        self.assertEqual(manifest['head'], '997013114a8c533c84078d174b220e541ea19f9a')
        self.assertEqual(len(manifest['files']), 603)
        rows = [r for r in manifest['files'] if r['path'].startswith('platform/agent_factory/')]
        self.assertEqual(len(rows), 135)
        self.assertEqual(len({row['path'] for row in rows}), 135)
        for row in rows:
            self.assertRegex(row['sha256'], r'^[a-f0-9]{64}$')
        self.assertNotIn('scripts/verify_pr50_closure.py', {r['path'] for r in manifest['files']})

    def fixture_source(self):
        source = self.root / 'source'
        package = source / 'platform/agent_factory'
        package.mkdir(parents=True)
        (package / '__init__.py').write_bytes(b'# exact\n')
        manifest = self.root / 'manifest.json'
        manifest.write_text(json.dumps({'head': closure.HEAD, 'files': [
            {'path': 'platform/agent_factory/__init__.py', 'sha256': closure.sha(package / '__init__.py')}
        ]}))
        return SimpleNamespace(source=source, manifest=manifest)

    def test_source_mutation_and_manifest_substitution_rejected(self):
        args = self.fixture_source()
        with patch.object(closure, 'MANIFEST', closure.sha(args.manifest)), \
                patch.object(closure, 'SOURCE_FILES', 1), patch.object(closure, 'PACKAGE_FILES', 1):
            self.assertEqual(len(closure.source(args)), 1)
            (args.source / 'platform/agent_factory/__init__.py').write_bytes(b'# changed\n')
            with self.assertRaises(ValueError):
                closure.source(args)
            args.manifest.write_text('{}')
            with self.assertRaises(ValueError):
                closure.source(args)

    def wheel(self, *, stale=False, extra=None):
        path = self.root / 'test.whl'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('agent_factory/__init__.py', b'# stale\n' if stale else b'# exact\n')
            archive.writestr('department_agent_factory-0.2.0.dist-info/METADATA',
                            'Name: department-agent-factory\nVersion: 0.2.0\n')
            if extra:
                archive.writestr(extra, b'unsafe')
        return path

    def test_same_version_stale_and_extra_payloads_rejected(self):
        rows = {'agent_factory/__init__.py': hashlib.sha256(b'# exact\n').hexdigest()}
        closure.verify_wheel(self.wheel(), rows)
        for options in [{'stale': True}, {'extra': 'startup.pth'},
                        {'extra': 'agent_factory/__pycache__/__init__.pyc'}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                closure.verify_wheel(self.wheel(**options), rows)

    def test_snapshot_preserves_95_versions_without_reading_config(self):
        site, evidence = self.root / 'site', self.root / 'evidence'
        site.mkdir(); evidence.mkdir()
        for i in range(95):
            name = 'department-agent-factory' if i == 0 else f'fixture-{i}'
            dist = site / f'{i}.dist-info'
            dist.mkdir()
            (dist / 'METADATA').write_text(f'Name: {name}\nVersion: {"0.2.0" if i == 0 else "1.0"}\n')
        command = [sys.executable, '-I', '-B', str(ROOT / 'scripts/verify_pr50_closure.py'),
                   'snapshot', '--old-site', str(site), '--evidence', str(evidence),
                   '--config', str(self.root / 'must-not-read')]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads((evidence / 'old-versions.json').read_bytes())), 95)
        self.assertEqual(len((evidence / 'constraints.txt').read_text().splitlines()), 95)
        # Prior evidence is immutable; an invocation cannot overwrite it.
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
        self.assertFalse(any(self.root.rglob('*.pyc')))

    def test_cli_requires_isolation_and_explicit_bytecode_suppression(self):
        for flags in [[], ['-I'], ['-B']]:
            result = subprocess.run([sys.executable, *flags,
                str(ROOT / 'scripts/verify_pr50_closure.py'), 'source'], capture_output=True)
            self.assertEqual(result.returncode, 2)

    def test_receipt_pins_runtime_and_manifest_separately(self):
        evidence = self.root / 'evidence'; evidence.mkdir()
        rows = {'agent_factory/__init__.py': hashlib.sha256(b'# exact\n').hexdigest()}
        args = ['verify_pr50_closure.py', 'wheel', '--wheel', str(self.wheel()), '--evidence', str(evidence)]
        with patch('sys.argv', args), patch.object(closure, 'source', return_value=rows), \
                patch.object(closure.sys, 'dont_write_bytecode', True), \
                patch.object(closure.sys, 'flags', SimpleNamespace(**{name: (1 if name == 'isolated' else getattr(sys.flags, name))
                    for name in dir(sys.flags) if not name.startswith('_')})), redirect_stdout(io.StringIO()):
            closure.main()
        receipt = json.loads((evidence / 'wheel-verification.json').read_bytes())
        self.assertEqual(receipt['head'], closure.HEAD)
        self.assertEqual(receipt['sourceManifestSha256'], closure.MANIFEST)
        self.assertNotIn('sourcePatch', receipt)

    @unittest.skipUnless(os.name == 'posix', 'Linux installation procedure')
    def test_historical_pins_unchanged_and_new_script_syntax_valid(self):
        old = (ROOT / 'scripts/verify_closure.py').read_text()
        self.assertIn("HEAD = '6d6eb9f5fbd3ead921a82b1226edbe6f3d96c12f'", old)
        self.assertIn("PATH_FIX_SHA256 = 'ee479cf871534572d62b292bdd616e7e657ddc2a93e1d2713e26af78c91bc587'", old)
        result = subprocess.run(['bash', '-n', str(ROOT / 'scripts/install-pr50-handoff.sh')], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.name == 'posix', 'Linux installation procedure')
    def test_installer_rejects_clone_policy_override_and_old_tree_overlap_before_writes(self):
        old = self.root / 'old'; old.mkdir()
        source = self.root / 'source'; source.mkdir()
        new = self.root / 'fresh'
        env = {**os.environ, 'UV': '/does-not-exist', 'CONTROL_PYTHON': sys.executable,
               'BASE_PYTHON': sys.executable, 'OLD_PROJECT': str(old), 'OLD_SITE': str(old),
               'OLD_CONFIG': str(old / 'unread-config'), 'NEW_ROOT': str(new),
               'SOURCE': str(source), 'MANIFEST': str(source / 'unread-manifest'),
               'VERIFIER': str(ROOT / 'scripts/verify_pr50_closure.py'), 'UV_CACHE_DIR': str(self.root)}
        command = ['bash', str(ROOT / 'scripts/install-pr50-handoff.sh')]
        for args in [['--copy-mode', 'clone'], ['--compile-bytecode'], ['--python', sys.executable]]:
            with self.subTest(args=args):
                self.assertEqual(subprocess.run(command + args, env=env, capture_output=True).returncode, 2)
                self.assertFalse(new.exists())
        env['NEW_ROOT'] = str(old / 'fresh')
        self.assertNotEqual(subprocess.run(command, env=env, capture_output=True).returncode, 0)
        self.assertEqual(list(old.iterdir()), [])
