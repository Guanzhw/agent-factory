#!/usr/bin/env python3
"""One fixed 12-case prefix plus one readiness case. Diagnostic, not benchmark.
No parameters, SQL text, return values, credentials or object reprs are recorded.
The original deadlines/assertions are unchanged. No retry. Output is exclusive.
"""

import argparse
import asyncio
from contextlib import ExitStack, asynccontextmanager
from contextvars import ContextVar
import gc
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
import unittest
import weakref
from unittest.mock import patch

CASES = (
    "test_credential_vault_postgres.CredentialVaultPostgresTests.test_ciphertext_restart_rotation_revoke_and_cas",
    "test_department_admission_postgres.DepartmentAdmissionPostgresTests.test_member_runs_multiple_applications_and_workflow_without_admin_decision",
    "test_department_publication.DepartmentPublicationPostgresTests.test_http_member_can_publish_and_archive_own_resource",
    "test_department_publication.DepartmentPublicationPostgresTests.test_http_own_private_archive_preserves_owner_visibility",
    "test_environment_bindings_postgres.EnvironmentBindingPostgresTests.test_explicit_generation_restore_after_restart_rotation_and_lost_ack_never_selects_default",
    "test_model_command_recovery_postgres.ModelCommandRecoveryPostgresTests.test_default_replay_recovers_original_receipt_after_another_default_command",
    "test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests.test_credential_resolution_failure_releases_capacity_without_mcp_io",
    "test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests.test_delete_not_supported_releases_predispatch_failure_capacity",
    "test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests.test_http_authentication_rejection_releases_capacity_without_tool_dispatch",
    "test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests.test_schema_failure_releases_capacity_and_keeps_original_receipt_after_restart",
    "test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests.test_sdk_exit_failure_keeps_capacity_and_never_redispatches",
    "test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests.test_slow_delete_releases_predispatch_failure_after_local_cleanup",
    "test_personal_mcp.PersonalMCPTests.test_slow_delete_cannot_extend_cancellation_teardown_indefinitely",
)
TARGETS = {CASES[8], CASES[11], CASES[12]}
CTX = ContextVar("probe_identity", default=None)
KIND = ContextVar("probe_callback_kind", default=None)
THREAD = threading.local()


