"""Opt-in TCP/PG bounded-process acceptance server, never production startup.

Generated identities/configuration only. The parent owns both disposable DBs and
0600 configuration files and removes provider credentials from child environment.
"""
from __future__ import annotations

import copy
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import threading
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.engine import make_url

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.material_governance import MaterialDefinition
from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec, birth, same_birth
from agent_factory.process_provider import ProcessResourceProvider
from agent_factory.process_runtime_profile import (MODEL_ID, TOOL_NAME, process_settings,
    publish_process_application, registrations)
from agent_factory.remote_authority import OriginAuthorityTransport
from agent_factory.remote_bindings import TrustedRemoteBindingMapping
from agent_factory.remote_handoff import HandoffTarget, TrustedOrigin
from agent_factory.store import Store
from agent_factory.resources import ComputePool, RemoteTarget
from controlled_remote_worker import (  # pyright: ignore[reportMissingImports]
ORIGIN_OWNER, RECEIVER_OWNER, OTHER_OWNER, MANAGER, REVIEWER,
    ORIGIN_REF, TARGET_REF, pin, token)

ORIGIN_PROCESS = "origin-process"
RECEIVER_PROCESS = "receiver-process"


class AllocationDiagnostics:
    """Bounded in-memory observations; never add SQL to the dispatch boundary."""
    def __init__(self):
        self.records = []
        self.dropped = 0
        self.lock = threading.Lock()

    def record(self, lease, phase, error=None):
        now = datetime.now(timezone.utc)
        deadline = datetime.fromisoformat(lease["deadlineAt"])
        value = {"phase": phase, "leaseId": lease["id"], "taskId": lease["localTaskId"],
            "nativeRunId": lease.get("nativeRunId"), "deadlineAt": deadline.isoformat(),
            "observedAt": now.isoformat(), "deadlineElapsed": now >= deadline}
        if error is not None:
            value.update(safe_allocation_error(error))
        with self.lock:
            if len(self.records) < 128:
                self.records.append(value)
            else:
                self.dropped += 1

    async def allocate(self, original, lease, before_effect):
        self.record(lease, "ALLOCATE_ENTRY")
        def observed_effect():
            self.record(lease, "BEFORE_EFFECT_ENTRY")
            try:
                result = before_effect()
            except BaseException as error:
                self.record(lease, "BEFORE_EFFECT_ERROR", error)
                raise
            self.record(lease, "BEFORE_EFFECT_RETURNED")
            return result
        try:
            result = await original(lease, before_effect=observed_effect)
        except BaseException as error:
            self.record(lease, "ALLOCATE_ERROR", error)
            raise
        self.record(lease, "ALLOCATE_RETURNED")
        return result

    def snapshot(self):
        with self.lock:
            return {"records": copy.deepcopy(self.records), "dropped": self.dropped}


def safe_allocation_error(error):
    category = next((name for kind, name in ((HTTPException, "HTTPException"),
        (asyncio.CancelledError, "CancelledError"), (TimeoutError, "TimeoutError"),
        (PermissionError, "PermissionError"), (OSError, "OSError"),
        (ValueError, "ValueError"), (RuntimeError, "RuntimeError")) if isinstance(error, kind)), "UnknownError")
    value: dict[str, Any] = {"errorType": category, "errorCategory": {
        "HTTPException": "HTTP_REJECTION", "CancelledError": "CANCELLED", "TimeoutError": "TIMEOUT",
        "PermissionError": "PERMISSION", "OSError": "OS_ERROR", "ValueError": "INVALID_STATE",
        "RuntimeError": "RUNTIME_ERROR", "UnknownError": "UNKNOWN"}[category],
        "httpStatus": None, "errorCode": None}
    if isinstance(error, HTTPException):
        data = BaseException.__dict__["__dict__"].__get__(error)
        status, detail = dict.get(data, "status_code"), dict.get(data, "detail")
        if type(status) is int and 400 <= status <= 599:
            value["httpStatus"] = status
        codes = {"Canceled, terminal or expired work cannot allocate new effects": "ADMISSION_WORK_ENDED",
            "Allocation configuration changed before dispatch": "ADMISSION_CONFIGURATION_CHANGED",
            "PROCESS_EXECUTION_FAILED_WITH_STOP_PROOF": "PROCESS_EXECUTION_FAILED_WITH_STOP_PROOF",
            "PROCESS_EXECUTION_EFFECT_UNSUPPORTED": "PROCESS_EXECUTION_EFFECT_UNSUPPORTED"}
        if type(detail) is str:
            value["errorCode"] = codes.get(detail)
    return value


