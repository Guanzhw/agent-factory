"""Self-authored CPython venv-layout checks; no uv install, packages or ML."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_factory.process_enforcement import (BoundedProcessAdapter, ProcessEnforcementError,
    ProcessLimits, ProcessSpec, ResearchProcessLimits, UvResearchProcessSpec, execute_pinned_interpreter)
from agent_factory.research_interpreter import capture_interpreter_contract, open_interpreter


@unittest.skipUnless(sys.platform == 'linux', 'Linux guardian and descriptor exec required')
class ResearchUvGuardianTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='synthetic-uv-guardian-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'; self.project.mkdir(mode=0o700)
        self.venv = self.project / '.venv'; self.venv.mkdir(mode=0o700)
        (self.venv / 'bin').mkdir()
        self.site = self.venv / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        self.site.mkdir(parents=True)
        self.package = self.site / 'known.py'; self.package.write_text('# inert fixture package\n')
        self.base_interpreter = Path(sys.executable).resolve()
        approved = self.root / 'approved'; approved.mkdir(mode=0o700)
        (approved / 'bin').mkdir()
        (approved / 'lib').symlink_to(self.base_interpreter.parent.parent / 'lib', target_is_directory=True)
        self.target = approved / 'bin' / 'python-real'
        shutil.copyfile(self.base_interpreter, self.target); self.target.chmod(0o700)
        self.sha = hashlib.sha256(self.target.read_bytes()).hexdigest()
        self.link = self.venv / 'bin' / 'python'; self.link.symlink_to(self.target)
        self.cfg = self.venv / 'pyvenv.cfg'
        self.cfg.write_text(f'home = {self.base_interpreter.parent}\ninclude-system-site-packages = false\n')
        self.project_file = self.project / 'pyproject.toml'; self.project_file.write_text('[project]\nname="synthetic"\n')
        self.lock = self.project / 'uv.lock'; self.lock.write_text('version = 1\n')
        self.inventory = self.project / 'inventory.json'; self.inventory.write_text('{"synthetic":true}')
        self.cwd = self.root / 'job'; self.cwd.mkdir(mode=0o700)
        self.entry = self.cwd / 'entry.py'
        self.entry.write_text('import json,sys\nprint(json.dumps({"prefix":sys.prefix,"executable":sys.executable,"noUserSite":sys.flags.no_user_site}))\n')
        self.journal_dir = self.root / 'custody'; self.journal_dir.mkdir(mode=0o700)
        self.path = self.journal_dir / 'custody.sqlite'
        self.limits = ResearchProcessLimits(cpu_seconds=3, address_space_mb=256, file_size_bytes=65536,
            wall_seconds=3, disk_bytes=131072, output_bytes=65536)

    def spec(self):
        contract = capture_interpreter_contract(executable=str(self.link), sha256=self.sha,
            project_root=self.project, venv_root=self.venv, approved_interpreter_roots=[self.target.parent],
            pyvenv_cfg=self.cfg, pyproject_toml=self.project_file, uv_lock=self.lock,
            package_inventory=self.inventory, package_files=[self.package])
        info = self.cwd.stat()
        return UvResearchProcessSpec(str(self.link), self.sha, ('-B', str(self.entry)),
            str(self.cwd), tuple((key, '1') for key in
                ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE'))
                + (('PYTHONPYCACHEPREFIX', str(self.cwd)),), (info.st_dev, info.st_ino), contract)

    def create(self, spec):
        return BoundedProcessAdapter.create(self.path, owner_id='alice', task_id='task1', request_id='request1',
            spec=spec, limits=self.limits)

    def test_real_uv_layout_prefix_logical_executable_and_original_stop(self):
        adapter = self.create(self.spec())
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        result = adapter.wait(owner_id='alice')
        self.assertEqual(result['state'], 'COMPLETED', result)
        self.assertTrue(result['stoppedProof'])
        self.assertEqual(result['stopReceipt']['kind'], 'original-group-stopped')
        observed = json.loads(self.path.with_suffix('.output').read_text())
        self.assertEqual(observed, {'prefix': str(self.venv), 'executable': str(self.link), 'noUserSite': 1})
        with self.assertRaises(ProcessEnforcementError):
            BoundedProcessAdapter(self.path).launch(owner_id='alice', before_effect=lambda: None)

    def test_cfg_drift_before_create_has_no_journal_or_spawn(self):
        spec = self.spec()
        self.cfg.write_text(self.cfg.read_text() + 'prompt = changed\n')
        with patch('agent_factory.process_enforcement.subprocess.Popen') as spawn:
            with self.assertRaises((ValueError, ProcessEnforcementError)):
                self.create(spec)
            spawn.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_link_drift_before_launch_never_spawns(self):
        adapter = self.create(self.spec())
        self.link.unlink(); self.link.symlink_to('/nonexistent-synthetic-interpreter')
        with patch('agent_factory.process_enforcement.subprocess.Popen') as spawn:
            with self.assertRaises((ValueError, ProcessEnforcementError)):
                adapter.launch(owner_id='alice', before_effect=lambda: None)
            spawn.assert_not_called()

    def test_target_drift_before_create_has_no_journal(self):
        copied = self.root / 'replacement'; copied.mkdir()
        target = copied / 'python-real'; shutil.copyfile(self.target, target); target.chmod(0o700)
        self.link.unlink(); self.link.symlink_to(target)
        self.target = target
        spec = self.spec()
        target.write_bytes(b'synthetic changed executable, never executed')
        with self.assertRaises((ValueError, ProcessEnforcementError)):
            self.create(spec)
        self.assertFalse(self.path.exists())

    def test_running_link_deletion_does_not_prevent_original_cancel(self):
        self.entry.write_text('import time\ntime.sleep(10)\n')
        adapter = self.create(self.spec())
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if adapter.inspect(owner_id='alice')['state'] == 'RUNNING':
                break
            time.sleep(.01)
        self.assertEqual(adapter.inspect(owner_id='alice')['state'], 'RUNNING')
        self.link.unlink()
        reopened = BoundedProcessAdapter(self.path)
        reopened.cancel(owner_id='alice')
        result = reopened.wait(owner_id='alice')
        adapter.wait(owner_id='alice')
        self.assertEqual(result['state'], 'CANCELLED', result)
        self.assertTrue(result['stoppedProof'])
        self.assertFalse(result['capacityHeld'])

    def test_ordinary_spec_still_rejects_interpreter_symlink(self):
        spec = ProcessSpec(str(self.link), self.sha, ('-I', '-c', 'pass'))
        adapter = BoundedProcessAdapter.create(self.path, owner_id='alice', task_id='task1', request_id='request1',
            spec=spec, limits=ProcessLimits())
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        result = adapter.wait(owner_id='alice', timeout=1)
        self.assertNotEqual(result['state'], 'COMPLETED')
        self.assertIsNone(result['child'])

    def test_postgate_cfg_drift_with_held_fd_denies_exec(self):
        spec = self.spec()
        fd = open_interpreter(spec.interpreter_contract, spec.executable, spec.sha256)
        try:
            self.cfg.write_text(self.cfg.read_text() + 'prompt = changed-after-gate\n')
            with patch('agent_factory.process_enforcement.os.execve') as execute:
                with self.assertRaises((ValueError, ProcessEnforcementError)):
                    execute_pinned_interpreter(asdict(spec), fd, dict(spec.environment), lambda: True)
                execute.assert_not_called()
        finally:
            os.close(fd)

    def test_postgate_link_drift_with_held_fd_denies_exec(self):
        spec = self.spec()
        fd = open_interpreter(spec.interpreter_contract, spec.executable, spec.sha256)
        try:
            self.link.unlink(); self.link.symlink_to('/synthetic-replaced-interpreter')
            with patch('agent_factory.process_enforcement.os.execve') as execute:
                with self.assertRaises((ValueError, ProcessEnforcementError)):
                    execute_pinned_interpreter(asdict(spec), fd, dict(spec.environment), lambda: True)
                execute.assert_not_called()
        finally:
            os.close(fd)

    def test_postgate_new_site_files_deny_exec(self):
        for name in ('extra.pth', 'json.py'):
            spec = self.spec()
            fd = open_interpreter(spec.interpreter_contract, spec.executable, spec.sha256)
            injected = self.site / name
            try:
                injected.write_text('# inert newly added namespace entry\n')
                with patch('agent_factory.process_enforcement.os.execve') as execute:
                    with self.subTest(name=name), self.assertRaises((ValueError, ProcessEnforcementError)):
                        execute_pinned_interpreter(asdict(spec), fd, dict(spec.environment), lambda: True)
                    execute.assert_not_called()
            finally:
                os.close(fd)
                injected.unlink()

    def test_postgate_custody_false_or_awaitable_denies_exec(self):
        async def asynchronous_approval():
            return True
        spec = self.spec()
        fd = open_interpreter(spec.interpreter_contract, spec.executable, spec.sha256)
        try:
            for callback in (lambda: False, asynchronous_approval):
                with patch('agent_factory.process_enforcement.os.execve') as execute:
                    with self.assertRaises(ProcessEnforcementError):
                        execute_pinned_interpreter(asdict(spec), fd, dict(spec.environment), callback)
                    execute.assert_not_called()
        finally:
            os.close(fd)

    def test_actual_startup_guard_denies_base_prefix_before_entry(self):
        nested = self.venv / 'other' / 'bin'; nested.mkdir(parents=True)
        self.link = nested / 'python'; self.link.symlink_to(self.target)
        marker = self.cwd / 'entry-executed'
        self.entry.write_text("from pathlib import Path\nPath('entry-executed').write_text('unexpected')\n")
        adapter = self.create(self.spec())
        adapter.launch(owner_id='alice', before_effect=lambda: None)
        result = adapter.wait(owner_id='alice')
        self.assertEqual(result['state'], 'FAILED', result)
        self.assertEqual(result['exitCode'], 126)
        self.assertTrue(result['stoppedProof'])
        self.assertEqual(result['stopReceipt']['kind'], 'original-group-stopped')
        self.assertFalse(marker.exists())
        self.assertIn('RESEARCH_UV_STARTUP_UNVERIFIED', self.path.with_suffix('.output').read_text())
