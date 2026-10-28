"""Application request hooks through native Agno loops; no provider or database I/O."""
from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any, cast
import asyncio
import unittest

from agno.exceptions import InputCheckError, RunCancelledException
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.tools.function import Function
from fastapi import HTTPException

from agent_factory.application_runtime import ApplicationRuntimeRegistry
from agent_factory.execution_bindings import BindingContext
from agent_factory.model_dispatch import DelegatingModel


MODES = ('invoke', 'ainvoke', 'invoke_stream', 'ainvoke_stream')


class RequestModel(Model):
    def __init__(self, trace, *, tool_loop=False):
        super().__init__(id='synthetic-request-model', provider='controlled-fixture', retries=0)
        self.trace, self.tool_loop = trace, tool_loop
        self.requests, self.snapshots = [], []

    def answer(self, messages=None, **kwargs):
        self.trace.append('provider')
        self.requests.append(messages)
        self.snapshots.append([message.model_copy(deep=True) for message in messages]
            if isinstance(messages, list) and all(isinstance(message, Message) for message in messages) else messages)
        completed = sum(message.role == 'tool' for message in messages) if self.tool_loop else 0
        if self.tool_loop and completed < 2:
            return ModelResponse(role='assistant', tool_calls=[{'id': f'step-{completed + 1}',
                'type': 'function', 'function': {'name': 'fixture_step', 'arguments': '{"step":%d}' % (completed + 1)}}])
        return ModelResponse(role='assistant', content='synthetic-complete')

    def invoke(self, *args, **kwargs):
        return self.answer(*args, **kwargs)

    async def ainvoke(self, *args, **kwargs):
        return self.answer(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.answer(*args, **kwargs)
        if not self.tool_loop:
            yield ModelResponse(role='assistant', content='second-chunk')

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.answer(*args, **kwargs)
        if not self.tool_loop:
            yield ModelResponse(role='assistant', content='second-chunk')

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response, **kwargs):
        return response


