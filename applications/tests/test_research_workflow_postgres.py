"""Real optional deployment/native Workflow with synthetic model and real child tool.

The fixture decisions test evidence transport and governance, not scientific autonomy.
"""
from fixture_auth import authorize_client, initialize_members
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from threading import Event
from unittest.mock import patch

from sqlalchemy import select
import unittest

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool
from fastapi.testclient import TestClient

from fixture_settings import Settings
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits, KnowledgeContext
from agent_factory.usage_ledger import PricingRevision
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from pg_fixture import IsolatedPostgres
from research.workflow import FUNCTION_TOOLS, INPUT_SCHEMA, PERMISSION, WORKFLOW_ID

MODEL = 'research-native-fixture-v1'
PROVIDER = 'research-controlled-fixture'
PAYLOAD = 'actual original child research observation'
DIGEST = hashlib.sha256(PAYLOAD.encode()).hexdigest()
OBSERVED = []


def objects(messages):
    decoder = json.JSONDecoder()
    for message in messages:
        text = str(message.content)
        for index, char in enumerate(text):
            if char != '{':
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value


class ResearchModel(Model):
    def __init__(self, ctx):
        super().__init__(id=MODEL, provider=PROVIDER)
        self.context = ctx

    def _response(self, messages):
        observed = '\n'.join(str(message.content) for message in messages)
        OBSERVED.append(observed)
        if self.context.plan.get('mode') == 'experiment':
            outputs = [message.content for message in messages if message.role == 'tool']
            if outputs:
                return ModelResponse(role='assistant', content=outputs[-1])
            return ModelResponse(role='assistant', tool_calls=[{'id': 'actual-observation', 'type': 'function',
                'function': {'name': 'research_fixture_compute', 'arguments': '{}'}}])
        if 'Call factory_wait_operations' in observed:
            if any(message.role == 'tool' for message in messages):
                return ModelResponse(role='assistant', content='Original wait resolved.')
            launch = next(value for value in objects(messages) if 'operationIds' in value)
            return ModelResponse(role='assistant', tool_calls=[{'id': 'original-wait', 'type': 'function',
                'function': {'name': 'factory_wait_operations', 'arguments': json.dumps(launch)}}])
        values = list(objects(messages))
        result = next((value for value in values if 'operation' in value and 'evidenceIds' in value), None)
        if result:
            # The decision consumes the output visible to the model, never reads custody tables.
            actual = json.dumps(result['operation'], ensure_ascii=False)
            success = DIGEST in actual
            value = {'action': 'stop', 'outcome': 'met' if success else 'not_met',
                'reason': 'Observed expected checksum' if success else 'Actual evidence differs',
                'evidenceIds': result['evidenceIds']}
            if 'review prior measurement' in result['agreement']['objective']:
                value = {'action': 'continue', 'reason': 'Carry original evidence into the remaining review allocation',
                    'evidenceIds': result['evidenceIds']}
        else:
            context = next(value for value in values if 'agreement' in value and 'roundId' in value)
            if context.get('previousObservation') is not None:
                success = DIGEST in json.dumps(context['previousObservation'])
                value = {'action': 'stop', 'outcome': 'met' if success else 'not_met',
                    'reason': 'Review of actual original observation', 'evidenceIds': context['evidenceIds']}
            elif 'no experiment' in context['agreement']['objective']:
                value = {'action': 'stop', 'outcome': 'not_met', 'reason': 'Agreement rules out further experimentation'}
            else:
                value = {'action': 'experiment', 'reason': 'Measure the specified actual bytes',
                    'hypothesis': 'Checksum matches the agreed bytes', 'conditions': 'Local deterministic UTF-8 tool',
                    'goal': PAYLOAD}
        return ModelResponse(role='assistant', content=json.dumps(value))

    def invoke(self, messages, **kwargs): return self._response(messages)
    async def ainvoke(self, messages, **kwargs): return self._response(messages)
    def invoke_stream(self, messages, **kwargs): yield self._response(messages)
    async def ainvoke_stream(self, messages, **kwargs): yield self._response(messages)
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response, **kwargs): return response


