"""Synthetic GCC/linker descendants under the real guardian; no Torch or GPU."""
from dataclasses import replace
import json
import os
import sys
import unittest
from unittest.mock import patch

from agent_factory.process_enforcement import ResearchProcessLimits
import test_research_baseline_runner as baseline
import test_research_uv_guardian as guardian


@unittest.skipUnless(sys.platform == 'linux' and os.access('/usr/bin/gcc', os.X_OK)
                     and os.access('/usr/bin/ld', os.X_OK), 'Linux system GCC/linker required')
class ResearchToolchainPathTests(unittest.TestCase):
    # Reuse the pinned synthetic interpreter fixture without rediscovering its tests.
    setUp = guardian.ResearchUvGuardianTests.setUp
    spec = guardian.ResearchUvGuardianTests.spec
    create = guardian.ResearchUvGuardianTests.create

    def stop_adapter(self, adapter):
        if not adapter.inspect(owner_id='alice')['stoppedProof']:
            adapter.cancel(owner_id='alice')
        self.assertTrue(adapter.wait(owner_id='alice', timeout=10)['stoppedProof'])

    def test_guardian_preserves_fixed_tool_path_for_compiler_descendants(self):
        self.limits = ResearchProcessLimits(cpu_seconds=5, address_space_mb=512,
            file_size_bytes=1024**2, wall_seconds=10, disk_bytes=4 * 1024**2,
            output_bytes=65536)
        cache = self.cwd / 'cache'; cache.mkdir(mode=0o700)
        (self.cwd / 'synthetic.c').write_text('int answer(void) { return 42; }\n')
        # Neither the current directory nor an inherited host PATH may select ld.
        marker = self.cwd / 'untrusted-linker-ran'
        untrusted = self.cwd / 'ld'
        untrusted.write_text('#!/bin/sh\n/usr/bin/touch untrusted-linker-ran\nexit 99\n')
        untrusted.chmod(0o700)
        self.entry.write_text('''import json, os, subprocess, sys
result = subprocess.run(['/usr/bin/gcc', '-shared', '-fPIC', 'synthetic.c', '-o', 'synthetic.so'],
    capture_output=True, text=True, timeout=5)
print(json.dumps({'path': os.environ.get('PATH'), 'returncode': result.returncode,
    'stderr': result.stderr, 'filtered': all(key not in os.environ for key in
    ('SYNTHETIC_CREDENTIAL', 'COMPILER_PATH', 'LIBRARY_PATH', 'GCC_EXEC_PREFIX', 'LD_PRELOAD'))}))
sys.exit(result.returncode)
''')
        hostile = {'PATH': str(self.cwd), 'SYNTHETIC_CREDENTIAL': 'synthetic-only',
                   'COMPILER_PATH': str(self.cwd), 'LIBRARY_PATH': str(self.cwd),
                   'GCC_EXEC_PREFIX': str(self.cwd)}
        with patch.dict(os.environ, hostile):
            env = baseline.runner.launch_environment({'deviceUuid': 'synthetic-no-device'}, self.cwd, cache)
            adapter = self.create(replace(self.spec(), environment=tuple(env.items())))
            self.addCleanup(self.stop_adapter, adapter)
            adapter.launch(owner_id='alice', before_effect=lambda: None)
        result = adapter.wait(owner_id='alice')
        observed = json.loads(self.path.with_suffix('.output').read_text())
        self.assertEqual(result['state'], 'COMPLETED', observed)
        self.assertTrue(result['stoppedProof'])
        self.assertFalse(result['capacityHeld'])
        self.assertEqual(observed, {'path': '/usr/bin:/bin', 'returncode': 0, 'stderr': '', 'filtered': True})
        self.assertTrue((self.cwd / 'synthetic.so').is_file())
        self.assertFalse(marker.exists())
