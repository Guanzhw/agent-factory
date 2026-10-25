"""Explicit inert native fixtures; production startup never imports this module.

Agno owns execution. These registrations provide deterministic model responses,
a real UTF-8 checksum and native user input, with core authority/artifact checks.
"""
import asyncio
import hashlib
import subprocess
import sys
import json
from dataclasses import dataclass

from agno.exceptions import RunCancelledException
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools import tool
from agent_factory.application_schema import ApplicationDefinition, ApplicationDefinitionV2
from agent_factory.execution_bindings import ExecutionBindings, EnvironmentLimits, KnowledgeContext
from agent_factory.main import create_app as create_core_app
from agent_factory.usage_ledger import PricingRevision

MODEL_ADAPTER = 'fixture-model-v1'
ENVIRONMENT_ADAPTER = 'fixture-environment-v1'
SEEDS = [
    ('fixture-skill', 'skill', 'Checksum procedure', 'Check the supplied text and record its digest.', []),
    ('fixture-prompt', 'prompt', 'Checksum instructions', 'Use the declared tools on the supplied input.', []),
    ('fixture-knowledge', 'knowledge', 'Inert reference', 'SHA-256 computes a digest of UTF-8 bytes.', []),
    ('fixture-question-tool', 'tool', 'Scope input', 'ask_scope', ['question:ask']),
    ('fixture-checksum-tool', 'tool', 'Checksum', 'checksum', ['checksum:read']),
    ('fixture-model', 'model', 'Controlled native model', 'No provider network calls.', []),
    ('fixture-environment', 'environment', 'Bounded fixture', 'Inert local tools only.', []),
]
LEGACY_BINDINGS = {
    'fixture-operation-tool': ('tool', 'fixture-operation-v1'),
    'fixture-model': ('model', MODEL_ADAPTER),
    'fixture-environment': ('environment', ENVIRONMENT_ADAPTER),
    'fixture-knowledge': ('knowledge', 'fixture-knowledge-v1'),
    'fixture-question-tool': ('tool', 'fixture-ask-scope-v1'),
    'fixture-checksum-tool': ('tool', 'fixture-checksum-v1'),
}

@dataclass
class FixtureModel(Model):
    id: str = 'fixture-native-model'
    name: str = 'Controlled native checksum driver'
    provider: str = 'controlled-fixture'

    def _response(self, messages):
        system = next((str(m.content) for m in messages if m.role == 'system'), '')
        marker = 'FACTORY_SYNTHETIC_CONTEXT='
        encoded = next((line.split(marker, 1)[1] for line in reversed(system.splitlines()) if marker in line), '{}')
        plan = json.loads(encoded)
        results = {}
        for message in messages:
            if message.role != 'tool':
                continue
            if message.tool_call_error:
                return ModelResponse(role='assistant', content=json.dumps({'status': 'failed', 'errors': [str(message.content)]}))
            try:
                results[message.tool_name] = json.loads(message.content)
            except (TypeError, ValueError):
                results[message.tool_name] = {'message': str(message.content)}
        config = plan.get('config') or {}
        names = plan.get('tools') or []
        if config.get('askScope') and 'ask_scope' in names and 'ask_scope' not in results:
            name, arguments = 'ask_scope', {'question': 'Which text should be checked?'}
        elif 'fixture_operation' in names and 'fixture_operation' not in results:
            name, arguments = 'fixture_operation', {}
        elif 'checksum' in names and 'checksum' not in results:
            value = (plan.get('inputValues') or {}).get('payload', config.get('sample', plan.get('normalizedGoal', 'fixture')))
            name, arguments = 'checksum', {'text': str(value)}
        else:
            return ModelResponse(role='assistant', content=json.dumps({'status': 'synthetic-complete', 'evidenceKind': 'synthetic', 'modelId': self.id, 'results': results}))
        return ModelResponse(role='assistant', tool_calls=[{'id': 'fixture-' + name, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}])

    def invoke(self, messages, **kwargs): return self._response(messages)
    async def ainvoke(self, messages, **kwargs): return self._response(messages)
    def invoke_stream(self, messages, **kwargs): yield self._response(messages)
    async def ainvoke_stream(self, messages, **kwargs): yield self._response(messages)
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response, **kwargs): return response


