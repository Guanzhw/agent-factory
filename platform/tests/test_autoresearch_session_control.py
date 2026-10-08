"""Inert original-pause controller checks; no DB, ORX, model provider or process."""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import time
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock

from agno.models.message import Message

from agent_factory.autoresearch_session_control import (
    AutoResearchSessionControl, CALL_ID, EFFECT, SessionControlModel, TOOL,
)


class Harness:
    def __init__(self):
        self.task = {'id': 'task', 'owner_id': 'alice', 'plan_id': 'plan', 'run_id': 'run',
                     'request_id': 'original-request', 'terminal': False, 'cancel_requested': False}
        self.plan = {'id': 'plan', 'ownerId': 'alice', 'tools': [TOOL]}
        self.requirement = {'id': 'requirement', 'tool_execution': {'tool_name': TOOL,
            'tool_call_id': CALL_ID, 'external_execution_required': True, 'tool_args': {}, 'result': None}}
        self.body: dict[str, Any] = {'status': 'starting', 'deadline': time.time() + 10}
        self.result = {'allStopped': True, 'cancelled': False, 'research': {'original': 'actual-result'},
                       'scientificConclusionVerified': False}
        self.store = Mock()
        self.store.settings = SimpleNamespace(demo=True)
        self.store.task.return_value = self.task
        self.store.plan.return_value = self.plan
        self.store.lifecycle_observer._binding.return_value = {'id': 'run', 'status': 'paused', 'persistedRunStatus': 'paused'}
        self.store.native_db.get_session.return_value = SimpleNamespace(runs=[SimpleNamespace(run_id='run',
            agent_id='factory-executor', requirements=[SimpleNamespace(to_dict=lambda: deepcopy(self.requirement))])])
        self.store.execution_bindings.recheck.return_value = {'model': {'adapterId': 'original-model', 'config': {'presetId': 'preset'}}}
        self.store.autoresearch._unresolved_tools.return_value = False
        self.store.autoresearch.current.return_value = SimpleNamespace(external_session=True)
        self.store.autoresearch.row.side_effect = lambda *_: {'body': self.body}
        self.store.autoresearch.change.side_effect = lambda _o, _t, fn: fn(self.body)
        self.store.effects.return_value = []
        async def execute(ctx):
            self.body['status'] = 'awaiting-continuation'
            self.store.effects.return_value = [{'effect_key': 'run:' + EFFECT, 'status': 'DONE', 'result': self.result}]
            return {'untrustedReturn': 'ignored'}
        self.store.autoresearch.execute = AsyncMock(side_effect=execute)
        async def complete(*_):
            self.store.lifecycle_observer._binding.return_value.update(status='completed', persistedRunStatus='completed')
        self.complete = AsyncMock(side_effect=complete)
        self.store.delegation._root_lock.side_effect = lambda *_: nullcontext()
        self.store.delegation._descendants.return_value = []
        self.store.lifecycle_observer._cancel_bound = AsyncMock()
        self.control = AutoResearchSessionControl(self.store, Mock(), complete=self.complete)


class SessionControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_external_call_once_and_original_receipt_only(self):
        h = Harness()
        model = SessionControlModel(h.control._context(h.task))
        native = SimpleNamespace(run_id='run', session_id='task', user_id='alice', requirements=None)
        messages = []
        response = await model.aresponse(messages, run_response=native)
        assert response.tool_executions is not None
        self.assertEqual(response.tool_executions[0].tool_name, TOOL)
        self.assertEqual(len(native.requirements), 1)
        with self.assertRaises(ValueError):
            await model.aresponse(messages, run_response=native)
        result = h.result
        h.store.effects.return_value = [{'effect_key': 'run:' + EFFECT, 'status': 'DONE', 'result': result}]
        import json
        done = await model.aresponse([Message(role='tool', tool_name=TOOL, tool_call_id=CALL_ID, content=json.dumps(result))])
        assert isinstance(done.content, str)
        self.assertEqual(json.loads(done.content), result)
        with self.assertRaises(ValueError):
            await model.aresponse([Message(role='tool', tool_name=TOOL, tool_call_id=CALL_ID,
                content=json.dumps({**result, 'accepted': False}))])
        with self.assertRaises(ValueError):
            await model.aresponse([Message(role='tool', tool_name=TOOL, tool_call_id='replacement', content=json.dumps(result))])

    async def test_stream_pause_does_not_double_publish_requirement_or_charge_provider(self):
        h = Harness(); model = SessionControlModel(h.control._context(h.task))
        native = SimpleNamespace(run_id='run', session_id='task', user_id='alice', requirements=None)
        messages = []
        events = [item async for item in model.aresponse_stream(messages, run_response=native)]
        self.assertEqual(len(events), 1)
        executions = events[0].tool_executions
        assert executions is not None
        self.assertEqual(executions[0].tool_call_id, CALL_ID)
        self.assertIsNone(native.requirements)
        with self.assertRaises(ValueError): await model.ainvoke([])
        h.store.effect_reserve.assert_not_called()
        h.store.autoresearch.execute.assert_not_awaited()

    async def test_run_uses_trusted_binding_and_returns_persisted_done_not_callback(self):
        h = Harness()
        self.assertEqual(await h.control.run('alice', 'task'), h.result)
        ctx = h.store.autoresearch.execute.await_args.args[0]
        self.assertIs(ctx.store, h.store)
        self.assertEqual(ctx.run_context.run_id, 'run')
        h.store.delegation.consume_tool_budget.assert_called_once_with(ctx.run_context, CALL_ID, TOOL)
        self.assertEqual(ctx.spec['adapterId'], 'original-model')
        self.assertEqual(h.body['sessionControl']['nativeRunId'], 'run')
        with self.assertRaises(ValueError): await h.control.run('alice', 'task')
        h.store.autoresearch.execute.assert_awaited_once()

    async def test_exact_paused_requirements_and_optin_required_before_execute(self):
        for mutation in ('ticket', 'persisted', 'tool', 'args', 'result', 'optin', 'cancel'):
            h = Harness()
            if mutation == 'ticket': h.store.lifecycle_observer._binding.return_value['id'] = 'other'
            if mutation == 'persisted': h.store.lifecycle_observer._binding.return_value['persistedRunStatus'] = 'running'
            if mutation == 'tool': h.requirement['tool_execution']['tool_call_id'] = 'other'
            if mutation == 'args': h.requirement['tool_execution']['tool_args'] = {'injected': True}
            if mutation == 'result': h.requirement['tool_execution']['result'] = 'forged'
            if mutation == 'optin': h.store.autoresearch.current.return_value.external_session = False
            if mutation == 'cancel': h.task['cancel_requested'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                await h.control.run('alice', 'task')
            h.store.autoresearch.execute.assert_not_awaited()

    async def test_completion_rejects_unknown_cleanup_failed_body_and_stale_requirement(self):
        for mutation in ('effect', 'proof', 'cancelled', 'status', 'requirement'):
            h = Harness(); await h.control.run('alice', 'task')
            requirement = deepcopy(h.requirement)
            if mutation == 'effect': h.store.effects.return_value[0]['status'] = 'UNKNOWN'
            if mutation == 'proof': h.result['allStopped'] = False
            if mutation == 'cancelled': h.result['cancelled'] = True
            if mutation == 'status': h.body['status'] = 'failed'
            if mutation == 'requirement': requirement['tool_execution']['tool_args'] = {'changed': True}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                await h.control.completion(h.task, requirement)
            h.store.effect_reserve.assert_not_called()

    async def test_explicit_start_retains_original_handle_and_calls_completion_once(self):
        h = Harness()
        first = h.control.start('alice', 'task')
        self.assertIs(h.control.start('alice', 'task'), first)
        self.assertEqual(await first, h.result)
        self.assertIs(h.control.start('alice', 'task'), first)
        h.complete.assert_awaited_once(); h.store.autoresearch.execute.assert_awaited_once()
        reconstructed = AutoResearchSessionControl(h.store, Mock())
        with self.assertRaises(ValueError): reconstructed.start('alice', 'task')
        self.assertTrue(await h.control.close())
        with self.assertRaises(ValueError): h.control.start('alice', 'task')

    async def test_close_cancels_same_controller_and_never_restarts_unknown(self):
        h = Harness(); entered = asyncio.Event()
        async def execute(_):
            entered.set(); await asyncio.Event().wait()
        h.store.autoresearch.execute.side_effect = execute
        pending = h.control.start('alice', 'task')
        await entered.wait()
        self.assertTrue(await h.control.close())
        self.assertTrue(pending.cancelled())
        h.complete.assert_not_awaited()
        self.assertIn('sessionControl', h.body)
        h.store.autoresearch.execute.assert_awaited_once()

    async def test_failure_stops_original_parent_and_descendants_once_without_releasing_unknown(self):
        h = Harness()
        child = dict(h.task, id='child', run_id='child-run')
        h.store.task.side_effect = lambda task, _: child if task == 'child' else h.task
        h.store.delegation._descendants.return_value = [{'owner_id': 'alice', 'root_id': 'task', 'child_id': 'child'}]
        failure = ValueError('private detail never persisted')
        async def fail(_):
            h.body['status'] = 'unknown'
            raise failure
        h.store.autoresearch.execute.side_effect = fail
        with self.assertRaises(ValueError) as raised:
            await h.control.start('alice', 'task')
        self.assertIs(raised.exception, failure)
        self.assertEqual(h.body['status'], 'unknown')
        self.assertEqual(h.body['sessionControlFailure'], 'CONTROL_FAILED')
        self.assertEqual([call.args[0] for call in h.store.request_cancel.call_args_list], ['task', 'child'])
        self.assertEqual(h.store.lifecycle_observer._cancel_bound.await_count, 2)
        h.store.effect_complete.assert_not_called()
        h.complete.assert_not_awaited()

    async def test_unbound_child_intent_still_cancels_original_parent_without_release(self):
        h = Harness()
        h.store.delegation._descendants.return_value = [{'owner_id': 'alice', 'root_id': 'task', 'child_id': None}]
        async def fail(_):
            h.body['status'] = 'unknown'
            raise ValueError('unconfirmed child intent')
        h.store.autoresearch.execute.side_effect = fail
        with self.assertRaises(ValueError): await h.control.start('alice', 'task')
        h.store.request_cancel.assert_called_once_with('task')
        h.store.lifecycle_observer._cancel_bound.assert_awaited_once_with(h.task)
        self.assertEqual(h.body['status'], 'unknown')
        h.store.effect_complete.assert_not_called()
        self.assertNotIn(None, [call.args[0] for call in h.store.task.call_args_list])

    async def test_diagnostic_write_failure_cannot_block_original_stop(self):
        h = Harness(); failure = ValueError('original execution failure')
        h.store.autoresearch.execute.side_effect = failure
        def change(_owner, _task, callback):
            if 'sessionControl' in h.body:
                raise OSError('diagnostic write unavailable')
            callback(h.body)
        h.store.autoresearch.change.side_effect = change
        with self.assertRaises(ValueError) as raised:
            await h.control.start('alice', 'task')
        self.assertIs(raised.exception, failure)
        h.store.request_cancel.assert_called_once_with('task')
        h.store.lifecycle_observer._cancel_bound.assert_awaited_once_with(h.task)
        h.complete.assert_not_awaited()
        h.store.effect_complete.assert_not_called()

    async def test_historical_done_cannot_continue_or_deliver_with_unknown_tool(self):
        import json
        h = Harness(); await h.control.run('alice', 'task')
        h.body['status'] = 'completed'
        h.store.autoresearch._unresolved_tools.return_value = True
        with self.assertRaises(ValueError):
            await h.control.completion(h.task, h.requirement)
        model = SessionControlModel(h.control._context(h.task))
        messages = [Message(role='tool', tool_name=TOOL, tool_call_id=CALL_ID,
                            content=json.dumps({**h.result, 'accepted': True}))]
        with self.assertRaises(ValueError): await model.aresponse(messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(h.store.effects.return_value[0]['status'], 'DONE')
        h.store.effect_complete.assert_not_called()

    async def test_continuation_failure_stops_parent_and_cannot_report_completed(self):
        h = Harness()
        h.complete.side_effect = ValueError('continuation denied')
        with self.assertRaises(ValueError): await h.control.start('alice', 'task')
        self.assertEqual(h.body['status'], 'failed')
        h.store.request_cancel.assert_called_once_with('task')
        h.store.autoresearch.execute.assert_awaited_once()

    async def test_success_waits_for_original_native_completion(self):
        h = Harness(); continued = asyncio.Event()
        async def complete(*_): continued.set()
        h.complete.side_effect = complete
        pending = h.control.start('alice', 'task')
        await continued.wait()
        self.assertFalse(pending.done())
        self.assertEqual(h.body['status'], 'awaiting-continuation')
        h.store.lifecycle_observer._binding.return_value.update(status='completed', persistedRunStatus='completed')
        self.assertEqual(await pending, h.result)
        self.assertEqual(h.body['status'], 'completed')
        h.store.request_cancel.assert_not_called()


if __name__ == '__main__': unittest.main()
