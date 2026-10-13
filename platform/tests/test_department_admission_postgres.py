"""Department self-service over isolated PostgreSQL and the real native queue.

All users, models, applications and Workflow steps are synthetic. The existing
UNKNOWN/cancellation suites retain the separate external-stop proof.
"""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnError, StepInput, StepOutput
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory_research.config import ResearchSettings as Settings
from agent_factory.input_schema import input_model
from agent_factory_server.main import create_app
from agent_factory.native_workflows import NativeWorkflowRegistration
from pg_fixture import IsolatedPostgres
from test_applications_composition import app_definition, pin


WORKFLOW_ID = 'department-synthetic-workflow-v1'
INPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['goal'],
    'properties': {'goal': {'type': 'string', 'maxLength': 100}}}


def synthetic_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content={'evidenceKind': 'synthetic', 'received': step_input.input})


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class DepartmentAdmissionPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = TemporaryDirectory(prefix='department-admission-')
        self.addCleanup(self.directory.cleanup)
        workflow = Workflow(id=WORKFLOW_ID, name='Department synthetic Workflow',
            input_schema=input_model(INPUT_SCHEMA), telemetry=False,
            steps=[Step(name='checksum', step_id='department-summary', executor=synthetic_step,
                max_retries=0, human_review=HumanReview(on_error=OnError.fail))])
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name),
            max_workers=1, max_user_tasks=3, temporary_policy='admin-review',
            policy_revision='department-legacy-fixture',
            native_workflows=(NativeWorkflowRegistration(workflow, '1', ('checksum',), 'd' * 64),))
        # Explicit fixture mode also works before shared Settings assembly lands.
        self.settings.material_review_mode = 'member-self-service'
        self.settings.material_policy_revision = 'department-material-fixture'
        if 'legacy' not in self._testMethodName:
            self.member_mode()
        self.start()
        self.addCleanup(self.stop)

    def member_mode(self):
        self.settings.temporary_policy = 'member-self-service'
        self.settings.policy_revision = 'department-member-v1'

    def start(self):
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.client = TestClient(self.app).__enter__()

    def stop(self):
        if getattr(self, 'client', None) is not None:
            self.client.__exit__(None, None, None)
            self.client = None
            self.store.engine.dispose()
            self.store.native_db.db_engine.dispose()

    def request(self, method, path, body=None, *, owner='alice', expected=200, headers=None):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth.issue_demo_token(owner), **(headers or {})})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def plan(self, application='checksum', **values):
        return self.request('POST', '/plans', {'requestId': str(uuid4()), 'application': application,
            'topic': 'Department synthetic task with original request identity', 'mode': 'literature',
            **values}, expected=201)

    def wait(self, task_id, statuses):
        deadline = time.monotonic() + 20
        detail = None
        while time.monotonic() < deadline:
            detail = self.request('GET', '/jobs/' + task_id)
            if detail['job']['status'] in statuses:
                return detail
            time.sleep(.05)
        self.fail('Original native task observation deadline: ' + str(detail))

    def publish(self, identifier, *, workflow=False):
        definition = app_definition(self.store, identifier=identifier)
        if workflow:
            mode = definition['modes']['literature']
            mode['nativeComponent'] = self.store.native_workflows.pin(WORKFLOW_ID)
            mode['inputSchema'] = INPUT_SCHEMA
        application = self.request('POST', '/applications/drafts',
            {'definition': definition, 'requestId': str(uuid4())}, expected=201)
        self.request('POST', f'/applications/{identifier}/versions/1/publish',
            {'requestId': str(uuid4())})
        return application

    def test_member_runs_multiple_applications_and_workflow_without_admin_decision(self):
        with self.assertRaises(HTTPException) as denied:
            self.auth.require('alice', 'agent_os:admin')
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(self.client.get('/api/factory/session').status_code, 401)
        applications = [self.publish('department-text-one'), self.publish('department-text-two'),
            self.publish('department-original-workflow', workflow=True)]
        with patch.object(self.state['plan_policy'], 'request_review',
                side_effect=AssertionError('ORDINARY_TASK_MUST_NOT_REQUEST_REVIEW')), \
                patch.object(self.state['plan_policy'], 'decide',
                side_effect=AssertionError('ORDINARY_TASK_MUST_NOT_DECIDE_REVIEW')):
            for application in applications:
                with self.subTest(application=application['id']):
                    plan = self.plan(applicationRef=pin(application),
                        **({'inputValues': {'goal': 'Original synthetic Workflow'}}
                            if application['id'] == 'department-original-workflow' else {}))
                    authorization = self.request('GET', f'/plans/{plan["id"]}/authorization')
                    self.assertTrue(authorization['executionAllowed'], authorization)
                    body = {'planId': plan['id'], 'requestId': str(uuid4())}
                    task = self.request('POST', '/instances', body, expected=202)
                    detail = self.wait(task['id'], {'completed', 'failed'})
                    self.assertEqual(detail['job']['status'], 'completed', detail)
                    repeated = self.request('POST', '/instances', body, expected=202)
                    self.assertEqual(repeated['id'], task['id'])
                    native_task = self.store.task(task['id'], 'alice')
                    native = self.store.native_db.get_job(native_task['run_id'])
                    self.assertEqual(native['component_type'],
                        'workflow' if application['id'] == 'department-original-workflow' else 'agent')
                    self.assertEqual(self.store.sql('SELECT count(*) AS n FROM ai.agno_jobs WHERE session_id=:id',
                        id=task['id'])[0]['n'], 1)
                    self.request('POST', '/instances', body, owner='bob', expected=404)
                    self.request('POST', '/instances', body,
                        headers={'X-Factory-Expected-Owner': 'bob'}, expected=403)
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_plan_reviews')[0]['n'], 0)
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_application_reviews')[0]['n'], 0)
        self.request('POST', f'/applications/{applications[0]["id"]}/versions/1/archive',
            {'requestId': str(uuid4()), 'reason': 'Synthetic non-admin deletion attempt'}, expected=403)

    def test_member_self_service_keeps_native_confirmation_before_dangerous_tool(self):
        plan = self.plan(application='research', mode='experiment')
        authorization = self.request('GET', f'/plans/{plan["id"]}/authorization')
        self.assertTrue(authorization['executionAllowed'], authorization)
        self.assertFalse(authorization['reviewRequired'], authorization)
        with patch('subprocess.Popen', side_effect=AssertionError('UNCONFIRMED_TOOL_MUST_NOT_START')) as compute:
            task = self.request('POST', '/instances',
                {'planId': plan['id'], 'requestId': str(uuid4())}, expected=202)
            detail = self.wait(task['id'], {'waiting_approval', 'failed'})
            self.assertEqual(detail['job']['status'], 'waiting_approval', detail)
            self.assertTrue(detail['job']['approvalDetail'])
            self.assertEqual(detail['snapshot']['effects'], [])
            self.assertFalse(any(event['type'] == 'compute_started' for event in detail['events']))
            self.assertEqual(self.store.sql('SELECT count(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
            self.request('POST', '/jobs/' + task['id'] + '/cancel', {})
            stopped = self.wait(task['id'], {'canceled', 'cancelled', 'failed'})
            self.assertTrue(stopped['snapshot']['delegation']['allStopped'])
            self.assertEqual(compute.call_count, 0)

    def test_legacy_pending_denied_approved_and_unknown_remain_read_only_after_restart(self):
        policy = self.state['plan_policy']
        old = {}
        for state in ('pending', 'denied', 'approved', 'unknown'):
            plan = self.plan()
            review = policy.request_review('alice', plan['id'], 'legacy-request-' + state)
            if state != 'pending':
                policy.decide('manager', review['id'], state != 'denied', 'legacy-decision-' + state)
            old[state] = (plan, review)
        unknown_plan, _ = old['unknown']
        unknown_body = {'planId': unknown_plan['id'], 'requestId': 'legacy-unknown-original'}
        lost_ack = AsyncMock(side_effect=TimeoutError('Synthetic unconfirmed native acknowledgement'))
        with patch.object(self.state['bridge'], 'submit', lost_ack):
            unknown = self.request('POST', '/instances', unknown_body, expected=202)
        self.assertEqual(lost_ack.await_count, 1)
        self.assertEqual(unknown['status'], 'unknown')
        decisions_before = self.store.sql('SELECT * FROM af_plan_review_decisions ORDER BY id')
        plans_before = {state: self.store.plan(plan['id'], 'alice') for state, (plan, _) in old.items()}
        self.stop()
        self.member_mode()
        self.start()
        bridge = AsyncMock(side_effect=AssertionError('HISTORICAL_TASK_MUST_NOT_DISPATCH'))
        with patch.object(self.state['bridge'], 'submit', bridge):
            for state, (plan, review) in old.items():
                with self.subTest(state=state):
                    self.assertEqual(self.store.plan(plan['id'], 'alice'), plans_before[state])
                    request = unknown_body if state == 'unknown' else {
                        'planId': plan['id'], 'requestId': 'legacy-resubmit-' + state}
                    denied = self.request('POST', '/instances', request, expected=409)
                    self.assertEqual(denied['code'], 'LEGACY_PLAN_READ_ONLY')
                    history = self.request('GET', '/plan-reviews/' + review['id'])
                    self.assertEqual(history['decision'], state if state in {'pending', 'denied'} else 'approved')
                    self.request('POST', '/plan-reviews/' + review['id'] + '/decision',
                        {'requestId': str(uuid4()), 'approved': True}, owner='manager', expected=410)
            self.request('POST', '/jobs/' + unknown['id'] + '/reconcile', {})
        self.assertEqual(bridge.await_count, 0)
        self.assertEqual(self.store.sql('SELECT * FROM af_plan_review_decisions ORDER BY id'), decisions_before)
        persisted = self.store.task(unknown['id'], 'alice')
        self.assertEqual(persisted['admission'], 'unknown')
        self.assertIsNone(persisted['run_id'])
        self.assertFalse(persisted['terminal'])
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM ai.agno_jobs')[0]['n'], 0)
        self.assertEqual(len(self.store.tasks('alice')), 1)
        fresh = self.plan()
        task = self.request('POST', '/instances', {'planId': fresh['id'], 'requestId': str(uuid4())}, expected=202)
        self.assertEqual(self.wait(task['id'], {'completed', 'failed'})['job']['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
