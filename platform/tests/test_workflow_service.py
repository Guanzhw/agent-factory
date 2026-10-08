"""SQLite durable journal with inert runtime: no model/process/live execution."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from sqlalchemy import create_engine
from fastapi import HTTPException

from agent_factory.workflow_contracts import workflow_fingerprint
from agent_factory.workflow_service import WorkflowService


def stage(identifier, deps=(), routes=None, human=False):
    return {'id': identifier, 'adapterId': 'inert', 'revision': '1', 'dependencies': list(deps),
            'inputs': {}, 'failureRoutes': routes or {}, 'humanGate': human}


class Runtime:
    def __init__(self):
        self.starts = []; self.records = {}; self.lost = False; self.outcome = 'COMPLETED'; self.cancel_stopped = True
    async def start(self, context, operation_id, inputs):
        self.starts.append((context, operation_id, inputs))
        result = {'schema': 1, 'operationId': operation_id, 'handle': {'adapterId': 'inert', 'revision': '1', 'id': operation_id},
                  'state': self.outcome, 'allStopped': self.outcome in {'COMPLETED', 'FAILED'},
                  'output': {'value': context.stage_id} if self.outcome == 'COMPLETED' else None,
                  'failure': {'schema': 1, 'code': 'BAD_INPUT', 'messageCode': 'CONTROLLED_FAILURE', 'retryable': False} if self.outcome == 'FAILED' else None}
        self.records[operation_id] = result
        if self.lost: raise ConnectionError('controlled lost ACK')
        return deepcopy(result)
    async def lookup(self, context, operation_id): return deepcopy(self.records[operation_id])
    async def inspect(self, context, handle): return deepcopy(self.records[handle['id']])
    async def cancel(self, context, handle):
        result = deepcopy(self.records[handle['id']])
        result.update(state='CANCELLED' if self.cancel_stopped else 'UNKNOWN', allStopped=self.cancel_stopped, output=None, failure=None)
        return result


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.engine = create_engine('sqlite:///' + str(Path(self.temp.name) / 'journal.db')); self.addCleanup(self.engine.dispose)
        self.runtime = Runtime(); self.auth = SimpleNamespace(require=Mock())
        self.ctx = SimpleNamespace(user_id='alice', session_id='task', run_id='native')
        self.task = {'id': 'task', 'owner_id': 'alice', 'run_id': 'native', 'plan_id': 'plan', 'terminal': False, 'cancel_requested': False}
        self.plan = {'ownerId': 'alice', 'applicationRef': {'id': 'approved', 'version': 1, 'sha256': 'a'*64}, 'inputValues': {'goal': 'synthetic'}}
        self.store = SimpleNamespace(engine=self.engine, task=self.get_task, authorize_tool=Mock(side_effect=lambda *args: deepcopy(self.plan)))
        self.build([stage('A'), stage('B', ['A'])])
    def get_task(self, identifier, owner):
        if identifier != 'task' or owner != 'alice': raise PermissionError('owner')
        return deepcopy(self.task)
    def build(self, stages, maximum=2):
        if self._testMethodName in {'test_failure_routes_require_matching_failure', 'test_recovered_failure_satisfies_join_and_finish'}:
            stages = [stage('A', routes={'BAD_INPUT': 'B'}), stage('B', ['A'])]
            if self._testMethodName == 'test_recovered_failure_satisfies_join_and_finish':
                stages.append(stage('join', ['A']))
        elif self._testMethodName == 'test_human_version_idempotency':
            stages = [stage('A', human=True)]
        elif self._testMethodName == 'test_parallel_join_and_capacity':
            stages = [stage('A'), stage('B'), stage('join', ['A', 'B'])]; maximum = 1
        elif self._testMethodName == 'test_finish_skips_inactive_route_without_changing_source':
            stages = [stage('A', routes={'BAD_INPUT': 'B'}), stage('B', ['A'])]
        self.definition = {'schema': 1, 'id': 'work', 'revision': '1', 'maxParallel': maximum, 'stages': stages}
        self.plan['executionBindings'] = {'tools': [{'toolName': name, 'adapterId': 'workflow-' + name.removeprefix('workflow_') + '-v1', 'revision': '1', 'config': {'workflowId': 'work', 'workflowSha256': workflow_fingerprint(self.definition)}} for name in ('workflow_read', 'workflow_choose', 'workflow_inspect', 'workflow_wait', 'workflow_finish')]}
        self.plan['tools'] = [spec['toolName'] for spec in self.plan['executionBindings']['tools']]
        self.service = WorkflowService(self.store, self.auth, definitions={'work': self.definition}, runtimes={('inert', '1'): self.runtime})
        self.body = self.service.open(self.ctx, 'open')
    async def test_original_inputs_dependencies_and_command_replay(self):
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'B', 'too-early')
        a = await self.service.choose(self.ctx, 'A', 'a')
        self.assertEqual(await self.service.choose(self.ctx, 'A', 'a'), a)
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'B', 'a')
        await self.service.choose(self.ctx, 'B', 'b')
        self.assertEqual(len(self.runtime.starts), 2)
        self.assertEqual(self.runtime.starts[1][2]['values'], {'goal': 'synthetic'})
        self.assertEqual(self.runtime.starts[1][2]['dependencies']['A']['operationId'], a['stages']['A']['operationId'])
    async def test_lost_ack_restart_never_restarts_original_lookup_recovers(self):
        self.runtime.lost = True
        with self.assertRaises(ConnectionError): await self.service.choose(self.ctx, 'A', 'a')
        restored = WorkflowService(self.store, self.auth, definitions={'work': self.definition}, runtimes={('inert', '1'): self.runtime})
        body = restored.for_task('alice', 'task'); assert body is not None
        self.assertTrue(restored.task_held('task'))
        self.assertEqual((await restored.choose(self.ctx, 'A', 'a'))['stages']['A']['state'], 'UNKNOWN')
        with self.assertRaises(ValueError): await restored.choose(self.ctx, 'A', 'replacement')
        result = await restored.reconcile(self.ctx, 'A', 'lookup', expected_version=body['version'])
        self.assertEqual(result['stages']['A']['state'], 'COMPLETED'); self.assertEqual(len(self.runtime.starts), 1)
    async def test_cancellation_requires_positive_original_stop(self):
        self.runtime.outcome = 'RUNNING'
        await self.service.choose(self.ctx, 'A', 'a')
        self.runtime.cancel_stopped = False
        self.assertFalse(await self.service.cancel('alice', self.body['id']))
        self.runtime.cancel_stopped = True
        self.assertTrue(await self.service.cancel('alice', self.body['id']))
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'B', 'b')
    async def test_plan_drift_and_foreign_owner_denied(self):
        with self.assertRaises(ValueError): self.service.read('bob', self.body['id'])
        self.plan['inputValues']['goal'] = 'changed'
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'A', 'a')
        self.assertEqual(self.runtime.starts, [])
    async def test_runtime_handle_replacement_is_rejected(self):
        self.runtime.outcome = 'RUNNING'; body = await self.service.choose(self.ctx, 'A', 'a')
        operation = body['stages']['A']['operationId']; self.runtime.records[operation]['handle']['id'] = 'replacement'
        with self.assertRaises(ValueError): await self.service.inspect(self.ctx, 'A')
    async def test_unknown_without_handle_stays_held_after_cancel(self):
        self.runtime.lost = True
        setattr(self.runtime, 'lookup', None)
        with self.assertRaises(ConnectionError): await self.service.choose(self.ctx, 'A', 'a')
        self.assertFalse(await self.service.cancel('alice', self.body['id']))


    async def test_failure_routes_require_matching_failure(self):
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'B', 'premature')
        self.runtime.outcome = 'FAILED'; await self.service.choose(self.ctx, 'A', 'a')
        self.runtime.outcome = 'COMPLETED'; result = await self.service.choose(self.ctx, 'B', 'b')
        self.assertEqual(result['stages']['B']['state'], 'COMPLETED')
    async def test_human_version_idempotency(self):
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'A', 'early')
        with self.assertRaises(ValueError): self.service.decide(self.ctx, 'A', True, 'wrong', expected_version=9)
        approved = self.service.decide(self.ctx, 'A', True, 'decision', expected_version=0)
        self.assertEqual(self.service.decide(self.ctx, 'A', True, 'decision', expected_version=0), approved)
        await self.service.resume(self.ctx, 'A', 'resume', expected_version=approved['version'])
        with self.assertRaises(ValueError): await self.service.resume(self.ctx, 'A', 'again', expected_version=approved['version'])
    async def test_parallel_join_and_capacity(self):
        self.runtime.outcome = 'RUNNING'; a = await self.service.choose(self.ctx, 'A', 'a')
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'B', 'b')
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'join', 'join')
        self.runtime.records[a['stages']['A']['operationId']].update(state='COMPLETED', allStopped=True, output={})
        await self.service.inspect(self.ctx, 'A'); self.runtime.outcome = 'COMPLETED'
        await self.service.choose(self.ctx, 'B', 'b'); await self.service.choose(self.ctx, 'join', 'join')

    async def test_recovered_failure_satisfies_join_and_finish(self):
        self.runtime.outcome = 'FAILED'; await self.service.choose(self.ctx, 'A', 'a')
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'join', 'early')
        self.runtime.outcome = 'COMPLETED'; await self.service.choose(self.ctx, 'B', 'b')
        await self.service.choose(self.ctx, 'join', 'join')
        self.assertTrue(self.service.task_held('task'))
        body = self.service.finish(self.ctx, 'finish')
        self.assertEqual(body['status'], 'COMPLETED')
        self.assertEqual(body['stages']['A']['state'], 'FAILED')
        self.assertFalse(self.service.task_held('task'))

    async def test_finish_skips_inactive_route_without_changing_source(self):
        with self.assertRaises(ValueError): self.service.finish(self.ctx, 'early')
        await self.service.choose(self.ctx, 'A', 'a')
        result = self.service.finish(self.ctx, 'finish')
        self.assertEqual(result['stages']['A']['state'], 'COMPLETED')
        self.assertEqual(result['stages']['B']['state'], 'SKIPPED')

    async def test_concurrent_choose_does_not_duplicate_start(self):
        import asyncio
        original = self.runtime.start
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(*args):
            entered.set(); await release.wait()
            return await original(*args)
        setattr(self.runtime, 'start', blocked)
        first = asyncio.create_task(self.service.choose(self.ctx, 'A', 'original'))
        await entered.wait()
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'A', 'competing')
        replay = await self.service.choose(self.ctx, 'A', 'original')
        self.assertEqual(replay['stages']['A']['state'], 'UNKNOWN')
        release.set(); await first
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_lost_start_cancel_recovers_original_handle_without_dispatch(self):
        self.runtime.lost = True; self.runtime.outcome = 'RUNNING'
        with self.assertRaises(ConnectionError): await self.service.choose(self.ctx, 'A', 'a')
        restored = WorkflowService(self.store, self.auth, definitions={'work': self.definition}, runtimes={('inert', '1'): self.runtime})
        self.store.authorize_tool.side_effect = PermissionError('execution revoked')
        self.assertTrue(await restored.cancel_task('alice', 'task'))
        self.assertEqual(len(self.runtime.starts), 1)
        self.assertFalse(restored.task_held('task'))

    async def test_current_guard_withdrawal_drift_and_runtime_removal_no_authorization_recursion(self):
        self.store.authorize_tool.reset_mock()
        self.assertEqual(self.service.require_plan_current('alice', self.plan), self.definition)
        self.store.authorize_tool.assert_not_called()
        self.assertIsNone(self.service.require_plan_current('bob', {'tools': ['unrelated']}))
        original = deepcopy(self.service.definitions['work'])
        self.service.definitions['work']['revision'] = 'withdrawn'
        with self.assertRaises(HTTPException) as failed:
            self.service.require_plan_current('alice', self.plan)
        self.assertEqual(failed.exception.status_code, 409)
        self.service.definitions['work'] = original
        self.service.runtimes.clear()
        with self.assertRaises(HTTPException): self.service.require_plan_current('alice', self.plan)
        self.service.definitions.clear()
        with self.assertRaises(HTTPException): self.service.require_plan_current('alice', self.plan)
        self.assertEqual(self.runtime.starts, [])

    async def test_completed_cleanup_preserves_outcome_and_version(self):
        await self.service.choose(self.ctx, 'A', 'a'); await self.service.choose(self.ctx, 'B', 'b')
        original = self.service.finish(self.ctx, 'finish')
        self.store.authorize_tool.side_effect = PermissionError('execution ended')
        self.assertTrue(await self.service.cancel_task('alice', 'task'))
        self.assertEqual(self.service.read('alice', original['id']), original)

    async def test_cancelled_cleanup_preserves_original_terminal(self):
        self.assertTrue(await self.service.cancel_task('alice', 'task'))
        original = self.service.read('alice', self.body['id'])
        self.assertTrue(await self.service.cancel_task('alice', 'task'))
        self.assertEqual(self.service.read('alice', self.body['id']), original)

    async def test_business_workflow_prefix_is_not_a_reserved_core_namespace(self):
        business = {'ownerId': 'bob', 'tools': ['workflow_export'], 'executionBindings': {'tools': [
            {'toolName': 'workflow_export', 'adapterId': 'business-export', 'revision': 'custom', 'config': {}}]}}
        self.assertIsNone(self.service.require_plan_current('bob', business))
        mixed = deepcopy(self.plan)
        mixed['tools'].append('workflow_export')
        mixed['executionBindings']['tools'].extend(business['executionBindings']['tools'])
        self.assertEqual(self.service.require_plan_current('alice', mixed), self.definition)
