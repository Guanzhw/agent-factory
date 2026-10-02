"""Actual TCP process exits at durable command boundaries, isolated PostgreSQL."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4

import httpx

from pg_fixture import IsolatedPostgres
from test_governed_remote_process_postgres import loopback_port


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL")
class CommandProcessTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.workspace = self.root / "service"
        self.workspace.mkdir()
        self.config = self.root / "server.json"
        port = loopback_port()
        self.config.write_text(json.dumps({"database": self.database.url, "workspace": str(self.workspace), "port": port}))
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False)
        self.log = (self.root / "server.log").open("ab")
        self.process = None
        self.start()

    def start(self):
        project = Path(__file__).resolve().parents[2]
        environment = {**os.environ, "FACTORY_COMMAND_FIXTURE": str(self.config),
                       "PYTHONPATH": os.pathsep.join([str(project / "platform"), str(project / "platform/tests")])}
        self.process = subprocess.Popen([sys.executable, "-m", "controlled_command_worker"],
            env=environment, cwd=project, stdout=self.log, stderr=self.log)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            self.assertIsNone(self.process.poll(), (self.root / "server.log").read_text()[-3000:])
            try:
                if self.client.get("/api/health").is_success:
                    self.client.cookies.clear()
                    self.assertEqual(self.client.post("/api/factory/demo/login", json={"persona": "alice"}).status_code, 200)
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.05)
        self.fail("Owned server startup timed out")

    def tearDown(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        self.client.close()
        self.log.close()
        self.directory.cleanup()
        self.database.__exit__(None, None, None)

    def api(self, method, path, body=None):
        response = self.client.request(method, "/api/factory" + path, json=body)
        self.assertTrue(response.is_success, response.text)
        return response.json()

    def waiting(self, action):
        plan = self.api("POST", "/plans", {"topic": "sort" if action == "answer" else "Evaluate synthetic sorting", "mode": "literature" if action == "answer" else "experiment", "application": "research", "requestId": str(uuid4())})
        task = self.api("POST", "/instances", {"planId": plan["id"], "requestId": str(uuid4())})["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.api("GET", "/jobs/" + task)["job"]
            requirement = job.get("questionDetail" if action == "answer" else "approvalDetail")
            if requirement:
                return task, {"commandId": str(uuid4()), "action": action, "requirementId": requirement["id"], "version": requirement["version"], **({"answer": "Synthetic restart scope"} if action == "answer" else {"approved": True})}
            time.sleep(.05)
        self.fail("Native requirement not reached")

    def crash(self, task, command, phase):
        (self.workspace / "fault.json").write_text(json.dumps({"phase": phase, "commandId": command["commandId"]}))
        with self.assertRaises(httpx.TransportError):
            self.api("POST", "/jobs/" + task + "/commands", command)
        self.assertEqual(self.process.wait(10), 88)
        self.assertEqual(json.loads((self.workspace / "crashed.json").read_text())["commandId"], command["commandId"])
        self.start()
        return self.api("GET", f'/jobs/{task}/commands/{command["commandId"]}')

    def count(self, command):
        path = self.workspace / "continuations.jsonl"
        return sum(json.loads(line)["commandId"] == command["commandId"] for line in path.read_text().splitlines()) if path.exists() else 0

    def test_committed_answer_approval_rejection_and_cancel_survive_service_exit(self):
        for action, approved in (("answer", None), ("approve", False), ("approve", True), ("cancel", None)):
            with self.subTest(action=action, approved=approved):
                task, command = self.waiting("answer" if action == "cancel" else action)
                if action == "approve":
                    command["approved"] = approved
                if action == "cancel":
                    command = {"commandId": str(uuid4()), "action": "cancel"}
                receipt = self.crash(task, command, "after-cancel" if action == "cancel" else "after-native")
                self.assertTrue(receipt["decisionRecorded"], receipt)
                replay = self.api("POST", "/jobs/" + task + "/commands", command)
                self.assertEqual(replay["fingerprint"], receipt["fingerprint"])
                self.assertEqual(self.count(command), 0 if action == "cancel" else 1)
                if action == "cancel":
                    deadline = time.monotonic() + 15
                    while not receipt["stopConfirmed"] and time.monotonic() < deadline:
                        time.sleep(.1)
                        receipt = self.api("GET", f'/jobs/{task}/commands/{command["commandId"]}')
                    self.assertTrue(receipt["stopConfirmed"], receipt)
                else:
                    self.api("POST", "/jobs/" + task + "/cancel")

    def test_prepared_requires_explicit_dispatch_and_unknown_never_replays_after_restart(self):
        for phase in ("prepared", "before-native"):
            with self.subTest(phase=phase):
                task, command = self.waiting("answer")
                receipt = self.crash(task, command, phase)
                expected = "INTENT_RECORDED" if phase == "prepared" else "UNKNOWN"
                self.assertEqual(receipt["state"], expected)
                self.assertEqual(self.count(command), 0)
                self.assertEqual(self.api("GET", f'/jobs/{task}/commands/{command["commandId"]}')["state"], expected)
                if phase == "prepared":
                    receipt = self.api("POST", f'/jobs/{task}/commands/{command["commandId"]}/dispatch')
                    self.assertTrue(receipt["decisionRecorded"], receipt)
                    self.assertEqual(self.count(command), 1)
                else:
                    self.assertEqual(self.api("POST", "/jobs/" + task + "/commands", command)["state"], "UNKNOWN")
                    self.assertEqual(self.count(command), 0)
                self.api("POST", "/jobs/" + task + "/cancel")
