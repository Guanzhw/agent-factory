"""SQLite durable journal with inert runtime: no model/process/live execution."""
from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event
from fastapi import HTTPException

from agent_factory.workflow_contracts import WorkflowAcknowledgementUnknown, workflow_fingerprint
from agent_factory.workflow_service import WorkflowService, require_workflow_plan_current


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
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.directory = self.resources.enter_context(tempfile.TemporaryDirectory())
        self.engine = create_engine('sqlite:///' + str(Path(self.directory) / 'journal.db'))
        # Register immediately, before creating any journal or test double.
        # LIFO closes pooled SQLite handles before removing the directory.
        self.resources.callback(self.engine.dispose)
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
        elif self._testMethodName == 'test_cancel_failure_does_not_skip_other_original_handles':
            stages = [stage('A'), stage('B')]
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

    async def test_cancel_failure_does_not_skip_other_original_handles(self):
        self.runtime.outcome = 'RUNNING'
        await self.service.choose(self.ctx, 'A', 'a')
        original = await self.service.choose(self.ctx, 'B', 'b')
        original_cancel = self.runtime.cancel
        attempted = []
        async def cancel(context, handle):
            attempted.append(context.stage_id)
            if context.stage_id == 'A':
                raise ConnectionError('controlled unknown cancellation acknowledgment')
            return await original_cancel(context, handle)
        setattr(self.runtime, 'cancel', cancel)
        self.assertFalse(await self.service.cancel_task('alice', 'task'))
        self.assertEqual(attempted, ['A', 'B'])
        current = self.service.read('alice', self.body['id'])
        self.assertEqual(current['stages']['A']['state'], 'RUNNING')
        self.assertEqual(current['stages']['B']['state'], 'CANCELLED')
        for stage_id in ('A', 'B'):
            self.assertEqual(current['stages'][stage_id]['handle'], original['stages'][stage_id]['handle'])
        self.assertTrue(self.service.task_held('task'))
        self.assertEqual(len(self.runtime.starts), 2)

    async def test_nested_fixture_failed_setup_disposes_sqlite_before_directory_removal(self):
        nested = WorkflowTests('test_original_inputs_dependencies_and_command_replay')
        closed = []
        real_service = WorkflowService
        def fail_after_database_open(*args, **kwargs):
            real_service(*args, **kwargs)
            event.listen(nested.engine, 'close', lambda connection, record: closed.append(Path(nested.directory).exists()))
            raise RuntimeError('controlled setup failure after SQLite journal creation')
        try:
            with patch(__name__ + '.WorkflowService', side_effect=fail_after_database_open):
                with self.assertRaisesRegex(RuntimeError, 'controlled setup failure'):
                    nested.setUp()
            self.assertTrue(Path(nested.directory, 'journal.db').is_file())
            nested.resources.close()
            self.assertEqual(closed, [True], 'Close SQLite while its directory still exists, before deleting files')
            self.assertFalse(Path(nested.directory).exists())
            nested.resources.close()  # Explicit owner cleanup is idempotent.
        finally:
            nested.resources.close()

    async def test_readonly_plan_guard_never_constructs_service_or_touches_database(self):
        with patch('agent_factory.workflow_service.WorkflowService.__init__', side_effect=AssertionError('No service construction')), \
                patch.object(self.engine, 'begin', side_effect=AssertionError('No transactions')), \
                patch.object(self.engine, 'connect', side_effect=AssertionError('No database reads')):
            result = require_workflow_plan_current('alice', self.plan,
                definitions={'work': self.definition}, runtimes={('inert', '1'): self.runtime})
            self.assertEqual(result, self.definition)
            assert result is not None
            result['revision'] = 'detached'
            self.assertEqual(self.definition['revision'], '1')
            self.assertIsNone(require_workflow_plan_current('alice', {'tools': ['workflow_export']}, definitions={}, runtimes={}))
            with self.assertRaises(HTTPException) as error:
                require_workflow_plan_current('alice', self.plan, definitions={}, runtimes={})
            self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.runtime.starts, [])

    def typed_unknown_start(self, after_start=lambda: None):
        original = self.runtime.start
        async def uncertain(context, operation_id, inputs):
            await original(context, operation_id, inputs)
            after_start()
            raise WorkflowAcknowledgementUnknown()
        setattr(self.runtime, 'start', uncertain)

    async def test_typed_start_unknown_retains_original_identity_and_lookup_recovers(self):
        self.typed_unknown_start()
        unknown = await self.service.choose(self.ctx, 'A', 'original')
        operation_id = unknown['stages']['A']['operationId']
        self.assertEqual(unknown['stages']['A']['state'], 'UNKNOWN')
        self.assertIsNone(unknown['stages']['A']['handle'])
        self.assertTrue(self.service.task_held('task'))
        self.assertEqual(await self.service.choose(self.ctx, 'A', 'original'), unknown)
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'A', 'replacement')
        self.assertEqual(len(self.runtime.starts), 1)
        recovered = await self.service.reconcile(self.ctx, 'A', 'lookup-original', expected_version=unknown['version'])
        self.assertEqual(recovered['stages']['A']['operationId'], operation_id)
        self.assertEqual(recovered['stages']['A']['state'], 'COMPLETED')
        self.assertEqual(recovered['stages']['A']['handle']['id'], operation_id)
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_typed_unknown_does_not_swallow_fresh_authority_revocation(self):
        denied = PermissionError('controlled authority revoked after dispatch')
        self.typed_unknown_start(lambda: setattr(self.store.authorize_tool, 'side_effect', denied))
        with self.assertRaises(PermissionError) as caught:
            await self.service.choose(self.ctx, 'A', 'original')
        self.assertIs(caught.exception, denied)
        self.assertTrue(self.service.task_held('task'))
        self.assertEqual(len(self.runtime.starts), 1)

    async def test_typed_unknown_does_not_swallow_current_task_cancel(self):
        self.typed_unknown_start(lambda: self.task.update(cancel_requested=True))
        with self.assertRaises(ValueError): await self.service.choose(self.ctx, 'A', 'original')
        retained = self.service.read('alice', self.body['id'])
        self.assertEqual(retained['stages']['A']['state'], 'UNKNOWN')
        self.assertTrue(self.service.task_held('task'))

    async def test_ordinary_start_error_propagates_exact_exception(self):
        error = ConnectionError('controlled ordinary transport failure')
        original = self.runtime.start
        async def failed(context, operation_id, inputs):
            await original(context, operation_id, inputs)
            raise error
        setattr(self.runtime, 'start', failed)
        with self.assertRaises(ConnectionError) as caught:
            await self.service.choose(self.ctx, 'A', 'original')
        self.assertIs(caught.exception, error)
        self.assertTrue(self.service.task_held('task'))

    async def test_start_cancellation_propagates_exact_exception(self):
        import asyncio
        error = asyncio.CancelledError()
        original = self.runtime.start
        async def cancelled(context, operation_id, inputs):
            await original(context, operation_id, inputs)
            raise error
        setattr(self.runtime, 'start', cancelled)
        with self.assertRaises(asyncio.CancelledError) as caught:
            await self.service.choose(self.ctx, 'A', 'original')
        self.assertIs(caught.exception, error)
        self.assertTrue(self.service.task_held('task'))
        self.assertEqual(len(self.runtime.starts), 1)
