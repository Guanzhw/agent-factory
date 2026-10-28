"""Run-bound dispatch through Agno's public Model response methods.

Agno 3.1.0 passes native RunOutput to response/aresponse and their stream variants.
The stable executor model selects a fresh operator adapter from that identity,
never from prompt text and never by changing shared Agent.model. The selected
native Model retains its own provider formatting and native tool/HITL loop.
"""
from __future__ import annotations

import asyncio
from typing import Any

from agno.exceptions import InputCheckError, RunCancelledException, ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.run import RunContext
from agno.run.agent import RunOutput

from .execution_bindings import BindingContext, ExecutionBindings
from .billing_mode import ledger_for_plan


class DelegatingModel(Model):
    def __init__(self, bindings: ExecutionBindings):
        super().__init__(id="factory-material-dispatch-v1", name="Immutable material model dispatch", provider="factory-registered")
        self.bindings = bindings

    def __deepcopy__(self, memo):
        # This dispatcher holds trusted services, not a mutable per-run model.
        return self

    def _prepare_selection(self, arguments, kwargs, *, streaming=False):
        response = kwargs.get("run_response")
        if response is None and len(arguments) > (6 if streaming else 5):
            response = arguments[6 if streaming else 5]
        if not isinstance(response, RunOutput) or not response.run_id or not response.session_id or not response.user_id:
            raise InputCheckError("A trusted native run identity is required for model dispatch")
        store = self.bindings.store
        task = store.task(response.session_id, response.user_id)
        if task["run_id"] != response.run_id:
            raise InputCheckError("Native response identity differs from its original task binding")
        state = response.session_state or {}
        envelope = {"plan_ref": task["plan_id"], "user_id": task["owner_id"],
                    "task_id": task["id"], "request_id": task["request_id"]}
        if state.get("factory_envelope", envelope) != envelope:
            raise InputCheckError("Native response envelope differs from its immutable task binding")
        context = RunContext(run_id=response.run_id, session_id=response.session_id, user_id=response.user_id,
                             session_state={**state, "factory_envelope": envelope})
        plan = store.resolve_run(context)

        def local_current():
            if store.cancellation_requested(response.run_id):
                raise RunCancelledException("Factory cancellation requested before model invocation")

        def current():
            local_current()
            latest = store.resolve_run(context)
            self._check_selected_plan(latest, context)
            store.require_plan_execution(context.user_id, latest, run_context=context)

        current()
        self._check_task_wait(task)
        binding = self.bindings.resolve(plan, context)["model"]
        if not isinstance(binding, BindingContext):
            raise InputCheckError("Trusted model binding is required")
        return response, plan, context, current, local_current, binding

    def _complete_selection(self, prepared):
        response, plan, context, current, local_current, binding = prepared
        local_current()
        store = self.bindings.store
        model = self.bindings.model_from_binding(binding)
        # Only this fresh per-response adapter is wrapped. Shared Agent/model
        # state is unchanged, and every provider retry/tool-loop call rechecks.
        self._guard_provider_calls(model, current, local_current=local_current,
            ledger=ledger_for_plan(store, plan), plan=plan, context=context,
            before_model=lambda args, kwargs: self._before_model(context, args, kwargs),
            on_recovered=lambda: self._model_recovered(context),
            on_protocol_rejected=lambda: store.reject_model_protocol(context))
        response.model = model.id
        response.model_provider = model.provider
        store.event(response.run_id, "model_binding_selected", "Exact trusted model adapter selected for this native response",
                    {"modelId": model.id, "provider": model.provider,
                     "executionBindingsSha256": self.bindings.manifest(plan)["sha256"], "createsExecution": False})
        return model

    def _select(self, arguments, kwargs, *, streaming=False):
        return self._complete_selection(self._prepare_selection(arguments, kwargs, streaming=streaming))

    async def _aselect(self, arguments, kwargs, *, streaming=False):
        prepared = await asyncio.to_thread(self._prepare_selection, arguments, kwargs, streaming=streaming)
        return self._complete_selection(prepared)

    def _before_model(self, context, arguments, kwargs):
        """Let the exact application owner amend this provider request in place."""
        store = self.bindings.store
        runtime = getattr(store, "application_runtime", None)
        if not runtime:
            return
        task = store.task(context.session_id, context.user_id)
        callback = runtime.control(task, "before_model")
        if callback is None:
            return
        messages = kwargs.get("messages") if "messages" in kwargs else arguments[0] if arguments else None
        if not isinstance(messages, list) or not all(isinstance(message, Message) for message in messages):
            raise InputCheckError("Application model control requires the native request message list")
        callback(context, messages)

    @staticmethod
    def _guard_provider_calls(model: Model, current, *, ledger=None, plan=None, context=None, local_current=None, before_model=None, on_recovered=None, on_protocol_rejected=None):
        invoke, ainvoke, invoke_stream, ainvoke_stream = model.invoke, model.ainvoke, model.invoke_stream, model.ainvoke_stream

        def reserve(args, kwargs, *, streaming=False):
            current()
            if before_model is not None:
                before_model(args, kwargs)
            if local_current is not None:
                local_current()
            return ledger.begin_attempt(context, plan, model, streaming=streaming or getattr(model, "factory_wire_stream", False) is True,
                arguments=args, keyword_arguments=kwargs) if ledger is not None else None

        def finish(identity, value):
            if ledger is not None:
                ledger.finish_attempt(identity, ledger.evidence_for(plan, value))

        def reject_protocol(error):
            if (on_protocol_rejected is not None and isinstance(error, ModelProviderError)
                    and str(error) == 'PERSONAL_MODEL_TOOL_NOT_DECLARED'):
                on_protocol_rejected()

        def recovered():
            if on_recovered is not None:
                on_recovered()

        def guarded(*args, **kwargs):
            identity = reserve(args, kwargs)
            try:
                response = invoke(*args, **kwargs)
            except BaseException as error:
                try:
                    finish(identity, error)
                finally:
                    reject_protocol(error)
                raise
            # A later permission/cancellation check cannot erase incurred usage.
            finish(identity, response)
            current()
            recovered()
            return response

        async def aguard(*args, **kwargs):
            await asyncio.to_thread(current)
            if before_model is not None:
                await asyncio.to_thread(before_model, args, kwargs)
            if local_current is not None:
                local_current()
            identity = ledger.begin_attempt(context, plan, model, streaming=getattr(model, "factory_wire_stream", False) is True, arguments=args, keyword_arguments=kwargs) if ledger is not None else None
            try:
                response = await ainvoke(*args, **kwargs)
            except BaseException as error:
                try:
                    finish(identity, error)
                finally:
                    await asyncio.to_thread(reject_protocol, error)
                raise
            finish(identity, response)
            await asyncio.to_thread(current)
            if local_current is not None:
                local_current()
            recovered()
            return response

        def stream(*args, **kwargs):
            identity = reserve(args, kwargs, streaming=True)
            values, evidence = None, None
            try:
                values = invoke_stream(*args, **kwargs)
                for value in values:
                    if ledger is not None:
                        authoritative = ledger.evidence_for(plan, value)
                        if authoritative is not None:
                            evidence = authoritative
                    current()
                    yield value
                current()
                recovered()
            except BaseException as error:
                try:
                    if ledger is not None:
                        authoritative = ledger.evidence_for(plan, error)
                        if authoritative is not None:
                            evidence = authoritative
                finally:
                    reject_protocol(error)
                raise
            finally:
                # No final authoritative usage => UNKNOWN with the whole hold,
                # including GeneratorExit, cancellation and partial streams.
                try:
                    if ledger is not None:
                        ledger.finish_attempt(identity, evidence)
                finally:
                    close = getattr(values, "close", None)
                    if close is not None:
                        close()

        async def astream(*args, **kwargs):
            await asyncio.to_thread(current)
            if before_model is not None:
                await asyncio.to_thread(before_model, args, kwargs)
            if local_current is not None:
                local_current()
            identity = ledger.begin_attempt(context, plan, model, streaming=True, arguments=args, keyword_arguments=kwargs) if ledger is not None else None
            values, evidence = None, None
            try:
                values = ainvoke_stream(*args, **kwargs)
                async for value in values:
                    if ledger is not None:
                        authoritative = ledger.evidence_for(plan, value)
                        if authoritative is not None:
                            evidence = authoritative
                    await asyncio.to_thread(current)
                    if local_current is not None:
                        local_current()
                    yield value
                await asyncio.to_thread(current)
                if local_current is not None:
                    local_current()
                recovered()
            except BaseException as error:
                try:
                    if ledger is not None:
                        authoritative = ledger.evidence_for(plan, error)
                        if authoritative is not None:
                            evidence = authoritative
                finally:
                    await asyncio.to_thread(reject_protocol, error)
                raise
            finally:
                try:
                    if ledger is not None:
                        ledger.finish_attempt(identity, evidence)
                finally:
                    close = getattr(values, "aclose", None)
                    if close is not None:
                        await close()
        model.invoke, model.ainvoke = guarded, aguard
        model.invoke_stream, model.ainvoke_stream = stream, astream

    def response(self, *args, **kwargs):
        try:
            result = self._select(args, kwargs).response(*args, **kwargs)
            self._recovered(args, kwargs)
            return result
        except ModelProviderError as error:
            result = self._pause(args, kwargs, error)
            if result is None:
                raise
            return result

    async def aresponse(self, *args, **kwargs):
        try:
            model = await self._aselect(args, kwargs)
            result = await model.aresponse(*args, **kwargs)
            self._recovered(args, kwargs)
            return result
        except ModelProviderError as error:
            result = await self._apause(args, kwargs, error)
            if result is None:
                raise
            return result

    def response_stream(self, *args, **kwargs):
        try:
            yield from self._select(args, kwargs, streaming=True).response_stream(*args, **kwargs)
            self._recovered(args, kwargs, streaming=True)
        except ModelProviderError as error:
            result = self._pause(args, kwargs, error, streaming=True)
            if result is None:
                raise
            yield result

    async def aresponse_stream(self, *args, **kwargs):
        try:
            model = await self._aselect(args, kwargs, streaming=True)
            async for value in model.aresponse_stream(*args, **kwargs):
                yield value
            self._recovered(args, kwargs, streaming=True)
        except ModelProviderError as error:
            result = await self._apause(args, kwargs, error, streaming=True)
            if result is None:
                raise
            yield result

    async def _apause(self, arguments, kwargs, error, *, streaming=False):
        return None

    def _pause(self, arguments, kwargs, error, *, streaming=False):
        return None

    def _recovered(self, arguments, kwargs, *, streaming=False):
        """Optional adapter acknowledgement after the native response completes."""

    def _check_selected_plan(self, plan, context):
        """Application checks are installed by explicit trusted assembly."""

    def _check_task_wait(self, task):
        """The core does not invent a recovery policy for provider failures."""

    def _model_recovered(self, context):
        """Optional existing-wait acknowledgement; never dispatches work."""

    def invoke(self, *args, **kwargs):
        raise InputCheckError("Use native response dispatch with its trusted run identity")

    async def ainvoke(self, *args, **kwargs):
        raise InputCheckError("Use native response dispatch with its trusted run identity")

    def invoke_stream(self, *args, **kwargs):
        raise InputCheckError("Use native response dispatch with its trusted run identity")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args, **kwargs):
        raise InputCheckError("Use native response dispatch with its trusted run identity")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs):
        raise InputCheckError("Provider parsing belongs to the selected native Model")

    def _parse_provider_response_delta(self, response: Any):
        raise InputCheckError("Provider parsing belongs to the selected native Model")
