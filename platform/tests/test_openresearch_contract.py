"""SYNTHETIC CLI contract fixtures, real bounded OS subprocesses.

These tests do not execute ORX, retrieve papers, or prove live research. A
test-only subclass launches the synthetic Python fixture in place of ORX.
"""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_factory.openresearch import (
    BinaryPin, ExperimentBinding, OpenResearchAdapter, OpenResearchError, REVISION, VERSION,
)

FIXTURE = r'''
import json, os, pathlib, subprocess, sys, time
root = pathlib.Path.cwd()
args = sys.argv[1:]
with (root / 'synthetic-events.jsonl').open('a', encoding='utf-8') as f:
    f.write(json.dumps({'synthetic': True, 'args': args, 'env': dict(os.environ)}) + '\n')
args = [a for a in args if a != '--no-telemetry']
state_path = root / 'synthetic-state.json'
state = json.loads(state_path.read_text()) if state_path.exists() else {}
mode = (root / 'synthetic-mode').read_text() if (root / 'synthetic-mode').exists() else ''
if args == ['--version']:
    print('orx 0.2.10' if mode == 'old-version' else 'orx 0.2.13')
elif args[0] == 'discover':
    if args[2] == 'overflow':
        print('x' * 20000)
    elif args[2] == 'bad-json':
        print('not JSON')
    elif args[2] == 'slow':
        child = subprocess.Popen([sys.executable, '-c',
            "import pathlib,time; p=pathlib.Path('synthetic-heartbeat'); "
            "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(.02)')"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (root / 'synthetic-child-pid').write_text(str(child.pid))
        time.sleep(60)
    else:
        print(json.dumps([{'id': 'synthetic-paper', 'title': 'SYNTHETIC citation', 'query': args[2]}]))
elif args[0] == 'paper':
    print('SYNTHETIC paper fixture only')
elif args[:2] == ['exp', 'status']:
    print('Synthetic experiment (idle) [local]')
    print('  id:       ' + args[2])
    print('  branch:   synthetic')
    print('  command:  ' + ('changed' if mode == 'changed-command' else 'synthetic-only'))
    if mode == 'invalid-status':
        print('  last run: format-unknown')
    elif state.get('run_id'):
        print('  last run: ' + state['run_id'] + ' (' + state['status'] + ', commit abcdef0, ran 1s, updated now)')
    else:
        print('  last run: — (never run)')
elif args[:2] == ['exp', 'run']:
    if mode == 'unknown-before-effect':
        sys.exit(7)
    state.update(run_id='synthetic-run-1', status='running')
    state_path.write_text(json.dumps(state))
    if mode == 'unknown-after-effect':
        sys.exit(7)
    if mode == 'detached':
        kwargs = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, **kwargs)
        state['child_pid'] = child.pid
        state_path.write_text(json.dumps(state))
    print('SYNTHETIC detached launch accepted')
elif args[:2] == ['exp', 'wait']:
    if state.get('status') != 'cancelled':
        state['status'] = 'failed' if mode == 'failed' else 'done'
        state_path.write_text(json.dumps(state))
    print(state['run_id'] + ' ' + state['status'])
elif args[:2] == ['exp', 'cancel']:
    if state.get('child_pid'):
        if os.name == 'nt':
            subprocess.run([str(pathlib.Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'),
                            '/PID', str(state['child_pid']), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            import signal
            try: os.killpg(state['child_pid'], signal.SIGKILL)
            except ProcessLookupError: pass
    state['status'] = 'cancelled'
    state_path.write_text(json.dumps(state))
    print('SYNTHETIC cancel requested')
elif args[0] == 'logs':
    print('SYNTHETIC run log')
else:
    sys.exit(8)
'''


