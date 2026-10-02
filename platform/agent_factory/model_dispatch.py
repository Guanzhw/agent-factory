"""Run-bound dispatch through Agno's public Model response methods.

Agno 3.1.0 passes native RunOutput to response/aresponse and their stream variants.
The stable executor model selects a fresh operator adapter from that identity,
never from prompt text and never by changing shared Agent.model. The selected
native Model retains its own provider formatting and native tool/HITL loop.
"""
from __future__ import annotations

from typing import Any

from agno.exceptions import InputCheckError, RunCancelledException
from agno.models.base import Model
from agno.run import RunContext
from agno.run.agent import RunOutput

from .execution_bindings import ExecutionBindings


class DelegatingModel(Model):
    def __init__(self, bindings: ExecutionBindings):
        super().__init__(id="factory-material-dispatch-v1", name="Immutable material model dispatch", provider="factory-registered")
        self.bindings = bindings

    def __deepcopy__(self, memo):
        # This dispatcher holds trusted services, not a mutable per-run model.
        return self

    def _select(self, arguments, kwargs, *, streaming=False):
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

        def current():
            if store.cancellation_requested(response.run_id):
                raise RunCancelledException("Factory cancellation requested before model invocation")
            latest = store.resolve_run(context)
            store.require_plan_execution(context.user_id, latest, run_context=context)
            self.bindings.recheck(latest, context)

        current()
        model = self.bindings.model_for(plan, context)
        # Only this fresh per-response adapter is wrapped. Shared Agent/model
        # state is unchanged, and every provider retry/tool-loop call rechecks.
        self._guard_provider_calls(model, current)
        response.model = model.id
        response.model_provider = model.provider
        store.event(response.run_id, "model_binding_selected", "Exact trusted model adapter selected for this native response",
                    {"modelId": model.id, "provider": model.provider,
                     "executionBindingsSha256": self.bindings.manifest(plan)["sha256"], "createsExecution": False})
        return model

    @staticmethod
    def _guard_provider_calls(model: Model, current):
        invoke, ainvoke, invoke_stream, ainvoke_stream = model.invoke, model.ainvoke, model.invoke_stream, model.ainvoke_stream
        def guarded(*args, **kwargs):
            current()
            response = invoke(*args, **kwargs)
            current()
            return response
        async def aguard(*args, **kwargs):
            current()
            response = await ainvoke(*args, **kwargs)
            current()
            return response
        def stream(*args, **kwargs):
            current()
            values = invoke_stream(*args, **kwargs)
            try:
                for value in values:
                    current()
                    yield value
                current()
            finally:
                close = getattr(values, "close", None)
                if close is not None:
                    close()
        async def astream(*args, **kwargs):
            current()
            values = ainvoke_stream(*args, **kwargs)
            try:
                async for value in values:
                    current()
                    yield value
                current()
            finally:
                close = getattr(values, "aclose", None)
                if close is not None:
                    await close()
        model.invoke, model.ainvoke = guarded, aguard
        model.invoke_stream, model.ainvoke_stream = stream, astream

    def response(self, *args, **kwargs):
        return self._select(args, kwargs).response(*args, **kwargs)

    async def aresponse(self, *args, **kwargs):
        return await self._select(args, kwargs).aresponse(*args, **kwargs)

    def response_stream(self, *args, **kwargs):
        yield from self._select(args, kwargs, streaming=True).response_stream(*args, **kwargs)

    async def aresponse_stream(self, *args, **kwargs):
        async for value in self._select(args, kwargs, streaming=True).aresponse_stream(*args, **kwargs):
            yield value

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
