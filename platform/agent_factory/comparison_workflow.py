"""Verified controlled comparisons over the original native process lifecycle.

One reviewed paired computation is one existing process effect. This service
never launches, schedules, retries or repairs execution. Its report is a derived
artifact, not scientific validation or permission to execute arbitrary code.
"""
import asyncio
import hashlib
import json
import threading
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request

from .comparison_contract import fingerprint
from .comparison_fixture import CHOICES, fixture_candidate, fixture_contract, fixture_limits, fixture_spec, input_manifest, validate_output
from .process_provider import ProcessResourceProvider
from .process_runtime import TOOL
from .store import canonical, digest

APPLICATION = "controlled-comparison-fixture-v1"
EFFECT = "comparison-report-v1"
GOAL = "使用明确标记的合成开发数据，比较固定基线与候选；不作为科研结论。"
_ADAPTERS = {"model": "controlled-comparison-model-v1", "environment": "controlled-comparison-environment-v1",
             "tool": "controlled-comparison-run-v1", "knowledge": "controlled-comparison-knowledge-v1"}


def _require(value):
    if not value:
        raise HTTPException(409, "COMPARISON_EVIDENCE_INVALID")


def validate_plan(store, plan, *, current=True):
    """Verify exact approved inputs; runtime contract is derived after plan hash.

    The final plan already pins all source inputs via materials and mode. Its
    derived comparison contract may refer to that final fingerprint without
    embedding its own hash back into the plan (no circular hash or placeholder).
    """
    execution = plan.get("executionBindings") or {}
    items = [execution.get("model", {}), execution.get("environment", {}),
             *execution.get("tools", []), *execution.get("knowledge", [])]
    related = plan.get("application") == APPLICATION or any(item.get("adapterId") in _ADAPTERS.values() for item in items)
    if not related:
        return None
    _require(store.settings.demo is True and store.settings.temporary_policy == "admin-review"
             and plan.get("application") == APPLICATION and (plan.get("applicationRef") or {}).get("id") == APPLICATION
             and plan.get("mode") in CHOICES and not plan.get("delegation") and not plan.get("remoteHandoff")
             and plan.get("tools") == [TOOL] and plan.get("capabilities") == ["compute:local"])
    choice = plan["mode"]
    _require(len(execution.get("tools", [])) == len(execution.get("knowledge", [])) == 1)
    tool = execution["tools"][0]
    config = tool.get("config")
    _require(type(config) is dict and set(config) == {"targetRef"} and type(config["targetRef"]) is str)
    target_ref = config["targetRef"]
    for kind, spec in (("model", execution.get("model")), ("environment", execution.get("environment")),
                       ("tool", tool), ("knowledge", execution["knowledge"][0])):
        _require(type(spec) is dict and spec.get("adapterId") == _ADAPTERS[kind] and spec.get("revision") == "1"
                 and spec.get("config") == ({"targetRef": target_ref} if kind == "tool" else {"choice": choice, "targetRef": target_ref}))
    _require(tool.get("toolName") == TOOL)
    knowledge = [item for item in plan.get("materials", []) if item.get("kind") == "knowledge"]
    _require(len(knowledge) == 1 and json.loads(knowledge[0]["content"]) == input_manifest(choice))
    if current:
        target = store.settings.remote_targets.get(target_ref)
        _require(target is not None and target.axis == "compute")
        provider = target.provider
        _require(type(provider) is ProcessResourceProvider and provider.aggregate_config is None
                 and provider.limits == fixture_limits()
                 and provider.spec == fixture_spec(provider.spec.executable, provider.spec.sha256, choice))
    return choice, target_ref


