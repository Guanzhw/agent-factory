# pyright: reportMissingImports=false
"""Actual pinned ORX binary through Factory/Agno, with a no-provider local model.

Generated fixture roles/data are isolated. No command transport, experiment row,
run row, metric, or status is mocked. File/command changes are adversarial inputs.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import subprocess
import tempfile
import tarfile
import time
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.connections import TrustedConnectionBinding
from agent_factory.execution_bindings import EnvironmentLimits
from agent_factory.main import create_app
from agent_factory.orx_experiment_tools import (
    ADAPTER_ID, MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION, LocalORXWorkflowModel,
    TOOL_NAMES, READ_CAPABILITY, RUN_CAPABILITY, initialize_orx_experiments,
    inspect_orx_experiment, register_orx_experiment_adapters, validate_experiment_config,
)
from agent_factory.orx_local import TaskLocalORXProvider
from agent_factory.store import digest
from pg_fixture import IsolatedPostgres


class ORXWorkflowContractTests(unittest.TestCase):
    def test_inert_config_rejects_arbitrary_commands_paths_and_scenarios(self):
        for value in ({"command": "whoami"}, {"scenario": "other"}, {"path": "/tmp"}, {"binary": "orx"}):
            with self.assertRaises(ValueError):
                validate_experiment_config(value)
        for scenario in ("success", "evaluator_failure", "long_running"):
            validate_experiment_config({"scenario": scenario})

    def _messages(self, results):
        return [SimpleNamespace(role="system", content="FACTORY_SYNTHETIC_CONTEXT=" + json.dumps({"tools": list(TOOL_NAMES)})),
                *[SimpleNamespace(role="tool", tool_name=name, content=json.dumps(value), tool_call_error=False)
                  for name, value in results]]

    def test_unknown_ack_stops_native_model_loop_without_relaunch_or_wait(self):
        messages = self._messages([(TOOL_NAMES[0], {"status": "NOT_STARTED"}),
                                  (TOOL_NAMES[1], {"status": "UNKNOWN", "orxRunId": None})])
        response = LocalORXWorkflowModel().invoke(messages)
        self.assertFalse(response.tool_calls)
        self.assertEqual(json.loads(response.content)["status"], "blocked-unknown")

    def test_deterministic_model_uses_only_approved_zero_argument_launch(self):
        messages = self._messages([(TOOL_NAMES[0], {"status": "NOT_STARTED"})])
        response = LocalORXWorkflowModel().invoke(messages)
        function = response.tool_calls[0]["function"]
        self.assertEqual(function["name"], TOOL_NAMES[1])
        self.assertEqual(json.loads(function["arguments"]), {})
        self.assertEqual(LocalORXWorkflowModel().provider, "local-deterministic")


def pin(material):
    return {key: material[key] for key in ("id", "version", "sha256")}


_ACTUAL_ENV = ("FACTORY_TEST_DATABASE_URL", "FACTORY_ORX_BINARY", "FACTORY_ORX_SOURCE_ARCHIVE", "FACTORY_ORX_GIT_BINARY")


@unittest.skipUnless(os.name == "nt" and all(os.getenv(key) for key in _ACTUAL_ENV),
                     "Requires explicit Windows task-containment, loopback PostgreSQL and pinned ORX toolchain")
class ActualORXNativeFactoryTests(unittest.TestCase):
    process_limit = 8

    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix="factory-actual-orx-")
        self.addCleanup(self.workspace.cleanup)
        if self.process_limit == 64:
            self.addCleanup(self._remove_disposable_containers)
        self.provider = TaskLocalORXProvider(binary=Path(os.environ["FACTORY_ORX_BINARY"]).resolve(),
            source_archive=Path(os.environ["FACTORY_ORX_SOURCE_ARCHIVE"]).resolve(),
            git_binary=Path(os.environ["FACTORY_ORX_GIT_BINARY"]).resolve(),
            python_binary=Path(os.getenv("FACTORY_ORX_PYTHON_BINARY", sys._base_executable)).resolve())
        self.registration = "actual-orx-local-toy-fixture"
        trusted = TrustedConnectionBinding("alice", "orx", ADAPTER_ID,
            frozenset({READ_CAPABILITY, RUN_CAPABILITY}), "actual-orx-task-toy-v1", available=True,
            opaque_handle=self.provider, handle_ref="actual-reviewed-task-local-toy-v1")
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.workspace.name),
            max_workers=1, queue_poll=.03, max_tool_calls=8, experiment_timeout_seconds=30,
            experiment_output_bytes=65536, temporary_policy="admin-review", policy_revision="actual-orx-plan-v1",
            material_policy_revision="actual-orx-material-v1", runtime_tool_contract="local-orx-v1",
            trusted_connections={self.registration: trusted})
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        bindings = self.state["execution_bindings"]
        if ("model", MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION) not in bindings._adapters:
            bindings.register("model", MODEL_ADAPTER_ID, MODEL_ADAPTER_REVISION, lambda _: LocalORXWorkflowModel())
        if ("tool", ADAPTER_ID + "-run", "1") not in bindings._adapters:
            register_orx_experiment_adapters(bindings)
        bindings.register("environment", "fixture-orx-environment-v1", "1", lambda _: EnvironmentLimits(
            runtime_id="local-orx-reviewed-toy-v1", timeout_seconds=30, output_bytes=65536,
            memory_bytes=512 * 1024 * 1024, process_limit=self.process_limit, cpu_percent=25))
        initialize_orx_experiments(self.store)
        # Only this generated disposable database receives a distinct fixture reviewer.
        self.auth.authorization.unassign("bob", "factory-user")
        self.auth.authorization.assign("bob", "factory-manager")
        self.client = TestClient(self.app).__enter__()  # type: ignore[arg-type]
        self.addCleanup(self.client.__exit__, None, None, None)
        self.task_id = None
        self._publish_application()
        self.connection = self.state["connections"].bind("alice", self.registration,
            "fixture-task-local-orx", capabilities=[READ_CAPABILITY, RUN_CAPABILITY])

    def _remove_disposable_containers(self):
        # Runs after the native app closes; only this generated workspace is retired.
        for marker in Path(self.workspace.name).rglob("factory-linux-container.json"):
            saved = json.loads(marker.read_text())
            cid = saved["containerId"]
            value = json.loads(subprocess.check_output(["docker", "inspect", cid], text=True))[0]
            self.assertEqual(value["Config"]["Labels"]["agent-factory.orx-spec"], saved["specSha256"])
            self.assertIn(str(marker.parent), [m["Source"] for m in value["Mounts"] if m["RW"]])
            if value["State"]["Running"]:
                subprocess.run(["docker", "kill", cid], check=True, capture_output=True)
            subprocess.run(["docker", "rm", cid], check=True, capture_output=True)

    def tearDown(self):
        if self.task_id:
            task = self.store.task(self.task_id)
            if not task["terminal"]:
                self.store.request_cancel(self.task_id)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    effects = self.store.effects(self.task_id)
                    if not effects or all(row["status"] != "UNKNOWN" for row in effects):
                        break
                    time.sleep(.05)

    def login(self, owner):
        self.client.cookies.clear()
        result = self.client.post("/api/factory/demo/login", json={"persona": owner})
        self.assertEqual(result.status_code, 200, result.text)

    def request(self, method, path, expected, body=None):
        result = self.client.request(method, "/api/factory" + path, json=body)
        self.assertEqual(result.status_code, expected, result.text)
        return result.json()

    def publish_material(self, identifier, kind, adapter, *, tool_name=None, scenario=None):
        self.login("manager")
        config = {"connectionName": "localExperiment"} if kind == "tool" else {}
        if scenario is not None:
            config["scenario"] = scenario
        permissions = ([RUN_CAPABILITY] if tool_name in {TOOL_NAMES[1], TOOL_NAMES[3]}
                       else [READ_CAPABILITY] if kind == "tool" else [])
        material = self.request("POST", "/material-governance/drafts", 201, {
            "requestId": "draft-" + identifier, "definition": {
                "id": identifier, "kind": kind, "name": "Original reviewed " + identifier,
                "description": "Generated no-provider deterministic toy experiment fixture.",
                "content": tool_name or "Original task-owned local toy workflow", "license": "MIT",
                "compatibility": ["agno:3.1.0"], "dependencies": [], "permissions": permissions,
                "runtimeBinding": {"adapterId": adapter, "revision": "1", "config": config},
                "provenance": {"kind": "original", "notice": "Original generated acceptance fixture."}}})
        review = self.request("POST", "/material-governance/reviews", 201, {
            "materialId": material["id"], "version": material["version"], "requestId": "review-" + identifier})
        self.login("bob")
        self.request("POST", "/material-governance/reviews/" + review["id"] + "/decision", 200,
                     {"approved": True, "requestId": "approve-" + identifier})
        return next(row for row in self.store.materials(published_only=True) if row["id"] == identifier)

    def _publish_application(self):
        model = self.publish_material("fixture-orx-model", "model", MODEL_ADAPTER_ID)
        environment = self.publish_material("fixture-orx-environment", "environment", "fixture-orx-environment-v1")
        tools = [self.publish_material("fixture-orx-" + name.rsplit("_", 1)[1], "tool",
                 ADAPTER_ID + "-" + name.rsplit("_", 1)[1], tool_name=name)
                 for name in (TOOL_NAMES[0], TOOL_NAMES[2], TOOL_NAMES[4])]
        modes = {}
        for scenario in ("success", "evaluator_failure", "long_running"):
            run = self.publish_material("fixture-orx-run-" + scenario, "tool", ADAPTER_ID + "-run",
                                        tool_name=TOOL_NAMES[1], scenario=scenario)
            modes[scenario] = {"materialRefs": [pin(model), pin(environment), *[pin(tool) for tool in tools], pin(run)],
                "capabilities": [READ_CAPABILITY, RUN_CAPABILITY],
                "toolOrder": [TOOL_NAMES[0], TOOL_NAMES[1], TOOL_NAMES[2], TOOL_NAMES[4]],
                "connectionRequirements": [{"name": "localExperiment", "kind": "orx",
                    "requiredCapabilities": [READ_CAPABILITY, RUN_CAPABILITY], "required": True}],
                "budget": {"toolCalls": 8, "maxDepth": 1, "maxChildren": 1,
                           "experimentSeconds": 30, "outputBytes": 65536}}
        self.login("bob")
        application = self.request("POST", "/applications/drafts", 201, {"requestId": "actual-orx-app-draft",
            "definition": {"id": "fixture-orx-local-toy", "name": "Reviewed actual ORX local toy",
                "description": "Actual CLI deterministic comparison without model providers.",
                "defaultMode": "success", "modes": modes, "discoveryKeywords": ["toy experiment"]}})
        review = self.request("POST", f"/applications/{application['id']}/versions/{application['version']}/review", 201,
                              {"requestId": "actual-orx-app-review"})
        self.login("manager")
        self.request("POST", f"/applications/reviews/{review['id']}/decision", 200,
                     {"approved": True, "requestId": "actual-orx-app-publish"})
        self.application = application

    def start(self, scenario):
        self.login("alice")
        proposal = self.request("POST", "/compositions/proposals", 201, {
            "goal": "Run the approved local toy baseline and candidate evaluator",
            "mode": scenario, "applicationRef": pin(self.application),
            "connectionRefs": {"localExperiment": self.connection["ref"]}, "requestId": str(uuid4())})
        self.assertEqual(proposal["candidate"]["status"], "ready", proposal["candidate"])
        plan = self.request("POST", f"/compositions/proposals/{proposal['id']}/accept", 201, {"requestId": str(uuid4())})
        review = self.request("POST", "/plan-reviews", 201, {"planId": plan["id"], "requestId": str(uuid4())})
        self.login("manager")
        self.request("POST", f"/plan-reviews/{review['id']}/decision", 200, {"approved": True, "requestId": str(uuid4())})
        self.login("alice")
        job = self.request("POST", "/instances", 202, {"planId": plan["id"], "requestId": str(uuid4())})
        self.task_id = job["id"]
        detail = self.wait({"waiting_approval", "failed", "unknown"}, 90 if self.process_limit == 64 else 30)
        self.assertEqual(detail["job"]["status"], "waiting_approval", detail)
        self.assertEqual(self.store.effects(self.task_id), [], "Native run confirmation precedes launch intent")
        return detail

    def approve(self, detail):
        approval = detail["job"]["approvalDetail"]
        return self.request("POST", f"/jobs/{self.task_id}/approve", 200,
            {"requirementId": approval["id"], "version": approval["version"], "approved": True})

    def wait(self, states, timeout=30):
        deadline = time.monotonic() + timeout
        detail = None
        while time.monotonic() < deadline:
            detail = self.request("GET", f"/jobs/{self.task_id}", 200)
            if detail["job"]["status"] in states:
                return detail
            time.sleep(.05)
        self.fail(str(detail))

    def observed(self, states, timeout=15):
        deadline = time.monotonic() + timeout
        value = None
        while time.monotonic() < deadline:
            value = inspect_orx_experiment(self.store, "alice", self.task_id)
            if value and value["status"] in states:
                return value
            time.sleep(.05)
        self.fail(str(value))

    def native_rows(self):
        owner_key = hashlib.sha256(b"alice").hexdigest()[:24]
        scope = self.settings.workspace / "orx-tasks" / owner_key / self.task_id
        with closing(sqlite3.connect(scope / "orx-store" / "orx.db")) as database:
            database.row_factory = sqlite3.Row
            return scope, [dict(row) for row in database.execute("SELECT * FROM runs")]

    def assert_result(self, detail, expected):
        observed = inspect_orx_experiment(self.store, "alice", self.task_id)
        self.assertEqual(observed["status"], expected, observed)
        self.assertEqual(observed["evaluation"]["baseline"], {"value": 16.0})
        self.assertEqual(observed["evaluation"]["candidate"], {"value": 0.0})
        self.assertEqual(observed["evaluation"]["metric"], "mean_squared_error")
        _, rows = self.native_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], observed["orxRunId"])
        self.assertEqual(rows[0]["status"], expected)
        self.assertEqual(rows[0]["commit_sha"], observed["provenance"]["sourceCommit"])
        artifact = next(row for row in detail["artifacts"] if row["name"].startswith("orx-toy-evaluation-"))
        response = self.client.get(f"/api/factory/jobs/{self.task_id}/artifacts/{artifact['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), artifact["sha256"])
        result = json.loads(response.content)["result"]
        self.assertEqual(result["orxRunId"], rows[0]["id"])
        self.assertEqual(result["provenance"]["resultSha256"], result["evaluation"]["resultSha256"])
        self.assertEqual(result["evidenceKind"], "toy_local_evaluation")
        source = next(row for row in detail["artifacts"] if row["id"] == result["sourceArtifactId"])
        source_response = self.client.get(f"/api/factory/jobs/{self.task_id}/artifacts/{source['id']}")
        self.assertEqual(source_response.status_code, 200)
        self.assertEqual(hashlib.sha256(source_response.content).hexdigest(), result["provenance"]["sourceArchiveSha256"])
        with tarfile.open(fileobj=io.BytesIO(source_response.content), mode="r:") as archive:
            self.assertEqual(sorted(archive.getnames()), ["baseline.py", "candidate.py", "dataset.json", "evaluator.py"])
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                raw = archive.extractfile(member).read()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), result["provenance"]["fileSha256"][member.name])
        effect = self.store.effects(self.task_id)
        self.assertEqual(len(effect), 1)
        self.assertEqual(effect[0]["status"], "DONE")
        bound = self.store.sql("SELECT * FROM af_orx_task_experiments WHERE task_id=:task", task=self.task_id)[0]
        self.assertEqual(digest(bound["binding"]), bound["binding_hash"])
        self.assertEqual(digest(bound["observation"]), bound["observation_hash"])

    def test_01_actual_binary_success_native_factory_approval_and_download(self):
        self.approve(self.start("success"))
        detail = self.wait({"completed", "failed", "unknown"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assert_result(detail, "done")

    def test_02_actual_evaluator_failure_retains_native_failed_metrics(self):
        self.approve(self.start("evaluator_failure"))
        detail = self.wait({"failed", "unknown"})
        self.assertEqual(detail["job"]["status"], "failed", detail)
        self.assert_result(detail, "failed")

    def test_03_cancel_running_native_experiment_positive_process_stop(self):
        self.approve(self.start("long_running"))
        running = self.observed({"starting", "running"})
        self.assertIsNotNone(running["orxRunId"])
        self.request("POST", f"/jobs/{self.task_id}/cancel", 200)
        stopped = self.observed({"cancelled"}, 25)
        self.assertTrue(stopped["stopEvidence"]["allStopped"], stopped)
        self.assertEqual(stopped["stopEvidence"]["activeProcesses"], 0)
        _, rows = self.native_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], running["orxRunId"])
        self.assertEqual(rows[0]["status"], "cancelled")
        self.assertEqual(self.store.effects(self.task_id)[0]["status"], "CANCELLED")

    def test_04_revoke_owner_connection_stops_owned_experiment_without_new_launch(self):
        self.approve(self.start("long_running"))
        running = self.observed({"starting", "running"})
        self.state["connections"].revoke("alice", self.connection["ref"], "actual-orx-revoke")
        stopped = self.observed({"cancelled"}, 25)
        self.assertTrue(stopped["stopEvidence"]["allStopped"], stopped)
        _, rows = self.native_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], running["orxRunId"])
        self.assertEqual(self.store.effects(self.task_id)[0]["status"], "CANCELLED")

    def test_05_source_drift_after_inspect_before_confirmation_denies_launch(self):
        paused = self.start("success")
        scope, rows = self.native_rows()
        self.assertEqual(rows, [])
        path = scope / "toy-repository" / "candidate.py"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n# adversarial source drift\n")
            self.approve(paused)
            detail = self.wait({"failed", "unknown"})
            self.assertEqual(detail["job"]["status"], "failed", detail)
            _, rows = self.native_rows()
            self.assertEqual(rows, [])
            self.assertEqual(self.store.effects(self.task_id), [])
        finally:
            path.write_bytes(original)

    def test_06_command_drift_after_inspect_before_confirmation_denies_launch(self):
        paused = self.start("success")
        scope, rows = self.native_rows()
        self.assertEqual(rows, [])
        with closing(sqlite3.connect(scope / "orx-store" / "orx.db")) as database:
            original = database.execute("SELECT run_command FROM local_experiments").fetchone()[0]
            database.execute("UPDATE local_experiments SET run_command=?", (original + " --unreviewed",))
            database.commit()
        try:
            self.approve(paused)
            detail = self.wait({"failed", "unknown"})
            self.assertEqual(detail["job"]["status"], "failed", detail)
            _, rows = self.native_rows()
            self.assertEqual(rows, [])
            self.assertEqual(self.store.effects(self.task_id), [])
        finally:
            with closing(sqlite3.connect(scope / "orx-store" / "orx.db")) as database:
                database.execute("UPDATE local_experiments SET run_command=?", (original,))
                database.commit()


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(sys.platform.startswith("linux") and os.getenv("FACTORY_ORX_LINUX_CONTAINER") == "1"
    and all(os.getenv(key) for key in _ACTUAL_ENV),
    "Requires explicit Linux task container, loopback PostgreSQL and pinned ORX toolchain")
class ActualLinuxORXNativeFactoryTests(ActualORXNativeFactoryTests):
    __unittest_skip__ = False
    process_limit = 64
