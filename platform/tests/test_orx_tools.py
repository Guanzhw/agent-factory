"""Factory integration tests for the bounded OpenResearch discovery tool.

The adapter is a deterministic in-process fixture. These tests do not contact
OpenAlex/alphaXiv, call a model, or launch research/compute operations.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4

from agno.exceptions import RunCancelledException
from agno.run import RunContext

from agent_factory.openresearch import BinaryPin, REVISION, VERSION
from agent_factory.orx_tools import (
    CAPABILITY, TOOL_NAME, ResolvedORXBinding, make_orx_discover_tool,
    OpenResearchError,
)
from agent_factory.store import digest

APPROVED_BINARY_SHA256 = "d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7"


class ControlledAdapter:
    """No-network adapter stand-in with controllable completion/cancellation."""
    def __init__(self, owner_id: str, task_id: str, *, results=None, fail=False):
        self.owner_id, self.task_id = owner_id, task_id
        self.pin = BinaryPin(revision=REVISION, version=VERSION, sha256=APPROVED_BINARY_SHA256)
        self.enabled = True
        self.transport_kind = "controlled_transport_fixture"
        self.max_output_bytes = 32768
        self.command_timeout: float = 10
        self._processes = set()
        self.results = results or [{"source": "openalex", "id": "W123", "title": "Synthetic metadata fixture"}]
        self.fail = fail
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cleaned = asyncio.Event()

    async def discover(self, query, *, corpus, limit):
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
            if self.fail:
                raise RuntimeError("synthetic transport failure")
            return self.results[:limit]
        finally:
            self.cleaned.set()


class FixtureStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.allowed = True
        self.cancelled = False
        self.authorization_calls = []
        self.events = []
        self.effects = {}
        self.artifact_rows = []
        self.artifact_bytes = {}
        self.plan = {
            "id": "plan-fixture", "fingerprint": "a" * 64,
            "tools": [TOOL_NAME], "capabilities": [CAPABILITY],
            "materialRefs": [{"id": "orx-discover-material", "version": 2, "sha256": "b" * 64}],
            "budget": {"toolCalls": 8, "outputBytes": 65536},
            "runtimePolicy": {"timeoutSeconds": 15},
        }

    def resolve_run(self, ctx):
        return {**self.plan, "taskId": ctx.session_id, "runId": ctx.run_id}

    def authorize_tool(self, ctx, name):
        self.authorization_calls.append((ctx.user_id, ctx.session_id, name))
        if not self.allowed:
            raise PermissionError("fixture authorization revoked")
        if name not in self.plan["tools"]:
            raise PermissionError("fixture plan does not include tool")
        return self.plan

    def cancellation_requested(self, run_id):
        return self.cancelled

    def effect_reserve(self, run_id, key, request):
        effect_id = run_id + ":" + key
        fingerprint = digest(request)
        old = self.effects.get(effect_id)
        if old is None:
            self.effects[effect_id] = {"status": "UNKNOWN", "fingerprint": fingerprint, "result": None}
            return {"status": "new"}
        if old["fingerprint"] != fingerprint:
            raise ValueError("Effect fingerprint conflict")
        return {"status": "done" if old["status"] in {"DONE", "CANCELLED"} else "unknown",
                "result": old["result"]}

    def effect_complete(self, run_id, key, result):
        row = self.effects[run_id + ":" + key]
        row["status"] = "CANCELLED" if result.get("cancelled") else "DONE"
        row["result"] = result

    def event(self, run_id, event_type, message, data=None):
        self.events.append({"runId": run_id, "type": event_type, "message": message, "data": data or {}})

    def artifact_write(self, run_id, name, content, media_type, metadata):
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        artifact_id = str(uuid4())
        body = {"id": artifact_id, "jobId": run_id, "name": name, "mediaType": media_type,
                "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "provenance": metadata}
        self.artifact_rows.append(body)
        self.artifact_bytes[artifact_id] = raw
        return body

    def artifacts(self, task_id):
        return list(self.artifact_rows)

    def artifact(self, task_id, artifact_id):
        body = next(row for row in self.artifact_rows if row["id"] == artifact_id)
        raw = self.artifact_bytes[artifact_id]
        if hashlib.sha256(raw).hexdigest() != body["sha256"]:
            raise ValueError("artifact integrity failed")
        return body, raw


class ORXToolFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(prefix="orx-tool-fixture-")
        self.root = Path(self.temp.name).resolve()
        self.store = FixtureStore(self.root)
        self.settings = SimpleNamespace(workspace=self.root, experiment_output_bytes=65536,
                                        experiment_timeout_seconds=15, orx_command_timeout_seconds=15)
        self.task_id = str(uuid4())
        self.ctx = RunContext(user_id="alice", session_id=self.task_id, run_id="run-fixture")
        self.adapter = ControlledAdapter("alice", self.task_id)
        self.binding = ResolvedORXBinding(
            adapter=self.adapter, owner_id="alice", task_id=self.task_id, ref="orx-local",
            version=1, fingerprint="c" * 64, revision="connection-revision-1",
            capabilities=(CAPABILITY,))
        self.provider_calls = 0

        def provider(ctx, plan):
            self.provider_calls += 1
            self.assertEqual(ctx.user_id, "alice")
            self.assertEqual(ctx.session_id, self.task_id)
            self.assertEqual(plan["id"], "plan-fixture")
            return self.binding

        self.provider = provider
        self.tool = make_orx_discover_tool(self.settings, self.store, self.provider)

    async def asyncTearDown(self):
        self.adapter.release.set()
        self.temp.cleanup()

    async def test_discovery_records_durable_effect_artifact_and_exact_provenance(self):
        self.adapter.release.set()
        raw = await self.tool("retrieval augmented generation", self.ctx, corpus="openalex", limit=3)
        result = json.loads(raw)
        self.assertEqual(result["evidenceKind"], "controlled_transport_fixture")
        self.assertEqual(result["results"][0]["id"], "W123")
        self.assertEqual(result["provenance"]["sourceRevision"], REVISION)
        self.assertEqual(result["provenance"]["sourceVersion"], VERSION)
        self.assertEqual(result["provenance"]["configuredBinarySha256"], APPROVED_BINARY_SHA256)
        self.assertNotIn("binarySha256", result["provenance"])
        self.assertEqual(result["provenance"]["connection"], {
            "ref": "orx-local", "version": 1, "fingerprint": "c" * 64,
            "revision": "connection-revision-1", "capabilities": [CAPABILITY]})
        self.assertEqual(len(self.store.artifact_rows), 1)
        self.assertEqual(self.store.artifact_rows[0]["sha256"], result["artifactSha256"])
        self.assertEqual(len(self.store.effects), 1)
        self.assertEqual(next(iter(self.store.effects.values()))["status"], "DONE")
        self.assertEqual(self.adapter.calls, 1)
        self.assertTrue(any(row["type"] == "orx_discovery_completed" for row in self.store.events))

    async def test_same_fingerprint_returns_recorded_result_without_repeating_discovery(self):
        self.adapter.release.set()
        first = json.loads(await self.tool("same query", self.ctx))
        second = json.loads(await self.tool("same query", self.ctx))
        self.assertEqual(first, second)
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(len(self.store.artifact_rows), 1)

    async def test_unknown_transport_acknowledgement_never_replays_same_effect(self):
        self.adapter.fail = True
        self.adapter.release.set()
        with self.assertRaises(OpenResearchError) as error:
            await self.tool("uncertain query", self.ctx)
        self.assertEqual(error.exception.code, "UNKNOWN_EFFECT")
        with self.assertRaises(OpenResearchError) as error:
            await self.tool("uncertain query", self.ctx)
        self.assertEqual(error.exception.code, "UNKNOWN_EFFECT")
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(len(self.store.artifact_rows), 0)

    async def test_current_authority_revocation_cancels_active_adapter_operation(self):
        operation = asyncio.create_task(self.tool("slow query", self.ctx))
        await asyncio.wait_for(self.adapter.started.wait(), timeout=1)
        self.store.allowed = False
        with self.assertRaises(RunCancelledException):
            await asyncio.wait_for(operation, timeout=2)
        self.assertTrue(self.adapter.cleaned.is_set())
        self.assertEqual(len(self.store.artifact_rows), 0)
        self.assertEqual(next(iter(self.store.effects.values()))["status"], "CANCELLED")
        self.assertTrue(any(row["type"] == "protected_denied" for row in self.store.events))

    async def test_factory_cancel_cancels_active_adapter_operation(self):
        operation = asyncio.create_task(self.tool("cancelled query", self.ctx))
        await asyncio.wait_for(self.adapter.started.wait(), timeout=1)
        self.store.cancelled = True
        with self.assertRaises(RunCancelledException):
            await asyncio.wait_for(operation, timeout=2)
        self.assertTrue(self.adapter.cleaned.is_set())
        self.assertEqual(len(self.store.artifact_rows), 0)
        self.assertEqual(next(iter(self.store.effects.values()))["status"], "CANCELLED")

    async def test_timeout_terminates_owned_operation_and_keeps_effect_unknown(self):
        self.store.plan["runtimePolicy"]["timeoutSeconds"] = 0.1
        self.adapter.command_timeout = 0.05
        operation = asyncio.create_task(self.tool("slow timeout", self.ctx))
        await asyncio.wait_for(self.adapter.started.wait(), timeout=1)
        with self.assertRaises(OpenResearchError) as error:
            await asyncio.wait_for(operation, timeout=2)
        self.assertEqual(error.exception.code, "TIMEOUT")
        self.assertTrue(self.adapter.cleaned.is_set())
        self.assertEqual(len(self.store.artifact_rows), 0)
        self.assertEqual(next(iter(self.store.effects.values()))["status"], "UNKNOWN")
        self.assertEqual(self.adapter.calls, 1)

    async def test_unconfigured_and_mismatched_task_bindings_fail_before_discovery(self):
        with self.assertRaises(OpenResearchError) as error:
            await make_orx_discover_tool(self.settings, self.store, None)("query", self.ctx)
        self.assertEqual(error.exception.code, "CONNECTION_NOT_CONFIGURED")
        self.binding = ResolvedORXBinding(
            adapter=self.adapter, owner_id="bob", task_id=self.task_id, ref="orx-local",
            version=1, fingerprint="c" * 64, revision="connection-revision-1",
            capabilities=(CAPABILITY,))
        with self.assertRaises(OpenResearchError) as error:
            await self.tool("query", self.ctx)
        self.assertEqual(error.exception.code, "BINDING_MISMATCH")
        self.assertEqual(self.adapter.calls, 0)

    async def test_missing_tool_capability_and_resource_overrun_are_denied(self):
        self.store.plan["capabilities"] = []
        with self.assertRaises(PermissionError):
            await self.tool("query", self.ctx)
        self.store.plan["capabilities"] = [CAPABILITY]
        self.adapter.max_output_bytes = 65536
        with self.assertRaises(OpenResearchError) as error:
            await self.tool("query", self.ctx)
        self.assertEqual(error.exception.code, "RESOURCE_LIMIT_EXCEEDED")
        self.assertEqual(self.adapter.calls, 0)


if __name__ == "__main__":
    unittest.main()