def build_tools(settings, store, operation_name='fixture_operation'):
    def checked(context, name):
        if store.cancellation_requested(context.run_id):
            raise RunCancelledException('Fixture cancellation requested')
        store.authorize_tool(context, name)
        return store.resolve_run(context)

    @tool(requires_user_input=True, user_input_fields=['scope'])
    def ask_scope(question: str, scope: str, run_context: RunContext) -> str:
        """Ask for the input scope using Agno's native input boundary."""
        checked(run_context, 'ask_scope')
        if not scope.strip() or len(scope) > 4000:
            raise ValueError('Scope must contain between 1 and 4000 characters')
        result = {'question': question, 'scope': scope.strip(), 'evidenceKind': 'synthetic'}
        store.event(run_context.run_id, 'scope_answered', 'Fixture scope accepted', {'scope': scope.strip()})
        return json.dumps(result)

    def checksum(text: str, run_context: RunContext) -> str:
        """Compute the digest of the actual supplied UTF-8 bytes."""
        plan = checked(run_context, 'checksum')
        raw = text.encode()
        if len(raw) > 65536:
            raise ValueError('Checksum input exceeds 64 KiB')
        result = {'algorithm': 'sha256', 'sha256': hashlib.sha256(raw).hexdigest(),
            'inputBytes': len(raw), 'evidenceKind': 'synthetic-input-real-computation'}
        encoded = json.dumps(result, sort_keys=True)
        manifest = plan.get('executionBindings') or {}
        metadata = {'evidenceKind': result['evidenceKind'], 'modelAdapterId': manifest.get('model', {}).get('adapterId', MODEL_ADAPTER),
            'environmentAdapterId': manifest.get('environment', {}).get('adapterId', ENVIRONMENT_ADAPTER),
            'executionBindingsSha256': manifest.get('sha256'), 'sha256': hashlib.sha256(encoded.encode()).hexdigest()}
        store.artifact_write(run_context.run_id, 'checksum.json', encoded, 'application/json', metadata)
        store.event(run_context.run_id, 'checksum_completed', 'Fixture checksum computed', result)
        return json.dumps(result)
    @tool(name=operation_name, requires_confirmation=True)
    async def fixture_operation(run_context: RunContext) -> str:
        """Run and reap one inert owned subprocess under current native authority."""
        checked(run_context, operation_name)
        key = 'fixture-operation-v1'
        reserved = store.effect_reserve(run_context.run_id, key, {'taskId': run_context.session_id})
        if reserved['status'] == 'done':
            return json.dumps(reserved['result'])
        if reserved['status'] != 'new':
            raise RuntimeError('UNKNOWN original fixture operation cannot be dispatched again')
        try:
            plan = store.resolve_run(run_context)
            limits = await asyncio.to_thread(store.execution_bindings.environment_limits, plan, run_context)
            checked(run_context, operation_name)
        except BaseException as error:
            store.effect_complete(run_context.run_id, key, {
                'cancelled': True, 'dispatchState': 'never-dispatched',
                'allStopped': True, 'cleanupComplete': True})
            if isinstance(error, (RunCancelledException, asyncio.CancelledError)):
                raise
            store.event(run_context.run_id, 'protected_denied', 'Preflight denied before dispatch', {'tool': operation_name})
            raise RunCancelledException('Preflight denied before dispatch') from error
        started = asyncio.get_running_loop().time()
        process = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(3)'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        store.event(run_context.run_id, 'operation_started', 'Owned inert process started', {'pid': process.pid})
        failure = None
        try:
            while process.poll() is None:
                await asyncio.sleep(.02)
                if asyncio.get_running_loop().time() - started >= limits.timeout_seconds:
                    raise TimeoutError('Selected environment wall time exceeded')
                try:
                    await asyncio.to_thread(checked, run_context, operation_name)
                except RunCancelledException:
                    raise
                except Exception as error:
                    store.event(run_context.run_id, 'protected_denied', 'Current authority ended for original operation', {'tool': operation_name})
                    raise RunCancelledException('Current authority ended for original operation') from error
        except BaseException as error:
            failure = error
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                await asyncio.to_thread(process.wait, 2)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 2)
            result = {'allStopped': True, 'cancelled': isinstance(failure, (RunCancelledException, asyncio.CancelledError)) or store.cancellation_requested(run_context.run_id),
                'exitCode': process.returncode, 'cleanupComplete': True, 'evidenceKind': 'synthetic-owned-process'}
            store.event(run_context.run_id, 'operation_stopped', 'Original owned process reaped',
                {'pid': process.pid, 'allStopped': True, 'cleanupComplete': True})
            store.effect_complete(run_context.run_id, key, result)
        if failure is not None:
            if result['cancelled']:
                store.event(run_context.run_id, 'operation_cancelled', 'Original operation stopped after cancellation', result)
            raise failure
        store.event(run_context.run_id, 'operation_completed', 'Owned fixture completed', result)
        return json.dumps(result)
    return {'ask_scope': ask_scope, 'checksum': checksum, operation_name: fixture_operation}


