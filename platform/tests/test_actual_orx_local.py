"""Opt-in pinned REAL ORX local CLI acceptance. No provider/network/paid calls."""
from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from uuid import uuid4

from agent_factory.execution_bindings import EnvironmentLimits
from agent_factory.openresearch import BinaryPin, OpenResearchError, REVISION, VERSION
from agent_factory.orx_local import SOURCE_ARCHIVE_SHA256, TaskLocalORXProvider, TOY_FILES


@unittest.skipUnless(os.name == "nt" and os.getenv("FACTORY_ORX_BINARY")
    and os.getenv("FACTORY_ORX_SOURCE_ARCHIVE") and os.getenv("FACTORY_ORX_SHA256"),
    "Requires explicitly pinned actual Windows ORX binary and source archive")
class ActualLocalORXTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="actual-orx-local-acceptance-")
        self.scope = Path(self.temp.name).resolve() / "exclusive-task"
        self.task_id = str(uuid4())
        self.owner = "synthetic-local-evaluator-owner"
        self.allowed = True
        self.pin = BinaryPin(REVISION, VERSION, os.environ["FACTORY_ORX_SHA256"])
        self.provider = TaskLocalORXProvider(binary=Path(os.environ["FACTORY_ORX_BINARY"]),
            source_archive=Path(os.environ["FACTORY_ORX_SOURCE_ARCHIVE"]),
            git_binary=Path(os.environ.get("FACTORY_ORX_GIT_BINARY", os.environ.get("FACTORY_ORX_GIT", ""))), python_binary=Path(sys._base_executable))
        self.environment = EnvironmentLimits(timeout_seconds=30, output_bytes=65536,
            memory_bytes=512 * 1024**2, process_limit=8, cpu_percent=25)
        self.adapters = []

    def adapter(self, scenario="success", **overrides):
        parameters = dict(owner_id=self.owner, task_id=self.task_id, scope=self.scope,
            authorize=lambda _operation: self.allowed, pin=self.pin, max_output_bytes=65536,
            command_timeout=10, environment=self.environment, scenario=scenario)
        parameters.update(overrides)
        result = self.provider.create_experiment_adapter(**parameters)
        self.adapters.append(result)
        return result

    async def asyncTearDown(self):
        for adapter in self.adapters:
            if adapter._job:
                if adapter._receipt_path.exists():
                    try:
                        await adapter.reclaim_experiment()
                    except Exception:
                        adapter._job.terminate()
                self.assertTrue(adapter._job.evidence()["allStopped"])
                adapter._job.close()
        self.temp.cleanup()

    async def test_01_original_status_error_exits_without_dialog_timeout(self):
        adapter = self.adapter()
        await adapter.preflight()
        result = await adapter._execute(("--no-telemetry", "exp", "status", "nonexistent"),
                                        allow_failure=True, timeout=2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("was not found in the local orx store", result.stderr)
        self.assertLess(result.elapsed_seconds, 2)
        self.assertNotIn("API_KEY", adapter.env)
        self.assertNotIn("OPENAI_API_KEY", adapter.env)

    async def test_02_actual_success_source_metrics_snapshot_and_logs(self):
        adapter = self.adapter()
        provenance = await adapter.ensure_experiment()
        receipt = await adapter.launch_experiment()
        receipt = await adapter.wait_experiment(timeout_seconds=12)
        self.assertEqual(receipt["state"], "done")
        result = adapter.evaluation_result()
        self.assertIsNotNone(result)
        self.assertEqual(result["baseline"], {"value": 16.0})
        self.assertEqual(result["candidate"], {"value": 0.0})
        self.assertEqual(result["sampleCount"], 7)
        self.assertEqual(result["fileSha256"], TOY_FILES)
        self.assertEqual(provenance["upstreamArchiveSha256"], SOURCE_ARCHIVE_SHA256)
        self.assertRegex(provenance["recipeSourceCommit"], r"^[0-9a-f]{40}$")
        row = adapter._native_run()
        backend = json.loads(row["backend_json"])
        self.assertEqual(hashlib.sha256(Path(backend["sourcePath"]).read_bytes()).hexdigest(), provenance["recipeArchiveSha256"])
        self.assertEqual(backend["sourceDigest"], provenance["recipeArchiveSha256"])
        logs = await adapter.run_logs()
        self.assertIn("baseline MSE=16, candidate MSE=0", logs.stdout)
        with adapter._db() as db:
            self.assertEqual(db.execute("select github_sync_enabled from local_projects").fetchone()[0], 0)
            self.assertEqual(db.execute("select count(*) from chat_sessions").fetchone()[0], 0)
            self.assertEqual(db.execute("select count(*) from runs").fetchone()[0], 1)
        self.assertTrue(receipt["stop_evidence"]["allStopped"])

    async def test_03_actual_evaluator_failure_keeps_scored_failure_evidence(self):
        adapter = self.adapter("evaluator_failure")
        await adapter.ensure_experiment()
        await adapter.launch_experiment()
        receipt = await adapter.wait_experiment(timeout_seconds=12)
        self.assertEqual(receipt["state"], "failed")
        result = adapter.evaluation_result()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failureCode"], "REVIEWED_EVALUATOR_FAILURE")
        self.assertEqual(result["candidate"], {"value": 0.0})
        self.assertIn("failed deliberately", (await adapter.run_logs()).stdout)

    async def test_04_actual_running_cancel_proves_detached_tree_stopped(self):
        adapter = self.adapter("long_running")
        await adapter.ensure_experiment()
        receipt = await adapter.launch_experiment()
        self.assertIn(receipt["state"], {"starting", "running"})
        self.assertFalse(receipt["stop_evidence"]["allStopped"])
        self.assertGreaterEqual(receipt["stop_evidence"]["activeProcesses"], 2)
        self.assertEqual(receipt["stop_evidence"]["limits"]["maxProcesses"], 8)
        stopped = await adapter.cancel_experiment()
        self.assertEqual(stopped["state"], "cancelled")
        self.assertTrue(stopped["stop_evidence"]["allStopped"])
        self.assertIsNone(adapter.evaluation_result())

    async def test_05_real_commit_lost_ack_reconciles_without_second_launch(self):
        adapter = self.adapter("long_running")
        await adapter.ensure_experiment()
        real = adapter._command
        async def lose_ack(operation, *argv, **kwargs):
            result = await real(operation, *argv, **kwargs)
            if argv[:2] == ("exp", "run"):
                raise OpenResearchError("TIMEOUT", "Synthetic lost ACK after actual committed ORX launch")
            return result
        with mock.patch.object(adapter, "_command", side_effect=lose_ack):
            with self.assertRaises(OpenResearchError):
                await adapter.launch_experiment()
        replacement = self.adapter("long_running")
        await replacement.ensure_experiment()
        old = json.loads(adapter._receipt_path.read_text())
        self.assertEqual(old["state"], "UNKNOWN")
        recovered = await replacement.launch_experiment()
        self.assertIsNotNone(recovered["run_id"])
        with replacement._db() as db:
            self.assertEqual(db.execute("select count(*) from runs").fetchone()[0], 1)
        self.assertTrue((await replacement.cancel_experiment())["stop_evidence"]["allStopped"])

    async def test_06_supervisor_hard_exit_recovered_by_native_cancel(self):
        adapter = self.adapter("long_running")
        await adapter.ensure_experiment()
        receipt = await adapter.launch_experiment()
        pids = adapter._job.process_ids()
        kernel = adapter._job.kernel
        kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        killed = []
        for pid in pids:
            process = kernel.OpenProcess(0x1000 | 1, False, pid)
            if not process:
                continue
            try:
                name = ctypes.create_unicode_buffer(32768); length = ctypes.c_ulong(32768)
                if kernel.QueryFullProcessImageNameW(process, 0, name, ctypes.byref(length)) and Path(name.value).resolve() == adapter.binary:
                    self.assertTrue(kernel.TerminateProcess(process, 27)); killed.append(pid)
            finally:
                kernel.CloseHandle(process)
        self.assertEqual(len(killed), 1, "Exactly the task-owned detached ORX supervisor should remain after CLI exit")
        await asyncio.sleep(0.1)
        self.assertGreater(adapter._job.evidence()["activeProcesses"], 0, "Evaluator tree must survive the supervisor crash")
        recovered = await self.adapter("long_running").ensure_experiment()
        self.assertEqual(recovered["experimentId"], adapter.binding.experiment_id)
        stopped = await self.adapters[-1].cancel_experiment()
        self.assertEqual(stopped["run_id"], receipt["run_id"])
        self.assertEqual(stopped["state"], "cancelled")
        self.assertTrue(stopped["stop_evidence"]["allStopped"])

    async def test_07_revocation_source_command_drift_deny_but_trusted_stop_retained(self):
        adapter = self.adapter("long_running")
        await adapter.ensure_experiment()
        receipt = await adapter.launch_experiment()
        self.allowed = False
        with self.assertRaises(OpenResearchError) as denied:
            await adapter.launch_experiment()
        self.assertEqual(denied.exception.code, "FORBIDDEN")
        (adapter.repo / "candidate.py").write_text("drift\n")
        with self.assertRaises(OpenResearchError):
            await adapter.reconcile_experiment()
        cleanup = self.adapter("long_running", cleanup_only=True)
        stopped = await cleanup.reclaim_experiment()
        self.assertEqual(stopped["run_id"], receipt["run_id"])
        self.assertTrue(stopped["stop_evidence"]["allStopped"])
        with self.assertRaises(OpenResearchError) as denied:
            await cleanup.launch_experiment()
        self.assertEqual(denied.exception.code, "CLEANUP_ONLY")
        with adapter._db() as db:
            self.assertEqual(db.execute("select count(*) from runs").fetchone()[0], 1)

    async def test_08_task_schema_and_native_command_drift_refused_before_launch(self):
        adapter = self.adapter()
        await adapter.ensure_experiment()
        with adapter._db(writable=True) as db:
            db.execute("update local_experiments set run_command='echo unreviewed'")
        with self.assertRaises(OpenResearchError) as denied:
            await adapter.launch_experiment()
        self.assertEqual(denied.exception.code, "COMMAND_CHANGED")
        self.assertFalse(adapter._receipt_path.exists())
        with adapter._db() as db:
            self.assertEqual(db.execute("select count(*) from runs").fetchone()[0], 0)
        with self.assertRaises(OpenResearchError):
            await self.adapter(owner_id="another-synthetic-owner").ensure_experiment()

    async def test_09_unsupported_environment_and_source_pin_refused_before_native_launch(self):
        with self.assertRaises(OpenResearchError):
            self.adapter(environment=EnvironmentLimits(process_limit=4))
        adapter = self.adapter()
        with mock.patch("agent_factory.orx_local.SOURCE_ARCHIVE_SHA256", "0" * 64):
            with self.assertRaises(OpenResearchError) as denied:
                await adapter.ensure_experiment()
        self.assertEqual(denied.exception.code, "SOURCE_CHANGED")
        self.assertFalse(adapter._manifest_path.exists())


    async def test_10_factory_worker_hard_exit_reattaches_original_run_without_duplicate(self):
        worker = Path(self.temp.name) / "owned-launch-worker.py"
        marker = Path(self.temp.name) / "committed-launch.json"
        parameters = {
            "binary": str(self.provider.binary), "sourceArchive": str(self.provider.source_archive),
            "git": str(self.provider.git_binary), "python": str(self.provider.python_binary),
            "scope": str(self.scope), "taskId": self.task_id, "ownerId": self.owner,
            "binarySha256": self.pin.sha256, "marker": str(marker),
            "platform": str(Path(__file__).resolve().parents[1]),
        }
        worker.write_text("\n".join([
            "import sys,os,json,asyncio", "from pathlib import Path",
            "p=" + repr(parameters),
            "sys.path.insert(0,p['platform'])",
            "from agent_factory.orx_local import TaskLocalORXProvider",
            "from agent_factory.openresearch import BinaryPin,REVISION,VERSION",
            "async def main():",
            " provider=TaskLocalORXProvider(binary=Path(p['binary']),source_archive=Path(p['sourceArchive']),git_binary=Path(p['git']),python_binary=Path(p['python']))",
            " adapter=provider.create_experiment_adapter(owner_id=p['ownerId'],task_id=p['taskId'],scope=Path(p['scope']),authorize=lambda _:True,pin=BinaryPin(REVISION,VERSION,p['binarySha256']),max_output_bytes=65536,command_timeout=10,environment={'timeoutSeconds':30,'outputBytes':65536,'memoryBytes':536870912,'maxProcesses':8,'cpuPercent':25},scenario='long_running')",
            " await adapter.ensure_experiment()",
            " result=await adapter.launch_experiment()",
            " Path(p['marker']).write_text(json.dumps(result))",
            " os._exit(31)",
            "asyncio.run(main())",
        ]), encoding="utf-8")
        process = subprocess.Popen([sys._base_executable, "-I", str(worker)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS)
        self.assertEqual(await asyncio.to_thread(process.wait, 15), 31)
        old = json.loads(marker.read_text())
        replacement = self.adapter("long_running")
        await replacement.ensure_experiment()
        self.assertGreater(replacement._job.evidence()["activeProcesses"], 0,
            "Named job must retain detached evaluator and supervisor after the owning Factory worker exits")
        recovered = await replacement.launch_experiment()
        self.assertEqual(recovered["run_id"], old["run_id"])
        with replacement._db() as db:
            self.assertEqual(db.execute("select count(*) from runs").fetchone()[0], 1)
        stopped = await replacement.cancel_experiment()
        self.assertEqual(stopped["state"], "cancelled")
        self.assertTrue(stopped["stop_evidence"]["allStopped"])


if __name__ == "__main__":
    unittest.main()
