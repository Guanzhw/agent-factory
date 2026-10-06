"""Public delivery helpers: synthetic package integrity and fail-closed artifacts."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('install_closure', Path(__file__).parents[2] / 'scripts/verify_closure.py')
assert SPEC and SPEC.loader
closure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(closure)


class InstallHandoffTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()

    def metadata(self, directory, name, version):
        p = self.site / directory
        p.mkdir()
        (p / 'METADATA').write_text(f'Name: {name}\nVersion: {version}\n')

    def test_duplicate_normalized_distribution_rejected(self):
        self.metadata('one.dist-info', 'Some_Package', '1.0')
        self.metadata('two.dist-info', 'some-package', '1.0')
        with self.assertRaisesRegex(ValueError, 'INSTALL_CLOSURE_REJECTED'):
            closure.versions(self.site)

    def test_constraint_line_injection_rejected(self):
        self.metadata('one.dist-info', 'some-package', '1.0 --index-url=unsafe')
        with self.assertRaises(ValueError):
            closure.versions(self.site)

    def test_private_receipt_cannot_overwrite_prior_evidence(self):
        target = self.evidence / 'receipt.json'
        closure.save(target, {'original': True})
        with self.assertRaises(FileExistsError):
            closure.save(target, {'replacement': True})
        self.assertEqual(json.loads(target.read_bytes()), {'original': True})

    def test_snapshot_requires_complete_original_package_set(self):
        self.metadata('factory.dist-info', 'department-agent-factory', '0.2.0')
        argv = ['verify_closure.py', 'snapshot', '--old-site', str(self.site), '--evidence', str(self.evidence)]
        with patch('sys.argv', argv), self.assertRaises(ValueError):
            closure.main()
        self.assertEqual(list(self.evidence.iterdir()), [])

    def test_full_snapshot_preserves_all_exact_versions(self):
        self.metadata('factory.dist-info', 'department-agent-factory', '0.2.0')
        for i in range(94):
            self.metadata(f'fixture{i}.dist-info', f'fixture{i}', '1.0')
        argv = ['verify_closure.py', 'snapshot', '--old-site', str(self.site), '--evidence', str(self.evidence)]
        with patch('sys.argv', argv), redirect_stdout(io.StringIO()):
            closure.main()
        self.assertEqual(len(json.loads((self.evidence / 'old-versions.json').read_bytes())), 95)
        self.assertEqual(len((self.evidence / 'constraints.txt').read_text().splitlines()), 95)

    def wheel(self, *, extra=False, stale=False):
        path = self.root / 'fixture.whl'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('agent_factory/__init__.py', b'stale' if stale else b'# exact\n')
            z.writestr('department_agent_factory-0.2.0.dist-info/METADATA',
                       'Name: department-agent-factory\nVersion: 0.2.0\n')
            if extra:
                z.writestr('unexpected.pth', 'import unsafe\n')
        return path

    def verify_wheel(self, path):
        argv = ['verify_closure.py', 'wheel', '--wheel', str(path), '--evidence', str(self.evidence)]
        rows = {'agent_factory/__init__.py': hashlib.sha256(b'# exact\n').hexdigest()}
        with patch('sys.argv', argv), patch.object(closure, 'source', return_value=rows), redirect_stdout(io.StringIO()):
            closure.main()

    def test_extra_startup_payload_rejected_before_install(self):
        with self.assertRaises(ValueError):
            self.verify_wheel(self.wheel(extra=True))
        self.assertEqual(list(self.evidence.iterdir()), [])

    def test_same_version_stale_wheel_rejected(self):
        with self.assertRaises(ValueError):
            self.verify_wheel(self.wheel(stale=True))

    def test_exact_wheel_receipt_binds_payload(self):
        wheel = self.wheel()
        self.verify_wheel(wheel)
        receipt = json.loads((self.evidence / 'wheel-verification.json').read_bytes())
        self.assertEqual(receipt['wheelSha256'], closure.sha(wheel))
        self.assertEqual(receipt['head'], closure.HEAD)

    def test_delivery_manifest_pin_remains_distinct_from_new_tool_commit(self):
        manifest = Path(__file__).parents[2] / 'docs/evidence/pr47-source-manifest.json'
        self.assertEqual(closure.sha(manifest), closure.MANIFEST)
        value = json.loads(manifest.read_bytes())
        self.assertEqual(value['head'], closure.HEAD)
        self.assertEqual(len(value['files']), 585)
        self.assertNotIn('scripts/verify_closure.py', {r['path'] for r in value['files']})
