"""Actual Workflow wait/restart and child output; deterministic model only."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tempfile
from typing import Any, cast
import unittest
from uuid import uuid4

from agno.agent import Agent
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool
from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnError, StepInput, StepOutput
from fastapi import Request

from agent_factory.application_schema import definition_model
from agent_factory.delegated_operations import DELEGATED_OPERATION_PIN
from agent_factory.execution_bindings import AdapterRegistration
from agent_factory.main import create_app
from agent_factory.store import digest
from agent_factory.native_external_wait import factory_wait_operations
from agent_factory.native_workflows import NativeWorkflowRegistration
from agent_factory.usage_ledger import PricingRevision
from pg_fixture import IsolatedPostgres
import test_native_workflow_factory_postgres as fixture

PAYLOAD = 'actual delegated child checksum'
CHILD_REPORT = '实际测量\nhttps://example.invalid/result\n' + '测量结果' * 3500


def child_result():
    return {'sha256': hashlib.sha256(PAYLOAD.encode()).hexdigest(), 'inputBytes': len(PAYLOAD.encode()),
        'report': CHILD_REPORT, 'token': 'ordinary measurement token'}


class DelegatedModel(fixture.WorkflowFixtureModel):
    def _response(self, messages):
        if self.context.plan.get('mode') == 'child':
            results = [message.content for message in messages if message.role == 'tool']
            if results:
                return ModelResponse(role='assistant', content=results[-1])
            return ModelResponse(role='assistant', tool_calls=[{'id': 'child-compute', 'type': 'function',
                'function': {'name': 'child_compute', 'arguments': '{}'}}])
        results = [message.content for message in messages if message.role == 'tool']
        if results:
            return ModelResponse(role='assistant', content=json.dumps({'receivedOriginalChild': json.loads(results[-1])}))
        return super()._response(messages)


def configured(configuration, holder):
    settings = fixture.settings(configuration, fixture.DurableOperations(Path(configuration['workspace']) / 'unused.sqlite'), holder)
    async def prepare(step_input: StepInput, run_context: RunContext):
        record = await holder['state']['store'].workflow.start(run_context, 'fixture_prepare', 'child',
            DELEGATED_OPERATION_PIN, {'goal': PAYLOAD, 'mode': 'child'})
        return StepOutput(content=json.dumps({'operationId': record['id']}))
    workflow = Workflow(id=fixture.APP, name='Delegated native wait fixture', input_schema=fixture.WorkflowInput,
        steps=cast(Any, [Step(name='fixture_prepare', step_id='fixture_prepare', executor=cast(Any, prepare),
            max_retries=0, human_review=HumanReview(on_error=OnError.fail)),
            Step(name='original_wait', step_id='original_wait', agent=Agent(id='delegated-wait',
                tools=[factory_wait_operations], telemetry=False), max_retries=0, human_review=HumanReview(on_error=OnError.fail))]), telemetry=False)
    settings.native_workflows = (NativeWorkflowRegistration(workflow, '1', ('fixture_prepare',), 'b' * 64),)
    settings.workflow_runtimes = {}
    settings.runtime_adapters = [entry for entry in settings.runtime_adapters if entry.kind != 'model']
    settings.runtime_adapters.append(AdapterRegistration('model', fixture.MODEL, '1', DelegatedModel, ))
    def tools(ctx):
        @tool
        def child_compute(run_context: RunContext):
            """Compute actual fixture bytes, preserving the original task artifact."""
            ctx.store.authorize_tool(run_context, 'child_compute')
            value = json.dumps(child_result(), ensure_ascii=False)
            ctx.store.artifact_write(run_context.run_id, 'child-checksum.json', value)
            return value
        return child_compute
    settings.runtime_adapters.append(AdapterRegistration('tool', 'delegated-compute-v1', '1', tools,
        tool_name='child_compute', permissions=(fixture.PERMISSION,)))
    settings.usage_pricing = (PricingRevision(fixture.MODEL, '1', fixture.PROVIDER, fixture.MODEL,
        'delegated-zero-v1', local_model_type=DelegatedModel, per_attempt_input_tokens=32768, per_attempt_output_tokens=4096),)
    return settings


def publish(state):
    from fixture_auth import initialize_members
    initialize_members(state['auth'])
    original = fixture.publish(state)
    value = {key: original[key] for key in definition_model(original).model_fields}
    material = state['material_governance'].create_draft('manager', {'id': 'delegated-compute-material',
        'kind': 'tool', 'name': 'Actual child checksum', 'content': 'child_compute',
        'permissions': [fixture.PERMISSION], 'runtimeBinding': {'adapterId': 'delegated-compute-v1', 'revision': '1', 'config': {}}},
        'delegated-compute:draft')
    state['material_governance'].publish('manager', material['id'], material['version'], 'delegated-compute:publish')
    parent = value['modes']['workflow']
    parent['materialRefs'].append({key: material[key] for key in ('id', 'version', 'sha256')})
    parent['toolOrder'].append('child_compute')
    child = {key: val for key, val in parent.items() if key not in {'nativeComponent', 'inputSchema'}}
    child['toolOrder'] = ['child_compute']
    child['materialRefs'] = [ref for ref in parent['materialRefs'] if ref['id'] not in
        {fixture.APP + '-' + name for name in fixture.TOOLS}]
    value['modes']['child'] = child
    application = state['applications'].create_draft('manager', value, 'delegated-application:draft')
    state['applications'].publish('manager', application['id'], application['version'], 'delegated-application:publish')
    return application


def serve(configuration):
    import uvicorn
    from fastapi import HTTPException
    holder = {}
    app = create_app(configured(configuration, holder))
    state = holder['state'] = app.app.state.factory
    application = publish(state)
    @app.app.post('/__workflow_fixture/budget')
    async def budget(request: Request):
        if request.headers.get('X-Fixture-Control') != configuration['controlKey']:
            raise HTTPException(403, 'FIXTURE_CONTROL_DENIED')
        value = await request.json()
        store, scopes = state['store'], state['store'].local_budget_scopes
        plan = store.plan(value['planId'], 'alice')
        store.admit_plan('alice', value['requestId'], {'fixturePlanId': plan['id']}, lambda: plan)
        caps = {'rounds': 1, 'toolCalls': 32, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        scopes.create_scope('alice', 'fixture-scope', digest({'task': 'delegated-native'}), caps, time.time() + 300)
        with store.transaction() as conn:
            scopes.admission_lock(conn)
            scopes.allocate(conn, 'alice', 'fixture-scope', 'fixture-round', digest(plan), caps)
            scopes.bind_request(conn, 'alice', 'fixture-round', value['requestId'])
        return {'ok': True}

    @app.app.get('/__workflow_fixture/facts')
    async def facts(request: Request, taskId: str | None = None):
        if request.headers.get('X-Fixture-Control') != configuration['controlKey']:
            raise HTTPException(403, 'FIXTURE_CONTROL_DENIED')
        store = state['store']
        task = store.task(taskId, 'alice') if taskId else None
        operations = [store.workflow.read('alice', row['id']) for row in store.sql(
            'SELECT id FROM af_external_operations WHERE task_id=:id', id=taskId)] if task else []
        children = store.sql('SELECT child_id FROM af_delegation_links WHERE parent_id=:id', id=taskId) if task else []
        workflow_output = state['store'].native_workflows.registrations[fixture.APP].component.get_run_output(
            run_id=task['run_id'], session_id=task['id']) if task and task['run_id'] else None
        return {'application': application, 'task': task,
            'native': store.native_db.get_job(task['run_id']) if task else None, 'custody': operations,
            'children': [store.task(row['child_id'], 'alice') for row in children],
            'childNative': [store.native_db.get_job(store.task(row['child_id'], 'alice')['run_id'])
                if store.task(row['child_id'], 'alice')['run_id'] else None for row in children],
            'scope': store.local_budget_scopes.inspect('alice', 'fixture-scope') if task else None,
            'workflowContent': workflow_output.content if workflow_output else None,
            'effects': store.sql('SELECT status FROM af_effects WHERE task_id=:id', id=taskId) if task else [],
            'nativeSteps': fixture.persisted_steps(store, task, configuration) if task else [],
            'nativeCount': store.sql('SELECT count(*) AS n FROM ai.agno_jobs WHERE session_id=:id', id=taskId)[0]['n'] if task else 0}
    uvicorn.run(state["http_app"], host='127.0.0.1', port=configuration['port'], log_level='error', access_log=False)


class Server(fixture.WorkflowServer):
    module = 'test_delegated_workflow_native_postgres'


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires real PostgreSQL/native worker')
class DelegatedNativeWorkflowTests(unittest.TestCase):
    request = fixture.NativeWorkflowFactoryPostgresTests.request
    post = fixture.NativeWorkflowFactoryPostgresTests.post
    until = fixture.NativeWorkflowFactoryPostgresTests.until
    paused = fixture.NativeWorkflowFactoryPostgresTests.paused
    view = fixture.NativeWorkflowFactoryPostgresTests.view
    command = fixture.NativeWorkflowFactoryPostgresTests.command

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        database = self.stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        root = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='delegated-native-'))
        self.server = Server(database.url, root)
        self.stack.callback(self.server.stop)
        self.server.start()
        self.application = self.server.facts()['application']

    def start_task(self):
        proposal = self.post('/compositions/proposals', {'goal': 'Representative delegated workflow',
            'mode': 'workflow', 'applicationRef': {key: self.application[key] for key in ('id', 'version', 'sha256')},
            'inputValues': {'scenario': 'success'}})
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept')
        request = {'planId': plan['id'], 'requestId': str(uuid4())}
        bound = self.server.request('POST', '/__workflow_fixture/budget', request, fixture=True)
        self.assertEqual(bound.status_code, 200, bound.text)
        return self.request('POST', '/instances', request)

    def test_original_workflow_wait_restart_and_actual_child_result(self):
        task = self.start_task()
        paused = self.paused(task)
        operation = paused['custody'][0]
        child = paused['children'][0]
        # A hard restart preserves a paused original run without asking graceful
        # shutdown to cancel it. The restarted service owns recovery as usual.
        self.server.process.kill()
        self.server.process.wait(5)
        self.server.log.close()
        self.server.start()
        restarted = self.server.facts(task['id'])
        self.assertEqual(restarted['task']['run_id'], paused['task']['run_id'])
        self.assertEqual(restarted['children'][0]['id'], child['id'])
        self.until(task, lambda facts: facts['childNative'] and facts['childNative'][0]
            and facts['childNative'][0]['status'] == 'completed')
        command = {'commandId': str(uuid4()), 'action': 'reconcile', 'version': self.view(task)['version'],
            'operationId': operation['id']}
        response = self.request('POST', '/workflows/' + task['id'] + '/commands', command)
        repeated = self.request('POST', '/workflows/' + task['id'] + '/commands', command)
        self.assertEqual({key: value for key, value in response.items() if key != 'workflow'},
            {key: value for key, value in repeated.items() if key != 'workflow'})
        done = self.until(task, lambda facts: facts['native']['status'] == 'completed'
            and facts['scope']['allocations'][0]['state'] == 'SETTLED')
        serialized = json.dumps(done['nativeSteps'])
        self.assertIn(hashlib.sha256(PAYLOAD.encode()).hexdigest(), serialized)
        self.assertIn('receivedOriginalChild', serialized)
        observation = done['custody'][0]['observation']
        child_content = json.dumps(child_result(), ensure_ascii=False)
        self.assertGreater(len(child_content.encode()), 32768)
        self.assertLess(len(child_content.encode()), 65536)
        self.assertTrue(done['custody'][0]['closed'])
        self.assertEqual(observation['state'], 'COMPLETED')
        self.assertEqual(observation['output']['result'], child_content)
        received = json.loads(done['workflowContent'])['receivedOriginalChild']['operations']
        self.assertEqual(received, [observation])
        self.assertEqual({effect['status'] for effect in done['effects']}, {'DONE'})
        self.assertEqual(len(done['children']), 1)
        self.assertEqual(done['custody'][0]['id'], operation['id'])
        self.assertEqual(done['nativeCount'], 1)
        self.assertEqual(done['scope']['allocatedRounds'], 1)
        self.assertEqual(len(done['scope']['allocations']), 1)
        self.assertEqual(done['scope']['allocations'][0]['taskId'], task['id'])
        self.assertIsNotNone(response)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve':
        serve(json.loads(Path(sys.argv[2]).read_text()))
    else:
        unittest.main()
