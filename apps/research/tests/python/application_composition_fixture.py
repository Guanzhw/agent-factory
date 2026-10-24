"""Lazy second-application fixture; native Agno performs every task execution.

The controlled tool's shielded operation models an unacknowledged external
stop. It has no process, network provider, model API or scientific behavior.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import threading

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool

from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.usage_ledger import PricingRevision, UsagePolicy
from agent_factory_research.autoresearch import ResearchPreset
from agent_factory_server.application_composition import ApplicationAssembly


APPLICATION = 'composition-second-app'
MODEL = 'composition-second-model'
PROVIDER = 'composition-controlled-provider'
TOOL = 'composition_original_operation'
TOOL_ADAPTER = 'composition-second-tool'
ENVIRONMENT = 'composition-second-environment'
EFFECT = 'composition-original-operation-v1'
PERMISSION = 'research:read'


class SecondModel(Model):
    def __init__(self):
        super().__init__(id=MODEL, name='Controlled composition tool driver', provider=PROVIDER, retries=0)

    def response_for(self, messages):
        if any(message.role == 'tool' and message.tool_name == TOOL for message in messages):
            return ModelResponse(role='assistant', content='Original controlled operation finished.')
        return ModelResponse(role='assistant', tool_calls=[{'id': 'composition-original-call',
            'type': 'function', 'function': {'name': TOOL, 'arguments': '{}'}}])

    def invoke(self, messages, **kwargs): return self.response_for(messages)
    async def ainvoke(self, messages, **kwargs): return self.response_for(messages)
    def invoke_stream(self, messages, **kwargs): yield self.response_for(messages)
    async def ainvoke_stream(self, messages, **kwargs): yield self.response_for(messages)
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response, **kwargs): return response


class ResearchRuntime:
    def __init__(self):
        self.started = threading.Event()
        self.finish = threading.Event()
        self.run_calls = self.stop_calls = self.cancel_calls = 0
        self.identity = None

    async def run(self):
        self.run_calls += 1
        self.started.set()
        async with asyncio.timeout(90):
            while not self.finish.is_set():
                await asyncio.sleep(.02)
        return {'evidenceMode': 'controlled-composition', 'modelExecuted': False}

    async def stop(self):
        self.stop_calls += 1
        return True

    async def cancel(self):
        self.cancel_calls += 1
        self.finish.set()

    def counters(self):
        return self.run_calls, self.stop_calls, self.cancel_calls


class SecondApplication:
    def __init__(self):
        self.store = None
        self.operations = {}
        self.tasks = {}
        self.calls = []
        self.mark_calls = []
        self.cancel_calls = []
        self.project_calls = []
        self.model_builds = 0
        self.closed = False

    def model_factory(self, _context):
        self.model_builds += 1
        return SecondModel()

    def registrations(self):
        return (
            AdapterRegistration('model', MODEL, '1', self.model_factory, demo_only=True),
            AdapterRegistration('tool', TOOL_ADAPTER, '1', self.tool_factory,
                                tool_name=TOOL, permissions=(PERMISSION,), demo_only=True),
            AdapterRegistration('environment', ENVIRONMENT, '1',
                                lambda _: EnvironmentLimits(timeout_seconds=30), demo_only=True),
        )

    def install(self, state):
        self.store = state['store']
        self.store.application_runtime.register(APPLICATION, self,
            bindings=tuple((entry.kind, entry.adapter_id, entry.revision) for entry in self.registrations()),
            effects=(EFFECT,))

    def assembly(self):
        return ApplicationAssembly(APPLICATION, self.install, self.lifespan)

    @asynccontextmanager
    async def lifespan(self, app):
        try:
            yield
        finally:
            self.closed = True
            self.release_all()
            pending = [task for task in self.tasks.values() if not task.done()]
            if pending:
                deadline = app.state.factory['shutdown_deadline']
                _, unfinished = await asyncio.wait(pending,
                    timeout=max(0, deadline - asyncio.get_running_loop().time()))
                if unfinished:
                    app.state.factory['shutdown_failed']({'application': APPLICATION, 'reason': 'incomplete'})

    def release_all(self):
        for operation in self.operations.values():
            operation['allowStop'].set()

    def tool_factory(self, ctx):
        @tool(name=TOOL)
        async def original_operation(run_context: RunContext) -> str:
            """Execute the one original controlled operation, preserving its custody."""
            if self.closed or ctx.store is not self.store:
                raise ValueError('COMPOSITION_FIXTURE_OWNER_INVALID')
            identity = {'taskId': run_context.session_id, 'runId': run_context.run_id,
                        'ownerId': run_context.user_id}
            if any(getattr(run_context, field) != getattr(ctx.run_context, field)
                   for field in ('session_id', 'run_id', 'user_id')):
                raise ValueError('COMPOSITION_FIXTURE_IDENTITY_CHANGED')
            effect = self.store.effect_reserve(run_context.run_id, EFFECT, identity)
            if effect['status'] == 'done':
                return json.dumps(effect['result'])
            if effect['status'] != 'new':
                raise ValueError('COMPOSITION_ORIGINAL_EFFECT_UNKNOWN')
            self.calls.append(identity)
            operation = {**identity, 'allowStop': threading.Event(), 'stopped': threading.Event()}
            self.operations[run_context.session_id] = operation

            async def execute_original():
                # This provider fixture keeps working after native cancellation;
                # only its explicit stop handshake establishes positive proof.
                async with asyncio.timeout(90):
                    while not operation['allowStop'].is_set():
                        await asyncio.sleep(.02)
                operation['stopped'].set()
                result = {**identity, 'allStopped': True,
                          'cancelled': self.store.cancellation_requested(run_context.run_id)}
                self.store.effect_complete(run_context.run_id, EFFECT, result)
                return result

            pending = asyncio.create_task(execute_original())
            self.tasks[run_context.session_id] = pending
            pending.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            return json.dumps(await asyncio.shield(pending))

        return original_operation

    def task_held(self, store, task):
        operation = self.operations.get(task['id'])
        return operation is not None and not operation['stopped'].is_set()

    @staticmethod
    def effect_held(effect):
        return (effect.get('effect_key', '').endswith(':' + EFFECT)
                and (effect.get('result') or {}).get('allStopped') is not True)

    def ended_reason(self, store, task):
        return 'composition-original-stop-unconfirmed' if self.task_held(store, task) else None

    def mark_cancel(self, store, task_id):
        # Called inside Store.request_cancel's actual metadata transaction.
        self.mark_calls.append(task_id)

    async def cancel(self, store, task):
        self.cancel_calls.append((task['id'], task['run_id']))
        # An acknowledged stop request deliberately does not confirm completion.

    async def project_detail(self, api, task, plan, snapshot, events, job, wait):
        self.project_calls.append(task['id'])
        return {'compositionFixture': {'taskId': task['id'], 'runId': task['run_id'],
                'capacityHeld': self.task_held(self.store, task)}}, None

    def publish(self, state):
        governance, applications = state['material_governance'], state['applications']
        materials = []
        for kind, adapter in (('prompt', None), ('model', MODEL), ('tool', TOOL_ADAPTER),
                              ('environment', ENVIRONMENT)):
            definition = {'id': APPLICATION + '-' + kind, 'kind': kind, 'name': 'Composition ' + kind,
                'content': TOOL if kind == 'tool' else 'Call the declared controlled operation once.',
                'license': 'MIT', 'permissions': [PERMISSION] if kind == 'tool' else [],
                'compatibility': ['agno:3.1.0'], 'dependencies': [],
                'provenance': {'kind': 'original', 'notice': 'Inert composition acceptance fixture.'}}
            if adapter:
                definition['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': {}}
            row = governance.create_draft('alice', definition, APPLICATION + '-' + kind + '-draft')
            governance.publish('alice', row['id'], row['version'], APPLICATION + '-' + kind + '-publish')
            materials.append({key: row[key] for key in ('id', 'version', 'sha256')})
        draft = applications.create_draft('alice', {'contractVersion': 2, 'id': APPLICATION,
            'name': 'Controlled second application', 'description': 'Native composition fixture only.',
            'defaultMode': 'execute', 'modes': {'execute': {'materialRefs': materials,
                'capabilities': [PERMISSION], 'toolOrder': [TOOL],
                'budget': {'toolCalls': 2, 'maxDepth': 1, 'maxChildren': 1,
                           'operationSeconds': 30, 'outputBytes': 65536}}}}, APPLICATION + '-draft')
        applications.publish('alice', draft['id'], draft['version'], APPLICATION + '-publish')


def research_settings(database_url, workspace, runtime, second):
    source = Path(__file__).resolve().parents[4] / 'scripts/bootstrap_autoresearch.py'
    spec = importlib.util.spec_from_file_location('composition_autoresearch_bootstrap', source)
    assert spec and spec.loader
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)

    def runtime_factory(ctx, _service):
        runtime.identity = {'taskId': ctx.run_context.session_id, 'runId': ctx.run_context.run_id,
                            'ownerId': ctx.run_context.user_id}
        return runtime

    async def forbidden(*_):
        raise AssertionError('No scientific experiment or model call is requested')

    preset = ResearchPreset(id='composition-research', name='Controlled research composition',
        default_goal='Check original application ownership with an inert runtime', owner_id='alice',
        instructions='Synthetic composition only.', manifest={'schema': 1, 'evidenceMode': 'controlled'},
        limits={'totalSeconds': 120, 'experimentSeconds': 30, 'maxExperiments': 1,
                'toolCalls': 8, 'outputBytes': 65536}, runtime_factory=runtime_factory,
        context_reader=lambda: {}, candidate_validator=lambda _: {}, experiment=forbidden)
    settings = bootstrap.settings(db_url=database_url, workspace=workspace, preset=preset)
    settings.max_workers = settings.max_user_tasks = settings.max_total_tasks = 2
    settings.storage_low_water_bytes = 1
    settings.fee_management_enabled = settings.platform_paid_models_enabled = True
    settings.runtime_adapters = (*settings.runtime_adapters, *second.registrations())
    settings.usage_pricing = (*settings.usage_pricing, PricingRevision(MODEL, '1', PROVIDER, MODEL,
        'composition-zero-local-v1', local_model_type=SecondModel))
    settings.usage_policy = UsagePolicy(revision='composition-zero-local-v1', task_amount_micros=1_000_000,
        user_amount_micros=4_000_000, task_token_limit=1_000_000, user_token_limit=4_000_000)
    return settings, preset, bootstrap
