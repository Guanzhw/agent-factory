"""Service lifecycle contracts with in-memory seams; no ORX, provider or database."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import time
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock

from agno.exceptions import RunCancelledException
from fastapi import HTTPException

from agent_factory.autoresearch import ACCEPTANCE, AutoResearchService, ResearchPreset
from agent_factory.store import digest


class MemoryService(AutoResearchService):
    saved: dict[str, Any]

    def row(self, owner, task_id):
        self.store.task(task_id, owner)
        if owner != 'alice' or task_id != 'task':
            raise HTTPException(404)
        return self.saved

    def change(self, owner, task_id, fn):
        body = deepcopy(self.row(owner, task_id)['body'])
        result = fn(body)
        self.saved['body'] = body
        return result

    def recover(self, owner, request_id):
        self.auth.require(owner, 'read')
        return self.projection(owner, 'task') if request_id == self.saved['body']['requestId'] else None


class Harness:
    def __init__(self):
        self.run = SimpleNamespace(user_id='alice', session_id='task', run_id='run')
        self.ctx = SimpleNamespace(run_context=self.run)
        self.runtime = SimpleNamespace(run=AsyncMock(return_value={'actual': 'result'}),
                                       stop=AsyncMock(return_value=True), cancel=AsyncMock())
        self.factory = Mock(return_value=self.runtime)
        self.context = Mock(return_value={'baseline': 'fixed'})
        self.validator = Mock(return_value={'sha256': 'a' * 64})
        self.experiment = AsyncMock(return_value={'cleanupConfirmed': True, 'independentResult': True,
                                                 'actualMetric': 1.25, 'originalRun': 'child-run'})
        self.preset = ResearchPreset('preset', 'Synthetic', 'fixed goal', 'alice', 'fixed instructions', {},
            {'totalSeconds': 600, 'experimentSeconds': 1, 'maxExperiments': 1},
            application_ref={'id': 'app'}, runtime_factory=self.factory, context_reader=self.context,
            candidate_validator=self.validator, experiment=self.experiment)
        self.store = Mock()
        self.store.cancellation_requested.return_value = False
        self.store.task.return_value = {'id': 'task', 'run_id': 'run', 'owner_id': 'alice'}
        self.store.resolve_run.return_value = {'id': 'plan'}
        self.effects = {}
        def reserve(run, key, payload):
            pin = digest(payload)
            if key in self.effects:
                old = self.effects[key]
                if old['pin'] != pin:
                    raise ValueError('EFFECT_CONFLICT')
                return {'status': 'done', 'result': old['result']} if 'result' in old else {'status': 'unknown'}
            self.effects[key] = {'pin': pin}
            return {'status': 'new'}
        def complete(run, key, result):
            self.effects[key]['result'] = deepcopy(result)
        self.store.effect_reserve.side_effect = reserve
        self.store.effect_complete.side_effect = complete
        self.store.effects.side_effect = lambda _task: [
            {'effect_key': 'run:' + key, 'status': 'DONE' if 'result' in value else 'UNKNOWN',
             'result': deepcopy(value.get('result'))} for key, value in self.effects.items()]
        self.commands = SimpleNamespace(submit=AsyncMock())
        self.bridge = SimpleNamespace(submit=AsyncMock())
        self.service = MemoryService(self.store, Mock(), self.bridge, {'preset': self.preset}, commands=self.commands)
        self.service.saved = {'fingerprint': digest({'preset': self.preset.fingerprint, 'goal': 'fixed goal'}),
            'body': {'id': 'task', 'ownerId': 'alice', 'presetId': 'preset', 'presetFingerprint': self.preset.fingerprint,
                     'requestId': 'original-request', 'goal': 'fixed goal', 'status': 'starting',
                     'steps': [], 'evidence': [], 'acceptance': dict.fromkeys(ACCEPTANCE, False),
                     'intents': {}, 'session': {'id': 'session'}, 'candidates': {}, 'results': {},
                     'experimentCount': 0, 'deadline': time.time() + 600}}


class AutoResearchServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_rejections_do_not_create_unknown_effects_or_call_external_work(self):
        cases = (
            ('research_context', {'unexpected': True}, 'TOOL_PAYLOAD'),
            ('research_candidate', {'hypothesis': '', 'trainPy': 'inert'}, 'CANDIDATE_PAYLOAD'),
            ('research_experiment', {'candidateId': 'missing'}, 'EXPERIMENT_BUDGET'),
            ('research_experiment', {'candidateId': []}, 'EXPERIMENT_PAYLOAD'),
            ('research_result', {'candidateId': 'missing'}, 'INDEPENDENT_RESULT_UNAVAILABLE'),
            ('research_decision', {'action': 'stop', 'reason': 'diagnostic finished'}, 'DECISION_WITHOUT_RESULT'),
            ('research_decision', {'action': [], 'reason': 'invalid'}, 'DECISION_PAYLOAD'),
            ('unregistered', {}, 'TOOL_NOT_REGISTERED'),
        )
        for name, payload, code in cases:
            with self.subTest(name=name, payload=payload):
                h = Harness()
                with self.assertRaisesRegex(ValueError, code):
                    await h.service.tool(h.ctx, name, {'_factoryCallId': 'rejected', **payload})
                h.store.effect_reserve.assert_not_called()
                h.context.assert_not_called(); h.experiment.assert_not_awaited()
                self.assertEqual(h.effects, {})
                self.assertEqual(h.service.saved['body']['experimentCount'], 0)

    async def test_candidate_validation_failure_precedes_reservation_and_done_replay_skips_validation(self):
        h = Harness()
        payload = {'_factoryCallId': 'candidate', 'hypothesis': 'bounded', 'trainPy': 'inert'}
        h.validator.side_effect = ValueError('synthetic invalid candidate')
        with self.assertRaisesRegex(ValueError, 'synthetic invalid candidate'):
            await h.service.tool(h.ctx, 'research_candidate', payload)
        h.store.effect_reserve.assert_not_called()
        h.validator.side_effect = None
        result = await h.service.tool(h.ctx, 'research_candidate', payload)
        h.validator.side_effect = AssertionError('must not validate an original DONE again')
        self.assertEqual(await h.service.tool(h.ctx, 'research_candidate', payload), result)
        with self.assertRaisesRegex(ValueError, 'EFFECT_CONFLICT'):
            await h.service.tool(h.ctx, 'research_candidate', {**payload, 'trainPy': 'changed'})

    async def test_exhausted_evidence_denies_new_work_but_preserves_done_replay(self):
        h = Harness()
        payload = {'_factoryCallId': 'context'}
        result = await h.service.tool(h.ctx, 'research_context', payload)
        h.service.saved['body']['steps'] = [{} for _ in range(256)]
        self.assertEqual(await h.service.tool(h.ctx, 'research_context', payload), result)
        h.store.effect_reserve.reset_mock()
        with self.assertRaisesRegex(ValueError, 'EVIDENCE_LIMIT'):
            await h.service.tool(h.ctx, 'research_context', {'_factoryCallId': 'new'})
        h.store.effect_reserve.assert_not_called()
        h.context.assert_called_once()

    async def test_experiment_deadline_stop_and_budget_reject_before_reservation(self):
        for fault in ('deadline', 'stop', 'budget', 'unavailable'):
            with self.subTest(fault=fault):
                h = Harness(); body = h.service.saved['body']
                body['candidates']['candidate'] = {'validated': {}}
                if fault == 'deadline': body['deadline'] = time.time() + .5
                if fault == 'stop': body['decision'] = {'action': 'stop'}
                if fault == 'budget': body['experimentCount'] = 1
                if fault == 'unavailable':
                    h.service.presets['preset'] = replace(h.preset, experiment=None)
                with self.assertRaises(ValueError):
                    await h.service.tool(h.ctx, 'research_experiment', {'_factoryCallId': 'call', 'candidateId': 'candidate'})
                h.store.effect_reserve.assert_not_called(); h.experiment.assert_not_awaited()

    async def test_historical_unknown_rejects_replay_before_changed_preconditions(self):
        h = Harness()
        payload = {'action': 'stop', 'reason': 'diagnostic finished'}
        h.store.effect_reserve('run', 'autoresearch-tool:historical', {'tool': 'research_decision', 'payload': payload})
        original = deepcopy(h.effects)
        with self.assertRaisesRegex(ValueError, 'RESEARCH_TOOL_ORIGINAL_UNKNOWN'):
            await h.service.tool(h.ctx, 'research_decision', {'_factoryCallId': 'historical', **payload})
        self.assertEqual(h.effects, original)
        self.assertFalse(h.service.saved['body']['acceptance']['nextDecision'])

    async def test_runtime_stop_cannot_settle_unknown_tool_or_complete_session(self):
        h = Harness()
        h.store.effect_reserve('run', 'autoresearch-tool:unknown', {'original': True})
        with self.assertRaisesRegex(ValueError, 'RESEARCH_TOOL_EFFECT_UNKNOWN'):
            await h.service.execute(h.ctx)
        h.runtime.stop.assert_awaited_once()
        h.store.effect_complete.assert_not_called()
        self.assertEqual(h.service.saved['body']['status'], 'unknown')
        self.assertEqual(h.service.projection('alice', 'task')['allowedActions'], ['cancel'])
        with self.assertRaisesRegex(ValueError, 'REQUIRES_RECONCILIATION'):
            await h.service.execute(h.ctx)
        h.runtime.run.assert_awaited_once()

    async def test_historical_done_with_unknown_tool_projects_unknown_without_rewriting_receipts(self):
        h = Harness()
        result = await h.service.execute(h.ctx)
        h.store.effect_reserve('run', 'autoresearch-tool:historical', {'original': True})
        original = deepcopy(h.effects)
        projection = h.service.projection('alice', 'task')
        self.assertEqual(projection['status'], 'unknown')
        self.assertEqual(projection['allowedActions'], ['cancel'])
        self.assertEqual(h.service.saved['body']['status'], 'completed')
        with self.assertRaisesRegex(ValueError, 'RESEARCH_TOOL_EFFECT_UNKNOWN'):
            await h.service.execute(h.ctx)
        self.assertEqual(h.effects, original)
        self.assertEqual(h.effects['autoresearch-session-v1']['result'], result)
        h.runtime.run.assert_awaited_once()

    async def test_rejected_decision_can_be_followed_by_clean_diagnostic_completion(self):
        h = Harness()
        async def diagnostic():
            await h.service.tool(h.ctx, 'research_context', {'_factoryCallId': 'context'})
            with self.assertRaisesRegex(ValueError, 'DECISION_WITHOUT_RESULT'):
                await h.service.tool(h.ctx, 'research_decision', {'_factoryCallId': 'stop',
                    'action': 'stop', 'reason': 'public diagnostic done'})
            return {'actual': 'diagnostic reply'}
        h.runtime.run.side_effect = diagnostic
        result = await h.service.execute(h.ctx)
        self.assertEqual(result['outcome'], 'completed')
        self.assertTrue(all('result' in effect for effect in h.effects.values()))
        self.assertEqual(h.service.projection('alice', 'task')['status'], 'completed')
        self.assertFalse(h.service.saved['body']['acceptance']['nextDecision'])

    async def test_missing_scientific_child_wiring_denies_before_plan_or_dispatch(self):
        h = Harness()
        h.preset = replace(h.preset, external_session=True)
        h.service.presets['preset'] = h.preset
        h.store.autoresearch_children = None
        self.assertFalse(h.service.list_presets('alice')[0]['ready'])
        with self.assertRaises(HTTPException) as caught:
            await h.service.start('alice', 'preset', None, 'new-original-request')
        self.assertEqual(caught.exception.status_code, 409)
        h.store.composition.propose.assert_not_called()
        h.bridge.submit.assert_not_called()

    async def test_candidate_identity_preserves_distinct_bytes_even_if_validator_summary_matches(self):
        h = Harness()
        one = await h.service.tool(h.ctx, 'research_candidate', {'_factoryCallId': 'one',
            'hypothesis': 'same hypothesis', 'trainPy': 'candidate one'})
        two = await h.service.tool(h.ctx, 'research_candidate', {'_factoryCallId': 'two',
            'hypothesis': 'same hypothesis', 'trainPy': 'candidate two'})
        self.assertNotEqual(one['candidateId'], two['candidateId'])
        saved = h.service.saved['body']['candidates']
        self.assertEqual(saved[one['candidateId']]['trainPy'], 'candidate one')
        self.assertEqual(saved[two['candidateId']]['trainPy'], 'candidate two')

    async def test_cleaned_failure_cannot_become_success_on_native_retry(self):
        h = Harness()
        h.runtime.run.side_effect = ValueError('synthetic failure')
        with self.assertRaisesRegex(ValueError, 'synthetic failure'):
            await h.service.execute(h.ctx)
        self.assertEqual(h.service.saved['body']['status'], 'failed')
        with self.assertRaisesRegex(ValueError, 'RESEARCH_ORIGINAL_SESSION_FAILED'):
            await h.service.execute(h.ctx)
        self.assertEqual(h.runtime.run.await_count, 1)
        self.assertEqual(h.runtime.stop.await_count, 1)

    async def test_current_checks_native_cancel_policy_binding_and_preset(self):
        h = Harness()
        self.assertIs(h.service.current(h.ctx), h.preset)
        h.store.require_plan_execution.assert_called_once_with('alice', {'id': 'plan'}, run_context=h.run)
        h.store.execution_bindings.recheck.assert_called_once_with({'id': 'plan'}, h.run)
        h.store.cancellation_requested.return_value = True
        with self.assertRaises(RunCancelledException): h.service.current(h.ctx)
        h.store.execution_bindings.recheck.assert_called_once()
        h.store.cancellation_requested.return_value = False
        h.service.presets['preset'] = replace(h.preset, instructions='changed')
        with self.assertRaises(ValueError): h.service.current(h.ctx)

    async def test_same_request_recovers_original_without_submit_and_conflict_denies(self):
        h = Harness()
        result = await h.service.start('alice', 'preset', 'fixed goal', 'original-request')
        self.assertEqual(result['id'], 'task')
        h.bridge.submit.assert_not_awaited(); h.store.reserve_task.assert_not_called()
        with self.assertRaises(HTTPException) as error:
            await h.service.start('alice', 'preset', 'different goal', 'original-request')
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException): h.service.projection('bob', 'task')

    async def test_cancel_uses_native_command_original_key_and_runtime_interrupt(self):
        h = Harness(); h.service.active['task'] = h.runtime
        await h.service.cancel('alice', 'task', 'original-cancel')
        args = h.commands.submit.await_args.args
        self.assertEqual(args[:2], ('alice', 'task'))
        self.assertEqual((args[2].commandId, args[2].action), ('original-cancel', 'cancel'))
        h.runtime.cancel.assert_awaited_once()
        self.assertEqual(h.service.saved['body']['status'], 'stopping')
        h.service.commands = None
        with self.assertRaises(HTTPException): await h.service.cancel('alice', 'task', 'another-cancel')
        h.runtime.cancel.assert_awaited_once()

    async def test_success_preserves_actual_result_and_done_effect_never_reruns(self):
        h = Harness()
        result = await h.service.execute(h.ctx)
        self.assertEqual(result['research'], {'actual': 'result'})
        self.assertFalse(result['scientificConclusionVerified'])
        self.assertTrue(result['allStopped'])
        self.assertEqual(await h.service.execute(h.ctx), result)
        h.factory.assert_called_once(); h.runtime.run.assert_awaited_once(); h.runtime.stop.assert_awaited_once()
        self.assertEqual(h.service.saved['body']['status'], 'completed')

    async def test_unconfirmed_cleanup_retains_unknown_effect_and_handles_no_replay(self):
        h = Harness(); h.runtime.stop.return_value = False
        with self.assertRaisesRegex(ValueError, 'STOP_PROOF_UNKNOWN'): await h.service.execute(h.ctx)
        self.assertEqual(h.service.saved['body']['status'], 'unknown')
        self.assertIn('task', h.service.active)
        self.assertIn('task', h.service.cleanups)
        h.store.effect_complete.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'REQUIRES_RECONCILIATION'): await h.service.execute(h.ctx)
        h.factory.assert_called_once(); h.runtime.stop.assert_awaited_once()

    async def test_repeated_native_cancellation_keeps_one_original_cleanup(self):
        h = Harness(); entered, release = asyncio.Event(), asyncio.Event()
        async def stop():
            entered.set(); await release.wait(); return True
        h.runtime.stop.side_effect = stop
        execution = asyncio.create_task(h.service.execute(h.ctx))
        await entered.wait()
        try:
            execution.cancel(); await asyncio.sleep(0)
            execution.cancel(); await asyncio.sleep(0)
            self.assertFalse(h.service.cleanups['task'].cancelled())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError): await execution
        h.runtime.stop.assert_awaited_once()
        self.assertEqual(h.service.saved['body']['status'], 'failed')
        self.assertEqual(h.store.effect_complete.call_count, 1)
        self.assertNotIn('task', h.service.active)

    async def test_tool_original_keys_budgets_and_result_preservation(self):
        h = Harness()
        context = await h.service.tool(h.ctx, 'research_context', {'_factoryCallId': 'context-1'})
        self.assertEqual(context, {'baseline': 'fixed'})
        await h.service.tool(h.ctx, 'research_context', {'_factoryCallId': 'context-1'})
        h.context.assert_called_once()
        candidate = await h.service.tool(h.ctx, 'research_candidate',
            {'_factoryCallId': 'candidate-1', 'hypothesis': 'synthetic', 'trainPy': 'inert'})
        payload = {'_factoryCallId': 'experiment-1', 'candidateId': candidate['candidateId']}
        result = await h.service.tool(h.ctx, 'research_experiment', payload)
        self.assertEqual(result, h.experiment.return_value)
        self.assertEqual(await h.service.tool(h.ctx, 'research_experiment', payload), result)
        h.experiment.assert_awaited_once()
        self.assertEqual(await h.service.tool(h.ctx, 'research_result',
            {'_factoryCallId': 'result-1', 'candidateId': candidate['candidateId']}), result)
        h.store.authorize_tool.assert_called_with(h.run, 'research_result')
        h.store.delegation.consume_tool_budget.assert_called_with(h.run, 'result-1', 'research_result')

    async def test_experiment_without_cleanup_never_completes_or_marks_acceptance(self):
        h = Harness()
        h.service.saved['body']['candidates']['candidate'] = {'validated': {}}
        h.experiment.return_value = {'cleanupConfirmed': False}
        with self.assertRaisesRegex(ValueError, 'CUSTODY_UNKNOWN'):
            await h.service.tool(h.ctx, 'research_experiment', {'_factoryCallId': 'call-1', 'candidateId': 'candidate'})
        h.store.effect_complete.assert_not_called()
        self.assertFalse(h.service.saved['body']['acceptance']['managedExperiment'])
        self.assertEqual(h.service.saved['body']['results'], {})
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_UNKNOWN'):
            await h.service.tool(h.ctx, 'research_experiment', {'_factoryCallId': 'call-1', 'candidateId': 'candidate'})
        h.experiment.assert_awaited_once()

    async def test_post_tool_revocation_prevents_effect_completion(self):
        h = Harness()
        def context():
            h.store.cancellation_requested.return_value = True
            return {'original': 'data'}
        h.context.side_effect = context
        with self.assertRaises(RunCancelledException):
            await h.service.tool(h.ctx, 'research_context', {'_factoryCallId': 'call-1'})
        h.store.effect_complete.assert_not_called()

    async def test_denied_tool_authority_reserves_no_effect(self):
        h = Harness()
        h.store.authorize_tool.side_effect = HTTPException(403)
        with self.assertRaises(HTTPException):
            await h.service.tool(h.ctx, 'research_context', {'_factoryCallId': 'denied'})
        h.store.effect_reserve.assert_not_called()
        h.store.delegation.consume_tool_budget.assert_not_called()
        h.context.assert_not_called()

    async def test_stop_intent_survives_revocation_but_original_identity_and_key_are_fixed(self):
        h = Harness(); h.store.cancellation_requested.return_value = True
        intent = {'operation': 'interrupt', 'key': 'original-stop', 'sessionId': 'session'}
        h.service.commit_stop_intent(h.ctx, intent=intent)
        self.assertEqual(h.service.saved['body']['intents']['original-stop'], intent)
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_STOP_UNKNOWN'):
            h.service.commit_stop_intent(h.ctx, intent=intent)
        with self.assertRaisesRegex(ValueError, 'STOP_IDENTITY_INVALID'):
            h.service.commit_stop_intent(h.ctx, intent={**intent, 'key': 'wrong', 'sessionId': 'replacement'})
        h.store.task.return_value['run_id'] = 'replacement-run'
        with self.assertRaisesRegex(ValueError, 'STOP_IDENTITY_INVALID'):
            h.service.commit_stop_intent(h.ctx, intent={**intent, 'key': 'another'})


if __name__ == '__main__':
    unittest.main()
