"""Small real cooperative child processes; no cgroup, host or network changes."""
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessEnforcementError, ProcessLimits, ProcessSpec, birth, boot_id, same_birth


@unittest.skipUnless(sys.platform == "linux", "Linux /proc and POSIX rlimits required")
class ProcessEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="bounded-process-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "custody.sqlite"
        executable = Path(sys.executable).resolve()
        self.executable = str(executable)
        self.sha = hashlib.sha256(executable.read_bytes()).hexdigest()

    def adapter(self, code, **limits):
        return BoundedProcessAdapter.create(self.path, owner_id="alice", task_id="task1", request_id="request1",
            spec=ProcessSpec(self.executable, self.sha, ("-I", "-c", code)), limits=ProcessLimits(**limits))

    def execute(self, code, **limits):
        adapter = self.adapter(code, **limits)
        adapter.launch(owner_id="alice", before_effect=lambda: None)
        result = adapter.wait(owner_id="alice")
        self.assertTrue(result["stoppedProof"], result)
        self.assertFalse(result["capacityHeld"])
        if result["child"]:
            current = birth(result["child"]["pid"])
            self.assertTrue(current is None or current["start"] != result["child"]["start"])
        return result

    def test_real_child_observes_kernel_limits_and_clean_environment(self):
        code = "import resource,json,os;print(json.dumps({'cpu':resource.getrlimit(resource.RLIMIT_CPU),'memory':resource.getrlimit(resource.RLIMIT_AS),'file':resource.getrlimit(resource.RLIMIT_FSIZE),'environment':sorted(os.environ)}))"
        result = self.execute(code, address_space_mb=64, file_size_bytes=4096)
        self.assertEqual(result["state"], "COMPLETED")
        observed = json.loads(self.path.with_suffix(".output").read_text())
        self.assertEqual(observed["cpu"], [1, 1])
        self.assertEqual(observed["memory"], [64 * 1024 * 1024] * 2)
        self.assertEqual(observed["file"], [4096, 4096])
        self.assertTrue(set(observed["environment"]) <= {"LANG", "LC_CTYPE"})
        self.assertFalse(result["enforcement"]["aggregateQuota"])
        self.assertFalse(result["enforcement"]["networkIsolation"])

    def test_cpu_spin_is_actually_stopped_by_kernel_cpu_limit(self):
        result = self.execute("while True: pass", wall_seconds=4)
        self.assertEqual(result["state"], "LIMIT_STOPPED")
        self.assertIn(result["exitCode"], {-signal.SIGKILL, -signal.SIGXCPU})

    def test_address_space_prevents_large_allocation(self):
        result = self.execute("import sys\ntry: x=bytearray(256*1024*1024)\nexcept MemoryError: sys.exit(7)", address_space_mb=64)
        self.assertEqual(result["exitCode"], 7)
        self.assertEqual(result["state"], "FAILED")

    def test_file_limit_bounds_actual_regular_output(self):
        result = self.execute("import os;os.write(1,b'x'*65536);os.write(1,b'x')", file_size_bytes=4096)
        self.assertNotEqual(result["exitCode"], 0)
        self.assertLessEqual(self.path.with_suffix(".output").stat().st_size, 4096)

    def test_wall_deadline_stops_cooperative_descendant_group(self):
        result = self.execute("import os,time;os.fork();time.sleep(20)", wall_seconds=.2)
        self.assertEqual(result["state"], "LIMIT_STOPPED")
        self.assertEqual(result["stopEvidence"], "original-root-reaped-and-no-live-process-group-members")

    def test_reopened_owner_can_cancel_original_without_dispatch(self):
        original = self.adapter("import time;time.sleep(20)")
        original.launch(owner_id="alice", before_effect=lambda: None)
        deadline = time.monotonic() + 2
        while original.inspect(owner_id="alice")["state"] != "RUNNING" and time.monotonic() < deadline:
            time.sleep(.01)
        reopened = BoundedProcessAdapter(self.path)
        with self.assertRaises(ProcessEnforcementError):
            reopened.launch(owner_id="alice", before_effect=lambda: None)
        with self.assertRaises(ProcessEnforcementError):
            reopened.cancel(owner_id="bob")
        reopened.cancel(owner_id="alice")
        result = original.wait(owner_id="alice")
        self.assertEqual(result["state"], "CANCELLED")
        self.assertTrue(result["stoppedProof"])

    def test_fresh_authority_denial_precedes_launch_and_lost_receipt_never_replays(self):
        adapter = self.adapter("pass")
        def deny():
            raise PermissionError("Controlled current authority denial")
        with patch("agent_factory.process_enforcement.subprocess.Popen") as spawn:
            with self.assertRaises(PermissionError):
                adapter.launch(owner_id="alice", before_effect=deny)
            spawn.assert_not_called()
        self.assertEqual(adapter.inspect(owner_id="alice")["state"], "PREPARED")
        with patch("agent_factory.process_enforcement.subprocess.Popen", side_effect=OSError("Controlled lost receipt")) as spawn:
            with self.assertRaises(ProcessEnforcementError):
                adapter.launch(owner_id="alice", before_effect=lambda: None)
            spawn.assert_called_once()
        reopened = BoundedProcessAdapter(self.path)
        facts = reopened.inspect(owner_id="alice")
        self.assertEqual(facts["state"], "UNKNOWN")
        self.assertTrue(facts["capacityHeld"])
        with self.assertRaises(ProcessEnforcementError):
            reopened.launch(owner_id="alice", before_effect=lambda: None)
        with self.assertRaises(FileExistsError):
            self.adapter("pass")

    def test_async_authority_callback_cannot_skip_authorization(self):
        adapter = self.adapter("pass")
        ran = []
        async def guard():
            ran.append(True)
        with patch("agent_factory.process_enforcement.subprocess.Popen") as spawn:
            with self.assertRaises(ProcessEnforcementError):
                adapter.launch(owner_id="alice", before_effect=guard)
            spawn.assert_not_called()
        self.assertEqual(ran, [])
        facts = adapter.inspect(owner_id="alice")
        self.assertEqual(facts["state"], "PREPARED")
        self.assertTrue(facts["capacityHeld"])


    def rewrite(self, change):
        with sqlite3.connect(self.path) as conn:
            body = json.loads(conn.execute("SELECT body FROM custody").fetchone()[0])
            change(body)
            conn.execute("UPDATE custody SET body=?", (json.dumps(body),))

    def test_birth_identity_rejects_boot_group_and_pid_reuse(self):
        actual = birth(os.getpid())
        self.assertIsNotNone(actual)
        assert actual is not None
        self.assertTrue(same_birth(actual, dict(actual)))
        for key, value in (("bootId", "0" * 36), ("start", "different"), ("pid", -1), ("group", -1)):
            with self.subTest(key=key):
                self.assertFalse(same_birth(actual, {**actual, key: value}))

    def test_reopen_rejects_changed_spec_and_replaced_journal_inode(self):
        self.adapter("pass")
        original = self.path.read_bytes()
        self.rewrite(lambda body: body["spec"].update(argv=["-I", "-c", "unexpected"]))
        with self.assertRaises(ProcessEnforcementError):
            BoundedProcessAdapter(self.path)
        self.path.write_bytes(original)
        copied = self.path.with_suffix(".copy")
        shutil.copyfile(self.path, copied)
        os.chmod(copied, 0o600)
        os.replace(copied, self.path)
        with self.assertRaises(ProcessEnforcementError):
            BoundedProcessAdapter(self.path)

    def test_missing_stop_receipt_and_new_boot_never_release(self):
        adapter = self.adapter("pass")
        adapter.cancel(owner_id="alice")
        self.assertTrue(BoundedProcessAdapter(self.path).inspect(owner_id="alice")["stoppedProof"])
        with patch("agent_factory.process_enforcement.boot_id", return_value="0" * 36):
            drift = BoundedProcessAdapter(self.path).inspect(owner_id="alice")
        self.assertEqual(drift["state"], "UNKNOWN")
        self.assertTrue(drift["capacityHeld"])
        self.rewrite(lambda body: body.update(stopReceipt=None))
        missing = BoundedProcessAdapter(self.path).inspect(owner_id="alice")
        self.assertEqual(missing["state"], "UNKNOWN")
        self.assertFalse(missing["stoppedProof"])
        self.assertTrue(missing["capacityHeld"])

    def test_guardian_lost_keeps_unknown_even_after_fixture_stops_original_child(self):
        adapter = self.adapter("import time;time.sleep(20)")
        adapter.launch(owner_id="alice", before_effect=lambda: None)
        deadline = time.monotonic() + 2
        facts = adapter.inspect(owner_id="alice")
        while facts["state"] != "RUNNING" and time.monotonic() < deadline:
            time.sleep(.01)
            facts = adapter.inspect(owner_id="alice")
        self.assertEqual(facts["state"], "RUNNING")
        guardian, child = facts["guardian"], facts["child"]
        try:
            self.assertEqual(guardian["bootId"], boot_id())
            self.assertTrue(same_birth(birth(guardian["pid"]), guardian))
            os.kill(guardian["pid"], getattr(signal, "SIGKILL"))
            assert adapter._process is not None
            adapter._process.wait(timeout=2)
            reopened = BoundedProcessAdapter(self.path)
            lost = reopened.inspect(owner_id="alice")
            self.assertEqual(lost["state"], "UNKNOWN")
            self.assertTrue(lost["capacityHeld"])
            with patch("agent_factory.process_enforcement.subprocess.Popen") as spawn:
                with self.assertRaises(ProcessEnforcementError):
                    reopened.launch(owner_id="alice", before_effect=lambda: None)
                spawn.assert_not_called()
        finally:
            # Test-only emergency cleanup signals only the positively matched
            # original trusted child; adapter itself never guesses release.
            if same_birth(birth(child["pid"]), child):
                getattr(os, "killpg")(child["pid"], getattr(signal, "SIGKILL"))
            cleanup_deadline = time.monotonic() + 1
            current = birth(child["pid"])
            while same_birth(current, child) and current is not None and current["state"] != "Z" and time.monotonic() < cleanup_deadline:
                time.sleep(.01)
                current = birth(child["pid"])
            self.assertTrue(not same_birth(current, child) or current is not None and current["state"] == "Z")
            if adapter._process is not None and adapter._process.poll() is None:
                adapter.cancel(owner_id="alice")
                adapter._process.wait(timeout=6)
        stopped = BoundedProcessAdapter(self.path).inspect(owner_id="alice")
        self.assertEqual(stopped["state"], "UNKNOWN")
        self.assertFalse(stopped["stoppedProof"])


if __name__ == "__main__":
    unittest.main()