class Recorder:
    def __init__(self, output):
        self.file = output.open("x", encoding="utf8")
        self.lock = threading.RLock()
        self.started = time.monotonic_ns()
        self.case = None
        self.active = False
        self.serial = 0
        self.event_count = 0
        self.dropped = 0
        self.loops = {}  # id -> weakref only
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()

    def number(self):
        with self.lock:
            self.serial += 1
            return self.serial

    def emit(self, event, **fields):
        with self.lock:
            if self.file.closed:
                return
            self.event_count += 1
            if self.event_count > 100000 and event not in {
                "result",
                "failure_before_teardown",
            }:
                self.dropped += 1
                return
            self.file.write(
                json.dumps(
                    {
                        "event": event,
                        "atNs": time.monotonic_ns() - self.started,
                        "case": self.case,
                        "thread": threading.get_ident(),
                        **fields,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            self.file.flush()

    def loop(self):
        loop = asyncio.get_running_loop()
        with self.lock:
            self.loops[id(loop)] = weakref.ref(loop)

    def sample(self):
        while not self.stop.wait(0.5):
            if not self.active:
                continue
            data = {}
            for name in ("cpu.stat", "memory.events"):
                try:
                    data[name] = {
                        k: int(v)
                        for k, v in (
                            line.split()
                            for line in Path("/sys/fs/cgroup", name)
                            .read_text()
                            .splitlines()
                        )
                    }
                except (OSError, ValueError):
                    data[name] = None
            self.emit(
                "resource_sample", processCpuNs=time.process_time_ns(), counters=data
            )
            with self.lock:
                loops = list(self.loops.items())
            for identifier, ref in loops:
                loop = ref()
                if loop is None or loop.is_closed():
                    continue
                scheduled = time.monotonic_ns()
                try:
                    from functools import partial

                    loop.call_soon_threadsafe(
                        partial(
                            self.emit,
                            "loop_heartbeat",
                            loop=identifier,
                            scheduledNs=scheduled - self.started,
                        )
                    )
                except RuntimeError:
                    pass
                finally:
                    del loop

    def failure(self, phase, error):
        stacks = []
        for ident, frame in sys._current_frames().items():
            frames = []
            while frame is not None and len(frames) < 20:
                frames.append(
                    [
                        Path(frame.f_code.co_filename).name,
                        frame.f_code.co_name,
                        frame.f_lineno,
                    ]
                )
                frame = frame.f_back
            stacks.append({"thread": ident, "frames": frames})
        self.emit(
            "failure_before_teardown",
            phase=phase,
            errorType=type(error).__name__,
            stacks=stacks,
        )

    def close(self):
        self.stop.set()
        self.thread.join(2)
        self.file.close()


def identity(state):
    invocation = state.invocation
    context = getattr(invocation, "run_context", None)
    return {
        "runId": getattr(context, "run_id", None),
        "taskId": getattr(context, "session_id", None),
        "callId": getattr(invocation, "call_id", None),
    }


def install(rec, stack):
    import httpx2
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from sqlalchemy.pool import QueuePool
    from agno.os.job_queue import QueueWorker
    from agno.run import concurrency
    from agent_factory import personal_mcp as mcp
    import test_personal_mcp_capacity_postgres as fixture

    def wrap_sync(cls, name, phase):
        original = getattr(cls, name)

        def wrapper(self, *args, **kwargs):
            if not rec.active:
                return original(self, *args, **kwargs)
            start = time.monotonic_ns()
            generation = rec.number() if phase == "generation_start" else None
            rec.emit(phase + "_begin", objectId=id(self), generation=generation)
            try:
                return original(self, *args, **kwargs)
            finally:
                rec.emit(
                    phase + "_end",
                    objectId=id(self),
                    durationNs=time.monotonic_ns() - start,
                    generation=generation,
                    storeId=id(getattr(self, "store", None))
                    if phase.startswith("generation_")
                    else None,
                    engineId=id(getattr(getattr(self, "store", None), "engine", None))
                    if phase.startswith("generation_")
                    else None,
                    appId=id(getattr(self, "app", None))
                    if phase.startswith("generation_")
                    else None,
                )

        stack.enter_context(patch.object(cls, name, wrapper))

    wrap_sync(httpx2.AsyncHTTPTransport, "__init__", "transport_construct")
    wrap_sync(fixture.PersonalMCPCapacityPostgresTests, "start", "generation_start")
    wrap_sync(fixture.PersonalMCPCapacityPostgresTests, "stop", "generation_stop")
    wrap_sync(Engine, "dispose", "engine_dispose")

    original_checked = mcp._InvocationState.checked_callback

    async def checked(state, callback):
        if not rec.active:
            return await original_checked(state, callback)
        rec.loop()
        fields = {
            **identity(state),
            "case": rec.case,
            "callback": rec.number(),
            "kind": KIND.get()
            or (
                "authorize"
                if callback is state.invocation.check_authorized
                else "credential"
            ),
        }
        rec.emit("callback_schedule", **fields)

        def call():
            previous = getattr(THREAD, "metrics", None)
            metrics = {
                "sqlCount": 0,
                "sqlNs": 0,
                "sqlMaxNs": 0,
                "poolCount": 0,
                "poolNs": 0,
                "poolMaxNs": 0,
                "tables": {},
            }
            THREAD.metrics = metrics
            wall, cpu = time.monotonic_ns(), time.thread_time_ns()
            rec.emit("callback_thread_enter", **fields)
            try:
                return callback()
            finally:
                rec.emit(
                    "callback_thread_exit",
                    **fields,
                    wallNs=time.monotonic_ns() - wall,
                    threadCpuNs=time.thread_time_ns() - cpu,
                    **metrics,
                )
                THREAD.metrics = previous

        outcome = "returned"
        try:
            return await original_checked(state, call)
        except BaseException as error:
            outcome = type(error).__name__
            raise
        finally:
            rec.emit("callback_await_exit", **fields, outcome=outcome)

    stack.enter_context(patch.object(mcp._InvocationState, "checked_callback", checked))

    ring_checked = fixture.MCPPhaseRing.checked

    async def checked_ring(self, original, state, callback):
        token = KIND.set(
            "authorize"
            if callback is state.invocation.check_authorized
            else "credential"
        )
        try:
            return await ring_checked(self, original, state, callback)
        finally:
            KIND.reset(token)

    stack.enter_context(patch.object(fixture.MCPPhaseRing, "checked", checked_ring))
    stack.enter_context(
        patch.object(
            fixture.MCPPhaseRing,
            "native_identity",
            staticmethod(
                lambda row: (
                    row["id"],
                    row.get("status"),
                    row.get("attempt"),
                    row.get("locked_by"),
                )
            ),
        )
    )

    execute = QueueWorker._execute_claimed

    async def execute_claimed(worker, job):
        if not rec.active:
            return await execute(worker, job)
        rec.loop()
        fields = {
            "runId": job["id"],
            "taskId": job.get("session_id"),
            "attempt": job.get("attempt"),
            "lockedBy": job.get("locked_by"),
            "workerId": worker.worker_id,
        }
        rec.emit("claim_enter", **fields)
        try:
            return await execute(worker, job)
        finally:
            rec.emit("claim_exit", **fields)

    stack.enter_context(patch.object(QueueWorker, "_execute_claimed", execute_claimed))
    slot = concurrency.background_run_slot

    @asynccontextmanager
    async def slot_scope(*args, **kwargs):
        active = rec.active
        run = kwargs.get("run_id") or (
            args[0] if args and isinstance(args[0], str) else None
        )
        if active:
            rec.loop()
            rec.emit("slot_wait", runId=run)
        try:
            async with slot(*args, **kwargs) as value:
                if active:
                    rec.emit("slot_enter", runId=run)
                yield value
        finally:
            if active:
                rec.emit("slot_exit", runId=run)

    stack.enter_context(patch.object(concurrency, "background_run_slot", slot_scope))

    for method in ("_run", "_call"):
        original = getattr(mcp.MCPToolAdapter, method)

        def make(original, phase):
            async def wrapped(self, *args, **kwargs):
                if not rec.active:
                    return await original(self, *args, **kwargs)
                state = args[0] if phase == "_run" else args[1]
                fields = identity(state)
                rec.loop()
                rec.emit(phase + "_enter", **fields)
                token = CTX.set(fields)
                try:
                    return await original(self, *args, **kwargs)
                finally:
                    rec.emit(phase + "_exit", **fields)
                    CTX.reset(token)

            return wrapped

        stack.enter_context(
            patch.object(mcp.MCPToolAdapter, method, make(original, method))
        )

    invoke = mcp.MCPToolAdapter.invoke

    async def invocation(self, item):
        if not rec.active:
            return await invoke(self, item)
        context = getattr(item, "run_context", None)
        fields = {
            "case": rec.case,
            "runId": getattr(context, "run_id", None),
            "taskId": getattr(context, "session_id", None),
            "callId": getattr(item, "call_id", None),
        }
        rec.loop()
        rec.emit("invocation_enter", **fields)
        outcome = "completed"
        stopped = None
        try:
            return await invoke(self, item)
        except BaseException as error:
            outcome = getattr(error, "outcome", type(error).__name__)
            stopped = getattr(error, "stopped", None)
            raise
        finally:
            rec.emit("invocation_exit", **fields, outcome=outcome, stopped=stopped)

    stack.enter_context(patch.object(mcp.MCPToolAdapter, "invoke", invocation))

    transport = httpx2.AsyncHTTPTransport.handle_async_request

    async def http_request(self, request):
        active = rec.active
        if active:
            rec.loop()
            rec.emit("http_method_enter", method=request.method, identity=CTX.get())
        try:
            return await transport(self, request)
        finally:
            if active:
                rec.emit("http_method_exit", method=request.method, identity=CTX.get())

    stack.enter_context(
        patch.object(httpx2.AsyncHTTPTransport, "handle_async_request", http_request)
    )

    def before(conn, cursor, statement, parameters, context, executemany):
        metrics = getattr(THREAD, "metrics", None)
        if metrics is not None:
            context._mcp_probe_start = time.monotonic_ns()
            # Only statically shaped Factory table names; no SQL or parameters.
            names = set(re.findall(r"\baf_[a-z_]+\b", statement))
            for table in names or {"OTHER"}:
                metrics["tables"][table] = metrics["tables"].get(table, 0) + 1

    def after(conn, cursor, statement, parameters, context, executemany):
        metrics = getattr(THREAD, "metrics", None)
        start = getattr(context, "_mcp_probe_start", None)
        if metrics is not None and start is not None:
            duration = time.monotonic_ns() - start
            metrics["sqlCount"] += 1
            metrics["sqlNs"] += duration
            metrics["sqlMaxNs"] = max(metrics["sqlMaxNs"], duration)

    event.listen(Engine, "before_cursor_execute", before)
    event.listen(Engine, "after_cursor_execute", after)
    stack.callback(event.remove, Engine, "before_cursor_execute", before)
    stack.callback(event.remove, Engine, "after_cursor_execute", after)
    acquire = QueuePool._do_get

    def pool_get(self):
        start = time.monotonic_ns()
        try:
            return acquire(self)
        finally:
            metrics = getattr(THREAD, "metrics", None)
            if metrics is not None:
                duration = time.monotonic_ns() - start
                metrics["poolCount"] += 1
                metrics["poolNs"] += duration
                metrics["poolMaxNs"] = max(metrics["poolMaxNs"], duration)

    stack.enter_context(patch.object(QueuePool, "_do_get", pool_get))

    def collection(phase, info):
        if rec.active:
            rec.emit(
                "gc_" + phase,
                generation=info["generation"],
                collected=info.get("collected"),
                threadCpuNs=time.thread_time_ns(),
            )

    gc.callbacks.append(collection)
    stack.callback(gc.callbacks.remove, collection)

    # Hooks execute inside unittest before teardown; traceback/locals never saved.
    for cls, name in [
        (cls, name)
        for cls in (unittest.TestCase, unittest.IsolatedAsyncioTestCase)
        for name in ("_callSetUp", "_callTestMethod", "_callTearDown")
    ]:
        original = getattr(cls, name)

        def make_failure(original, phase):
            def guarded(self, *args, **kwargs):
                try:
                    return original(self, *args, **kwargs)
                except BaseException as error:
                    if rec.active:
                        rec.failure(phase, error)
                    raise

            return guarded

        stack.enter_context(patch.object(cls, name, make_failure(original, name)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    sys.path[:0] = [
        str(repo / "platform/tests"),
        str(repo / "platform"),
        str(repo / "apps/research"),
        str(repo / "apps/research/tests/python"),
    ]
    summary_path = args.output.with_suffix(".summary.json")
    if (
        args.output.exists()
        or summary_path.exists()
        or args.output.name == "recorder.json"
    ):
        parser.error("Output and summary must be new files; recorder.json is reserved")
    suite = unittest.defaultTestLoader.loadTestsFromNames(CASES)
    if unittest.defaultTestLoader.errors:
        raise RuntimeError("Fixed case collection failed; nothing executed")
    rec = Recorder(args.output)

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            rec.case, rec.active = test.id(), test.id() in TARGETS
            rec.emit("test_start", instrumented=rec.active)
            super().startTest(test)

        def stopTest(self, test):
            rec.emit("test_stop")
            rec.active = False
            super().stopTest(test)

    try:
        rec.emit(
            "selection",
            orderedIds=list(CASES),
            count=13,
            originalPrefixCount=12,
            addedHypothesis="initial readiness: transport construction vs callback vs protocol",
            probeSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        )
        with ExitStack() as stack:
            install(rec, stack)
            result = unittest.TextTestRunner(
                resultclass=Result, verbosity=2, failfast=True
            ).run(suite)
        summary = {
            "testsRun": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "success": result.wasSuccessful()
            and not result.skipped
            and result.testsRun == 13,
            "plannedCount": 13,
            "failedIds": [test.id() for test, _ in result.failures + result.errors],
            "observerOverhead": True,
            "retryCount": 0,
            "eventsDropped": rec.dropped,
        }
        rec.emit("result", **summary)
        with summary_path.open("x") as stream:
            json.dump(summary, stream, indent=2)
        return 0 if summary["success"] else 1
    finally:
        rec.close()


if __name__ == "__main__":
    raise SystemExit(main())
