"""Public application start over actual native Factory custody; synthetic only."""
import os
from pathlib import Path
import importlib.util
import unittest
from unittest.mock import AsyncMock, patch

import test_applications_composition as fixtures

from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnError
from agent_factory.native_workflows import NativeWorkflowRegistration
from agent_factory.input_schema import input_model
from agent_factory.plan_policy import PlanPolicyConfig

INPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['goal'],
    'properties': {'goal': {'type': 'string', 'maxLength': 100}}}


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class ApplicationInterfacePostgresTests(fixtures.ApplicationCompositionPostgresTests):
    prefix = '/api/factory/application-interface/v1/starts'

    def test_v1_and_v2_start_original_native_task_and_keep_definitions_unchanged(self):
        v1 = self.publish_http()
        self.login('alice')
        for app_id, mode, contract in [(v1['id'], 'literature', 1), ('checksum-neutral', 'execute', 2)]:
            before = self.apps.list_active('alice')
            key = 'public-native-' + str(contract)
            body = {'interfaceVersion': 1, 'application': app_id, 'mode': mode,
                'goal': 'Original controlled public application task', 'requestId': key}
            started = self.client.post(self.prefix, json=body, headers={'X-Factory-Expected-Owner': 'alice'})
            self.assertEqual(started.status_code, 202, started.text)
            result = started.json(); self.assertEqual(result['requestId'], key)
            detail = self.wait_job(result['job']['id'])
            self.assertEqual(detail['job']['status'], 'completed', detail)
            self.assertTrue(detail['artifacts'])
            receipt = self.client.get(self.prefix + '/' + key)
            self.assertEqual(receipt.status_code, 200, receipt.text)
            self.assertFalse(receipt.json()['createsExecution'])
            self.assertFalse(receipt.json()['automaticReplay'])
            self.assertEqual(receipt.json()['taskId'], result['job']['id'])
            task = self.store.task(result['job']['id'], 'alice')
            plan = self.store.plan(task['plan_id'], 'alice')
            self.assertEqual(plan.get('contractVersion', 1), contract)
            self.assertEqual(self.apps.list_active('alice'), before)
            repeated = self.client.post(self.prefix, json=body)
            self.assertEqual(repeated.status_code, 202, repeated.text)
            self.assertEqual(repeated.json()['job']['id'], task['id'])
            changed = {**body, 'goal': 'Changed intent must never reuse original identity'}
            self.assertEqual(self.client.post(self.prefix, json=changed).status_code, 409)
        self.assertEqual(len(self.store.tasks('alice')), 2)

    def test_unknown_admission_original_receipt_restart_and_owner_scope_never_resubmit(self):
        self.login('alice')
        body = {'application': 'checksum-neutral', 'mode': 'execute',
            'goal': 'Controlled lost native acknowledgement', 'requestId': 'public-unknown-001'}
        submit = AsyncMock(side_effect=TimeoutError('synthetic unconfirmed acknowledgement'))
        with patch.object(self.state['bridge'], 'submit', submit):
            first = self.client.post(self.prefix, json=body)
            self.assertEqual(first.status_code, 202, first.text)
            task_id = first.json()['job']['id']
            repeated = self.client.post(self.prefix, json=body)
            self.assertEqual(repeated.status_code, 202, repeated.text)
            self.assertEqual(submit.await_count, 1)
            self.assertEqual(repeated.json()['job']['id'], task_id)
        receipt = self.client.get(self.prefix + '/public-unknown-001')
        self.assertEqual(receipt.status_code, 200, receipt.text)
        self.assertEqual(receipt.json()['state'], 'unknown')
        self.stop(); self.start(); self.login('alice')
        after = self.client.get(self.prefix + '/public-unknown-001')
        self.assertEqual(after.json(), receipt.json())
        self.login('bob')
        self.assertEqual(self.client.get(self.prefix + '/public-unknown-001').status_code, 404)
        self.assertEqual(self.client.post(self.prefix, json=body, headers={'X-Factory-Expected-Owner': 'alice'}).status_code, 403)
        self.assertEqual(len(self.store.tasks('alice')), 1)


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class ApplicationContextNativePostgresTests(fixtures.ApplicationCompositionPostgresTests):
    def start(self):
        path = Path(__file__).resolve().parents[2] / 'examples/minimal_application.py'
        spec = importlib.util.spec_from_file_location('public_native_example', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        workflow = Workflow(id='public-context-fixture-v1', name='Public context fixture', input_schema=input_model(INPUT_SCHEMA), steps=[
            Step(name='checksum', step_id='summary-v1', executor=module.summarize,
                max_retries=0, human_review=HumanReview(on_error=OnError.fail))])
        self.settings.native_workflows = (NativeWorkflowRegistration(workflow, '1', ('checksum',), 'd' * 64),)
        super().start()

    def publish_native_context(self):
        definition = fixtures.app_definition(self.store, identifier='public-context-fixture')
        mode = definition['modes']['literature']
        mode['nativeComponent'] = self.store.native_workflows.pin('public-context-fixture-v1')
        mode['inputSchema'] = INPUT_SCHEMA
        draft = self.apps.create_draft('manager', definition, 'public-context-draft')
        review = self.apps.request_publication('manager', draft['id'], draft['version'], 'public-context-review')
        self.apps.decide_publication('bob', review['id'], True, 'public-context-approve')
        return draft

    def test_public_context_example_runs_in_original_native_workflow_and_persists_scoped_output(self):
        draft = self.publish_native_context()
        self.login('alice')
        response = self.client.post('/api/factory/application-interface/v1/starts', json={
            'requestId': 'public-context-run', 'application': draft['id'], 'mode': 'literature',
            'goal': 'Run original synthetic public-context example', 'inputValues': {'goal': 'Original controlled goal'}})
        self.assertEqual(response.status_code, 202, response.text)
        detail = self.wait_job(response.json()['job']['id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)
        self.assertEqual(len(detail['artifacts']), 1)
        artifact = detail['artifacts'][0]
        self.assertEqual(artifact['name'], 'summary.json')
        self.assertEqual(artifact['provenance']['applicationInterfaceVersion'], 1)
        self.assertEqual(artifact['provenance']['verificationStatus'], 'unverified')
        self.assertTrue(any(event['type'] == 'application_summary_ready' for event in detail['events']))

    def test_existing_managed_review_handoff_admits_the_same_original_plan_without_automatic_approval(self):
        draft = self.publish_native_context()
        policy = self.store.plan_policy.current()
        self.store.plan_policy.replace_configuration(PlanPolicyConfig(name='admin-review', revision='public-native-review'),
            expected_revision=policy['revision'])
        self.login('alice')
        body = {'requestId': '_request..001', 'application': draft['id'], 'mode': 'literature',
            'goal': 'Original managed synthetic native goal', 'inputValues': {'goal': 'Original controlled managed input'}}
        prefix = '/api/factory/application-interface/v1/starts'
        submit = AsyncMock(wraps=self.state['bridge'].submit)
        with patch.object(self.state['bridge'], 'submit', submit):
            blocked = self.client.post(prefix, json=body)
            self.assertEqual(blocked.status_code, 409, blocked.text)
            error = blocked.json(); self.assertEqual(error['code'], 'PLAN_REVIEW_REQUIRED')
            receipt = self.client.get(prefix + '/' + body['requestId'])
            self.assertEqual(receipt.status_code, 200, receipt.text)
            original = receipt.json(); self.assertEqual(original['planId'], error['planId'])
            self.assertEqual(original['handoff'], error['handoff']); self.assertIsNone(original['taskId'])
            self.assertFalse(original['createsExecution']); self.assertFalse(original['automaticReplay'])
            self.assertEqual(submit.await_count, 0); self.assertEqual(self.store.tasks('alice'), [])
            immutable = self.store.plan(original['planId'], 'alice')
            authorization = self.client.get(original['handoff']['authorizationURL']).json()
            self.assertTrue(authorization['reviewRequired']); self.assertFalse(authorization['executionAllowed'])
            reviewed = self.client.post(original['handoff']['reviewRequestURL'], json={
                'planId': original['planId'], 'requestId': 'public-managed-review'})
            self.assertEqual(reviewed.status_code, 201, reviewed.text)
            review_id = reviewed.json()['id']
            self.login('bob')
            decided = self.client.post('/api/factory/plan-reviews/' + review_id + '/decision', json={
                'approved': True, 'requestId': 'public-managed-decision'})
            self.assertEqual(decided.status_code, 200, decided.text)
            self.login('alice')
            admitted = self.client.post(original['handoff']['instantiateURL'], json=original['handoff']['instantiateBody'])
            self.assertEqual(admitted.status_code, 202, admitted.text)
            detail = self.wait_job(admitted.json()['id'])
            self.assertEqual(detail['job']['status'], 'completed', detail)
            queried = self.client.get(prefix + '/' + body['requestId']).json()
            self.assertEqual(queried['planId'], immutable['id']); self.assertEqual(queried['taskId'], admitted.json()['id'])
            self.assertEqual(self.store.plan(immutable['id'], 'alice'), immutable)
            again = self.client.post(prefix, json=body)
            self.assertEqual(again.status_code, 202, again.text)
            self.assertEqual(again.json()['job']['id'], admitted.json()['id']); self.assertEqual(submit.await_count, 1)
        self.assertEqual(len(self.store.tasks('alice')), 1)


# Reuse lifecycle helpers without rerunning inherited unrelated cases.
for _name in dir(fixtures.ApplicationCompositionPostgresTests):
    if _name.startswith('test_'):
        setattr(ApplicationInterfacePostgresTests, _name, None)
        setattr(ApplicationContextNativePostgresTests, _name, None)


if __name__ == '__main__': unittest.main()