def fixture_bindings(settings, store, connections=None):
    registry = ExecutionBindings(settings, store, connections, legacy_materials=SEEDS, legacy_bindings=LEGACY_BINDINGS)
    def empty(config):
        if config: raise ValueError('Fixture adapter accepts no configuration')
    registry.register('model', MODEL_ADAPTER, '1', lambda _: FixtureModel(), demo_only=True, validator=empty)
    for name, permission in [('checksum', 'checksum:read'), ('ask_scope', 'question:ask')]:
        registry.register('tool', 'fixture-' + name.replace('_', '-') + '-v1', '1',
            lambda context, name=name: build_tools(context.settings, context.store)[name],
            tool_name=name, permissions=(permission,), validator=empty)
    registry.register('tool', 'fixture-operation-v1', '1',
        lambda context: build_tools(context.settings, context.store)['fixture_operation'],
        tool_name='fixture_operation', permissions=('fixture:operate',), demo_only=True, validator=empty)
    def knowledge(context):
        ref = context.spec['materialRef']
        material = next(item for item in context.plan['materials'] if all(item[k] == ref[k] for k in ref))
        return KnowledgeContext(material['content'], {'evidenceKind': 'synthetic', 'source': 'approved-material-content'})
    registry.register('knowledge', 'fixture-knowledge-v1', '1', knowledge, demo_only=True, validator=empty)
    fields = {'runtimeId': 'runtime_id', 'timeoutSeconds': 'timeout_seconds', 'outputBytes': 'output_bytes',
        'memoryBytes': 'memory_bytes', 'processLimit': 'process_limit', 'cpuPercent': 'cpu_percent'}
    def environment(context):
        config = context.spec['config']
        if set(config) - fields.keys(): raise ValueError('Unknown bounded environment configuration')
        return EnvironmentLimits(**{fields[k]: v for k, v in config.items()})
    def validate_environment(config):
        from types import SimpleNamespace
        environment(SimpleNamespace(spec={'config': config}))
    registry.register('environment', ENVIRONMENT_ADAPTER, '1', environment, validator=validate_environment)
    return registry


def fixture_zero_prices():
    return (PricingRevision(MODEL_ADAPTER, '1', 'controlled-fixture', 'fixture-native-model',
        'zero-local-v1', local_model_type=FixtureModel),)


def fixture_definitions(seeds):
    def mode(ask=False):
        ids = ['fixture-model', 'fixture-environment', 'fixture-checksum-tool']
        if ask: ids += ['fixture-question-tool', 'fixture-skill', 'fixture-prompt', 'fixture-knowledge']
        return {'materialRefs': [{k: seeds[mid][k] for k in ('id', 'version', 'sha256')} for mid in ids],
            'capabilities': ['checksum:read'] + (['question:ask'] if ask else []),
            'toolOrder': (['ask_scope'] if ask else []) + ['checksum'], 'config': {'askScopeBelowLength': 12 if ask else 0}}
    values = [{'id': app_id, 'name': app_id, 'defaultForDiscovery': ask, 'discoveryKeywords': ['scope'] if ask else ['checksum'],
        'modes': {'literature': mode(ask), 'experiment': ({**mode(ask),
            'materialRefs': mode(ask)['materialRefs'] + [{k: seeds['fixture-operation-tool'][k] for k in ('id', 'version', 'sha256')}],
            'capabilities': mode(ask)['capabilities'] + ['fixture:operate'],
            'toolOrder': ['ask_scope', 'fixture_operation', 'checksum']} if ask else mode(False))}}
        for app_id, ask in [('fixture-text', True), ('fixture-checksum', False)]]
    return [ApplicationDefinition.model_validate(value).model_dump(exclude_none=True) for value in values]