def provider_observations(leases, rows):
    states = {"UNKNOWN", "ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "LIMIT_STOPPED", "RECLAIMED"}
    kinds = {"never-dispatched", "original-root-reaped-and-no-live-process-group-members", "original-delegated-cgroup-released"}
    records = {row["id"]: row["body"] for row in rows}
    result = []
    for lease in leases[:100]:
        body = records.get(lease["id"])
        value = {"leaseId": lease["id"], "providerRowPresent": body is not None}
        if body is not None:
            value.update(state=body.get("state") if body.get("state") in states else "unrecognized",
                executionStatus=body.get("executionStatus") if body.get("executionStatus") in states else "unrecognized",
                exitCode=body.get("exitCode") if type(body.get("exitCode")) is int and -255 <= body["exitCode"] <= 255 else None,
                allStopped=body.get("allStopped") is True, released=body.get("released") is True,
                stopKind=body.get("stopKind") if body.get("stopKind") in kinds else None,
                processPinPresent=bool(body.get("processPin")), journalPinPresent=bool(body.get("journalIdentity")))
        result.append(value)
    return result


class DropControlAcknowledgement:
    """One post-effect acknowledgement loss; no dispatch/cancel call replay."""
    def __init__(self, app, controls, store, marker):
        self.app, self.controls, self.store, self.marker = app, controls, store, marker

    async def __call__(self, scope, receive, send):
        fault = self.controls.get("fault")
        if (fault == "disconnect_reads" and scope["type"] == "http" and scope.get("method") == "GET"
                and re.fullmatch(r"/api/factory/remote-handoffs/(?:receipts/by-request|[^/]+(?:/detail)?)", scope.get("path", ""))):
            # Persistent fixture-only read outage. Authority callbacks, fixture
            # controls, cancellation and all other mutations remain reachable.
            records = []
            if not self.controls.get("disconnectRecorded"):
                rows = self.store.sql("SELECT body FROM af_leases WHERE body->>'nativeRunId' IS NOT NULL ORDER BY id LIMIT 20")
                count = self.store.sql("SELECT count(*) AS count FROM af_events WHERE type='fixture_process_cancel_attempt'")[0]["count"]
                for row in rows:
                    lease = row["body"]
                    task = self.store.task(lease["localTaskId"], lease["ownerId"])
                    records.append((task["id"], {
                        "leaseId": lease["id"], "deadlineAt": datetime.fromisoformat(lease["deadlineAt"]).isoformat(),
                        "cancelAttemptCount": count, "cancelRequested": task.get("cancel_requested") is True,
                        "state": lease["state"] if lease["state"] in {"RESERVED", "ACCEPTED", "RUNNING", "UNKNOWN",
                            "CANCEL_REQUESTED", "CANCEL_CONFIRMED", "COMPLETED", "FAILED", "RECLAIMING", "RECLAIMED"} else "unrecognized"}))
                self.controls["disconnectRecorded"] = True
            observed_at = None
            async def traced_send(message):
                nonlocal observed_at
                if message["type"] == "http.response.start":
                    observed_at = datetime.now(timezone.utc).isoformat()
                await send(message)
            await JSONResponse({"detail": "CONTROLLED_RECEIPT_READ_UNAVAILABLE"}, status_code=503)(scope, receive, traced_send)
            # Persist after the response boundary so the diagnostic write cannot
            # move a pre-deadline timestamp ahead of a delayed actual 503 send.
            for task_id, record in records:
                self.store.event(task_id, "fixture_disconnect_response", "First controlled receipt read 503 boundary",
                    {**record, "observedAt": observed_at})
            return
        suffix = "/dispatch" if fault in {"drop_dispatch_ack", "exit_after_dispatch", "exit_after_queued_dispatch"} else "/cancel" if fault == "drop_cancel_ack" else None
        if (scope["type"] != "http" or scope.get("method") != "POST" or suffix is None
                or not scope.get("path", "").startswith("/api/factory/remote-") or not scope["path"].endswith(suffix)):
            return await self.app(scope, receive, send)
        buffered = []
        async def capture(message):
            buffered.append(message)
        await self.app(scope, receive, capture)
        status = next(item["status"] for item in buffered if item["type"] == "http.response.start")
        if 200 <= status < 300:
            if fault in {"exit_after_dispatch", "exit_after_queued_dispatch"}:
                if fault == "exit_after_dispatch":
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if self.store.sql("SELECT id FROM af_events WHERE type='fixture_process_launch_returned' LIMIT 1"):
                            break
                        await asyncio.sleep(.025)
                    else:
                        for message in buffered:
                            await send(message)
                        return
                self.marker.write_text(json.dumps({"phase": "after-process-launch-before-http-ack" if fault == "exit_after_dispatch"
                    else "after-native-queue-before-http-ack", "pid": os.getpid()}))
                os._exit(41)
            self.controls["fault"] = None
            self.controls["droppedAcknowledgements"] += 1
            return await JSONResponse({"detail": "CONTROLLED_ACKNOWLEDGEMENT_LOST"}, status_code=503)(scope, receive, send)
        for message in buffered:
            await send(message)


def process_identity_observation(pin):
    if not isinstance(pin, dict) or type(pin.get("pid")) is not int:
        return {"currentState": "UNPINNED", "matchesOriginal": None}
    current = birth(pin["pid"])
    if current is None:
        # Missing and unreadable are deliberately not claimed as positive stop.
        return {"currentState": "UNKNOWN", "matchesOriginal": None}
    return {"currentState": current["state"] if current.get("state") in
            {"R", "S", "D", "Z", "T", "t", "X", "I", "K", "W", "P"} else "UNKNOWN",
            "matchesOriginal": same_birth(current, pin)}


def custody_observations(store, custody):
    """Read only journals whose initialization was durably pinned by the provider.

    An allocation intent and even its SQLite path precede journal initialization.
    Neither observation is positive process/stop evidence.
    """
    values = []
    for row in store.sql("SELECT id,owner_id,body FROM af_process_allocations"):
        body = row["body"]
        if isinstance(body, str):
            body = json.loads(body)
        if not body.get("processPin") or not body.get("journalIdentity"):
            values.append({"leaseId": row["id"], "state": "UNKNOWN", "stoppedProof": False,
                           "capacityHeld": True, "observation": "custody-not-pinned"})
            continue
        path = custody / row["id"] / "custody.sqlite"
        try:
            observed = BoundedProcessAdapter(path).inspect(owner_id=row["owner_id"])
        except Exception as error:
            # Do not echo exception strings, private paths, SQL or server logs.
            category = next((name for kind, name in ((OSError, "OSError"), (ValueError, "ValueError"),
                (TypeError, "TypeError")) if isinstance(error, kind)), "UnexpectedError")
            raise HTTPException(500, {"fixturePhase": "pinned-custody-inspect", "errorType": category}) from None
        values.append({"leaseId": row["id"], **{key: observed.get(key) for key in
            ("id", "taskId", "ownerId", "state", "child", "guardian", "stoppedProof", "capacityHeld")},
            "guardianObservation": process_identity_observation(observed.get("guardian")),
            "childObservation": process_identity_observation(observed.get("child"))})
    return values


def _provision(state, owner):
    auth = state["auth"]
    read = ["agents:factory-executor:read", "components:read", "registry:read", "sessions:read", "filesystem:read"]
    auth.authorization.define_role("fixture-reader", read)
    auth.authorization.define_role("fixture-user", [*read, "agents:factory-executor:run", "compute:local"])
    auth.authorization.define_role("fixture-admin-role", ["agent_os:admin"])
    for subject in (ORIGIN_OWNER, RECEIVER_OWNER, OTHER_OWNER, MANAGER, REVIEWER):
        if auth.directory.get(subject) is None:
            auth.directory.upsert(subject, name=subject)
            auth.authorization.assign(subject, "fixture-admin-role" if subject in {MANAGER, REVIEWER}
                else "fixture-user" if subject in {owner, OTHER_OWNER} else "fixture-reader")


def _source_specs(materials):
    result: dict[str, Any] = {"tools": []}
    for material in materials.values():
        if "runtimeBinding" not in material:
            continue
        spec = {"materialRef": pin(material), **copy.deepcopy(material["runtimeBinding"])}
        if material["kind"] == "tool":
            spec["toolName"] = TOOL_NAME
            result["tools"].append(spec)
        else:
            result[material["kind"]] = spec
    return result


def _publish(state, source):
    if source is None:
        application = publish_process_application(state, target_ref=ORIGIN_PROCESS, author=MANAGER, reviewer=REVIEWER)
    else:
        # Exact source materials retain IDs, versions and hashes. Receiver
        # grants fresh local publication approval; source approval is not copied.
        for material in source["materials"].values():
            governance = state["material_governance"]
            definition = {key: value for key, value in material.items() if key in MaterialDefinition.model_fields}
            draft = governance.create_draft(MANAGER, definition, "process-fixture-import-" + material["id"])
            if pin(draft) != pin(material):
                raise ValueError("Exact source process material changed on receiver")
            review = governance.request_publication(MANAGER, draft["id"], draft["version"], "process-fixture-review-" + draft["id"])
            governance.decide_publication(REVIEWER, review["id"], True, "process-fixture-approve-" + draft["id"])
        applications = state["applications"]
        application = applications.import_snapshot(MANAGER, source["application"], "process-fixture-application-import")
        review = applications.request_publication(MANAGER, application["id"], application["version"], "process-fixture-application-review")
        applications.decide_publication(REVIEWER, review["id"], True, "process-fixture-application-approve")
    materials = {row["id"]: row for row in state["store"].materials(published_only=True)
                 if row["id"] in {ref["id"] for ref in application["modes"]["controlled-fixture"]["materialRefs"]}}
    return application, materials


def main():
    config_path = Path(os.environ["FACTORY_REMOTE_PROCESS_CONFIG"]).resolve()
    if stat.S_IMODE(config_path.stat().st_mode) != 0o600:
        raise ValueError("Generated fixture configuration must have mode 0600")
    configuration = json.loads(config_path.read_text(encoding="utf-8"))
    directory = config_path.parent
    url = make_url(configuration["dbUrl"])
    if url.host not in {"127.0.0.1", "localhost", "::1"} or not re.fullmatch(r"af_test_[a-f0-9]{32}", url.database or ""):
        raise ValueError("Fixture requires generated loopback PostgreSQL")
    role = configuration["role"]
    if role not in {"origin", "receiver"}:
        raise ValueError("Invalid fixture role")
    workspace = Path(configuration["workspace"]).resolve()
    if not workspace.is_relative_to(directory):
        raise ValueError("Fixture workspace is outside its owned root")
    workload = configuration.get("workload", "normal")
    if workload not in {"normal", "sleep", "unknown", "deadline"}:
        raise ValueError("Only fixed synthetic workloads are supported")
    owner = ORIGIN_OWNER if role == "origin" else RECEIVER_OWNER
    target_ref = ORIGIN_PROCESS if role == "origin" else RECEIVER_PROCESS
    bootstrap = Store(configuration["dbUrl"], Settings(db_url=configuration["dbUrl"], workspace=workspace))
    custody = workspace / "process-custody"
    custody.mkdir(parents=True, mode=0o700, exist_ok=True)
    executable = Path(sys.executable).resolve()
    code = "print('Controlled remote bounded process')" if workload == "normal" else "import time; time.sleep(30)"
    spec = ProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(), ("-I", "-c", code))
    provider = ProcessResourceProvider(bootstrap, custody, spec, ProcessLimits(wall_seconds=.3 if workload == "deadline" else 5))
    pool = ComputePool("fixture-process-pool", 1, 128, 1, max_leases=1, max_owner_leases=1)
    target = RemoteTarget("Controlled process target", "compute", frozenset({owner}), provider=provider,
        synthetic_fixture=True, max_cpu=1, max_memory_mb=128, max_disk_mb=1, max_seconds=5, capacity_pool=pool)
    class MustNotAllocate:
        async def allocate(self, lease_id, owner, fingerprint, limits):
            raise AssertionError("Shared pool admission must deny before allocation")
        async def inspect(self, lease_id, owner):
            raise AssertionError("Probe must never acquire provider custody")
        async def cancel(self, lease_id, owner):
            raise AssertionError("Probe must never acquire provider custody")
        async def reclaim(self, lease_id, owner):
            raise AssertionError("Probe must never acquire provider custody")
    probe_target = RemoteTarget("Controlled pool probe", "compute", frozenset({OTHER_OWNER}), provider=MustNotAllocate(),
        synthetic_fixture=True, max_cpu=1, max_memory_mb=128, max_disk_mb=1, max_seconds=5, capacity_pool=pool)
    settings = process_settings(db_url=configuration["dbUrl"], workspace=workspace, target_ref=target_ref,
        remote_targets={target_ref: target, "capacity-probe": probe_target}, owner=owner)
    settings.jwt_key, settings.port = configuration["jwtKey"], configuration["port"]
    settings.max_user_tasks, settings.max_total_tasks = 12, 24
    created = []
    entries = registrations(target_ref=target_ref, owner=owner, include_fixture_model=True)
    def fixture_factory(original):
        def create(context):
            if role == "origin":
                raise AssertionError("Origin model must not execute a remote placement")
            model = original(context)
            created.append({"ownerId": owner, "taskId": context.run_context.session_id, "runId": context.run_context.run_id})
            return model
        return create
    settings.runtime_adapters = [replace(entry, factory=fixture_factory(entry.factory)) if entry.adapter_id == MODEL_ID else entry for entry in entries]
    handoff = HandoffTarget(TARGET_REF, ORIGIN_REF, configuration["receiverUrl"], {ORIGIN_OWNER: RECEIVER_OWNER},
        lambda _: {"Authorization": "Bearer " + token(configuration["receiverJwtKey"], RECEIVER_OWNER)},
        configuration_revision="fixture-process-target-v1")
    mappings = {}
    if role == "origin":
        settings.handoff_targets = {TARGET_REF: handoff}
    else:
        transport = OriginAuthorityTransport(base_url=configuration["originUrl"], origin_ref=ORIGIN_REF,
            target_ref=TARGET_REF, target_revision=handoff.configuration_revision, target_fingerprint=handoff.fingerprint,
            receiver_identity_map=handoff.identity_map,
            credential_provider=lambda _: token(configuration["originJwtKey"], RECEIVER_OWNER))
        settings.handoff_origins = {ORIGIN_REF: TrustedOrigin(ORIGIN_REF, {ORIGIN_OWNER: RECEIVER_OWNER}, transport,
            tools=frozenset({TOOL_NAME}), capabilities=frozenset({"compute:local"}),
            configuration_revision="fixture-process-origin-v1", tool_contract="bounded-process-v1")}
        specs = configuration["sourceSpecs"]
        for kind, source in [("model", specs["model"]), ("environment", specs["environment"]), *[("tool", value) for value in specs["tools"]]]:
            reference = "fixture-process-" + kind
            effective = {**copy.deepcopy(source), "config": {"targetRef": RECEIVER_PROCESS}}
            mappings[reference] = TrustedRemoteBindingMapping(reference, "1", ORIGIN_REF, ORIGIN_OWNER, RECEIVER_OWNER, kind, source, effective)
        settings.remote_binding_mappings = dict(mappings)
    app = create_app(settings)
    state = app.app.state.factory
    _provision(state, owner)
    source = None if role == "origin" else {"application": configuration.get("sourceApplication", configuration.get("sourceSnapshot")),
                                            "materials": configuration["sourceMaterials"]}
    snapshot, materials = _publish(state, source)
    controls = {"fault": None, "droppedAcknowledgements": 0}
    allocation_diagnostics = AllocationDiagnostics()
    original_allocate = provider.allocate_bound
    async def diagnostic_allocate(lease, *, before_effect):
        return await allocation_diagnostics.allocate(original_allocate, lease, before_effect)
    provider.allocate_bound = diagnostic_allocate
    original_launch, original_cancel = BoundedProcessAdapter.launch, BoundedProcessAdapter.cancel
    def counted_launch(self, *, owner_id, before_effect):
        adapter = self
        original = adapter.inspect(owner_id=owner_id)
        state["store"].event(original["taskId"], "fixture_process_launch_attempt", "Owned fixture launch boundary", {"processId": original["id"]})
        if workload == "unknown":
            with patch("agent_factory.process_enforcement.subprocess.Popen", side_effect=OSError("Controlled launch acknowledgement unknown")):
                return original_launch(adapter, owner_id=owner_id, before_effect=before_effect)
        result = original_launch(adapter, owner_id=owner_id, before_effect=before_effect)
        state["store"].event(original["taskId"], "fixture_process_launch_returned", "Original guardian launch returned", {"processId": original["id"]})
        return result
    def counted_cancel(self, *, owner_id):
        adapter = self
        original = adapter.inspect(owner_id=owner_id)
        state["store"].event(original["taskId"], "fixture_process_cancel_attempt", "Owned fixture cancel boundary", {"processId": original["id"]})
        return original_cancel(adapter, owner_id=owner_id)
    BoundedProcessAdapter.launch = counted_launch
    BoundedProcessAdapter.cancel = counted_cancel

    last_reasons = {}
    original_reason = state["store"].process_runtime._reason
    def diagnostic_reason(lease, task, ticket):
        result = original_reason(lease, task, ticket)
        finite = {"TASK_CANCEL_REQUESTED", "NATIVE_TERMINAL", "LEASE_EXPIRED", "AUTHORITY_ENDED", None}
        last_reasons[lease["id"]] = {
            "runtimeReason": result if result in finite else "unrecognized",
            "runtimeReasonObservedAt": datetime.now(timezone.utc).isoformat()}
        return result
    state["store"].process_runtime._reason = diagnostic_reason

    original_provider_cancel = provider.cancel
    async def diagnostic_provider_cancel(lease_id, owner):
        store = state["store"]
        rows = store.sql("SELECT body FROM af_leases WHERE id=:id AND owner_id=:owner", id=lease_id, owner=owner)
        if rows:
            lease = rows[0]["body"]
            current = datetime.now(timezone.utc)
            task = store.task(lease["localTaskId"], owner)
            native = store.native_db.get_job(task["run_id"]) if task.get("run_id") else None
            native_status = native.get("status") if native else None
            allowed_native = {"pending", "queued", "running", "paused", "completed", "failed", "cancelled"}
            path = custody / lease_id / "custody.sqlite"
            observed = BoundedProcessAdapter(path).inspect(owner_id=owner) if path.exists() else {}
            process_status = observed.get("state")
            allowed_process = {"PREPARED", "DISPATCHING", "RUNNING", "UNKNOWN", "COMPLETED", "FAILED", "CANCELLED", "LIMIT_STOPPED"}
            receipt = observed.get("stopReceipt") or {}
            stop_kind = receipt.get("kind")
            allowed_stop = {"original-root-reaped-and-no-live-process-group-members", "never-dispatched"}
            deadline = datetime.fromisoformat(lease["deadlineAt"])
            store.event(task["id"], "fixture_provider_cancel_diagnostic", "Before original provider cancel; observation only", {
                "leaseId": lease_id, "taskId": task["id"], "observedAt": current.isoformat(),
                **last_reasons.get(lease_id, {"runtimeReason": "not-observed", "runtimeReasonObservedAt": None}),
                "deadlineAt": deadline.isoformat(), "deadlineElapsed": current >= deadline,
                "taskCancelRequested": task.get("cancel_requested") is True,
                "taskTerminal": task.get("terminal") is True,
                "nativeStatus": native_status if native_status in allowed_native else "unrecognized",
                "processState": process_status if process_status in allowed_process else "unrecognized",
                "processStoppedProof": observed.get("stoppedProof") is True,
                "stopKind": stop_kind if stop_kind in allowed_stop else None,
                "leaseExecutionStatus": lease.get("executionStatus") if lease.get("executionStatus") in allowed_process else "unrecognized"})
        return await original_provider_cancel(lease_id, owner)
    provider.cancel = diagnostic_provider_cancel

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("X-Fixture-Control", ""), configuration["controlKey"]):
            raise HTTPException(403, "Explicit fixture control required")

    def _facts(request: Request, taskId: str | None = None):
        authenticate(request)
        store, db = state["store"], state["store"].native_db
        count = 0
        if inspect(db.db_engine).has_table(db.job_table_name, schema=db.db_schema):
            table = Table(db.job_table_name, MetaData(), schema=db.db_schema, autoload_with=db.db_engine)
            query = select(func.count()).select_from(table)
            if taskId:
                query = query.where(table.c.session_id == taskId)
            with db.db_engine.connect() as conn:
                count = conn.execute(query).scalar()
        task = store.task(taskId, owner) if taskId else None
        native = db.get_job(task["run_id"]) if task and task.get("run_id") else None
        disk = store.sql("SELECT state FROM af_disk_holds WHERE task_id=:task", task=taskId) if taskId else []
        leases = [row["body"] for row in store.sql("SELECT body FROM af_leases")]
        allocations = store.sql("SELECT * FROM af_process_allocations")
        return {"fixtureOnly": True, "demo": True, "mode": "controlled-process-fixture", "pid": os.getpid(),
            "workspace": str(workspace), "applicationRef": pin(snapshot), "applicationSnapshot": snapshot,
            "materials": materials, "sourceSpecs": _source_specs(materials), "providerCreated": list(created),
            "nativeTickets": count, "tasks": store.tasks(owner), "task": task,
            "nativeStatus": native.get("status") if native else None, "diskHold": disk[0]["state"] if disk else None,
            "plan": store.plan(store.task(taskId, owner)["plan_id"], owner) if taskId else None,
            "leases": leases, "allocationDiagnostics": allocation_diagnostics.snapshot(),
            "providerDiagnostics": provider_observations(leases, allocations), "processMappings": store.sql("SELECT * FROM af_process_runs"),
            "processAllocations": [{"id": row["id"], "owner_id": row["owner_id"], "body": {
                key: row["body"].get(key) for key in ("processPin", "state", "released", "allStopped", "executionStatus", "exitCode")}}
                for row in allocations],
            "custody": custody_observations(store, custody),
            "launchAttemptCount": store.sql("SELECT count(*) AS count FROM af_events WHERE type='fixture_process_launch_attempt'")[0]["count"],
            "disconnectDiagnostics": [row["data"] for row in store.sql(
                "SELECT data FROM af_events WHERE type='fixture_disconnect_response' ORDER BY id LIMIT 100")],
            "cancelDiagnostics": [row["data"] for row in store.sql(
                "SELECT data FROM af_events WHERE type='fixture_provider_cancel_diagnostic' ORDER BY id LIMIT 100")],
            "cancelAttemptCount": store.sql("SELECT count(*) AS count FROM af_events WHERE type='fixture_process_cancel_attempt'")[0]["count"],
            "placements": store.sql("SELECT * FROM af_remote_placements") if role == "origin" else [],
            "handoffs": store.sql("SELECT * FROM af_remote_handoffs") if role == "receiver" else [],
            "bindingProofs": store.sql("SELECT * FROM af_remote_binding_proofs") if role == "receiver" else [],
            "usageLedger": store.usage_ledger.inspect(owner, taskId) if taskId else None,
            "droppedAcknowledgements": controls["droppedAcknowledgements"]}

    @app.app.get("/__fixture/state")
    def facts(request: Request, taskId: str | None = None):
        try:
            return _facts(request, taskId)
        except HTTPException:
            raise
        except Exception as error:
            category = next((name for kind, name in ((OSError, "OSError"), (ValueError, "ValueError"),
                (TypeError, "TypeError"), (KeyError, "KeyError")) if isinstance(error, kind)), "UnexpectedError")
            raise HTTPException(500, {"fixturePhase": "state-snapshot", "errorType": category}) from None

    @app.app.post("/__fixture/control")
    async def control(request: Request):
        authenticate(request)
        body = await request.json()
        if type(body) is not dict or set(body) - {"op", "fault"}:
            raise HTTPException(422, "Unsupported fixture controls")
        op = body.get("op")
        if op == "capacity-probe":
            store = state["store"]
            probe_plan = store.save_plan({"id": str(uuid4()), "ownerId": OTHER_OWNER, "syntheticFixture": True})
            probe_task, _ = store.reserve_task(probe_plan, str(uuid4()))
            try:
                await state["resources"].allocate(OTHER_OWNER, "capacity-probe", probe_task["id"], str(uuid4()),
                    {"cpu": 1, "memoryMb": 128, "diskMb": 1, "seconds": 5})
            except HTTPException as error:
                return {"fixtureOnly": True, "status": error.status_code}
            raise AssertionError("Pool probe unexpectedly allocated")
        if op == "cleanup":
            stopped = True
            for row in state["store"].sql("SELECT id,owner_id FROM af_process_allocations"):
                await provider.cancel(row["id"], row["owner_id"])
                path = custody / row["id"] / "custody.sqlite"
                if path.exists():
                    adapter = BoundedProcessAdapter(path)
                    observed = adapter.inspect(owner_id=row["owner_id"])
                    if observed.get("child") or observed.get("guardian"):
                        observed = await asyncio.to_thread(adapter.wait, owner_id=row["owner_id"], timeout=7)
                        stopped = stopped and observed.get("stoppedProof") is True
            return {"fixtureOnly": True, "allOwnedProcessesStopped": stopped}
        if op == "fault":
            if body.get("fault") not in {None, "exit_after_dispatch", "exit_after_queued_dispatch", "drop_dispatch_ack", "drop_cancel_ack", "disconnect_reads"}:
                raise HTTPException(422, "Unsupported fixture fault")
            if body.get("fault") == "exit_after_queued_dispatch":
                await app.app.state.queue_worker.stop()
            controls["fault"] = body.get("fault")
            controls["disconnectRecorded"] = False
        elif op in {"role-revoke", "role-restore"}:
            state["auth"].authorization.unassign(owner, "fixture-user" if op == "role-revoke" else "fixture-reader")
            state["auth"].authorization.assign(owner, "fixture-reader" if op == "role-revoke" else "fixture-user")
        elif op in {"mapping-remove", "mapping-restore", "mapping-rotate"} and role == "receiver":
            live = state["store"].remote_bindings.mappings
            live.clear()
            if op != "mapping-remove":
                live.update(mappings if op == "mapping-restore" else {key: replace(value, revision="2") for key, value in mappings.items()})
        else:
            raise HTTPException(422, "Unsupported fixture operation")
        return {"fixtureOnly": True, "op": op}

    import uvicorn
    wrapped = DropControlAcknowledgement(app, controls, state["store"], directory / (role + "-fault.json"))
    uvicorn.run(wrapped, host="127.0.0.1", port=settings.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
