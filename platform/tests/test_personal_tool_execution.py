"""Native Agno calls with offline authority/custody fixtures and synthetic leases."""
import asyncio
import base64
import copy
from dataclasses import replace
import json
import threading
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.tools.function import FunctionCall

from agent_factory.execution_bindings import BindingContext, ExecutionBindings
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocationError
from agent_factory.personal_tool_execution import personal_tool_registration, register_personal_tools
from agent_factory.store import digest


SCHEMA = {'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 100}},
    'required': ['query'], 'additionalProperties': False}


class Adapter:
    def __init__(self, behavior=None):
        self.descriptor = ToolDescriptor('fixture-cli', 'v1', 'fixture_query', 'Synthetic bounded lookup',
            copy.deepcopy(SCHEMA), 'cli', 'fixture-vault', 'fixture://tool', ('tool:query',),
            permission='fixture:query', read_only=True)
        self.calls = []
        self.behavior = behavior

    async def invoke(self, invocation):
        self.calls.append(invocation)
        invocation.check_authorized()
        if self.behavior:
            return await self.behavior(invocation)
        invocation.resolve_credential()
        return {'owner': invocation.owner_id, 'query': invocation.arguments['query']}


class Handle:
    def __init__(self, owner, adapter, service):
        self.owner, self.adapter, self.service = owner, adapter, service
        self.configuration = {'registrationRef': 'registration-' + owner, 'revision': 'registration-v1'}
        self.valid = True
        self.resolutions = 0
        self.checks = 0
        self.lease = SecretLease('synthetic-user', 'synthetic-secret-' + owner)

    def check_authorized(self):
        self.checks += 1
        if not self.valid:
            raise PermissionError('fixture revoked')

    def resolve_credential(self):
        self.check_authorized()
        self.resolutions += 1
        return self.lease


class Store:
    """Atomic effect fixture retains the production fingerprint/status contract."""
    def __init__(self, adapter):
        self.personal_tools = SimpleNamespace(adapters={adapter.descriptor.adapter_id: adapter})
        self.execution_bindings = SimpleNamespace(recheck=self.recheck)
        self.effects = {}
        self.contexts = {}
        self.plan_allowed = self.binding_allowed = self.tool_allowed = True
        self.cancelled = False
        self.checks = {'plan': 0, 'binding': 0, 'tool': 0}
        self.lock = threading.Lock()

    def require_plan_execution(self, owner, plan, *, run_context):
        self.checks['plan'] += 1
        if not self.plan_allowed or owner != plan['ownerId'] or owner != run_context.user_id:
            raise PermissionError('fixture plan revoked')

    def recheck(self, plan, context):
        self.checks['binding'] += 1
        if self.cancelled:
            raise RunCancelledException('fixture cancelled')
        if not self.binding_allowed or self.contexts[context.run_id] != (context.user_id, context.session_id, plan['id']):
            raise PermissionError('fixture binding revoked')

    def authorize_tool(self, context, name):
        self.checks['tool'] += 1
        if not self.tool_allowed or name != 'fixture_query':
            raise PermissionError('fixture tool revoked')

    def cancellation_requested(self, run_id):
        return self.cancelled

    def effect_reserve(self, run_id, key, request):
        with self.lock:
            previous = self.effects.get((run_id, key))
            if previous is None:
                self.effects[run_id, key] = {'fingerprint': digest(request), 'status': 'UNKNOWN', 'result': None}
                return {'status': 'new'}
            if previous['fingerprint'] != digest(request):
                raise ValueError('fixture effect conflict')
            return {'status': 'done' if previous['status'] in {'DONE', 'CANCELLED'} else 'unknown',
                'result': copy.deepcopy(previous['result'])}

    def effect_complete(self, run_id, key, result):
        with self.lock:
            self.effects[run_id, key].update(status='CANCELLED' if result.get('cancelled') else 'DONE',
                result=copy.deepcopy(result))


class PersonalToolExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.store = Store(self.adapter)
        self.registration = personal_tool_registration(self.adapter)

    def call(self, *, owner='alice', run='run-alice', call_id='native-call-1', arguments=None):
        context = RunContext(user_id=owner, session_id='task-' + owner, run_id=run, session_state={})
        plan = {'id': 'plan-' + owner, 'ownerId': owner}
        self.store.contexts[run] = (owner, context.session_id, plan['id'])
        handle = Handle(owner, self.adapter, self.store.personal_tools)
        spec = {'connection': {'ref': 'connection-' + owner, 'revision': 'connection-v1'}}
        binding = BindingContext(None, self.store, plan, context, spec, handle)
        function = self.registration.factory(binding)
        function._run_context = context
        fc = FunctionCall(function=function, arguments=arguments if arguments is not None else {'query': 'bounded'},
            call_id=call_id)
        return fc, handle, context

    async def invoke(self, fc, context=None):
        return await fc.function.entrypoint(run_context=context or fc.function._run_context, fc=fc, **fc.arguments)

    def effect(self, run='run-alice', call_id='native-call-1'):
        return self.store.effects[run, 'personal-tool:' + call_id]

    def test_registration_and_native_schema_are_exact_and_metadata_only(self):
        registration = self.registration
        self.assertEqual((registration.kind, registration.adapter_id, registration.revision,
            registration.tool_name, registration.connection_kind), ('tool', 'fixture-cli', 'v1', 'fixture_query', 'tool'))
        self.assertEqual(registration.permissions, ('fixture:query',))
        self.assertEqual(registration.required_capabilities, ('tool:query',))
        self.assertIs(registration.factory._personal_tool_adapter, self.adapter)
        fc, handle, _ = self.call()
        self.assertEqual(fc.function.parameters, SCHEMA)
        self.assertTrue(fc.function.skip_entrypoint_processing)
        self.assertEqual(handle.resolutions, 0)
        self.assertFalse(self.adapter.calls)
        registration.validator({})
        with self.assertRaisesRegex(ValueError, 'PERSONAL_TOOL_CONFIGURATION_INVALID'):
            registration.validator({'command': 'arbitrary'})
        bindings = ExecutionBindings(SimpleNamespace(), self.store)
        register_personal_tools(bindings, self.store.personal_tools)
        self.assertIn(('tool', 'fixture-cli', 'v1'), bindings._adapters)

    async def test_native_function_injects_original_call_and_run_identity(self):
        fc, handle, context = self.call(call_id='provider-original-call')
        result = await fc.aexecute()
        self.assertEqual(result.status, 'success')
        self.assertEqual(fc.result, {'owner': 'alice', 'query': 'bounded'})
        invocation = self.adapter.calls[0]
        self.assertEqual(invocation.call_id, 'provider-original-call')
        self.assertIs(invocation.run_context, context)
        self.assertEqual((invocation.connection_ref, invocation.connection_revision), ('connection-alice', 'connection-v1'))
        self.assertEqual(handle.resolutions, 1)
        self.assertEqual(self.effect(call_id='provider-original-call')['status'], 'DONE')
        self.assertTrue(all(count >= 4 for count in self.store.checks.values()))

    async def test_native_injected_identity_cannot_be_overridden_by_arguments(self):
        fc, _, _ = self.call(arguments={'query': 'safe', 'run_context': 'forged', 'fc': 'forged'})
        result = await fc.aexecute()
        self.assertEqual(result.status, 'success')
        self.assertEqual(self.adapter.calls[0].owner_id, 'alice')
        self.assertEqual(self.adapter.calls[0].arguments, {'query': 'safe'})

    async def test_native_function_survives_binding_copy_guard_and_hooks(self):
        _, handle, context = self.call()
        plan = {'id': 'plan-alice', 'ownerId': 'alice'}
        spec = {'adapterId': 'fixture-cli', 'revision': 'v1', 'toolName': 'fixture_query',
            'config': {'connectionName': 'personal'},
            'connection': {'ref': 'connection-alice', 'revision': 'connection-v1'}}
        bindings = ExecutionBindings(SimpleNamespace(), self.store)
        register_personal_tools(bindings, self.store.personal_tools)
        binding = BindingContext(None, self.store, plan, context, spec, handle)
        hook_calls = []
        async def boundary(run_context, function_name, function_call, arguments):
            hook_calls.append((run_context.run_id, function_name))
            return await function_call(**arguments)
        with patch.object(bindings, 'resolve', return_value={'tools': [binding]}), \
                patch.object(bindings, 'recheck', side_effect=self.store.recheck):
            function = bindings.tools_for(plan, context)[0]
            function._run_context = context
            function.tool_hooks = [boundary]
            fc = FunctionCall(function=function, arguments={'query': 'guarded'}, call_id='guarded-native-call')
            result = await fc.aexecute()
        self.assertEqual(result.status, 'success')
        self.assertEqual(fc.result, {'owner': 'alice', 'query': 'guarded'})
        self.assertEqual(hook_calls, [('run-alice', 'fixture_query')])
        self.assertEqual(self.adapter.calls[0].call_id, 'guarded-native-call')

    async def test_two_owners_share_adapter_but_not_context_or_leases(self):
        arrived = asyncio.Event()
        seen = []
        async def behavior(invocation):
            lease = invocation.resolve_credential()
            seen.append((invocation.owner_id, lease.password, invocation.run_context.run_id))
            if len(seen) == 2:
                arrived.set()
            await asyncio.wait_for(arrived.wait(), 2)
            invocation.check_authorized()
            return {'owner': invocation.owner_id}
        self.adapter.behavior = behavior
        alice, _, _ = self.call()
        bob, _, _ = self.call(owner='bob', run='run-bob')
        outputs = await asyncio.gather(self.invoke(alice), self.invoke(bob))
        self.assertEqual(outputs, [{'owner': 'alice'}, {'owner': 'bob'}])
        self.assertCountEqual(seen, [('alice', 'synthetic-secret-alice', 'run-alice'),
            ('bob', 'synthetic-secret-bob', 'run-bob')])
        self.assertEqual(len(self.store.effects), 2)

    async def test_missing_native_call_id_and_foreign_context_do_not_reserve(self):
        for call_id in (None, '', 'bad\ncall'):
            with self.subTest(call_id=call_id):
                fc, _, _ = self.call(call_id=call_id)
                with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_CONTEXT_DENIED'):
                    await self.invoke(fc)
        fc, _, context = self.call()
        for field, value in (('user_id', 'bob'), ('run_id', 'foreign-run'), ('session_id', 'foreign-task')):
            original = getattr(context, field)
            setattr(context, field, value)
            with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_AUTHORIZATION_DENIED'):
                await self.invoke(fc)
            setattr(context, field, original)
        self.assertFalse(self.store.effects)
        self.assertFalse(self.adapter.calls)

    async def test_cross_owner_handle_is_rejected_at_assembly(self):
        fc, _, context = self.call()
        bob_handle = Handle('bob', self.adapter, self.store.personal_tools)
        binding = BindingContext(None, self.store, {'id': 'plan-alice'}, context,
            {'connection': {'ref': 'connection-alice', 'revision': 'v1'}}, bob_handle)
        with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_BINDING_DENIED'):
            self.registration.factory(binding)
        self.assertFalse(self.adapter.calls)

    async def test_retained_function_rechecks_every_authority_before_dispatch(self):
        for attribute in ('plan_allowed', 'binding_allowed', 'tool_allowed'):
            fc, _, _ = self.call()
            setattr(self.store, attribute, False)
            with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_AUTHORIZATION_DENIED'):
                await self.invoke(fc)
            setattr(self.store, attribute, True)
        fc, handle, _ = self.call()
        handle.valid = False
        with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_AUTHORIZATION_DENIED'):
            await self.invoke(fc)
        self.assertFalse(self.adapter.calls)
        self.assertFalse(self.store.effects)

    async def test_mutated_descriptor_or_adapter_registry_cannot_dispatch(self):
        fc, _, _ = self.call()
        self.adapter.descriptor.input_schema['properties']['query']['maxLength'] = 200
        with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_AUTHORIZATION_DENIED'):
            await self.invoke(fc)
        self.adapter.descriptor.input_schema['properties']['query']['maxLength'] = 100
        self.store.personal_tools.adapters['fixture-cli'] = Adapter()
        with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_AUTHORIZATION_DENIED'):
            await self.invoke(fc)
        self.assertFalse(self.store.effects)

    async def test_invalid_arguments_fail_before_effect_or_credentials(self):
        for arguments in ({}, {'query': 7}, {'query': 'x', 'command': 'arbitrary'}, {'query': 'x' * 101}):
            fc, handle, _ = self.call(arguments=arguments)
            with self.assertRaisesRegex(ValueError, 'PERSONAL_TOOL_INPUT_INVALID'):
                await self.invoke(fc)
            self.assertEqual(handle.resolutions, 0)
        self.assertFalse(self.store.effects)

    async def test_done_replays_original_receipt_without_dispatch_or_credentials(self):
        fc, handle, _ = self.call()
        first = await self.invoke(fc)
        self.assertEqual(await self.invoke(fc), first)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(handle.resolutions, 1)
        handle.valid = False
        with self.assertRaises(PermissionError):
            await self.invoke(fc)
        self.assertEqual(self.effect()['status'], 'DONE')

    async def test_revocation_while_reading_done_receipt_withholds_output(self):
        fc, handle, _ = self.call()
        await self.invoke(fc)
        read, release = threading.Event(), threading.Event()
        reserve = self.store.effect_reserve
        def paused_reserve(*args):
            receipt = reserve(*args)
            read.set()
            if not release.wait(2):
                raise AssertionError('fixture receipt barrier timed out')
            return receipt
        with patch.object(self.store, 'effect_reserve', side_effect=paused_reserve):
            task = asyncio.create_task(self.invoke(fc))
            try:
                self.assertTrue(await asyncio.to_thread(read.wait, 2))
                self.store.tool_allowed = False
            finally:
                release.set()
            with self.assertRaisesRegex(PermissionError, 'PERSONAL_TOOL_AUTHORIZATION_DENIED'):
                await task
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(handle.resolutions, 1)
        self.assertEqual(self.effect()['status'], 'DONE')

    async def test_reused_call_with_changed_arguments_cannot_dispatch(self):
        fc, _, _ = self.call()
        await self.invoke(fc)
        fc.arguments = {'query': 'different'}
        with self.assertRaisesRegex(ToolInvocationError, 'PERSONAL_TOOL_OUTCOME_UNKNOWN'):
            await self.invoke(fc)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.effect()['result']['output']['query'], 'bounded')

    async def test_concurrent_duplicate_call_is_unknown_and_never_redispatched(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def behavior(invocation):
            started.set()
            await finish.wait()
            return {'ok': True}
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        task = asyncio.create_task(self.invoke(fc))
        await asyncio.wait_for(started.wait(), 2)
        try:
            with self.assertRaisesRegex(ToolInvocationError, 'PERSONAL_TOOL_OUTCOME_UNKNOWN'):
                await self.invoke(fc)
        finally:
            finish.set()
        self.assertEqual(await task, {'ok': True})
        self.assertEqual(len(self.adapter.calls), 1)

    async def test_adapter_exception_is_sanitized_and_unknown_is_never_replayed(self):
        async def behavior(invocation):
            lease = invocation.resolve_credential()
            raise RuntimeError('Bearer ' + lease.password)
        self.adapter.behavior = behavior
        fc, handle, _ = self.call()
        for _ in range(2):
            try:
                await self.invoke(fc)
            except ToolInvocationError as error:
                rendered = ''.join(traceback.format_exception(error))
                self.assertEqual(str(error), 'PERSONAL_TOOL_OUTCOME_UNKNOWN')
                self.assertNotIn(handle.lease.password, rendered)
            else:
                self.fail('unknown adapter outcome must fail')
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.effect()['status'], 'UNKNOWN')
        self.assertIsNone(self.effect()['result'])

    async def test_known_failure_receipt_prevents_redispatch_and_redacts_adapter_code(self):
        async def behavior(invocation):
            raise ToolInvocationError('secret-adapter-detail', outcome='failed')
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        for _ in range(2):
            with self.assertRaisesRegex(ToolInvocationError, '^PERSONAL_TOOL_FAILED$'):
                await self.invoke(fc)
        self.assertEqual(self.effect()['status'], 'DONE')
        self.assertEqual(self.effect()['result'], {'outcome': 'failed'})
        self.assertEqual(len(self.adapter.calls), 1)

    async def test_only_positive_stop_evidence_settles_cancellation(self):
        for index, stopped in enumerate((False, True, 1)):
            async def behavior(invocation):
                raise ToolInvocationError('secret-cancellation-detail', outcome='cancelled', stopped=stopped)
            self.adapter.behavior = behavior
            fc, _, _ = self.call(call_id='cancel-' + str(index))
            expected = RunCancelledException if stopped is True else ToolInvocationError
            with self.assertRaises(expected):
                await self.invoke(fc)
            effect = self.effect(call_id='cancel-' + str(index))
            self.assertEqual(effect['status'], 'CANCELLED' if stopped is True else 'UNKNOWN')
            if stopped is True:
                self.assertTrue(effect['result']['stopped'])
                self.assertNotIn('cleanupComplete', effect['result'])
            else:
                self.assertIsNone(effect['result'])

    async def test_native_cancel_without_stop_proof_remains_unknown_and_sanitized(self):
        async def behavior(invocation):
            raise RunCancelledException('secret-native-cancellation-detail')
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        with self.assertRaisesRegex(RunCancelledException, '^PERSONAL_TOOL_CANCELLED$'):
            await self.invoke(fc)
        self.assertEqual(self.effect()['status'], 'UNKNOWN')

    async def test_asyncio_cancel_message_cannot_leak_adapter_details(self):
        async def behavior(invocation):
            raise asyncio.CancelledError('secret-adapter-cancel-detail')
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        try:
            await self.invoke(fc)
        except asyncio.CancelledError as error:
            self.assertEqual(str(error), '')
            self.assertNotIn('secret-adapter-cancel-detail', ''.join(traceback.format_exception(error)))
        else:
            self.fail('native cancellation must propagate')
        self.assertEqual(self.effect()['status'], 'UNKNOWN')

    async def test_cancelled_receipt_replay_does_not_dispatch(self):
        async def behavior(invocation):
            raise ToolInvocationError('fixture-stopped', outcome='cancelled', stopped=True)
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        for _ in range(2):
            with self.assertRaisesRegex(RunCancelledException, '^PERSONAL_TOOL_CANCELLED$'):
                await self.invoke(fc)
        self.assertEqual(self.effect()['status'], 'CANCELLED')
        self.assertEqual(len(self.adapter.calls), 1)

    async def test_task_cancel_runs_adapter_finally_and_retains_unknown(self):
        started, cleaned = asyncio.Event(), asyncio.Event()
        async def behavior(invocation):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        task = asyncio.create_task(self.invoke(fc))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cleaned.is_set())
        self.assertEqual(self.effect()['status'], 'UNKNOWN')

    async def test_cancellation_before_dispatch_does_not_reserve(self):
        fc, _, _ = self.call()
        self.store.cancelled = True
        with self.assertRaises(RunCancelledException):
            await self.invoke(fc)
        self.assertFalse(self.adapter.calls)
        self.assertFalse(self.store.effects)

    async def test_adapter_callback_rechecks_revocation_before_resolving(self):
        fc, handle, _ = self.call()
        async def behavior(invocation):
            self.store.tool_allowed = False
            invocation.resolve_credential()
        self.adapter.behavior = behavior
        with self.assertRaises(ToolInvocationError):
            await self.invoke(fc)
        self.assertEqual(handle.resolutions, 0)
        self.assertEqual(self.effect()['status'], 'UNKNOWN')

    async def test_completed_effect_is_retained_but_result_withheld_after_revocation(self):
        async def behavior(invocation):
            self.store.tool_allowed = False
            return {'ok': True}
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        with self.assertRaises(PermissionError):
            await self.invoke(fc)
        self.assertEqual(self.effect()['status'], 'DONE')
        self.store.tool_allowed = True
        self.assertEqual(await self.invoke(fc), {'ok': True})
        self.assertEqual(len(self.adapter.calls), 1)

    async def test_known_credential_echoes_never_reach_receipts(self):
        for index, form in enumerate(('password', 'basic', 'bearer', 'key')):
            async def behavior(invocation):
                lease = invocation.resolve_credential()
                encoded = base64.b64encode((lease.username + ':' + lease.password).encode()).decode()
                return {'password': {'data': lease.password}, 'basic': {'data': 'Basic ' + encoded},
                    'bearer': {'data': 'Bearer ' + lease.password}, 'key': {lease.password: 'value'}}[form]
            self.adapter.behavior = behavior
            fc, handle, _ = self.call(call_id='echo-' + str(index))
            with self.assertRaisesRegex(ToolInvocationError, '^PERSONAL_TOOL_OUTCOME_UNKNOWN$'):
                await self.invoke(fc)
            self.assertNotIn(handle.lease.password, json.dumps(list(self.store.effects.values())))
            self.assertIsNone(self.effect(call_id='echo-' + str(index))['result'])

    async def test_invalid_or_oversized_json_cannot_be_persisted(self):
        for index, value in enumerate((b'bytes', float('nan'), {'large': 'x' * 16001})):
            async def behavior(invocation):
                return value
            self.adapter.behavior = behavior
            fc, _, _ = self.call(call_id='invalid-' + str(index))
            with self.assertRaises(ToolInvocationError):
                await self.invoke(fc)
            self.assertIsNone(self.effect(call_id='invalid-' + str(index))['result'])

    async def test_tool_payload_cannot_forge_cancelled_effect(self):
        async def behavior(invocation):
            return {'cancelled': True, 'stopped': True}
        self.adapter.behavior = behavior
        fc, _, _ = self.call()
        self.assertEqual(await self.invoke(fc), {'cancelled': True, 'stopped': True})
        self.assertEqual(self.effect()['status'], 'DONE')

    def test_descriptor_reserved_fields_and_invalid_bounds_fail_at_contract(self):
        for field in ('fc', 'run_context', '_agno_run_context'):
            schema = copy.deepcopy(SCHEMA)
            schema['properties'][field] = {'type': 'string', 'maxLength': 20}
            with self.assertRaises(ValueError):
                replace(self.adapter.descriptor, input_schema=schema)
        for values in ({'timeout_seconds': float('nan')}, {'max_output_bytes': 1}, {'permission': ''}):
            with self.assertRaises(ValueError):
                replace(self.adapter.descriptor, **values)


if __name__ == '__main__':
    unittest.main()