def fixture_compute(ctx):
    @tool
    def research_fixture_compute(run_context: RunContext):
        """Compute and archive the actual deterministic fixture observation."""
        ctx.store.authorize_tool(run_context, 'research_fixture_compute')
        value = {'sha256': hashlib.sha256(PAYLOAD.encode()).hexdigest(), 'inputBytes': len(PAYLOAD.encode())}
        ctx.store.artifact_write(run_context.run_id, 'research-observation.json', json.dumps(value))
        return json.dumps(value)
    return research_fixture_compute


def publish(state):
    initialize_members(state['auth'])
    governance, apps = state['material_governance'], state['applications']
    tools = [*FUNCTION_TOOLS, 'factory_wait_operations', 'research_fixture_compute']
    entries = [('model', 'model', MODEL), ('environment', 'environment', 'research-fixture-environment-v1'),
        ('knowledge', 'knowledge', 'research-fixture-knowledge-v1'), ('prompt', 'prompt', None), ('skill', 'skill', None)]
    adapters = {entry.tool_name: entry.adapter_id for entry in state['store'].settings.runtime_adapters if entry.kind == 'tool'}
    entries += [('tool', name, adapters[name]) for name in tools]
    refs = {}
    for kind, name, adapter in entries:
        identifier = 'research-fixture-' + name.replace('_', '-')
        value = {'id': identifier, 'kind': kind, 'name': name, 'content': name if kind == 'tool' else 'Synthetic research fixture only.',
            'permissions': [PERMISSION] if kind == 'tool' else []}
        if adapter:
            value['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': {}}
        material = governance.create_draft('manager', value, identifier + ':draft')
        governance.publish('manager', identifier, material['version'], identifier + ':publish')
        refs[name] = {key: material[key] for key in ('id', 'version', 'sha256')}
    mode = {'materialRefs': list(refs.values()), 'capabilities': [PERMISSION], 'toolOrder': tools,
        'budget': {'toolCalls': 32, 'maxDepth': 1, 'maxChildren': 1, 'experimentSeconds': 30, 'outputBytes': 65536}}
    child = {**mode, 'materialRefs': [ref for name, ref in refs.items() if name not in tools or name == 'research_fixture_compute'],
        'toolOrder': ['research_fixture_compute']}
    definition = {'id': 'research-fixture-application', 'name': 'Fixed research native fixture', 'defaultMode': 'research',
        'modes': {'research': {**mode, 'nativeComponent': state['store'].native_workflows.pin(WORKFLOW_ID), 'inputSchema': INPUT_SCHEMA},
                  'experiment': child}}
    app = apps.create_draft('manager', definition, 'research-fixture-app:draft')
    apps.publish('manager', app['id'], app['version'], 'research-fixture-app:publish')
    return {key: app[key] for key in ('id', 'version', 'sha256')}


