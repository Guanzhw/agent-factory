"""Real inert guardian verifies explicit no-bytecode dispatch; no PG/GPU/model."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_factory import process_enforcement as module


@unittest.skipUnless(sys.platform == 'linux', 'Owned guardian requires Linux /proc')
class ResearchBytecodeContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.support = self.root / 'sealed-support'; self.support.mkdir(mode=0o700)
        original = Path(module.__file__).parent
        for name in ('process_enforcement.py', 'process_enforcement_guardian.py'):
            shutil.copyfile(original / name, self.support / name)
        self.executable = Path(sys.executable).resolve()

    def snapshot(self):
        return {str(path.relative_to(self.support)): (path.stat().st_ino, path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest())
                for path in self.support.rglob('*') if path.is_file()}

    def test_real_guardian_launch_uses_B_and_preserves_complete_support_tree(self):
        before = self.snapshot()
        spec = module.ProcessSpec(str(self.executable), hashlib.sha256(self.executable.read_bytes()).hexdigest(),
                                  ('-I', '-B', '-c', "print('inert controlled child')"))
        adapter = module.BoundedProcessAdapter.create(self.root / 'custody.sqlite', owner_id='alice',
            task_id='original-task', request_id='original-request', spec=spec, limits=module.ProcessLimits())
        original_popen = subprocess.Popen
        launched = []
        def popen(args, **kwargs):
            launched.append(list(args))
            return original_popen(args, **kwargs)
        with patch.object(module, '__file__', str(self.support / 'process_enforcement.py')), \
                patch.object(module.subprocess, 'Popen', side_effect=popen):
            adapter.launch(owner_id='alice', before_effect=lambda: None)
        try:
            result = adapter.wait(owner_id='alice')
            self.assertEqual(result['state'], 'COMPLETED')
            self.assertTrue(result['stoppedProof']); self.assertFalse(result['capacityHeld'])
            self.assertEqual(len(launched), 1)
            self.assertEqual(launched[0][:3], [sys.executable, '-I', '-B'])
            self.assertEqual(launched[0][3], str(self.support / 'process_enforcement_guardian.py'))
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(list(self.support.rglob('*.pyc')), [])
            self.assertEqual({p.name for p in self.support.iterdir()}, set(before))
        finally:
            if adapter._process is not None and adapter._process.poll() is None:
                adapter.cancel(owner_id='alice'); adapter.wait(owner_id='alice')

    def test_missing_B_rejects_before_local_import_even_with_environment_variable(self):
        marker = self.root / 'local-module-imported'
        (self.support / 'process_enforcement.py').write_text(
            'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("unexpected")\n')
        before = self.snapshot()
        result = subprocess.run([sys.executable, '-I', str(self.support / 'process_enforcement_guardian.py'),
            str(self.root / 'never-created.sqlite')], env={'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
        self.assertEqual(result.returncode, 126)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'PROCESS_GUARDIAN_BYTECODE_DENIED\n')
        self.assertFalse(marker.exists()); self.assertFalse((self.root / 'never-created.sqlite').exists())
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(path.name == '__pycache__' for path in self.support.rglob('*')))