class SyntheticCLI(OpenResearchAdapter):
    async def _spawn(self, argv):
        kwargs = {"cwd": str(self.scope), "env": {**self.env, "PYTHONIOENCODING": "utf-8"},
                  "stdin": asyncio.subprocess.DEVNULL,
                  "stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.PIPE}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        return await asyncio.create_subprocess_exec(sys.executable, str(self.binary), *argv, **kwargs)


class OpenResearchContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        # Hosted Windows TEMP can traverse a junction; compare canonical paths.
        self.root = Path(self.directory.name).resolve()
        self.fixture = self.root / "synthetic-orx.py"
        self.fixture.write_text(FIXTURE, encoding="utf-8")
        self.task_id = str(uuid4())
        self.scope = self.root / self.task_id
        self.granted = True
        self.operations = []
        self.pin = BinaryPin(REVISION, VERSION, hashlib.sha256(self.fixture.read_bytes()).hexdigest())
        self.binding = ExperimentBinding("alice", self.task_id, "synthetic-project", "synthetic-experiment",
                                         hashlib.sha256(b"synthetic-only").hexdigest(), "a" * 40, "synthetic-local")
        self.adapter = self.make_adapter()

    def authorize(self, operation):
        self.operations.append(operation)
        return self.granted

    def make_adapter(self, **kwargs):
        options = dict(binary=self.fixture, scope=self.scope, owner_id="alice", task_id=self.task_id,
                       authorize=self.authorize, pin=self.pin, enabled=True, binding=self.binding)
        options.update(kwargs)
        return SyntheticCLI(**options)

    async def asyncTearDown(self):
        for process in tuple(self.adapter._processes):
            await self.adapter._terminate(process)
        state = self.scope / "synthetic-state.json"
        if state.exists() and json.loads(state.read_text()).get("child_pid"):
            # Native fixture cancel owns/terminates only the fixture-created PID.
            await self.adapter.cancel_experiment(timeout_seconds=1)
        self.directory.cleanup()

    def events(self):
        path = self.scope / "synthetic-events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def mode(self, value):
        (self.scope / "synthetic-mode").write_text(value)

    async def test_disabled_and_unverified_builds_fail_before_subprocess(self):
        for kwargs, code in [({"enabled": False}, "DISABLED"), ({"pin": None}, "UNVERIFIED_BINARY"),
                             ({"pin": replace(self.pin, revision="b" * 40)}, "UNVERIFIED_BINARY"),
                             ({"pin": replace(self.pin, sha256="0" * 64)}, "UNVERIFIED_BINARY")]:
            with self.assertRaises(OpenResearchError) as error:
                await self.make_adapter(**kwargs).preflight()
            self.assertEqual(error.exception.code, code)
        self.assertEqual(self.events(), [])

    async def test_version_only_and_replaced_binary_are_rejected(self):
        self.mode("old-version")
        with self.assertRaises(OpenResearchError) as error:
            await self.adapter.preflight()
        self.assertEqual(error.exception.code, "VERSION_MISMATCH")
        self.fixture.write_text(FIXTURE + "\n# replaced", encoding="utf-8")
        with self.assertRaises(OpenResearchError) as error:
            await self.adapter.preflight()
        self.assertEqual(error.exception.code, "UNVERIFIED_BINARY")

    async def test_literal_query_and_owned_environment(self):
        query = "synthesis & $(no_shell) ; literal"
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-do-not-inherit", "SSH_AUTH_SOCK": "synthetic"}):
            hits = await self.adapter.discover(query, corpus="pubmed", limit=2)
        self.assertEqual(hits[0]["query"], query)
        event = self.events()[-1]
        self.assertEqual(event["args"], ["--no-telemetry", "discover", "pubmed", query, "--limit", "2"])
        self.assertTrue(event["synthetic"])
        self.assertNotIn("OPENAI_API_KEY", event["env"])
        self.assertNotIn("SSH_AUTH_SOCK", event["env"])
        for name in ["HOME", "USERPROFILE", "XDG_CONFIG_HOME", "ORX_DATA_DIR", "ORX_CACHE_DIR", "TEMP"]:
            self.assertTrue(Path(event["env"][name]).is_relative_to(self.scope))
        self.assertEqual(event["env"]["ORX_NO_UPDATE_CHECK"], "1")

    async def test_revocation_while_waiting_for_capacity_prevents_spawn(self):
        await self.adapter._semaphore.acquire()
        operation = asyncio.create_task(self.adapter.discover("valid"))
        await asyncio.sleep(.02)
        self.granted = False
        self.adapter._semaphore.release()
        with self.assertRaises(OpenResearchError) as error:
            await operation
        self.assertEqual(error.exception.code, "FORBIDDEN")
        self.assertEqual(self.events(), [])

    async def test_invalid_inputs_and_revocation_do_not_execute(self):
        for arguments in [{"query": "--help"}, {"query": "x", "corpus": "ssh"}, {"query": "x", "limit": 201}]:
            with self.assertRaises(ValueError):
                await self.adapter.discover(**arguments)
        self.granted = False
        with self.assertRaises(OpenResearchError) as error:
            await self.adapter.discover("valid")
        self.assertEqual(error.exception.code, "FORBIDDEN")
        self.assertEqual(self.events(), [])

    async def test_full_text_argument_contract(self):
        result = await self.adapter.paper("2501.12345v2", full=True)
        self.assertEqual(result.argv, ("--no-telemetry", "paper", "2501.12345v2", "--source", "alphaxiv", "--full"))
        with self.assertRaises(ValueError):
            await self.adapter.paper("openalex:W123", full=True)
        with self.assertRaises(ValueError):
            await self.adapter.paper("https://untrusted.invalid/paper")

    async def test_one_launch_intent_survives_adapter_restart(self):
        first = await self.adapter.launch_experiment()
        self.assertEqual((first["run_id"], first["state"]), ("synthetic-run-1", "running"))
        recovered = await self.make_adapter().launch_experiment()
        self.assertEqual(recovered["run_id"], first["run_id"])
        launches = [e for e in self.events() if e["args"][1:3] == ["exp", "run"]]
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0]["args"], ["--no-telemetry", "exp", "run", "synthetic-experiment", "--backend", "local"])

    async def test_failed_experiment_is_not_successful_wait(self):
        await self.adapter.launch_experiment()
        self.mode("failed")
        result = await self.adapter.wait_experiment(timeout_seconds=2)
        self.assertEqual(result["state"], "failed")
        self.assertIn("SYNTHETIC", (await self.adapter.run_logs()).stdout)

    async def test_concurrent_instances_admit_one_launch_intent(self):
        second = self.make_adapter()
        checked = asyncio.Barrier(2)
        def initial_status_barrier(original):
            first = True
            async def status():
                nonlocal first
                value = await original()
                if first:
                    first = False
                    self.assertEqual(value["status"], "NOT_STARTED")
                    # Both real status subprocesses observe no launch before
                    # either caller competes for the exclusive intent file.
                    await checked.wait()
                return value
            return status
        with patch.object(self.adapter, "experiment_status", side_effect=initial_status_barrier(self.adapter.experiment_status)), \
             patch.object(second, "experiment_status", side_effect=initial_status_barrier(second.experiment_status)):
            # Harness bound only; adapter command/business deadlines unchanged.
            async with asyncio.timeout(10), asyncio.TaskGroup() as group:
                group.create_task(self.adapter.launch_experiment())
                group.create_task(second.launch_experiment())
        launches = [e for e in self.events() if e["args"][1:3] == ["exp", "run"]]
        self.assertEqual(len(launches), 1)
        self.assertEqual((await self.adapter.reconcile_experiment())["run_id"], "synthetic-run-1")

    async def test_late_status_after_other_instance_launch_fails_closed_without_duplicate(self):
        second = self.make_adapter()
        entered, launched = asyncio.Event(), asyncio.Event()
        original = second.experiment_status
        async def delayed_status():
            # No receipt was seen, but another instance launches before this
            # caller's real status subprocess observes the existing run.
            entered.set()
            await launched.wait()
            return await original()
        with patch.object(second, "experiment_status", side_effect=delayed_status):
            operation = asyncio.create_task(second.launch_experiment())
            try:
                async with asyncio.timeout(10):
                    await entered.wait()
                    first = await self.adapter.launch_experiment()
                    self.assertEqual(first["run_id"], "synthetic-run-1")
                    launched.set()
                    with self.assertRaises(OpenResearchError) as caught:
                        await operation
                    self.assertEqual(caught.exception.code, "ALREADY_RUNNING")
            finally:
                if not operation.done():
                    operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
        launches = [e for e in self.events() if e["args"][1:3] == ["exp", "run"]]
        self.assertEqual(len(launches), 1)
        # A later call sees the original receipt and reconciles, never relaunches.
        self.assertEqual((await second.launch_experiment())["run_id"], "synthetic-run-1")
        self.assertEqual(len([e for e in self.events() if e["args"][1:3] == ["exp", "run"]]), 1)

    async def test_uncertain_launch_never_retries_before_or_after_side_effect(self):
        self.mode("unknown-before-effect")
        with self.assertRaises(OpenResearchError):
            await self.adapter.launch_experiment()
        self.assertEqual((await self.make_adapter().launch_experiment())["state"], "UNKNOWN")
        launches = [e for e in self.events() if e["args"][1:3] == ["exp", "run"]]
        self.assertEqual(len(launches), 1)
        # Fresh owned task for a failed acknowledgement after native side effect.
        fresh_id = str(uuid4())
        fresh = self.make_adapter(task_id=fresh_id, scope=self.root / fresh_id,
                                  binding=replace(self.binding, task_id=fresh_id))
        (fresh.scope / "synthetic-mode").write_text("unknown-after-effect")
        with self.assertRaises(OpenResearchError):
            await fresh.launch_experiment()
        self.assertEqual((await fresh.reconcile_experiment())["state"], "running")

    async def test_changed_command_unknown_status_and_cross_owner_fail_closed(self):
        self.mode("changed-command")
        with self.assertRaises(OpenResearchError) as error:
            await self.adapter.launch_experiment()
        self.assertEqual(error.exception.code, "COMMAND_CHANGED")
        self.mode("invalid-status")
        with self.assertRaises(OpenResearchError) as error:
            await self.adapter.launch_experiment()
        self.assertEqual(error.exception.code, "UNKNOWN_RUN")
        with self.assertRaises(OpenResearchError):
            await self.make_adapter(binding=replace(self.binding, owner_id="bob")).experiment_status()
        self.assertFalse(any(e["args"][1:3] == ["exp", "run"] for e in self.events()))

    async def test_output_bound_and_invalid_json(self):
        with self.assertRaises(OpenResearchError) as error:
            await self.make_adapter(max_output_bytes=1024).discover("overflow")
        self.assertEqual(error.exception.code, "OUTPUT_LIMIT")
        with self.assertRaises(OpenResearchError) as error:
            await self.adapter.discover("bad-json")
        self.assertEqual(error.exception.code, "INVALID_OUTPUT")

    async def test_timeout_terminates_owned_subprocesses(self):
        adapter = self.make_adapter(command_timeout=.75)
        with self.assertRaises(OpenResearchError) as error:
            await adapter.discover("slow")
        self.assertEqual(error.exception.code, "TIMEOUT")
        self.assertEqual(len(adapter._processes), 0)
        heartbeat = self.scope / "synthetic-heartbeat"
        self.assertTrue(heartbeat.exists())
        first = heartbeat.read_text()
        await asyncio.sleep(.15)
        self.assertEqual(heartbeat.read_text(), first)

    async def test_cancelled_request_terminates_owned_process_tree(self):
        operation = asyncio.create_task(self.adapter.discover("slow"))
        for _ in range(100):
            heartbeat = self.scope / "synthetic-heartbeat"
            if heartbeat.exists():
                break
            await asyncio.sleep(.02)
        self.assertTrue(heartbeat.exists(), "Synthetic process child did not start")
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        first = heartbeat.read_text()
        await asyncio.sleep(.15)
        self.assertEqual(heartbeat.read_text(), first)
        self.assertEqual(len(self.adapter._processes), 0)

    async def test_detached_supervisor_cancel_and_reconciliation(self):
        self.mode("detached")
        await self.adapter.launch_experiment()
        self.assertEqual(len(self.adapter._processes), 0)
        result = await self.make_adapter().cancel_experiment(timeout_seconds=2)
        self.assertEqual(result["state"], "cancelled")
        self.assertTrue(result["cancel_requested"])
        args = [event["args"] for event in self.events()]
        self.assertIn(["--no-telemetry", "exp", "cancel", "synthetic-experiment"], args)
        self.assertIn(["--no-telemetry", "exp", "wait", "synthetic-experiment", "--timeout", "2", "--interval", "1"], args)


if __name__ == "__main__":
    unittest.main()
