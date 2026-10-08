"""Real stdlib cooperative children only; no training, GPU or cgroup execution."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from agent_factory.process_enforcement import BoundedProcessAdapter, ResearchProcessLimits, ResearchProcessSpec


@unittest.skipUnless(sys.platform == 'linux', 'Linux guardian required')
class ResearchGuardianTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cwd = self.root / 'work'
        self.cwd.mkdir(mode=0o700)
        self.path = self.root / 'custody.sqlite'

    def adapter(self, code, **limits):
        binary = Path(sys.executable).resolve()
        info = self.cwd.stat()
        env = tuple((key, '1') for key in ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE'))
        spec = ResearchProcessSpec(str(binary), hashlib.sha256(binary.read_bytes()).hexdigest(), ('-I', '-c', code),
            working_directory=str(self.cwd), environment=env, working_directory_identity=(info.st_dev, info.st_ino))
        return BoundedProcessAdapter.create(self.path, owner_id='alice', task_id='task', request_id='request',
            spec=spec, limits=ResearchProcessLimits(cpu_seconds=2, address_space_mb=128,
                file_size_bytes=2 * 1024**3, wall_seconds=3, **limits))

    def execute(self, adapter):
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        result = adapter.wait(owner_id='alice')
        self.assertTrue(result['stoppedProof'], result)
        self.assertFalse(result['capacityHeld'])
        return result

    def test_clean_environment_cwd_and_large_checkpoint_limit(self):
        result = self.execute(self.adapter("import os,json,resource;open('checkpoint','wb').write(b'x'*65536);print(json.dumps([os.getcwd(),dict(os.environ),resource.getrlimit(resource.RLIMIT_FSIZE)]))", output_bytes=1024))
        self.assertEqual(result['state'], 'COMPLETED')
        cwd, env, limit = json.loads(self.path.with_suffix('.output').read_bytes())
        self.assertEqual(cwd, str(self.cwd))
        self.assertEqual(set(env) - {'LANG', 'LC_CTYPE'}, {'HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE'})
        self.assertEqual(limit, [2 * 1024**3] * 2)
        self.assertEqual((self.cwd / 'checkpoint').stat().st_size, 65536)

    def test_combined_stdout_stderr_bound_stops_original_group(self):
        adapter = self.adapter("import os;os.fork()\nwhile True: os.write(1,b'x'*4096);os.write(2,b'y'*4096)", output_bytes=1024)
        result = self.execute(adapter)
        self.assertEqual(result['state'], 'LIMIT_STOPPED')
        self.assertEqual(self.path.with_suffix('.output').stat().st_size, 1024)
        self.assertEqual(result['stopEvidence'], 'original-root-reaped-and-no-live-process-group-members')

    def test_pipe_drains_without_deadlock_below_bound(self):
        result = self.execute(self.adapter("import os;os.write(1,b'x'*200000)", output_bytes=262144))
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(self.path.with_suffix('.output').read_bytes(), b'x'*200000)

    def test_reopened_cancel_keeps_original_child(self):
        adapter = self.adapter("import time;time.sleep(20)", output_bytes=1024)
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        deadline = time.monotonic() + 2
        while adapter.inspect(owner_id='alice')['state'] != 'RUNNING' and time.monotonic() < deadline:
            time.sleep(.01)
        child = adapter.inspect(owner_id='alice')['child']
        BoundedProcessAdapter(self.path).cancel(owner_id='alice')
        result = adapter.wait(owner_id='alice')
        self.assertEqual(result['state'], 'CANCELLED')
        self.assertEqual(result['child'], child)
        self.assertTrue(result['stoppedProof'])

    def test_replaced_cwd_denies_before_exec(self):
        adapter = self.adapter("open('executed','w').write('bad')", output_bytes=1024)
        self.cwd.rename(self.root / 'original')
        self.cwd.mkdir(mode=0o700)
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        result = adapter.wait(owner_id='alice')
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertTrue(result['capacityHeld'])
        self.assertIsNone(result['child'])
        self.assertFalse((self.cwd / 'executed').exists())

    def test_symlink_component_denied_before_journal(self):
        real = self.cwd
        self.cwd = self.root / 'link'
        self.cwd.symlink_to(real, target_is_directory=True)
        with self.assertRaises(OSError):
            self.adapter('pass', output_bytes=1024)
        self.assertFalse(self.path.exists())