class ComparisonService:
    def __init__(self, store, auth):
        self.store, self.auth = store, auth

    def catalog(self, owner):
        self.auth.require(owner, "components:read")
        items = []
        if self.store.settings.demo and self.store.settings.temporary_policy == "admin-review":
            apps = [app for app in self.store.applications.list_active(owner) if app["id"] == APPLICATION]
            for app in apps[:1]:
                for choice in CHOICES:
                    if choice not in app["modes"]:
                        continue
                    values = self.store.composition._input(GOAL, choice, APPLICATION,
                        {key: app[key] for key in ("id", "version", "sha256")}, {}, {})
                    candidate = self.store.composition._candidate(owner, values, app)
                    if candidate["status"] != "ready":
                        continue
                    selected = validate_plan(self.store, candidate)
                    _require(selected is not None)
                    assert selected is not None
                    try:
                        self.store.process_runtime.resources._authorize(owner, selected[1])
                    except HTTPException as error:
                        if error.status_code in {403, 404}:
                            continue
                        raise
                    items.append({"applicationRef": candidate["applicationRef"], "mode": choice,
                        "name": choice, "goal": GOAL, "input": input_manifest(choice)})
        return {"schema": 1, "ownerId": owner, "evidenceKind": "controlled_comparison",
                "scientificConclusionVerified": False, "items": items}

    def _scope(self, owner, task_id, *, current=False):
        task = self.store.task(task_id, owner)
        plan = self.store.plan(task["plan_id"], owner)
        selected = validate_plan(self.store, plan, current=current)
        if selected is None:
            return None
        choice, target_ref = selected
        contract = fixture_contract(plan["fingerprint"], plan["materialRefs"])
        candidate = fixture_candidate(contract, choice)
        return task, plan, choice, target_ref, contract, candidate

    def _identity(self, task, plan, contract, candidate):
        return {"schema": 1, "evidenceKind": "controlled_comparison", "ownerId": task["owner_id"],
                "taskId": task["id"], "planId": plan["id"], "nativeRunId": task["run_id"],
                "planFingerprint": plan["fingerprint"], "contractSha256": fingerprint(contract),
                "candidateSha256": fingerprint(candidate), "scientificConclusionVerified": False}

    def _process(self, task):
        row = self.store.process_runtime._original(task["id"])
        if row is None:
            return None, None
        lease, target, bound, _ = self.store.process_runtime._custody(row["lease_id"])
        _require(bound["id"] == task["id"] and bound["run_id"] == task["run_id"])
        return lease, target

    @staticmethod
    def _process_projection(lease):
        if lease is None:
            return None
        return {"leaseId": lease["id"], "providerJobId": lease.get("providerJobId"),
                "executionStatus": lease.get("executionStatus", "UNKNOWN"), "exitCode": lease.get("exitCode"),
                "allStopped": (lease.get("stopEvidence") or {}).get("allStopped") is True,
                "capacityHeld": lease.get("capacityHeld", True)}

    async def persist(self, context, receipt):
        # Filesystem custody inspection may wait on the existing bounded lock.
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(self._persist, context, receipt, cancelled)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def _persist(self, context, receipt, cancelled):
        def authorize():
            if cancelled.is_set():
                raise asyncio.CancelledError()
            self.store.authorize_tool(context, TOOL)
            if cancelled.is_set():
                raise asyncio.CancelledError()

        authorize()
        scoped = self._scope(context.user_id, context.session_id, current=True)
        _require(scoped is not None)
        assert scoped is not None
        task, plan, choice, _, contract, candidate = scoped
        _require(task["run_id"] == context.run_id)
        lease, target = self._process(task)
        _require(lease is not None and target is not None and receipt.get("leaseId") == lease["id"]
                 and receipt.get("nativeRunId") == context.run_id and receipt.get("state") == "RECLAIMED"
                 and lease["state"] == "RECLAIMED" and lease.get("executionStatus") == "COMPLETED"
                 and lease.get("exitCode") == 0 and (lease.get("stopEvidence") or {}).get("allStopped") is True)
        assert lease is not None and target is not None
        raw = target.provider.read_completed_output(lease["id"], context.user_id)
        authorize()
        checked = validate_output(raw, contract, candidate, choice)
        identity = self._identity(task, plan, contract, candidate)
        process = self._process_projection(lease)
        document = {**identity, "choice": choice, "input": input_manifest(choice), "contract": contract,
                    "candidateDefinition": candidate, "process": process, "rawSha256": hashlib.sha256(raw).hexdigest(), **checked}
        intent = {**identity, "rawSha256": document["rawSha256"], "reportSha256": digest(document)}
        authorize()
        effect = self.store.effect_reserve(context.run_id, EFFECT, intent)
        if effect["status"] == "done":
            authorize()
            evidence = self.inspect(context.user_id, context.session_id)
            _require(evidence is not None and evidence["status"] == "ready")
            return effect["result"]
        _require(effect["status"] == "new")  # UNKNOWN is never repaired by replay.
        artifacts = {}
        for key, name, content in (("raw", "comparison-output.json", raw),
                                   ("report", "comparison-report.json", canonical(document))):
            authorize()
            artifacts[key] = self.store.artifact_write(context.run_id, name, content, metadata=identity)
        result = {**identity, "artifactIds": {key: item["id"] for key, item in artifacts.items()},
                  "artifactHashes": {key: item["sha256"] for key, item in artifacts.items()}}
        authorize()
        self.store.effect_complete(context.run_id, EFFECT, result)
        return result

    def inspect(self, owner, task_id):
        # Ownership must precede every private read, even when evidence is invalid.
        task = self.store.task(task_id, owner)
        plan = self.store.plan(task["plan_id"], owner)
        if plan.get("application") != APPLICATION:
            return None
        empty = {"schema": 1, "evidenceKind": "controlled_comparison", "ownerId": owner,
                 "taskId": task_id, "planId": plan["id"], "nativeRunId": task["run_id"], "choice": plan.get("mode"),
                 "status": "invalid", "executionVerified": False, "scientificConclusionVerified": False,
                 "contractSha256": None, "candidateSha256": None, "input": None, "baseline": None,
                 "candidate": None, "assessment": None, "artifactIds": None, "artifactHashes": None, "process": None}
        try:
            scoped = self._scope(owner, task_id)
            _require(scoped is not None)
            assert scoped is not None
            task, plan, choice, _, contract, candidate = scoped
            identity = self._identity(task, plan, contract, candidate)
            lease, _ = self._process(task)
            process = self._process_projection(lease)
            empty.update(contractSha256=identity["contractSha256"], candidateSha256=identity["candidateSha256"],
                         input=input_manifest(choice), process=process)
            effects = [row for row in self.store.effects(task_id) if row["effect_key"] == task["run_id"] + ":" + EFFECT] if task["run_id"] else []
            if not effects or effects[0]["status"] != "DONE":
                state = (process or {}).get("executionStatus")
                native_status = task["body"].get("lastStatus")
                status = ("unknown" if effects or state in {"UNKNOWN", "COMPLETED"} or task["admission"] == "unknown" else
                          "cancelled" if task["cancel_requested"] or state == "CANCELLED" else
                          "failed" if state in {"FAILED", "LIMIT_STOPPED"} or native_status == "failed" else
                          "cancelled" if native_status == "cancelled" else "pending")
                return {**empty, "status": status}
            _require(len(effects) == 1 and process is not None and process["executionStatus"] == "COMPLETED"
                     and process["exitCode"] == 0 and process["allStopped"] is True and process["capacityHeld"] is False)
            result = effects[0]["result"]
            _require(type(result) is dict and all(result.get(key) == value for key, value in identity.items()))
            result = cast(dict[str, Any], result)
            blobs = {}
            for key, name in (("raw", "comparison-output.json"), ("report", "comparison-report.json")):
                artifact, raw = self.store.artifact(task_id, result["artifactIds"][key])
                _require(artifact["name"] == name and artifact["jobId"] == task_id
                         and artifact["mediaType"] == "application/json" and artifact["sha256"] == result["artifactHashes"][key]
                         and artifact["size"] == len(raw) and 0 < len(raw) <= 65536 and artifact.get("provenance") == identity)
                blobs[key] = raw
            checked = validate_output(blobs["raw"], contract, candidate, choice)
            expected = {**identity, "choice": choice, "input": input_manifest(choice), "contract": contract,
                        "candidateDefinition": candidate, "process": process,
                        "rawSha256": hashlib.sha256(blobs["raw"]).hexdigest(), **checked}
            _require(blobs["report"] == canonical(expected).encode())
            return {**empty, "status": "ready", "executionVerified": True, **checked,
                    "artifactIds": result["artifactIds"], "artifactHashes": result["artifactHashes"]}
        except (HTTPException, ValueError, TypeError, KeyError, AttributeError, OSError):
            return {**empty, "status": "invalid"}


def comparison_router(auth, service):
    router = APIRouter(prefix="/api/factory/comparisons")

    @router.get("/catalog")
    def catalog(request: Request):
        return service.catalog(auth.user(request)["id"])

    @router.get("/tasks/{task_id}")
    def inspect(task_id: str, request: Request):
        value = service.inspect(auth.user(request)["id"], task_id)
        if value is None:
            raise HTTPException(404, "COMPARISON_NOT_FOUND")
        return value

    return router
