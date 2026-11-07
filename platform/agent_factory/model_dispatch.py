"""Select the owner's model per native run; Agno owns response and tool loops."""
from __future__ import annotations

import asyncio
from typing import Any

from agno.exceptions import InputCheckError, RunCancelledException
from agno.models.base import Model
from agno.run import RunContext
from agno.run.agent import RunOutput


class DelegatingModel(Model):
    def __init__(self, store):
        super().__init__(id='factory-owner-model', provider='factory')
        self.store = store

    def __deepcopy__(self, memo):
        return self

    def _prepare_selection(self, arguments, kwargs, *, streaming=False):
        index = 6 if streaming else 5
        response = kwargs.get('run_response')
        if response is None and len(arguments) > index:
            response = arguments[index]
        if not isinstance(response, RunOutput) or not response.run_id or not response.session_id or not response.user_id:
            raise InputCheckError('Model selection requires the native run identity')
        task = self.store.task(response.session_id, response.user_id)
        if task['run_id'] != response.run_id:
            raise InputCheckError('Model run differs from its task')
        context = RunContext(run_id=response.run_id, session_id=response.session_id, user_id=response.user_id,
            session_state=response.session_state or {})
        plan = self.store.plan(task['plan_id'], response.user_id)
        def current():
            if self.store.cancellation_requested(response.run_id):
                raise RunCancelledException('Factory cancellation requested')
        current()
        return response, plan, context, current, current, None

    def _complete_selection(self, prepared):
        response, plan, context, current, _, _ = prepared
        reference = plan['connectionRefs']['model']
        def auxiliary():
            model = self.store.personal_models.model_for(context.user_id, reference, context)
            model._on_text = None
            return model
        model = self.store.personal_models.model_for(context.user_id, reference, context)
        self._provider_hooks(model, context, current, auxiliary, plan)
        window = getattr(model, 'context_window', None)
        threshold = getattr(model, 'auto_compact_token_limit', None)
        if isinstance(window, int) and window > 0:
            threshold = min(threshold, window * 9 // 10) if isinstance(threshold, int) else window * 9 // 10
        if isinstance(threshold, int) and threshold > 0:
            from agno.compression.manager import CompressionManager
            model._factory_compression_manager = CompressionManager(model=auxiliary(), compress_token_limit=threshold)
        response.model, response.model_provider = model.id, model.provider
        return model

    def _provider_hooks(self, model, context, current, auxiliary, plan):
        sessions = getattr(self.store, 'research_sessions', None)
        inputs = plan.get('inputValues') or {}
        callback = (sessions.before_model if sessions is not None and plan.get('mode') != 'qa'
            and inputs.get('sessionId') and inputs.get('turnId') else None)
        def before(args, kwargs):
            current()
            if callback is not None:
                messages = kwargs.get('messages', args[0] if args else None)
                callback(context, messages, auxiliary)
        invoke, ainvoke = model.invoke, model.ainvoke
        invoke_stream, ainvoke_stream = model.invoke_stream, model.ainvoke_stream
        def sync(*args, **kwargs):
            before(args, kwargs)
            return invoke(*args, **kwargs)
        async def async_call(*args, **kwargs):
            await asyncio.to_thread(before, args, kwargs)
            return await ainvoke(*args, **kwargs)
        def stream(*args, **kwargs):
            before(args, kwargs)
            yield from invoke_stream(*args, **kwargs)
        async def async_stream(*args, **kwargs):
            await asyncio.to_thread(before, args, kwargs)
            async for item in ainvoke_stream(*args, **kwargs):
                yield item
        model.invoke, model.ainvoke = sync, async_call
        model.invoke_stream, model.ainvoke_stream = stream, async_stream

    def _select(self, arguments, kwargs, *, streaming=False):
        return self._complete_selection(self._prepare_selection(arguments, kwargs, streaming=streaming))

    async def _aselect(self, arguments, kwargs, *, streaming=False):
        prepared = await asyncio.to_thread(self._prepare_selection, arguments, kwargs, streaming=streaming)
        return self._complete_selection(prepared)

    def response(self, *args, **kwargs):
        model = self._select(args, kwargs)
        kwargs['compression_manager'] = getattr(model, '_factory_compression_manager', None)
        return model.response(*args, **kwargs)

    async def aresponse(self, *args, **kwargs):
        model = await self._aselect(args, kwargs)
        kwargs['compression_manager'] = getattr(model, '_factory_compression_manager', None)
        return await model.aresponse(*args, **kwargs)

    def response_stream(self, *args, **kwargs):
        model = self._select(args, kwargs, streaming=True)
        kwargs['compression_manager'] = getattr(model, '_factory_compression_manager', None)
        yield from model.response_stream(*args, **kwargs)

    async def aresponse_stream(self, *args, **kwargs):
        model = await self._aselect(args, kwargs, streaming=True)
        kwargs['compression_manager'] = getattr(model, '_factory_compression_manager', None)
        async for value in model.aresponse_stream(*args, **kwargs):
            yield value

    def invoke(self, *args, **kwargs):
        raise InputCheckError('Use native response dispatch with its run identity')

    async def ainvoke(self, *args, **kwargs):
        raise InputCheckError('Use native response dispatch with its run identity')

    def invoke_stream(self, *args, **kwargs):
        raise InputCheckError('Use native response dispatch with its run identity')
        yield

    async def ainvoke_stream(self, *args, **kwargs):
        raise InputCheckError('Use native response dispatch with its run identity')
        yield

    def _parse_provider_response(self, response: Any, **kwargs):
        return response

    def _parse_provider_response_delta(self, response: Any):
        return response