def fixture_v2_definitions(seeds):
    mode = {
        'materialRefs': [{k: seeds[mid][k] for k in ('id', 'version', 'sha256')}
            for mid in ('fixture-model', 'fixture-environment', 'fixture-checksum-tool')],
        'capabilities': ['checksum:read'], 'toolOrder': ['checksum']}
    return [ApplicationDefinitionV2.model_validate({'contractVersion': 2, 'id': 'fixture-checksum-v2', 'name': 'Fixture checksum v2',
        'defaultMode': 'execute', 'modes': {'execute': mode}}).model_dump(exclude_none=True)]


def all_fixture_definitions(seeds):
    return [*fixture_definitions(seeds), *fixture_v2_definitions(seeds)]


def governed_fixture_definitions(store, definitions=all_fixture_definitions):
    """Publish the fixture-only operation through normal material governance.

    Reuse its immutable first revision on restart, including withdrawn state;
    startup must never reactivate a withdrawn material.
    """
    def define(seeds):
        material = next((item for item in store.materials()
            if item['id'] == 'fixture-operation-tool' and item['version'] == 1), None)
        if material is None:
            governance = store.material_governance
            material = governance.create_draft('manager', {
                'id': 'fixture-operation-tool', 'kind': 'tool', 'name': 'Controlled operation',
                'content': 'fixture_operation', 'permissions': ['fixture:operate'],
                'runtimeBinding': {'adapterId': 'fixture-operation-v1', 'revision': '1', 'config': {}}},
                'fixture-operation:draft')
            governance.publish('manager', material['id'], material['version'], 'fixture-operation:publish')
        return definitions({**seeds, material['id']: material}) if callable(definitions) else definitions
    return define


def create_fixture_app(settings, **kwargs):
    prices = {(p.adapter_id, p.adapter_revision): p for p in (*fixture_zero_prices(), *settings.usage_pricing)}
    settings.usage_pricing = tuple(prices.values())
    options = dict(bindings_factory=fixture_bindings, seed_materials=SEEDS,
        demo_definitions=all_fixture_definitions, tool_catalog_factory=build_tools)
    options.update(kwargs)
    original_bindings = options['bindings_factory']
    original_definitions = options['demo_definitions']
    captured = {}
    def bindings(*args):
        captured['store'] = args[1]
        return original_bindings(*args)
    options['bindings_factory'] = bindings
    options['demo_definitions'] = lambda seeds: governed_fixture_definitions(captured['store'], original_definitions)(seeds)
    return create_core_app(settings, **options)


def publish_owner_application(state, *, author):
    """Publish a member fixture using the real owner-model adapter and checksum."""
    from agent_factory.byok_model import ADAPTER_ID
    governance, applications = state['material_governance'], state['applications']
    identifier = 'fixture-owner-checksum'
    model = governance.create_draft(author, {'id': identifier + '-model', 'kind': 'model',
        'name': 'Fixture owner model', 'content': 'Explicit owner model connection.',
        'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [], 'permissions': [],
        'runtimeBinding': {'adapterId': ADAPTER_ID, 'revision': '1', 'config': {'connectionName': 'ownerModel'}}},
        identifier + ':model-draft')
    governance.publish(author, model['id'], model['version'], identifier + ':model-publish')
    seeds = {item['id']: item for item in state['store'].materials(published_only=True)}
    materials = [model, seeds['fixture-environment'], seeds['fixture-checksum-tool']]
    definition = {'id': identifier, 'name': 'Fixture owner checksum', 'defaultMode': 'literature',
        'modes': {'literature': {'materialRefs': [applications.pin(item) for item in materials],
            'capabilities': ['checksum:read'], 'toolOrder': ['checksum'],
            'connectionRequirements': [{'name': 'ownerModel', 'kind': 'model', 'required': True,
                'requiredCapabilities': []}]}}}
    application = applications.create_draft(author, definition, identifier + ':draft')
    applications.publish(author, application['id'], application['version'], identifier + ':publish')
    return application


