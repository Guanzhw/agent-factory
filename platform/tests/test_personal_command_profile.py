from copy import deepcopy
import asyncio
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from agno.models.message import Message
from agno.run import RunContext
from agent_factory.config import Settings
from agent_factory.input_schema import validate_input_schema, validate_input_values
from agent_factory.personal_command_api import PrepareCommand, deny_direct_admission
from agent_factory.personal_command_profile import (APPLICATION_ID, CONTRACT, TOOL_NAME, PersonalCommandModel,
    admission_for, command_scope, input_schema, pricing, registrations, reconcile_command, EFFECT)
from agent_factory.store import canonical, digest


class PersonalCommandProfileTests(unittest.TestCase):
    def scope(self, action='prompt'):
        run = RunContext(user_id='alice', session_id='task-original', run_id='run-original')
        command = {'executionContract': CONTRACT, 'action': action, 'requestId': 'request-original',
            'connectionPin': {'ref': 'conn-original', 'version': 1}, 'nativeProjectId': 'project-original',
            'nativeSessionId': None if action == 'create' else 'session-original',
            'factorySessionId': '' if action == 'create' else 'factory-original',
            'title': 'Original', 'text': 'Exact original prompt', 'agent': None}
        values = {**command, 'connectionPin': canonical(command['connectionPin']),
            'nativeSessionId': command['nativeSessionId'] or '', 'agent': ''}
        plan = {'id': 'plan-original', 'application': APPLICATION_ID, 'applicationRef': {'id': APPLICATION_ID, 'version': 1},
            'mode': 'personal-command', 'inputValues': values, 'tools': [TOOL_NAME]}
        ctx = SimpleNamespace(run_context=run, plan=plan, store=SimpleNamespace(authorize_tool=Mock(return_value=plan)))
        intent = {k: command[k] for k in ('executionContract', 'action', 'requestId', 'connectionPin',
            'nativeProjectId', 'nativeSessionId')}
        intent['factorySessionId'] = 'personal-generated' if action == 'create' else command['factorySessionId']
        if action == 'create': intent['title'] = command['title']
        if action == 'prompt': intent.update(text=command['text'], agent=None, nativeMessageId='msg_generated')
        return ctx, run, command, intent

    def test_exact_immutable_intent_and_native_identity(self):
        for action in ('create', 'prompt', 'interrupt'):
            ctx, run, command, intent = self.scope(action)
            self.assertEqual(command_scope(ctx, run), command)
            admission = admission_for(ctx, run, command)
            expected = {'executionContract': CONTRACT, 'planId': 'plan-original',
                'taskId': 'task-original', 'nativeRunId': 'run-original'}
            self.assertEqual(admission('alice', intent), expected)
            self.assertEqual(admission('alice', deepcopy(intent)), expected)
            self.assertEqual(ctx.store.authorize_tool.call_count, 3)

    def test_changed_scope_and_generated_correlation_are_rejected(self):
        for key in ('text', 'action', 'nativeProjectId', 'nativeSessionId', 'requestId', 'factorySessionId', 'nativeMessageId'):
            ctx, run, command, intent = self.scope()
            admission = admission_for(ctx, run, command)
            admission('alice', intent)
            with self.assertRaises(HTTPException): admission('alice', {**intent, key: 'changed'})
        ctx, run, command, intent = self.scope()
        with self.assertRaises(HTTPException): admission_for(ctx, run, command)('bob', intent)
        with self.assertRaises(HTTPException): command_scope(ctx, SimpleNamespace(user_id='alice', session_id='other', run_id=run.run_id))

    def test_rechecks_revocation_at_dispatch(self):
        ctx, run, command, intent = self.scope()
        admission = admission_for(ctx, run, command)
        admission('alice', intent)
        ctx.store.authorize_tool.side_effect = HTTPException(403, 'revoked')
        with self.assertRaises(HTTPException): admission('alice', intent)

    def test_strict_inputs_and_no_direct_mutation(self):
        ctx, run, command, intent = self.scope()
        schema = validate_input_schema(input_schema())
        self.assertEqual(validate_input_values(schema, ctx.plan['inputValues']), ctx.plan['inputValues'])
        with self.assertRaises(ValueError): validate_input_values(schema, {**ctx.plan['inputValues'], 'bypassManaged': True})
        with self.assertRaises(HTTPException): deny_direct_admission('alice', intent)
        with self.assertRaises(ValueError): PrepareCommand(requestId='request-original', action='interrupt', sessionId='session', text='hidden prompt')

    def test_no_provider_model_and_opt_in_registered_policy(self):
        settings = Settings(db_url='postgresql://unused', personal_agent_commands_enabled=True)
        self.assertEqual(len(settings.runtime_adapters), 3)
        self.assertFalse(settings.tool_policies[0].read_only)
        self.assertIs(pricing().local_model_type, PersonalCommandModel)
        self.assertEqual(pricing().body['usageContract'], 'local-no-provider-v1')
        model = PersonalCommandModel()
        first = model.invoke([Message(role='user', content='ignored')])
        self.assertEqual(first.tool_calls[0]['function']['arguments'], '{}')
        result = model.invoke([Message(role='tool', tool_name=TOOL_NAME, content='{"state":"ack_unknown"}')])
        self.assertIn('ack_unknown', result.content)
        self.assertNotIn('allStopped', result.content)
        self.assertTrue(all(not e.demo_only for e in registrations()))

    def test_native_retry_reads_original_unknown_without_redispatch(self):
        ctx, run, command, intent = self.scope()
        ctx.spec = {'config': {}}
        ctx.store.connections = object()
        ctx.store.effect_reserve = Mock(return_value={'status': 'unknown', 'result': None})
        ctx.store.effect_complete = Mock()
        service = Mock()
        service.request_result.side_effect = HTTPException(404, 'not reserved')
        runner = next(e for e in registrations() if e.kind == 'tool').factory(ctx)
        with patch('agent_factory.personal_agent_sessions.PersonalAgentSessions', return_value=service):
            value = asyncio.run(runner.entrypoint(run_context=run))
        self.assertIn('ack_unknown', value)
        service.prompt.assert_not_called()
        service.create.assert_not_called()
        service.interrupt.assert_not_called()
        ctx.store.effect_complete.assert_not_called()

    def test_remote_acceptance_only_settles_command_not_stop(self):
        ctx, run, command, intent = self.scope()
        ctx.spec = {'config': {}}
        ctx.store.connections = object()
        ctx.store.effect_reserve = Mock(return_value={'status': 'new'})
        ctx.store.effect_complete = Mock()
        expected = {'executionContract': CONTRACT, 'planId': 'plan-original',
            'taskId': 'task-original', 'nativeRunId': 'run-original'}
        service = Mock()
        service.prompt.return_value = {'factoryIdentity': expected, 'state': 'acknowledged'}
        runner = next(e for e in registrations() if e.kind == 'tool').factory(ctx)
        with patch('agent_factory.personal_agent_sessions.PersonalAgentSessions', return_value=service):
            value = asyncio.run(runner.entrypoint(run_context=run))
        self.assertIn('remote-command-acceptance-only', value)
        self.assertNotIn('allStopped', value)
        service.prompt.assert_called_once_with('alice', 'factory-original', 'Exact original prompt',
            'request-original', agent=None)
        ctx.store.effect_complete.assert_called_once()
        service.prompt.return_value = {'factoryIdentity': {**expected, 'nativeRunId': 'different'}, 'state': 'acknowledged'}
        with patch('agent_factory.personal_agent_sessions.PersonalAgentSessions', return_value=service):
            with self.assertRaises(HTTPException): asyncio.run(runner.entrypoint(run_context=run))

    def recovery(self):
        ctx, run, command, intent = self.scope()
        identity = {'executionContract': CONTRACT, 'planId': 'plan-original',
            'taskId': 'task-original', 'nativeRunId': 'run-original'}
        row = {'intent': intent, 'identity': identity, 'state': 'result_observed',
            'result': {'nativeMessageId': intent['nativeMessageId']}}
        service = SimpleNamespace(auth=SimpleNamespace(require=Mock()), _command=Mock(return_value=row),
            request_result=Mock(return_value={'factoryIdentity': identity, 'state': 'result_observed'}))
        store = SimpleNamespace(task=Mock(return_value={'id': 'task-original', 'owner_id': 'alice',
            'plan_id': 'plan-original', 'run_id': 'run-original'}), plan=Mock(return_value=ctx.plan),
            sql=Mock(return_value=[{'fingerprint': digest(command), 'status': 'UNKNOWN'}]), effect_complete=Mock())
        return store, service, row

    def test_observed_original_result_reconciles_only_existing_effect(self):
        store, service, row = self.recovery()
        reconcile_command(store, service, 'alice', 'request-original')
        store.effect_complete.assert_called_once()
        args = store.effect_complete.call_args.args
        self.assertEqual(args[:2], ('run-original', EFFECT))
        self.assertFalse(args[2]['remoteStopVerified'])
        self.assertNotIn('allStopped', args[2])
        self.assertEqual(service.auth.require.call_args.args, ('alice', 'read'))
        # Idempotent already settled observation does not modify the effect again.
        store.sql.return_value[0]['status'] = 'DONE'
        reconcile_command(store, service, 'alice', 'request-original')
        self.assertEqual(store.effect_complete.call_count, 1)

    def test_reconcile_rejects_wrong_original_run_intent_effect_and_message(self):
        for change in ('run', 'text', 'effect', 'message', 'request'):
            store, service, row = self.recovery()
            if change == 'run': store.task.return_value['run_id'] = 'another-run'
            if change == 'text': row['intent']['text'] = 'another text'
            if change == 'effect': store.sql.return_value[0]['fingerprint'] = 'another-fingerprint'
            if change == 'message': row['result']['nativeMessageId'] = 'another-message'
            with self.assertRaises(HTTPException):
                reconcile_command(store, service, 'alice', 'another-request' if change == 'request' else 'request-original')
            store.effect_complete.assert_not_called()

    def test_unknown_or_local_attach_observation_cannot_settle_effect(self):
        for state, action in (('ack_unknown', 'prompt'), ('acknowledged', 'attach'), ('acknowledged', 'rebind')):
            store, service, row = self.recovery()
            row.update(state=state); row['intent']['action'] = action
            reconcile_command(store, service, 'alice', 'request-original')
            store.task.assert_not_called(); store.effect_complete.assert_not_called()

    def test_native_orx_nullable_message_id_is_not_invented(self):
        ctx, run, command, intent = self.scope()
        command['connectionPin']['kind'] = 'orx'
        ctx.plan['inputValues']['connectionPin'] = canonical(command['connectionPin'])
        intent['connectionPin'] = command['connectionPin']
        intent['nativeMessageId'] = None
        self.assertEqual(admission_for(ctx, run, command)('alice', intent)['nativeRunId'], 'run-original')
        command['connectionPin']['kind'] = 'environment'
        ctx.plan['inputValues']['connectionPin'] = canonical(command['connectionPin'])
        with self.assertRaises(HTTPException): admission_for(ctx, run, command)('alice', intent)

    def test_registered_tool_runs_actual_orx_service_off_running_event_loop(self):
        import test_personal_orx_transport as native_fixture
        fixture = native_fixture.PersonalOrxTests('test_true_native_existing_attach_multiturn_tool_transcript_and_interrupt')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        attached = fixture.attach()['session']
        ctx, run, command, intent = self.scope()
        command.update(connectionPin=attached['connectionPin'], nativeProjectId=attached['nativeProjectId'],
            nativeSessionId=attached['nativeSessionId'], factorySessionId=attached['id'])
        ctx.plan['inputValues'] = {**command, 'connectionPin': canonical(command['connectionPin']), 'agent': ''}
        ctx.spec = {'config': {}}
        ctx.store.connections = fixture.connections
        ctx.store.effect_reserve = Mock(return_value={'status': 'new'})
        ctx.store.effect_complete = Mock()
        runner = next(e for e in registrations() if e.kind == 'tool').factory(ctx)
        loop_thread, wire_threads = threading.get_ident(), []
        original = fixture.wire.request
        def wire(*args, **kwargs):
            wire_threads.append(threading.get_ident())
            return original(*args, **kwargs)
        fixture.wire.request = wire
        async def execute():
            self.assertIsNotNone(asyncio.get_running_loop())
            return await runner.entrypoint(run_context=run)
        result = json.loads(asyncio.run(execute()))
        self.assertEqual(result['state'], 'acknowledged')
        self.assertEqual(result['factoryIdentity']['nativeRunId'], 'run-original')
        self.assertEqual(fixture.wire.prompts, 1)
        self.assertTrue(wire_threads)
        self.assertTrue(all(thread != loop_thread for thread in wire_threads))
        self.assertFalse(result['remoteStopVerified'])
        ctx.store.effect_complete.assert_called_once()
