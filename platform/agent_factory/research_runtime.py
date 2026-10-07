"""Original native external-execution pause with existing process lease custody.

The controller submits only after a durable native pause. Maintenance cannot
launch or resume work. This boundary does not implement a GPU hardware driver.
"""
from __future__ import annotations

import asyncio
import json
import re

from agno.db.base import SessionType

from .process_runtime import ProcessRuntimeService, _require, process_reservation
from .research_manifest import validate_manifest, manifest_fingerprint
from .store import digest

TOOL = "research_process_run"
EFFECT = "research-process-run-v1"


class ResearchProcessRuntimeService(ProcessRuntimeService):
    tool_name = TOOL
    effect_key = EFFECT

    def _config(self, task, plan):
        bindings = self.store.execution_bindings
        _require(bindings is not None)
        tools = bindings.manifest(plan, context=self._context(task)).get("tools", [])
        selected = [item for item in tools if item.get("toolName") == TOOL]
        _require(len(selected) == 1)
        from .autoresearch_scientific_child import adapter_id, child_pin
        scientific_phase = next((phase for phase in ('training', 'evaluation')
            if selected[0].get('adapterId') == adapter_id(phase, 'tool')), None)
        if scientific_phase is not None:
            from .execution_bindings import BindingContext
            try:
                pin = child_pin(BindingContext(self.store.settings, self.store, plan,
                    self._context(task), selected[0]), scientific_phase, custody=True)
            except ValueError:
                raise PermissionError('AUTORESEARCH_CHILD_AUTHORITY_ENDED') from None
            return pin['targetRef'], pin['comparisonManifest'], pin['variantSha256']
        config = selected[0].get("config")
        _require(type(config) is dict and set(config) == {"targetRef", "comparisonManifestSha256", "variantSha256"})
        knowledge = bindings.knowledge_for(plan, self._context(task))
        manifests = [validate_manifest(json.loads(item.content)) for item in knowledge
                     if item.provenance.get("evidenceKind") == "offline_research_experiment_manifest"]
        _require(len(manifests) == 1 and manifest_fingerprint(manifests[0]) == config["comparisonManifestSha256"])
        manifest = manifests[0]
        variant = config["variantSha256"]
        _require(isinstance(variant, str) and re.fullmatch(r"[a-f0-9]{64}", variant) is not None)
        return config["targetRef"], manifest, variant

    def _paused(self, task, manifest, variant):
        from .factory_api import requirement_version
        observer = self.store.lifecycle_observer
        _require(observer is not None)
        ticket = observer._binding(task)
        _require(ticket is not None and ticket["status"] == "paused" and ticket["persistedRunStatus"] == "paused")
        session = self.store.native_db.get_session(task["id"], session_type=SessionType.AGENT, user_id=task["owner_id"])
        _require(session is not None)
        runs = [run for run in session.runs or [] if run.run_id == task["run_id"] and run.agent_id == "factory-executor"]
        _require(len(runs) == 1)
        requirements = [item.to_dict() for item in runs[0].requirements or []]
        _require(len(requirements) == 1)
        requirement = requirements[0]
        tool = requirement.get("tool_execution") or {}
        _require(tool.get("tool_name") == TOOL and tool.get("external_execution_required") is True
                 and tool.get("result") is None and tool.get("tool_args") in ({}, None)
                 and type(tool.get("tool_call_id")) is str and type(requirement.get("id")) is str)
        return {"id": requirement["id"], "version": requirement_version(requirement),
                "toolCallId": tool["tool_call_id"], "toolArgsSha256": digest(tool.get("tool_args")),
                "manifestSha256": manifest_fingerprint(manifest), "variantSha256": variant}

    def validate_execution(self, owner, task, plan, target_ref, execution):
        _require(type(execution) is dict and set(execution) == {"nativeRunId", "effectKey", "requirement"}
                 and execution["effectKey"] == EFFECT and execution["nativeRunId"] == task["run_id"]
                 and owner == task["owner_id"] and not task["terminal"] and not task["cancel_requested"])
        selected, manifest, variant = self._config(task, plan)
        _require(selected == target_ref and self._paused(task, manifest, variant) == execution["requirement"])
        self.store.authorize_tool(self._context(task), TOOL)

    def guard_lease(self, lease):
        self.resources._authorize(lease["ownerId"], lease["connectionRef"])
        task = self.store.task(lease["localTaskId"], lease["ownerId"])
        plan = self.store.plan(lease["planId"], lease["ownerId"])
        _require(task["plan_id"] == lease["planId"] and digest(plan) == lease["planHash"])
        self.validate_execution(lease["ownerId"], task, plan, lease["connectionRef"],
            {"nativeRunId": lease["nativeRunId"], "effectKey": EFFECT, "requirement": lease.get("executionGuard")})

    async def submit(self, owner, task_id):
        """Trusted controller entry, no model arguments, never a replacement run."""
        self.auth.require(owner, "run")
        task = self.store.task(task_id, owner)
        plan = self.store.plan(task["plan_id"], owner)
        target_ref, manifest, variant = self._config(task, plan)
        self.store.authorize_tool(self._context(task), TOOL)
        prior = self._original(task_id)
        if prior is not None:
            _require(prior["owner_id"] == owner and prior["native_run_id"] == task["run_id"])
            lease = self.resources.inspect(owner, prior["lease_id"])
            _require(lease["connectionRef"] == target_ref and lease.get("executionEffect") == EFFECT)
            return lease  # Includes reclaimed work; never dispatch again.
        guard = self._paused(task, manifest, variant)
        target = self.resources._authorize(owner, target_ref)
        provider = self.resources._provider(target)
        limits = getattr(provider, "limits", None)
        _require(limits is not None and target.gpu_binding is not None
                 and target.gpu_binding.identity_key == manifest["device"]["identitySha256"]
                 and limits.wall_seconds == manifest["protocol"]["totalWallSeconds"])
        assert limits is not None
        from .process_enforcement import ResearchProcessLimits
        if type(limits) is ResearchProcessLimits:
            _require(limits.output_bytes <= manifest['artifactLimits']['logBytes']
                     and limits.file_size_bytes >= min(manifest['artifactLimits']['checkpointBytes'], 2 * 1024**3)
                     and limits.disk_bytes >= 2 * limits.file_size_bytes + limits.output_bytes)
        reservation = process_reservation(provider)
        return await self.resources.allocate(owner, target_ref, task_id,
            "research-" + digest({"task": task_id, "run": task["run_id"], "effect": EFFECT}), reservation,
            execution={"nativeRunId": task["run_id"], "effectKey": EFFECT, "requirement": guard})

    async def inspect_task(self, owner, task_id):
        self.auth.require(owner, "run")
        task = self.store.task(task_id, owner)
        original = self._original(task_id)
        _require(original is not None and original["owner_id"] == owner and original["native_run_id"] == task["run_id"])
        assert original is not None
        return await self.observe_lease(original["lease_id"])

    async def completion(self, task, requirement):
        """Native continuation consumes process custody only, never a score."""
        original = self._original(task["id"])
        _require(original is not None)
        lease = await self.inspect_task(task["owner_id"], task["id"])
        self.guard_lease(lease)
        from .factory_api import requirement_version
        pin = lease["executionGuard"]
        _require(requirement.get("id") == pin["id"] and requirement_version(requirement) == pin["version"]
                 and lease["state"] == "RECLAIMED" and lease.get("executionStatus") == "COMPLETED"
                 and lease.get("exitCode") == 0 and lease.get("gpuEvidence", {}).get("state") == "RELEASED")
        return await asyncio.to_thread(self._receipt, self._context(task), lease)

    def _write_receipt(self, context, lease):
        # Intentionally not a scientific evaluation. No candidate stdout is read.
        self.store.authorize_tool(context, TOOL)
        _require(lease["state"] == "RECLAIMED" and lease.get("stopEvidence", {}).get("allStopped") is True
                 and lease.get("gpuEvidence", {}).get("state") == "RELEASED")
        return {"evidenceKind": "research_process_custody", "leaseId": lease["id"],
                "nativeRunId": lease["nativeRunId"], "providerJobId": lease["providerJobId"],
                "manifestSha256": lease["executionGuard"]["manifestSha256"],
                "state": lease["state"], "capacityHeld": lease["capacityHeld"],
                "syntheticFixture": lease["syntheticFixture"], "gpuExecutionVerified": False,
                "scientificConclusionVerified": False}