class ModelBeforeHookTests(unittest.IsolatedAsyncioTestCase):
    def selected(self, callback=None, *, registry=True, owned=True, tool_loop=False):
        trace, reservations = [], []
        context = RunContext(run_id='run', session_id='task', user_id='alice', session_state={})
        plan = {'id': 'plan', 'applicationRef': {'id': 'synthetic-application', 'version': 1}}
        task = {'id': 'task', 'owner_id': 'alice', 'plan_id': 'plan', 'run_id': 'run'}
        state = SimpleNamespace(denied=False, cancelled=False)

        def local_current():
            if state.cancelled:
                raise RunCancelledException('synthetic stop during before_model')

        def current():
            trace.append('current')
            if state.denied:
                raise PermissionError('synthetic revoked authority')

        def scoped_task(task_id, owner):
            trace.append('task')
            if (task_id, owner) != ('task', 'alice'):
                raise PermissionError('synthetic owner mismatch')
            return task

        def reserve(*args, **kwargs):
            trace.append('reserve')
            messages = kwargs['keyword_arguments'].get('messages')
            if 'messages' not in kwargs['keyword_arguments']:
                messages = kwargs['arguments'][0] if kwargs['arguments'] else None
            reservations.append(list(messages) if isinstance(messages, list) else messages)
            return 'attempt'

        store = SimpleNamespace(task=scoped_task, plan=lambda *args: plan, effects=lambda *args: [],
            event=lambda *args: None, reject_model_protocol=lambda *args: None,
            usage_ledger=SimpleNamespace(begin_attempt=reserve, evidence_for=lambda *args: None,
                finish_attempt=lambda *args: trace.append('finish')))
        if registry:
            store.application_runtime = ApplicationRuntimeRegistry(store)
            hooks = SimpleNamespace(before_model=callback) if callback is not None else SimpleNamespace()
            store.application_runtime.register('synthetic-owner', hooks,
                applications=(('synthetic-application' if owned else 'other-application', 1),))
        model = RequestModel(trace, tool_loop=tool_loop)
        bindings = SimpleNamespace(store=store, model_from_binding=lambda *args: model,
            manifest=lambda *args: {'sha256': 'synthetic-binding'})
        dispatcher = DelegatingModel(cast(Any, bindings))
        dispatcher._complete_selection((RunOutput(run_id='run', session_id='task', user_id='alice'),
            plan, context, current, local_current, BindingContext(None, store, plan, context, {})))
        return model, context, trace, reservations, state, store

    async def call(self, model, mode, args=(), kwargs=None):
        result = getattr(model, mode)(*args, **(kwargs or {}))
        if mode == 'ainvoke':
            return await result
        if mode == 'invoke_stream':
            return list(result)
        if mode == 'ainvoke_stream':
            return [item async for item in result]
        return result

    async def test_all_modes_amend_actual_messages_after_authority_before_reservation(self):
        for mode in MODES:
            for positional in (True, False):
                with self.subTest(mode=mode, positional=positional):
                    calls, loop_thread = [], get_ident()
                    messages = [Message(role='user', content='synthetic input')]

                    def before(context, actual):
                        calls.append((context, actual, get_ident()))
                        trace.append('hook')
                        actual.append(Message(id='correction-1', role='user', content='synthetic correction'))

                    model, context, trace, reservations, _, _ = self.selected(before)
                    await self.call(model, mode, (messages,) if positional else (),
                        {} if positional else {'messages': messages})
                    self.assertEqual(trace[:5], ['current', 'task', 'hook', 'reserve', 'provider'])
                    self.assertEqual(len(calls), 1, 'No callback after response or for individual stream chunks')
                    self.assertIs(calls[0][0], context)
                    self.assertIs(calls[0][1], messages)
                    self.assertEqual(calls[0][2] == loop_thread, not mode.startswith('a'))
                    self.assertIs(model.requests[0], messages)
                    self.assertEqual(reservations[0][-1].id, 'correction-1')
                    self.assertEqual(model.snapshots[0][-1].id, 'correction-1')

    async def test_invalid_or_absent_messages_with_callback_reject_before_accounting(self):
        invalid = [((), {}), ((), {'messages': None}), ((), {'messages': {}}),
            ((('tuple',),), {}), (([{'role': 'user', 'content': 'not native'}],), {}),
            (([Message(role='user', content='valid'), 'invalid-item'],), {})]
        for mode in MODES:
            for args, kwargs in invalid:
                with self.subTest(mode=mode, args=args, kwargs=kwargs):
                    calls = []
                    model, _, trace, reservations, _, _ = self.selected(lambda *args: calls.append(args))
                    with self.assertRaises(InputCheckError):
                        await self.call(model, mode, args, kwargs)
                    self.assertEqual((calls, reservations, model.requests), ([], [], []))
                    self.assertEqual(trace, ['current', 'task'])

    async def test_stop_received_during_hook_blocks_every_provider_mode(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                def before(context, messages):
                    state.cancelled = True
                model, _, _, reservations, state, _ = self.selected(before)
                with self.assertRaises(RunCancelledException):
                    await self.call(model, mode, ([Message(role='user', content='input')],))
                self.assertEqual((reservations, model.requests), ([], []))

    async def test_no_registry_no_owner_or_no_callback_preserves_original_dispatch(self):
        for mode in MODES:
            for options in ({'registry': False}, {'owned': False}, {}):
                with self.subTest(mode=mode, options=options):
                    model, _, _, reservations, _, _ = self.selected(**options)
                    await self.call(model, mode)
                    self.assertEqual(model.requests, [None])
                    self.assertEqual(reservations, [None])

    async def test_revocation_owner_mismatch_and_callback_failure_never_dispatch(self):
        for mode in MODES:
            for failure in ('authority', 'owner', 'callback'):
                with self.subTest(mode=mode, failure=failure):
                    calls = []

                    def before(*args):
                        calls.append(args)
                        raise PermissionError('synthetic application stop')

                    model, context, trace, reservations, state, _ = self.selected(before)
                    if failure == 'authority':
                        state.denied = True
                    if failure == 'owner':
                        context.user_id = 'bob'
                    with self.assertRaises(PermissionError):
                        await self.call(model, mode, ([Message(role='user', content='input')],))
                    self.assertEqual((reservations, model.requests), ([], []))
                    self.assertEqual(len(calls), int(failure == 'callback'))
                    if failure == 'authority':
                        self.assertEqual(trace, ['current'])

    async def test_ambiguous_application_callbacks_reject_without_dispatch(self):
        model, _, _, reservations, _, store = self.selected(lambda *args: None)
        plan = store.plan('plan', 'alice')
        plan['executionBindings'] = {'tools': [{'adapterId': name, 'revision': '1'} for name in ('a', 'b')]}
        for name in ('a', 'b'):
            store.application_runtime.register(name, SimpleNamespace(before_model=lambda *args: None),
                bindings=(('tool', name, '1'),))
        with self.assertRaises(HTTPException) as error:
            await self.call(model, 'ainvoke', ([Message(role='user', content='input')],))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual((reservations, model.requests), ([], []))

    async def test_native_multi_tool_loop_reads_new_corrections_once_per_request(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                pending, hook_calls, tools_called = ['initial'], [], []

                def before(context, messages):
                    hook_calls.append(messages)
                    existing = {message.id for message in messages}
                    for identifier in pending:
                        if identifier not in existing:
                            messages.append(Message(id=identifier, role='user', content='correction ' + identifier))

                def step(step: int) -> str:
                    tools_called.append(step)
                    pending.append(f'correction-{step}')
                    return f'synthetic result {step}'

                function = Function(name='fixture_step', description='Synthetic step', entrypoint=step,
                    parameters={'type': 'object', 'properties': {'step': {'type': 'integer'}}, 'required': ['step']})
                model, _, _, reservations, _, _ = self.selected(before, tool_loop=True)
                messages = [Message(role='user', content='perform two synthetic steps')]
                kwargs = {'messages': messages, 'tools': [function], 'tool_call_limit': 3}
                if mode == 'invoke':
                    model.response(**kwargs)
                elif mode == 'ainvoke':
                    await model.aresponse(**kwargs)
                elif mode == 'invoke_stream':
                    list(model.response_stream(**kwargs))
                else:
                    [item async for item in model.aresponse_stream(**kwargs)]
                self.assertEqual(tools_called, [1, 2])
                self.assertEqual((len(model.requests), len(hook_calls), len(reservations)), (3, 3, 3))
                for index, snapshot in enumerate(model.snapshots):
                    identifiers = [message.id for message in snapshot]
                    self.assertEqual(identifiers.count('initial'), 1)
                    self.assertEqual(identifiers.count('correction-1'), int(index >= 1))
                    self.assertEqual(identifiers.count('correction-2'), int(index >= 2))

    async def test_async_callback_leaves_loop_responsive_and_cancellation_prevents_dispatch(self):
        for mode in ('ainvoke', 'ainvoke_stream'):
            with self.subTest(mode=mode):
                entered, release, exited = Event(), Event(), Event()

                def before(context, messages):
                    entered.set()
                    try:
                        if not release.wait(3):
                            raise AssertionError('Synthetic callback was not released')
                    finally:
                        exited.set()

                model, _, _, reservations, _, _ = self.selected(before)
                task = asyncio.create_task(self.call(model, mode, ([Message(role='user', content='input')],)))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    progressed = asyncio.Event()
                    asyncio.get_running_loop().call_soon(progressed.set)
                    await asyncio.wait_for(progressed.wait(), 1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    release.set()
                    self.assertTrue(await asyncio.to_thread(exited.wait, 2))
                self.assertEqual((reservations, model.requests), ([], []))
