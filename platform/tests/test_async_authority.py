"""Deterministic async authority boundaries; synthetic callbacks and no provider I/O."""
import asyncio
from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import patch

from agno.exceptions import ModelProviderError, RunCancelledException
from agno.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput

from agent_factory.execution_bindings import BindingContext, ExecutionBindings
from agent_factory.model_dispatch import DelegatingModel
from agent_factory.openresearch import OpenResearchAdapter, OpenResearchError
from agent_factory.usage_ledger import native_response_usage


class Gate:
    def __init__(self, test, *, at=1, denied=False):
        self.test, self.at, self.denied = test, at, denied
        self.loop_thread = get_ident()
        self.entered, self.release, self.exited = Event(), Event(), Event()
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.test.assertNotEqual(get_ident(), self.loop_thread, "Authority callback blocked the event-loop thread")
        self.calls += 1
        if self.calls == self.at:
            self.entered.set()
            try:
                if not self.release.wait(3):
                    raise AssertionError("Test did not release authority callback")
                if self.denied:
                    raise PermissionError("Synthetic revoked authority")
            finally:
                self.exited.set()

    async def wait(self):
        if not await asyncio.to_thread(self.entered.wait, 2):
            raise AssertionError("Authority callback was not reached")
        # This must execute while the synchronous authority callback is waiting.
        progressed = asyncio.Event()
        asyncio.get_running_loop().call_soon(progressed.set)
        await asyncio.wait_for(progressed.wait(), 1)


class AsyncAuthorityTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, gate, **guards):
        calls, reservations, settlements = [], [], []
        response = ModelResponse(role="assistant", content="synthetic",
            response_usage=MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2))

        async def invoke(*args, **kwargs):
            calls.append(True)
            return response

        async def stream(*args, **kwargs):
            calls.append(True)
            yield response

        def reserve(*args, **kwargs):
            reservations.append(kwargs)
            return "attempt"

        ledger = SimpleNamespace(begin_attempt=reserve,
            evidence_for=lambda plan, value: native_response_usage(value),
            finish_attempt=lambda identity, evidence: settlements.append((identity, evidence)))
        model = SimpleNamespace(invoke=lambda: response, ainvoke=invoke,
            invoke_stream=lambda: iter([response]), ainvoke_stream=stream)
        DelegatingModel._guard_provider_calls(cast(Any, model), gate, ledger=ledger, **guards)
        return model, calls, reservations, settlements

    async def invoke(self, model, streaming):
        if streaming:
            return [value async for value in model.ainvoke_stream([])]
        return await model.ainvoke([])

    async def test_provider_pre_and_post_authority_leave_event_loop_responsive(self):
        for streaming in (False, True):
            for stage in range(1, 4 if streaming else 3):
                with self.subTest(streaming=streaming, stage=stage):
                    gate = Gate(self, at=stage)
                    model, calls, reservations, settlements = self.provider(gate)
                    task = asyncio.create_task(self.invoke(model, streaming))
                    try:
                        await gate.wait()
                        self.assertFalse(task.done())
                        self.assertEqual(len(calls), 0 if stage == 1 else 1)
                        self.assertEqual(len(reservations), 0 if stage == 1 else 1)
                    finally:
                        gate.release.set()
                    await task
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(len(reservations), 1)
                    self.assertEqual(len(settlements), 1)
                    self.assertIsNotNone(settlements[0][1])

    async def test_cancelled_provider_precheck_never_reserves_or_dispatches(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                gate = Gate(self)
                model, calls, reservations, settlements = self.provider(gate)
                task = asyncio.create_task(self.invoke(model, streaming))
                try:
                    await gate.wait()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    gate.release.set()
                    self.assertTrue(await asyncio.to_thread(gate.exited.wait, 2))
                self.assertEqual((calls, reservations, settlements), ([], [], []))

    async def test_revoked_provider_precheck_never_reserves_or_dispatches(self):
        for streaming in (False, True):
            gate = Gate(self, denied=True)
            model, calls, reservations, settlements = self.provider(gate)
            task = asyncio.create_task(self.invoke(model, streaming))
            try:
                await gate.wait()
            finally:
                gate.release.set()
            with self.assertRaises(PermissionError):
                await task
            self.assertEqual((calls, reservations, settlements), ([], [], []))

    async def test_revoked_provider_postcheck_preserves_incurred_usage(self):
        for streaming in (False, True):
            gate = Gate(self, at=2, denied=True)
            model, calls, reservations, settlements = self.provider(gate)
            task = asyncio.create_task(self.invoke(model, streaming))
            try:
                await gate.wait()
            finally:
                gate.release.set()
            with self.assertRaises(PermissionError):
                await task
            self.assertEqual((len(calls), len(reservations), len(settlements)), (1, 1, 1))
            self.assertIsNotNone(settlements[0][1])

    async def test_native_async_selection_cancellation_never_dispatches(self):
        for streaming in (False, True):
            gate, calls = Gate(self), []

            async def response(*args, **kwargs):
                calls.append(True)
                return ModelResponse()

            async def stream(*args, **kwargs):
                calls.append(True)
                yield ModelResponse()

            completed = []

            def prepare(*args, **kwargs):
                gate()
                return ("synthetic-preparation",)

            def complete(*args, **kwargs):
                completed.append(True)
                return SimpleNamespace(aresponse=response, aresponse_stream=stream)

            model = DelegatingModel(cast(Any, SimpleNamespace()))
            cast(Any, model)._prepare_selection = prepare
            cast(Any, model)._complete_selection = complete

            async def run():
                if streaming:
                    return [value async for value in model.aresponse_stream()]
                return await model.aresponse()

            task = asyncio.create_task(run())
            try:
                await gate.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                gate.release.set()
                self.assertTrue(await asyncio.to_thread(gate.exited.wait, 2))
            self.assertEqual(calls, [])
            self.assertEqual(completed, [])

    async def test_native_model_factory_and_metadata_publication_stay_on_loop(self):
        for streaming in (False, True):
            gate = Gate(self)
            loop = asyncio.get_running_loop()
            factories, publications = [], []
            output = RunOutput(run_id="run", session_id="task", user_id="owner")
            before = output.to_dict()
            plan = {"id": "plan"}
            task_row = {"id": "task", "run_id": "run", "plan_id": "plan", "owner_id": "owner", "request_id": "request"}

            async def response(*args, **kwargs):
                return ModelResponse(content="synthetic")

            async def stream(*args, **kwargs):
                yield ModelResponse(content="synthetic")

            def factory(*args):
                # Real plugin factories may create loop-owned Futures/clients.
                self.assertIs(asyncio.get_running_loop(), loop)
                factories.append(loop.create_future())
                return SimpleNamespace(id="synthetic-model", provider="synthetic-provider",
                    invoke=lambda: None, ainvoke=response, invoke_stream=lambda: iter([]),
                    ainvoke_stream=stream, aresponse=response, aresponse_stream=stream)

            def publish(*args):
                self.assertIs(asyncio.get_running_loop(), loop)
                publications.append(True)

            store = SimpleNamespace(task=lambda *args: task_row, resolve_run=lambda *args: plan,
                cancellation_requested=lambda *args: False, has_failures=lambda *args: False,
                require_plan_execution=gate, event=publish)
            bindings = SimpleNamespace(store=store, recheck=lambda *args: None,
                model_from_binding=factory, manifest=lambda *args: {"sha256": "synthetic"},
                resolve=lambda selected_plan, context: {"model": BindingContext(None, store, selected_plan, context, {})})
            model = DelegatingModel(cast(Any, bindings))

            async def run():
                if streaming:
                    return [value async for value in model.aresponse_stream(run_response=output)]
                return await model.aresponse(run_response=output)

            task = asyncio.create_task(run())
            try:
                await gate.wait()
                self.assertEqual(factories, [])
                self.assertEqual(output.to_dict(), before)
            finally:
                gate.release.set()
            await task
            self.assertEqual(len(factories), 1)
            self.assertEqual(publications, [True])
            self.assertEqual((output.model, output.model_provider), ("synthetic-model", "synthetic-provider"))

    async def test_async_tool_precheck_cancellation_and_revocation(self):
        for streaming in (False, True):
            for cancel in (False, True):
                gate, calls = Gate(self, denied=not cancel), []
                context = SimpleNamespace(user_id="synthetic", session_id="task", run_id="run")
                binding = SimpleNamespace(run_context=context, plan={}, spec={"toolName": "synthetic"})
                services = SimpleNamespace(store=SimpleNamespace(require_plan_execution=gate,
                    authorize_tool=lambda *args: None, cancellation_requested=lambda *args: False,
                    has_failures=lambda *args: False), recheck=lambda *args: None)

                async def tool():
                    calls.append(True)
                    return "synthetic"

                async def stream():
                    calls.append(True)
                    yield "synthetic"

                guarded = cast(Any, ExecutionBindings._guard_tool(cast(Any, services), stream if streaming else tool, cast(Any, binding)))

                async def run():
                    if streaming:
                        return [value async for value in guarded()]
                    return await guarded()

                task = asyncio.create_task(run())
                try:
                    await gate.wait()
                    if cancel:
                        task.cancel()
                    else:
                        gate.release.set()
                    with self.assertRaises(asyncio.CancelledError if cancel else PermissionError):
                        await task
                finally:
                    gate.release.set()
                    self.assertTrue(await asyncio.to_thread(gate.exited.wait, 2))
                self.assertEqual(calls, [])

    async def test_loop_local_guard_denial_after_thread_precheck_never_dispatches(self):
        for streaming in (False, True):
            gate = Gate(self)
            loop_thread, local_calls = get_ident(), []

            def local_current():
                self.assertEqual(get_ident(), loop_thread)
                local_calls.append(True)
                raise PermissionError("Synthetic cancellation committed during worker precheck")

            model, calls, reservations, settlements = self.provider(gate, local_current=local_current)
            task = asyncio.create_task(self.invoke(model, streaming))
            try:
                await gate.wait()
                self.assertEqual(local_calls, [])
            finally:
                gate.release.set()
            with self.assertRaises(PermissionError):
                await task
            self.assertEqual(local_calls, [True])
            self.assertEqual((calls, reservations, settlements), ([], [], []))

    async def test_tool_cancellation_committed_during_thread_precheck_denies_entrypoint(self):
        for streaming in (False, True):
            gate, calls, cancelled = Gate(self), [], []
            context = SimpleNamespace(user_id="synthetic", session_id="task", run_id="run")
            binding = SimpleNamespace(run_context=context, plan={}, spec={"toolName": "synthetic"})
            services = SimpleNamespace(store=SimpleNamespace(require_plan_execution=gate,
                authorize_tool=lambda *args: None, cancellation_requested=lambda *args: bool(cancelled),
                has_failures=lambda *args: False), recheck=lambda *args: None)

            async def tool():
                calls.append(True)
                return "synthetic"

            async def stream():
                calls.append(True)
                yield "synthetic"

            guarded = cast(Any, ExecutionBindings._guard_tool(cast(Any, services), stream if streaming else tool, cast(Any, binding)))

            async def run():
                if streaming:
                    return [value async for value in guarded()]
                return await guarded()

            task = asyncio.create_task(run())
            try:
                await gate.wait()
                cancelled.append(True)
            finally:
                gate.release.set()
            with self.assertRaises(RunCancelledException):
                await task
            self.assertEqual(calls, [])

    async def test_openresearch_sync_authorizer_can_return_loop_owned_future(self):
        loop = asyncio.get_running_loop()
        calls = []

        def authorize(operation):
            self.assertIs(asyncio.get_running_loop(), loop)
            calls.append(operation)
            result = loop.create_future()
            loop.call_soon(result.set_result, False)
            return result

        # Generic callback contract remains loop-local, including returned Future.
        # No filesystem/environment access or ORX process is needed here.
        adapter = SimpleNamespace(authorize=authorize)
        with self.assertRaises(OpenResearchError):
            await OpenResearchAdapter._allow(cast(Any, adapter), "inspect")
        self.assertEqual(calls, ["inspect"])

    async def test_cancelled_pause_preparation_never_publishes_or_mutates_native_output(self):
        for streaming in (False, True):
            gate = Gate(self)
            response = RunOutput(run_id="synthetic-run", session_id="synthetic-task", user_id="synthetic-owner")
            before = response.to_dict()
            messages = []
            model = DelegatingModel(cast(Any, SimpleNamespace(store=SimpleNamespace())))

            def prepare(*args):
                gate()
                return {"controlId": "synthetic-control"}

            with patch("agent_factory.inference_wait.prepare_pause", side_effect=prepare), \
                    patch("agent_factory.inference_wait.publish_pause") as publish:
                task = asyncio.create_task(model._apause((), {"run_response": response, "messages": messages},
                    ModelProviderError("synthetic", status_code=503), streaming=streaming))
                try:
                    await gate.wait()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    gate.release.set()
                    self.assertTrue(await asyncio.to_thread(gate.exited.wait, 2))
                await asyncio.sleep(0)
                publish.assert_not_called()
                self.assertEqual(response.to_dict(), before)
                self.assertEqual(messages, [])
