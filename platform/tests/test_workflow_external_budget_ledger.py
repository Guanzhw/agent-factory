"""Native wait + OperationCustody with actual SQLite delegation budget rows.

Only PostgreSQL advisory locking/ANY syntax are adapted. Native bridge replies
are synthetic; this is ledger coverage, not queue or physical-stop acceptance.
"""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agent_factory.delegation import DelegationService
from agent_factory.store import canonical, digest
from agent_factory.workflow_control import WorkflowCommand, WorkflowControl
import test_workflow_control as fixtures


class ExternalBudgetLedgerTests(unittest.IsolatedAsyncioTestCase):
    external = fixtures.WorkflowControlTests.external

    def setUp(self):
        # Reuse setup on this case: cleanup stays owned by its actual async runner.
        fixtures.WorkflowControlTests.setUp(self)
        self.plan.update(status='ready', tools=['factory_wait_operations'], budget={'toolCalls': 1})
        self.store.sql('UPDATE af_plans SET body=:body,hash=:hash', body=canonical(self.plan), hash=digest(self.plan))
        self.store.sql("ALTER TABLE af_tasks ADD COLUMN admission TEXT DEFAULT 'accepted'")
        original_sql = self.store.sql
        def sql(query, **parameters):
            if 'task_id=ANY(:ids)' in query:
                identifiers = parameters.pop('ids')
                names = [f'budget_id_{index}' for index in range(len(identifiers))]
                query = query.replace('task_id=ANY(:ids)', 'task_id IN (' + ','.join(':' + name for name in names) + ')')
                parameters.update(zip(names, identifiers))
            return original_sql(query, **parameters)
        self.store.sql = sql
        self.store.require_current_policy = Mock()
        self.store.has_failures = lambda task: False
        self.store.material_governance = None
        self.native['queue'].update(session_id='task', user_id='alice', component_type='workflow', component_id='controlled-workflow')
        self.store.native_db = SimpleNamespace(get_job=lambda identifier: deepcopy(self.native['queue']))
        self.store.event = Mock()
        self.reopen()
        self.store.delegation.initialize()

    def reopen(self):
        self.store.delegation = DelegationService(None, self.store, self.auth, self.bridge)
        self.store.delegation._root_lock = lambda root: nullcontext()
        self.control = WorkflowControl(self.service, self.api)

    def rows(self):
        return self.store.sql('SELECT * FROM af_delegation_tool_calls ORDER BY call_id')

    async def test_original_native_call_once_reopen_and_second_call_exhausted(self):
        operation, command = await self.external()
        self.assertEqual(self.rows(), [])
        await self.control.submit('alice', 'task', command)
        first = self.rows()
        self.assertEqual(len(first), 1)
        self.assertEqual((first[0]['call_id'], first[0]['tool_name']),
                         ('native-wait:' + digest({'stepId': 'wait', 'toolCallId': 'original-native-call'}), 'factory_wait_operations'))
        self.reopen()
        await self.control.submit('alice', 'task', command)
        self.assertEqual(self.rows(), first)
        context = self.control.context(self.store.task('task', 'alice'))
        self.assertFalse(self.store.delegation.consume_tool_budget(context,
            first[0]['call_id'], 'factory_wait_operations')['charged'])
        with self.assertRaises(PermissionError):
            self.store.delegation.consume_tool_budget(context, 'replacement-call', 'factory_wait_operations')
        self.assertEqual(self.rows(), first)
        self.assertEqual(self.runtime.starts, [operation['id']])
        self.assertEqual(self.bridge.continue_run.await_count, 1)

    async def test_unknown_before_completion_no_charge_and_custody_held(self):
        operation, command = await self.external()
        async def unknown(context, identifier):
            return {'schema': 1, 'operationId': identifier, 'handle': None, 'state': 'UNKNOWN',
                    'allStopped': False, 'output': None, 'failure': None}
        self.runtime.lookup = unknown
        await self.control.submit('alice', 'task', command)
        self.assertEqual(self.rows(), [])
        self.assertTrue(self.service.task_held('task'))
        self.assertFalse(await self.service.cancel_task('alice', 'task'))
        self.assertTrue(self.service.task_held('task'))
        self.assertEqual(self.runtime.starts, [operation['id']])
        self.bridge.continue_run.assert_not_awaited()

    async def test_prior_charge_survives_another_unknown_operation_and_cleanup(self):
        operation, command = await self.external()
        await self.control.submit('alice', 'task', command)
        first = self.rows()
        context = self.control.context(self.store.task('task', 'alice'))
        second = await self.service.start(context, 'second-step', 'slot', self.pin, {})
        self.runtime.lookup = None
        self.reopen()
        self.assertFalse(await self.service.cancel_task('alice', 'task'))
        self.assertTrue(self.service.task_held('task'))
        self.assertEqual(self.rows(), first)
        self.assertEqual(len(first), 1)
        self.assertFalse(self.store.sql('SELECT reclaimed FROM af_delegation_roots')[0]['reclaimed'])
        self.assertEqual(self.runtime.starts, [operation['id'], second['id']])

    async def test_different_wait_step_same_provider_call_cannot_borrow_first_charge(self):
        operation, command = await self.external()
        await self.control.submit('alice', 'task', command)
        original_rows = self.rows()
        self.assertEqual(len(original_rows), 1)
        self.assertEqual(self.bridge.continue_run.await_count, 1)
        self.reopen()
        # The provider may reuse its own call ID in a different native Agent step.
        # The original completed operation is readable, but this is a new wait.
        requirement = deepcopy(self.requirement)
        requirement['step_id'] = 'second-wait'
        self.native['step_requirements'] = [requirement]
        view = (await self.control.snapshot('alice', 'task'))['workflow']
        second = WorkflowCommand(commandId='second-wait-command', action='reconcile',
                                 version=view['version'], operationId=operation['id'])
        result = await self.control.submit('alice', 'task', second)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(self.rows(), original_rows)
        self.assertEqual(self.bridge.continue_run.await_count, 1)
        self.assertEqual(self.runtime.starts, [operation['id']])
        record = self.control._load('alice', 'task', second.commandId)
        self.assertEqual(record['errorType'], 'PermissionError')