def selected_bounded_operation(context):
    """Use the core Linux guardian for an explicit selected-limit acceptance case.

    ProcessLimits enforces per-process address space/CPU/file size and guarded
    wall time. It does not promise an aggregate process count or CPU percentage.
    A timed-out business operation stays UNKNOWN even after positive stop proof.
    """
    from pathlib import Path
    from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec

    @tool(name='fixture_operation', requires_confirmation=True)
    async def operation(run_context: RunContext) -> str:
        store = context.store
        plan = store.resolve_run(run_context)
        selected = store.execution_bindings.environment_limits(plan, run_context)
        key = 'fixture-selected-process-v1'
        intent = {'taskId': run_context.session_id, 'runtimeId': selected.runtime_id}
        reserved = store.effect_reserve(run_context.run_id, key, intent)
        if reserved['status'] != 'new':
            raise RuntimeError('UNKNOWN original bounded operation cannot be dispatched again')
        directory = Path(context.settings.runtime_directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        executable = Path(sys.executable).resolve()
        limits = ProcessLimits(cpu_seconds=1, address_space_mb=selected.memory_bytes // (1024 * 1024),
            file_size_bytes=selected.output_bytes, wall_seconds=selected.timeout_seconds)
        # Read back kernel limits inside the actual child before its inert wait.
        program = ('import json,resource,time; '
            'print(json.dumps({"memoryBytes":resource.getrlimit(resource.RLIMIT_AS)[0],'
            '"outputBytes":resource.getrlimit(resource.RLIMIT_FSIZE)[0],'
            '"cpuSeconds":resource.getrlimit(resource.RLIMIT_CPU)[0]}),flush=True); time.sleep(3)')
        spec = ProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(), ('-I', '-c', program))
        adapter = await asyncio.to_thread(BoundedProcessAdapter.create, directory / (run_context.run_id + '.sqlite'),
            owner_id=run_context.user_id, task_id=run_context.session_id, request_id=run_context.run_id,
            spec=spec, limits=limits)
        observation = None
        try:
            await asyncio.to_thread(adapter.launch, owner_id=run_context.user_id,
                before_effect=lambda: store.authorize_tool(run_context, 'fixture_operation'))
            async with asyncio.timeout(8):
                while True:
                    observation = await asyncio.to_thread(adapter.inspect, owner_id=run_context.user_id)
                    if observation['stoppedProof']:
                        break
                    await asyncio.sleep(.02)
        finally:
            # Cleanup always targets the original journal; it cannot relaunch.
            if observation is None or not observation['stoppedProof']:
                await asyncio.to_thread(adapter.cancel, owner_id=run_context.user_id)
                async with asyncio.timeout(5):
                    while not (await asyncio.to_thread(adapter.inspect, owner_id=run_context.user_id))['stoppedProof']:
                        await asyncio.sleep(.02)
        kernel_limits = json.loads(adapter.path.with_suffix('.output').read_text())
        store.event(run_context.run_id, 'bounded_operation_stopped', 'Original core process stop proof',
            {'runtimeId': selected.runtime_id, 'observation': observation, 'kernelLimits': kernel_limits})
        if observation['state'] != 'COMPLETED':
            store.event(run_context.run_id, 'effect_unknown', 'No successful business outcome after bounded stop',
                {'effectKey': key, 'state': observation['state']})
            raise TimeoutError('Selected environment stopped the original bounded operation')
        result = {'allStopped': True, 'evidenceKind': 'controlled-core-process'}
        store.effect_complete(run_context.run_id, key, result)
        return json.dumps(result)
    return operation