def settings_for(db_url, workspace, **overrides):
    return Settings(db_url=db_url, workspace=Path(workspace), max_workers=2, max_user_tasks=3,
        max_tool_calls=32, material_review_mode='member-self-service', material_policy_revision='research-fixture-v1',
        temporary_policy='member-self-service', policy_revision='research-fixture-v1', runtime_adapters=[
            AdapterRegistration('model', MODEL, '1', ResearchModel, ),
            AdapterRegistration('environment', 'research-fixture-environment-v1', '1', lambda ctx: EnvironmentLimits(timeout_seconds=30)),
            AdapterRegistration('knowledge', 'research-fixture-knowledge-v1', '1', lambda ctx: KnowledgeContext('Synthetic', {})),
            AdapterRegistration('tool', 'research-fixture-compute-v1', '1', fixture_compute,
                tool_name='research_fixture_compute', permissions=(PERMISSION,))],
        usage_pricing=(PricingRevision(MODEL, '1', PROVIDER, MODEL, 'research-zero-fixture-v1',
            local_model_type=ResearchModel, per_attempt_input_tokens=32768, per_attempt_output_tokens=4096),), **overrides)


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class ResearchNativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        OBSERVED.clear()
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.settings = settings_for(database.url, directory.name)
        self.app = create_app(self.settings)
        self.state = factory_state(self.app)
        self.addCleanup(self.state['store'].native_db.db_engine.dispose)
        self.addCleanup(self.state['store'].engine.dispose)
        self.addCleanup(self.state['store'].dispose_root_locks)
        self.client = TestClient(self.app, base_url="https://testserver").__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.ref = publish(self.state)
        self.assertEqual(len(self.settings.runtime_adapters), 4)
        self.assertEqual(self.settings.native_workflows, ())
        self.assertEqual(authorize_client(self.client, 'alice').status_code, 200)

    def start(self, objective, *, rounds=1):
        result = self.client.post('/api/factory/research/projects', json={'requestId': 'native-project-create', 'title': 'Native controlled research'})
        self.assertEqual(result.status_code, 201, result.text)
        self.url = '/api/factory/research/projects/' + result.json()['id']
        agreement = {'objective': objective, 'evaluation': 'Compare actual UTF-8 checksum evidence',
            'stopConditions': 'Stop on evidenced result or exhausted original budget', 'budget': {'rounds': rounds, 'toolCalls': 32 * rounds},
            'execution': {'applicationRef': self.ref, 'mode': 'research', 'deadline': time.time() + 180,
                'perRoundCaps': {'rounds': 1, 'toolCalls': 32}}}
        for path, body in (('/goals', {'requestId': 'native-goal-create', 'expectedVersion': 0, 'agreement': agreement}),
                           ('/confirm', {'requestId': 'native-goal-confirm', 'expectedVersion': 1})):
            reply = self.client.post(self.url + path, json=body)
            self.assertEqual(reply.status_code, 200, reply.text)
        reply = self.client.post(self.url + '/start', json={'requestId': 'native-research-start', 'expectedVersion': 1})
        self.assertEqual(reply.status_code, 202, reply.text)
        return reply.json()

    def completed(self, task_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            value = self.client.get('/api/factory/jobs/' + task_id).json()
            if value['job']['status'] in {'completed', 'failed', 'cancelled'}:
                self.assertEqual(value['job']['status'], 'completed', value)
                return value
            time.sleep(.05)
        self.fail('Original research native root did not reach terminal: ' + repr(value))

    def test_immediate_stop_uses_real_deployment_and_creates_no_child(self):
        receipt = self.start('no experiment is permitted for this agreed task')
        self.completed(receipt['execution']['taskId'])
        store = self.state['store']
        self.assertEqual(len(store.tasks('alice')), 1)
        listing = self.client.get(self.url + '/experiments').json()
        self.assertEqual(listing['items'], [])
        self.assertEqual(listing['rounds'][0]['decision']['outcome'], 'not_met')

    def test_original_child_output_reaches_model_and_terminal_record(self):
        receipt = self.start('Compute the actual agreed bytes once')
        self.completed(receipt['execution']['taskId'])
        self.assertEqual(len(self.state['store'].tasks('alice')), 2)
        listing = self.client.get(self.url + '/experiments').json()
        self.assertEqual(len(listing['items']), 1)
        self.assertIsNotNone(listing['rounds'][0]['decision'], listing)
        self.assertEqual(listing['rounds'][0]['decision']['outcome'], 'met')
        evaluation = [text for text in OBSERVED if 'Evaluate the actual original child' in text]
        self.assertTrue(evaluation)
        self.assertIn(DIGEST, evaluation[-1])
        self.assertIn('Compare actual UTF-8 checksum evidence', evaluation[-1])
        self.assertIn('Stop on evidenced result or exhausted original budget', evaluation[-1])

    def test_completion_failure_rolls_back_original_settlement_then_observer_finishes(self):
        rounds = self.state['research_rounds']
        original = rounds._publish
        failed, release = Event(), Event()
        def publication(owner, identifier, revision, content, **kwargs):
            if revision == 'terminal' and not release.is_set():
                failed.set()
                raise RuntimeError('Controlled terminal publication failure')
            return original(owner, identifier, revision, content, **kwargs)
        with patch.object(rounds, '_publish', publication):
            receipt = self.start('no experiment is permitted for this agreed task')
            self.assertTrue(failed.wait(15), 'Original finalizer was not reached')
            store = self.state['store']
            task = store.task(receipt['execution']['taskId'], 'alice')
            self.assertFalse(task['terminal'])
            self.assertEqual(task['body']['stoppedStatus'], 'completed')
            scope = store.local_budget_scopes.inspect('alice', receipt['scopeId'])
            self.assertEqual(scope['allocations'][0]['state'], 'BOUND')
            with store.transaction(read_only=True) as conn:
                row = conn.execute(select(rounds.rounds).where(rounds.rounds.c.id == receipt['roundId'])).mappings().one()
                self.assertIsNone(row['terminal'])
                self.assertIsNone(row['terminal_record'])
                self.assertEqual(row['continuations'], [])
            release.set()
            self.completed(task['id'])
        listing = self.client.get(self.url + '/experiments').json()
        self.assertIsNotNone(listing['rounds'][0]['terminalRecordId'])
        self.assertEqual(len(store.tasks('alice')), 1)
        scope = store.local_budget_scopes.inspect('alice', receipt['scopeId'])
        self.assertEqual(len(scope['allocations']), 1)
        self.assertEqual(scope['allocations'][0]['state'], 'SETTLED')

    def test_original_p3_event_admits_one_successor_and_transports_actual_prior_result(self):
        first = self.start('Measure once then review prior measurement against the agreement', rounds=2)
        self.completed(first['execution']['taskId'])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            listing = self.client.get(self.url + '/experiments').json()
            if len(listing['rounds']) == 2 and listing['rounds'][1]['terminal'] is not None:
                break
            time.sleep(.05)
        self.assertEqual(len(listing['rounds']), 2, listing)
        first_round, second = listing['rounds']
        self.assertIsNotNone(second['deliveryId'])
        self.assertIsNotNone(second['terminal'])
        self.assertEqual(first_round['decision']['action'], 'continue')
        self.assertEqual(second['decision']['outcome'], 'met')
        self.assertEqual(len(first_round['continuations']), 1)
        self.assertEqual(second['continuations'], [])
        self.assertEqual(len(listing['items']), 1)
        self.assertEqual(len(self.state['store'].tasks('alice')), 3)
        scope = self.state['local_budget_scopes'].inspect('alice', first['scopeId'])
        self.assertEqual(scope['allocatedRounds'], 2)
        self.assertEqual({a['taskId'] for a in scope['allocations']}, {r['taskId'] for r in listing['rounds']})
        reviewed = [text for text in OBSERVED if 'previousObservation' in text and DIGEST in text]
        self.assertTrue(reviewed, 'Successor model did not receive the actual original child output')

    def test_installed_setup_publishes_current_flat_pin_without_execution(self):
        model = self.client.post('/api/factory/personal-models', json={'requestId': 'installed-setup-model',
            'provider': 'openai-compatible', 'baseURL': 'http://localhost:9/v1', 'model': 'not-called'})
        self.assertEqual(model.status_code, 201, model.text)
        candidates = self.client.get('/api/factory/research/setup')
        self.assertEqual(candidates.status_code, 200, candidates.text)
        current_pin = self.state['store'].native_workflows.pin(WORKFLOW_ID)
        self.assertEqual(candidates.json()['workflowPin'], current_pin)
        tool = next(item for item in candidates.json()['experimentMaterials']
                    if item['id'] == 'research-fixture-research-fixture-compute')
        draft = self.client.post('/api/factory/research/setup/drafts', json={
            'requestId': 'installed-setup-prepare', 'name': 'Explicitly configured native research',
            'modelConnectionRef': model.json()['connectionRef'],
            'environment': {'adapterId': 'research-fixture-environment-v1', 'revision': '1'},
            'experimentMaterialRefs': [{key: tool[key] for key in ('id', 'version', 'sha256')}],
            'budget': {'toolCalls': 32, 'maxDepth': 1, 'maxChildren': 1}})
        self.assertEqual(draft.status_code, 200, draft.text)
        published = self.client.post('/api/factory/research/setup/' + draft.json()['id'] + '/publish',
            json={'requestId': 'installed-setup-publish'})
        self.assertEqual(published.status_code, 200, published.text)
        application = self.state['applications'].require_current(published.json()['applicationRef'])
        self.assertEqual(application['modes']['research']['nativeComponent'], current_pin)
        self.assertTrue(set(FUNCTION_TOOLS).issubset(application['modes']['research']['toolOrder']))
        self.assertNotIn('research_stop', application['modes']['research']['toolOrder'])
        self.assertEqual(application['modes']['experiment']['toolOrder'], ['research_fixture_compute'])
        self.assertEqual(self.state['store'].tasks('alice'), [])
        self.assertEqual(OBSERVED, [])
