"""Native Workflow route/identity contracts, without a worker or model execution."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from agno.db.base import SessionType
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from agent_factory.auth import EXECUTOR_ID
from agent_factory.native_bridge import NativeBridge


class NativeWorkflowBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = str(uuid4())
        self.pin = {'kind': 'workflow', 'id': 'operator-flow', 'revision': '1', 'sha256': 'a' * 64}
        self.ticket = {'id': 'run', 'session_id': self.session, 'user_id': 'alice',
                       'component_type': 'workflow', 'component_id': 'operator-flow', 'status': 'paused'}
        self.db = SimpleNamespace(id='db', get_job=Mock(side_effect=lambda _: deepcopy(self.ticket)), get_session=Mock())
        self.bridge = NativeBridge(None, self.db, SimpleNamespace(require=Mock()))
        self.bridge.configure_components(lambda session, owner: deepcopy(self.pin))
        self.http = AsyncMock(return_value={'run_id': 'run', 'workflow_id': 'operator-flow'})
        self.bridge._request = self.http
        self.plan = {'id': 'plan', 'ownerId': 'alice', 'task_id': self.session,
                     'nativeComponent': self.pin, 'inputValues': {'goal': 'controlled'}}

    async def test_registered_component_punctuation_matches_native_pin_contract(self):
        for identifier in ('local.workflow:v1', 'local_flow-1', 'w' * 100):
            with self.subTest(identifier=identifier):
                self.pin['id'] = identifier
                await self.bridge.submit(self.plan, 'alice', 'request')
                self.assertEqual(self.http.call_args.args[1],
                    '/workflows/' + identifier.replace(':', '%3A') + '/runs')

    async def test_submit_keeps_original_envelope_and_workflow_inputs(self):
        await self.bridge.submit(self.plan, 'alice', 'request')
        args, kwargs = self.http.call_args
        self.assertEqual(args, ('POST', '/workflows/operator-flow/runs', 'alice'))
        self.assertEqual(json.loads(kwargs['data']['message']), self.plan['inputValues'])
        self.assertEqual(json.loads(kwargs['data']['session_state'])['factory_envelope'],
                         {'plan_ref': 'plan', 'user_id': 'alice', 'task_id': self.session, 'request_id': 'request'})
        self.assertEqual(kwargs['data']['background'], 'true')
        self.assertEqual(kwargs['data']['stream'], 'false')
        for field, replacement in [('sha256', 'b' * 64), ('revision', '2'), ('id', 'different')]:
            plan = deepcopy(self.plan); plan['nativeComponent'][field] = replacement
            with self.subTest(field=field), self.assertRaises(HTTPException):
                await self.bridge.submit(plan, 'alice', 'request')
        self.assertEqual(self.http.await_count, 1)

    async def test_continue_preserves_entire_step_requirement_and_original_route(self):
        requirements = [{'step_id': 'step-1', 'step_name': 'review', 'step_index': 0,
                         'confirmation': True, 'user_input': {'approved': True}}]
        await self.bridge.continue_run('run', self.session, 'alice', requirements,
                                       command_proof={'commandId': 'command'})
        args, kwargs = self.http.call_args
        self.assertEqual(args[1], '/workflows/operator-flow/runs/run/continue')
        self.assertEqual(json.loads(kwargs['data']['step_requirements']), requirements)
        self.assertNotIn('tools', kwargs['data'])
        # Agno workflow continuation does not persist agent metadata proofs.
        self.assertNotIn('metadata', kwargs['data'])
        await self.bridge.cancel_run('run', self.session, 'alice')
        self.assertEqual(self.http.call_args.args[1], '/workflows/operator-flow/runs/run/cancel')

    async def test_detail_validates_original_queue_identity(self):
        result = await self.bridge.detail('run', self.session, 'alice')
        self.assertEqual(result['queue'], self.ticket)
        for key in ('id', 'session_id', 'user_id', 'component_type', 'component_id'):
            old = self.ticket[key]; self.ticket[key] = 'foreign'
            with self.subTest(key=key), self.assertRaises(HTTPException):
                await self.bridge.detail('run', self.session, 'alice')
            self.ticket[key] = old

    async def test_read_only_fallback_retains_native_step_requirements(self):
        value = {'run_id': 'run', 'workflow_id': 'operator-flow', 'step_requirements': [{'step_id': 'review'}]}
        run = SimpleNamespace(run_id='run', workflow_id='operator-flow', to_dict=lambda: deepcopy(value))
        self.db.get_session.return_value = SimpleNamespace(workflow_id='operator-flow', user_id='alice', runs=[run])
        self.http.side_effect = [HTTPException(403), {'run_id': 'run', 'workflow_id': 'operator-flow'}]
        result = await self.bridge.detail('run', self.session, 'alice')
        self.assertEqual(result['step_requirements'], value['step_requirements'])
        self.assertTrue(result['readOnly'])
        self.db.get_session.assert_called_once_with(self.session, session_type=SessionType.WORKFLOW, user_id='alice')

    async def test_find_run_filters_component_and_owner_in_actual_sql(self):
        engine = create_engine('sqlite:///:memory:'); self.addCleanup(engine.dispose)
        self.db.db_engine, self.db.job_table_name = engine, 'jobs'
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE jobs (id TEXT, session_id TEXT, user_id TEXT, component_type TEXT, component_id TEXT, status TEXT)'))
            rows = [self.ticket, dict(self.ticket, id='foreign', user_id='bob'),
                    dict(self.ticket, id='agent', component_type='agent', component_id=EXECUTOR_ID)]
            conn.execute(text('INSERT INTO jobs VALUES(:id,:session_id,:user_id,:component_type,:component_id,:status)'), rows)
        result = await self.bridge.find_run(self.session, 'alice')
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result['run_id'], 'run')
        self.http.assert_not_awaited()
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO jobs VALUES(:id,:session_id,:user_id,:component_type,:component_id,:status)'), dict(self.ticket, id='duplicate'))
        with self.assertRaises(HTTPException) as raised:
            await self.bridge.find_run(self.session, 'alice')
        self.assertEqual(raised.exception.status_code, 409)

    async def test_default_agent_routes_and_tools_unchanged(self):
        bridge = NativeBridge(None, self.db, SimpleNamespace(require=Mock()))
        bridge._request = AsyncMock(return_value={})
        plan = dict(self.plan); del plan['nativeComponent']
        await bridge.submit(plan, 'alice', 'request')
        self.assertEqual(bridge._request.call_args.args[1], f'/agents/{EXECUTOR_ID}/runs')
        requirement = {'tool_execution': {'tool_call_id': 'original', 'result': 'approved'}}
        await bridge.continue_run('run', self.session, 'alice', [requirement], command_proof={'commandId': 'original'})
        self.assertEqual(json.loads(bridge._request.call_args.kwargs['data']['tools']), [requirement['tool_execution']])
        self.assertIn('metadata', bridge._request.call_args.kwargs['data'])

    async def test_workflow_cannot_enter_agent_approved_repair(self):
        with self.assertRaises(HTTPException):
            await self.bridge.continue_approved_run('run', self.session, 'alice', [], command_proof={},
                original_proof={}, tools_sha256='a' * 64, paused_requirements_sha256='b' * 64)
        self.http.assert_not_awaited()

    async def test_configured_resolver_keeps_legacy_agent_plan_compatible(self):
        self.pin.update(kind='agent', id=EXECUTOR_ID)
        plan = dict(self.plan); del plan['nativeComponent']
        await self.bridge.submit(plan, 'alice', 'legacy')
        self.assertEqual(self.http.call_args.args[1], f'/agents/{EXECUTOR_ID}/runs')
        plan['nativeComponent'] = deepcopy(self.pin)
        await self.bridge.submit(plan, 'alice', 'explicit')
        plan['nativeComponent']['sha256'] = 'b' * 64
        with self.assertRaises(HTTPException):
            await self.bridge.submit(plan, 'alice', 'changed')
        self.assertEqual(self.http.await_count, 2)
