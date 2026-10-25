"""Actual OS interruption at three iteration admission boundaries.

Synthetic Agno model/tool pauses at native human confirmation; no ORX binary,
container or external model executes. The real iteration service, native bridge,
PG transactions, allocation ledger and driver's native recovery are exercised.
An allocation killed inside the transaction is rolled back, not a persisted
identity. Committed task bindings and dispatched native identities must survive.
This file is also its own bounded subprocess worker.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools import tool
from fastapi.testclient import TestClient

from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.store import digest
from agent_factory_research.config import ResearchSettings
from agent_factory_research.orx_local import TOY_FILES
from agent_factory_research.research_iteration_driver import ActualORXRoundDriver
from agent_factory_research.research_iterations import IterationPreset, ResearchIterations
from agent_factory_server.main import create_app
from pg_fixture import IsolatedPostgres

APP = 'iteration-crash-probe'
TOOL = 'iteration_recovery_probe'
MODEL = APP + '-model'
ENVIRONMENT = APP + '-environment'
TOOL_ADAPTER = APP + '-tool'
CAPABILITY = 'probe:read'
CAPS = {'rounds': 1, 'toolCalls': 8, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
CRASH_EXIT = 73


def save(path, value):
    with path.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def append(path, value):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def submissions(workspace):
    path = workspace / 'submissions.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class ApprovalProbeModel(Model):
    def __init__(self):
        super().__init__(id=MODEL, name='Synthetic interruption probe', provider='controlled-fixture', retries=0)

    def response(self, messages):
        if any(message.role == 'tool' for message in messages):
            return ModelResponse(role='assistant', content='Synthetic probe completed')
        return ModelResponse(role='assistant', tool_calls=[{'id': 'original-probe-call', 'type': 'function',
            'function': {'name': TOOL, 'arguments': '{}'}}])

    def invoke(self, messages, **kwargs):
        return self.response(messages)

    async def ainvoke(self, messages, **kwargs):
        return self.response(messages)

    def invoke_stream(self, messages, **kwargs):
        yield self.response(messages)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self.response(messages)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def settings_for(database_url, workspace):
    def build_tool(context):
        async def iteration_recovery_probe():
            """Synthetic business operation requiring native human confirmation."""
            append(workspace / 'business.jsonl', {'taskId': context.run_context.session_id})
            return {'synthetic': True}
        return tool(requires_confirmation=True)(iteration_recovery_probe)

    def install(state, *, research):
        governance, applications = state['material_governance'], state['applications']
        refs = []
        for kind, adapter in (('prompt', None), ('model', MODEL), ('tool', TOOL_ADAPTER), ('environment', ENVIRONMENT)):
            definition = {'id': APP + '-' + kind, 'kind': kind, 'name': 'Synthetic recovery ' + kind,
                'content': TOOL if kind == 'tool' else 'Request the synthetic confirmation probe.',
                'license': 'MIT', 'permissions': [CAPABILITY] if kind == 'tool' else [],
                'compatibility': ['agno:3.1.0'], 'dependencies': [],
                'provenance': {'kind': 'original', 'notice': 'Synthetic process interruption fixture only'}}
            if adapter:
                definition['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': {}}
            material = governance.create_draft('alice', definition, 'probe-draft-' + kind)
            governance.publish('alice', material['id'], material['version'], 'probe-publish-' + kind)
            refs.append({key: material[key] for key in ('id', 'version', 'sha256')})
        application = applications.create_draft('alice', {'contractVersion': 2, 'id': APP,
            'name': 'Synthetic iteration interruption', 'description': 'No ORX or external model',
            'defaultMode': 'execute', 'modes': {'execute': {'materialRefs': refs, 'capabilities': [CAPABILITY],
                'toolOrder': [TOOL], 'connectionRequirements': [], 'budget': {'toolCalls': 8, 'maxDepth': 1,
                    'maxChildren': 1, 'operationSeconds': 30, 'outputBytes': 65536}}}}, 'probe-application-draft')
        applications.publish('alice', application['id'], application['version'], 'probe-application-publish')
        pins = {'applicationRef': {key: application[key] for key in ('id', 'version', 'sha256')},
                'mode': 'execute', 'connectionRefs': {}}
        baseline = {'kind': 'reviewedSeed', 'sha256': TOY_FILES['baseline.py'], 'metricValue': 16.0,
            'datasetSha256': TOY_FILES['dataset.json'], 'evaluatorSha256': TOY_FILES['evaluator.py']}
        preset = IterationPreset(APP, 'alice', digest({'pins': pins, 'baseline': baseline}), pins, baseline, CAPS, 30)
        # Use its real reserve/submit/find_run/native-binding path only. The
        # synthetic native gate never produces or claims an ORX evaluation.
        driver = ActualORXRoundDriver(state['store'], state['auth'], state['bridge'],
                                      state['factory_api'].commands, research=research)
        return ResearchIterations(state['store'], state['auth'], research=research,
                                  presets={APP: preset}, round_driver=driver)

    return ResearchSettings(db_url=database_url, workspace=workspace, max_workers=1, queue_poll=.2,
        temporary_policy='member-self-service', research_iterations_factory=install,
        runtime_adapters=[AdapterRegistration('model', MODEL, '1', lambda _: ApprovalProbeModel(), demo_only=True),
            AdapterRegistration('tool', TOOL_ADAPTER, '1', build_tool, tool_name=TOOL, permissions=(CAPABILITY,)),
            AdapterRegistration('environment', ENVIRONMENT, '1', lambda _: EnvironmentLimits())])


def counts(store):
    return {table: store.sql('SELECT COUNT(*) AS n FROM ' + table)[0]['n'] for table in (
        'af_research_activities', 'af_research_rounds', 'af_local_budget_scopes', 'af_local_budget_allocations', 'af_tasks')}


def child(phase, boundary, workspace):
    case = json.loads((workspace / 'case.json').read_text())
    app = create_app(settings_for(os.environ['ITERATION_RECOVERY_DATABASE_URL'], workspace))
    state = app.app.state.factory
    store, service = state['store'], state['research'].iterations
    original_submit = state['bridge'].submit
    checkpoint_path = workspace / 'checkpoint.json'

    def crash(value):
        save(checkpoint_path, {'boundary': boundary, 'pid': os.getpid(), **value})
        os._exit(CRASH_EXIT)

    async def submit(plan, owner, request_id):
        receipt = await original_submit(plan, owner, request_id)
        append(workspace / 'submissions.jsonl', {'pid': os.getpid(), 'taskId': plan['task_id'],
            'requestId': request_id, 'runId': receipt['run_id']})
        if phase == 'crash' and boundary == 'after_submit_before_ack':
            round = service.round_for_task(owner, plan['task_id'])
            if round['dispatchAttempted'] is not True or store.task(plan['task_id'], owner)['run_id'] is not None:
                raise AssertionError('Interruption must follow the committed fence and precede native acceptance')
            crash({'snapshot': service.inspect(owner, round['activityId']), 'receipt': receipt})
        return receipt
    state['bridge'].submit = submit

    if phase == 'crash' and boundary == 'after_allocation_before_binding':
        allocate = store.local_budget_scopes.allocate
        def interrupted_allocate(conn, owner, scope_id, allocation_id, intent_sha, caps):
            value = allocate(conn, owner, scope_id, allocation_id, intent_sha, caps)
            crash({'scopeId': scope_id, 'allocationId': allocation_id, 'uncommittedAllocation': value})
        store.local_budget_scopes.allocate = interrupted_allocate
    if phase == 'crash' and boundary == 'after_committed_task_binding':
        async def interrupted_dispatch(owner, activity_id):
            snapshot = service.inspect(owner, activity_id)
            if snapshot['rounds'][0]['dispatchAttempted'] is not False or not snapshot['rounds'][0]['taskId']:
                raise AssertionError('Interruption requires committed task binding before the dispatch fence')
            crash({'snapshot': snapshot})
        service._dispatch = interrupted_dispatch

    previous = json.loads(checkpoint_path.read_text()) if phase == 'recover' else None
    before = counts(store) if phase == 'recover' else None
    check = unittest.TestCase()
    if previous is not None:
        check.assertNotEqual(previous['pid'], os.getpid())
        if boundary == 'after_allocation_before_binding':
            check.assertTrue(all(count == 0 for count in before.values()), before)
        else:
            check.assertTrue(all(count == 1 for count in before.values()), before)
            retained = service.inspect('alice', previous['snapshot']['activity']['id'])
            for key in ('id', 'taskId', 'planId', 'planSha256', 'requestId', 'allocationId', 'intentSha256', 'dispatchAttempted'):
                check.assertEqual(retained['rounds'][0][key], previous['snapshot']['rounds'][0][key])

    try:
        with TestClient(app) as client:
            def request(method, path, body=None, expected=200):
                response = client.request(method, '/api/factory' + path, json=body,
                    headers={'Authorization': 'Bearer ' + state['auth']._issue_native_token('alice'),
                             'X-Factory-Expected-Owner': 'alice'})
                check.assertEqual(response.status_code, expected, response.text)
                return response.json()
            if phase == 'crash':
                request('POST', '/research-iterations', case, 201)
                raise AssertionError('Configured interruption did not exit its owned process')
            if boundary == 'after_allocation_before_binding':
                # The interrupted transaction did not leave a free successor or
                # authority to advance. Retry the same submitted request only.
                request('GET', '/research-iterations/requests/' + case['requestId'], expected=404)
                request('POST', '/research-iterations/' + previous['scopeId'] + '/advance',
                    {'previousRoundId': previous['allocationId'], 'requestId': 'no-free-successor'}, 404)
                value = request('POST', '/research-iterations', case, 201)
                check.assertEqual(value['activity']['id'], previous['scopeId'])
                check.assertEqual(value['rounds'][0]['allocationId'], previous['allocationId'])
            else:
                value = request('GET', '/research-iterations/requests/' + case['requestId'])
            activity_id = value['activity']['id']
            end = time.monotonic() + 20
            binding = None
            binding_error = None
            while time.monotonic() < end:
                value = request('GET', '/research-iterations/' + activity_id)
                round = value['rounds'][0]
                task = store.task(round['taskId'], 'alice')
                try:
                    binding = state['lifecycle_observer']._binding(task) if task['run_id'] else None
                    binding_error = None
                except ValueError as error:
                    # Native queue admission may precede its persisted session.
                    # Require a successful strict read before the bounded wait ends.
                    binding, binding_error = None, type(error).__name__
                if round['runId'] == task['run_id'] and binding and binding['persistedRunStatus'] == 'paused':
                    break
                time.sleep(.05)
            else:
                raise AssertionError(json.dumps({'snapshot': value, 'coordinatorError':
                    state['research'].iteration_coordinator.last_error_type,
                    'strictBindingError': binding_error, 'binding': {key: (binding or {}).get(key) for key in ('id', 'status', 'persistedRunStatus')}}))
            check.assertEqual(len(value['rounds']), 1)
            check.assertEqual(value['budget']['allocatedRounds'], 1)
            check.assertEqual(value['budget']['heldToolCalls'], 8)
            check.assertEqual(value['budget']['settledToolCalls'], 0)
            check.assertEqual(store.effects(task['id']), [])
            check.assertFalse((workspace / 'business.jsonl').exists(), 'No human approved the synthetic tool')
            calls = submissions(workspace)
            check.assertEqual(len(calls), 1, calls)
            check.assertEqual((calls[0]['taskId'], calls[0]['runId']), (task['id'], task['run_id']))
            if boundary == 'after_submit_before_ack':
                check.assertEqual(calls[0]['pid'], previous['pid'], 'Recovery must never resubmit')
                check.assertEqual(task['run_id'], previous['receipt']['run_id'])
            else:
                check.assertEqual(calls[0]['pid'], os.getpid(), 'Exactly one initial submit after recovery')
            if boundary != 'after_allocation_before_binding':
                for key in ('id', 'taskId', 'planId', 'planSha256', 'requestId', 'allocationId', 'intentSha256'):
                    check.assertEqual(round[key], previous['snapshot']['rounds'][0][key])
            request('GET', '/research-iterations')
            request('GET', '/research-iterations/requests/' + case['requestId'])
            request('POST', '/research-iterations', case, 201)
            request('POST', '/research-iterations', {**case, 'goal': 'Changed original request must conflict'}, 409)
            check.assertEqual(submissions(workspace), calls)
            check.assertTrue(all(count == 1 for count in counts(store).values()), counts(store))
            report = {'pid': os.getpid(), 'previousPid': previous['pid'], 'boundary': boundary,
                'beforeCounts': before, 'afterCounts': counts(store), 'snapshot': value, 'submissions': calls,
                'binding': {key: binding[key] for key in ('id', 'session_id', 'user_id', 'status', 'persistedRunStatus')}}
            # Normal cleanup cancels only this owned synthetic paused task.
            request('POST', '/research-iterations/' + activity_id + '/cancel', {})
        save(workspace / 'recovery-report.json', report)
    finally:
        store.native_db.db_engine.dispose()
        store.engine.dispose()


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL/native processes')
class ResearchIterationProcessRecoveryTests(unittest.TestCase):
    def exercise(self, boundary):
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, \
                TemporaryDirectory(prefix='iteration-crash-') as directory:
            workspace = Path(directory)
            save(workspace / 'case.json', {'presetId': APP, 'requestId': 'original-interrupted-request',
                'goal': 'Pause synthetic native work for process recovery', 'caps': CAPS, 'deadline': time.time() + 600})
            root = Path(__file__).resolve().parents[4]
            environment = {**os.environ, 'ITERATION_RECOVERY_DATABASE_URL': database.url,
                'PYTHONPATH': os.pathsep.join(str(root / path) for path in (
                    'platform', 'apps/research', 'deployment', 'platform/tests', 'apps/research/tests/python'))}
            environment.pop('FACTORY_TEST_DATABASE_URL', None)
            observations = []
            try:
                for phase, expected in (('crash', CRASH_EXIT), ('recover', 0)):
                    log = workspace / (phase + '.log')
                    began, forced = time.monotonic(), False
                    with log.open('wb') as stream:
                        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', phase,
                            '--boundary', boundary, '--workspace', str(workspace)], cwd=root, env=environment,
                            stdout=stream, stderr=subprocess.STDOUT)
                        try:
                            code = process.wait(timeout=80)
                        except subprocess.TimeoutExpired:
                            forced = True
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill(); process.wait(timeout=5)
                            code = process.returncode
                        finally:
                            if process.poll() is None:
                                process.kill(); process.wait(timeout=5)
                    observations.append({'phase': phase, 'pid': process.pid, 'exitCode': code,
                        'forcedFixtureStop': forced, 'elapsedSeconds': round(time.monotonic() - began, 3)})
                    save(workspace / 'process-observations.json', observations)
                    tail = log.read_text(errors='replace')[-12000:].replace(database.url, '[synthetic-db-url]')
                    self.assertFalse(forced, tail)
                    self.assertEqual(code, expected, tail)
                checkpoint = json.loads((workspace / 'checkpoint.json').read_text())
                report = json.loads((workspace / 'recovery-report.json').read_text())
                self.assertEqual(checkpoint['pid'], observations[0]['pid'])
                self.assertEqual(report['pid'], observations[1]['pid'])
                self.assertNotEqual(report['pid'], checkpoint['pid'])
                self.assertEqual(len(report['submissions']), 1)
            finally:
                evidence = os.getenv('FACTORY_ITERATIONS_RECOVERY_EVIDENCE_DIR')
                if evidence:
                    destination = Path(evidence) / (boundary + '-' + workspace.name)
                    destination.mkdir(parents=True, exist_ok=False)
                    for source in workspace.glob('*'):
                        if source.name in {'case.json', 'checkpoint.json', 'recovery-report.json',
                                           'process-observations.json', 'submissions.jsonl'}:
                            shutil.copy2(source, destination / source.name)
                        elif source.suffix == '.log':
                            (destination / source.name).write_text(source.read_text(errors='replace')
                                .replace(database.url, '[synthetic-db-url]'))

    def test_exit_after_uncommitted_allocation_rolls_back_without_free_successor(self):
        self.exercise('after_allocation_before_binding')

    def test_exit_after_committed_task_binding_submits_original_once(self):
        self.exercise('after_committed_task_binding')

    def test_exit_after_native_submit_before_ack_recovers_original_without_resubmit(self):
        self.exercise('after_submit_before_ack')


if __name__ == '__main__':
    if '--worker' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--worker', choices=('crash', 'recover'), required=True)
        parser.add_argument('--boundary', choices=('after_allocation_before_binding', 'after_committed_task_binding',
                                                  'after_submit_before_ack'), required=True)
        parser.add_argument('--workspace', type=Path, required=True)
        arguments = parser.parse_args()
        child(arguments.worker, arguments.boundary, arguments.workspace)
    else:
        unittest.main()
