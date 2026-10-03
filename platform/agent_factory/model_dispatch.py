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
from agno.run import RunContext
from agno.run.agent import RunOutput

from .execution_bindings import BindingContext, ExecutionBindings


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
            from .go_development import is_go_plan
            if is_go_plan(latest) and store.has_failures(context.session_id):
                raise InputCheckError("GO_TASK_STOPPED: prior development failure denies replay")
            store.require_plan_execution(context.user_id, latest, run_context=context)
            self.bindings.recheck(latest, context)

        current()
        from .inference_wait import read as read_wait, observe as check_wait
        waiting = read_wait(store, task["id"]) if getattr(store, "usage_ledger", None) is not None else None
        if waiting and waiting["state"] in {"WAITING", "RESUMING"}:
            check_wait(store, task, waiting)
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
            ledger=getattr(store, "usage_ledger", None), plan=plan, context=context)
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

    @staticmethod
    def _guard_provider_calls(model: Model, current, *, ledger=None, plan=None, context=None, local_current=None):
        invoke, ainvoke, invoke_stream, ainvoke_stream = model.invoke, model.ainvoke, model.invoke_stream, model.ainvoke_stream

        def reserve(args, kwargs, *, streaming=False):
            current()
            return ledger.begin_attempt(context, plan, model, streaming=streaming or getattr(model, "factory_wire_stream", False) is True,
                arguments=args, keyword_arguments=kwargs) if ledger is not None else None

        def finish(identity, value):
            if ledger is not None:
                ledger.finish_attempt(identity, ledger.evidence_for(plan, value))

        def recovered():
            if ledger is not None and context is not None:
                ledger.store.sql("UPDATE af_inference_waits SET state='RECOVERED' WHERE task_id=:task AND state='RESUMING'", task=context.session_id)

        def guarded(*args, **kwargs):
            identity = reserve(args, kwargs)
            try:
                response = invoke(*args, **kwargs)
            except BaseException as error:
                finish(identity, error)
                raise
            # A later permission/cancellation check cannot erase incurred usage.
            finish(identity, response)
            current()
            recovered()
            return response

        async def aguard(*args, **kwargs):
            await asyncio.to_thread(current)
            if local_current is not None:
                local_current()
            identity = ledger.begin_attempt(context, plan, model, streaming=getattr(model, "factory_wire_stream", False) is True, arguments=args, keyword_arguments=kwargs) if ledger is not None else None
            try:
                response = await ainvoke(*args, **kwargs)
            except BaseException as error:
                finish(identity, error)
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
        from .inference_wait import prepare_pause, publish_pause
        response = kwargs.get("run_response")
        if response is None and len(arguments) > (6 if streaming else 5):
            response = arguments[6 if streaming else 5]
        messages = kwargs.get("messages", arguments[0] if arguments else None)
        if not isinstance(response, RunOutput) or not isinstance(messages, list):
            return None
        if await asyncio.to_thread(self._stop_development_replay, response):
            return None
        body = await asyncio.to_thread(prepare_pause, self.bindings.store, response, error)
        return None if body is None else publish_pause(self.bindings.store, response, messages, body, streaming=streaming)

    def _pause(self, arguments, kwargs, error, *, streaming=False):
        from .inference_wait import pause
        response = kwargs.get("run_response")
        if response is None and len(arguments) > (6 if streaming else 5):
            response = arguments[6 if streaming else 5]
        messages = kwargs.get("messages", arguments[0] if arguments else None)
        if not isinstance(response, RunOutput) or not isinstance(messages, list):
            return None
        if self._stop_development_replay(response):
            return None
        return pause(self.bindings.store, response, messages, error, streaming=streaming)

    def _stop_development_replay(self, response):
        """Persist final provider failure before the native queue can retry.

        Model-level 503 retries have already spent their explicit attempt budget.
        Queue restarts must not turn quota/unknown usage or an exhausted budget
        into a fresh model retry allowance. Existing protected failures provide
        the durable stop; no queue implementation or shared retry policy changes.
        """
        if response.model_provider != "opencode-go-development":
            return False
        from .go_development import is_go_plan
        store = self.bindings.store
        task = store.task(response.session_id, response.user_id)
        if task["run_id"] != response.run_id:
            raise InputCheckError("Native failure identity differs from task binding")
        plan = store.plan(task["plan_id"], response.user_id)
        if not is_go_plan(plan):
            return False
        if not store.has_failures(task["id"]):
            store.event(task["id"], "protected_denied", "Development provider failure stops task replay",
                        {"code": "GO_TASK_STOPPED", "createsExecution": False})
        return True

    def _recovered(self, arguments, kwargs, *, streaming=False):
        if getattr(self.bindings.store, "usage_ledger", None) is None:
            return
        response = kwargs.get("run_response")
        if response is None and len(arguments) > (6 if streaming else 5):
            response = arguments[6 if streaming else 5]
        if isinstance(response, RunOutput):
            self.bindings.store.sql("UPDATE af_inference_waits SET state='RECOVERED' WHERE task_id=:task AND state='RESUMING'", task=response.session_id)

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
