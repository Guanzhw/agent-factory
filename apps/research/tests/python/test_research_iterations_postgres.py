"""Two actual pinned ORX rounds through the opt-in production profile.

Requires disposable PG and the reviewed Linux container toolchain. Deterministic
local Agno models are real native tasks, not evidence of external model quality.
The recovery case restarts application services in this process, not the OS.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient

from agent_factory.store import digest
from agent_factory_server.main import create_app
from agent_factory_research.orx_local import TaskLocalORXProvider, TOY_FILES
from agent_factory_research.orx_linux import RUNTIME_IMAGE
from agent_factory_research.orx_experiment_tools import LAUNCH_EFFECT_KEY, inspect_orx_experiment
from agent_factory_research.research_iteration_profile import PROFILE_ID, local_iteration_profile_settings
from agent_factory_research.research_iteration_recipe import SEED_IDENTITY, PROMOTED_IDENTITY
from pg_fixture import IsolatedPostgres
import test_orx_experiment_factory as original


_REQUIRED = ('FACTORY_TEST_DATABASE_URL', 'FACTORY_ORX_BINARY', 'FACTORY_ORX_SOURCE_ARCHIVE', 'FACTORY_ORX_GIT_BINARY')


@unittest.skipUnless(sys.platform.startswith('linux') and os.getenv('FACTORY_ORX_LINUX_CONTAINER') == '1'
                     and all(os.getenv(key) for key in _REQUIRED),
                     'Requires disposable PG, pinned actual ORX and reviewed Linux container')
class ResearchIterationsPostgresTests(unittest.TestCase):
    process_limit = 64
    native_rows = original.ActualORXNativeFactoryTests.native_rows

    def setUp(self):
        self.database = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        self.directory = self.enterContext(TemporaryDirectory(prefix='factory-actual-iterations-'))
        self.workspace = Path(self.directory)
        self.dispatches, self.snapshots, self.artifact_proofs = [], [], []
        self.activity_ids = set()
        self.failure_snapshots = []
        self.lose_dispatch_once = False
        self.client = None
        self.addCleanup(self.preserve_evidence)
        self.addCleanup(self.remove_owned_containers)
        self.addCleanup(self.cleanup_activity)
        provider = TaskLocalORXProvider(binary=Path(os.environ['FACTORY_ORX_BINARY']).resolve(),
            source_archive=Path(os.environ['FACTORY_ORX_SOURCE_ARCHIVE']).resolve(),
            git_binary=Path(os.environ['FACTORY_ORX_GIT_BINARY']).resolve(),
            python_binary=Path(os.getenv('FACTORY_ORX_PYTHON_BINARY', sys._base_executable)).resolve())
        with provider.binary.open('rb') as binary:
            self.binary_sha = hashlib.file_digest(binary, 'sha256').hexdigest()
        self.settings = local_iteration_profile_settings(db_url=self.database.url, workspace=self.workspace, provider=provider)
        self.open()

    def open(self):
        # The real production profile performs idempotent metadata publication
        # on restart. This is not represented as a mutation-free startup.
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.research = self.state['research']
        self.service = self.research.iterations
        submit = self.state['bridge'].submit
        async def observed_submit(plan, owner, request_id):
            receipt = await submit(plan, owner, request_id)
            self.dispatches.append({'taskId': plan['task_id'], 'owner': owner, 'requestId': request_id,
                                    'runId': receipt['run_id']})
            if self.lose_dispatch_once:
                self.lose_dispatch_once = False
                raise TimeoutError('SYNTHETIC_ITERATION_NATIVE_ACK_LOST')
            return receipt
        self.state['bridge'].submit = observed_submit
        self.client = TestClient(self.app).__enter__()

    def cleanup_activity(self):
        try:
            if self.client is not None:
                for identifier in tuple(self.activity_ids):
                    current = self.service.inspect('alice', identifier)
                    if current['activity']['status'] != 'stopped':
                        self.request('POST', '/research-iterations/' + identifier + '/cancel', body={})
        finally:
            self.close()

    def close(self):
        if self.client is not None:
            client, self.client = self.client, None
            try:
                client.__exit__(None, None, None)
            finally:
                self.store.native_db.db_engine.dispose()
                self.store.engine.dispose()

    def remove_owned_containers(self):
        # Retire only containers whose own marker, label and mounted workspace agree.
        for marker in self.workspace.rglob('factory-linux-container.json'):
            saved = json.loads(marker.read_text())
            cid = saved['containerId']
            inspected = subprocess.run(['docker', 'inspect', cid], capture_output=True, text=True,
                                       check=True, timeout=15)
            container = json.loads(inspected.stdout)[0]
            self.assertEqual(container['Config']['Labels']['agent-factory.orx-spec'], saved['specSha256'])
            self.assertIn(str(marker.parent), [mount['Source'] for mount in container['Mounts'] if mount['RW']])
            if container['State']['Running']:
                subprocess.run(['docker', 'kill', cid], capture_output=True, check=True, timeout=15)
            subprocess.run(['docker', 'rm', cid], capture_output=True, check=True, timeout=15)

    def preserve_evidence(self):
        directory = os.getenv('FACTORY_ITERATIONS_EVIDENCE_DIR')
        if directory:
            destination = Path(directory) / self.workspace.name
            destination.mkdir(parents=True, exist_ok=False)
            (destination / 'observations.json').write_text(json.dumps({'test': self._testMethodName,
                'binarySha256': getattr(self, 'binary_sha', None), 'dispatches': self.dispatches,
                'snapshots': self.snapshots, 'artifacts': self.artifact_proofs,
                'failureSnapshots': self.failure_snapshots}, sort_keys=True))

    def request(self, method, path, expected=200, body=None, *, owner='alice'):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner),
                     'X-Factory-Expected-Owner': owner})
        self.assertEqual(response.status_code, expected, response.text)
        value = response.json()
        if isinstance(value, dict) and isinstance(value.get('activity'), dict):
            self.activity_ids.add(value['activity']['id'])
        return value

    def start_body(self, request_id, rounds=2):
        return {'presetId': PROFILE_ID, 'goal': 'Compare the reviewed candidate against its original and promoted baseline',
                'requestId': request_id, 'caps': {'rounds': rounds, 'toolCalls': 8 * rounds},
                'deadline': time.time() + 600}

    def snapshot(self, activity):
        value = self.request('GET', '/research-iterations/' + activity)
        if not self.snapshots or value != self.snapshots[-1]:
            self.snapshots.append(deepcopy(value))
        return value

    def failure_diagnostics(self, value):
        coordinator = self.research.iteration_coordinator
        observer = self.state['lifecycle_observer']
        diagnostics = {'coordinatorErrorType': coordinator.last_error_type,
            'coordinatorStopped': coordinator._stop.is_set(),
            'coordinatorTaskDone': coordinator._task.done() if coordinator._task is not None else None,
            'observerErrorType': observer.last_error_type, 'dispatches': deepcopy(self.dispatches), 'native': []}
        for round in (value or {}).get('rounds', []):
            item = {'roundId': round['id'], 'taskId': round['taskId']}
            try:
                task = self.store.task(round['taskId'], 'alice')
                item.update(runId=task['run_id'], terminal=task['terminal'], cancelRequested=task['cancel_requested'])
                # Strict original owner/component/admission/envelope checks;
                # this read never observes/reconciles/advances any work.
                binding = observer._binding(task)
                item['binding'] = ({key: binding.get(key) for key in (
                    'id', 'session_id', 'user_id', 'component_type', 'component_id', 'status', 'persistedRunStatus')}
                    if binding is not None else None)
                item['effects'] = [{key: effect.get(key) for key in ('effect_key', 'status')}
                                   for effect in self.store.effects(task['id'])]
            except Exception as error:
                item['strictBindingErrorType'] = type(error).__name__
            diagnostics['native'].append(item)
        self.failure_snapshots.append(deepcopy(diagnostics))
        return diagnostics

    def wait_snapshot(self, activity, predicate, timeout=90):
        deadline = time.monotonic() + timeout
        value = None
        while time.monotonic() < deadline:
            value = self.snapshot(activity)
            if predicate(value):
                return value
            time.sleep(.05)
        self.fail('Iteration did not reach expected original state: ' + json.dumps({
            'snapshot': value, 'diagnostics': self.failure_diagnostics(value)}))

    def approve_round(self, round):
        self.task_id = round['taskId']
        # Reuse the actual Linux fixture's 90s native admission/approval bound.
        detail = original.ActualORXNativeFactoryTests.wait(self, {'waiting_approval', 'failed', 'unknown'}, 90)
        self.assertEqual(detail['job']['status'], 'waiting_approval', detail)
        self.assertEqual(self.store.effects(self.task_id), [], 'No ORX launch precedes native human confirmation')
        approval = detail['job']['approvalDetail']
        self.request('POST', '/jobs/' + self.task_id + '/approve', body={
            'requirementId': approval['id'], 'version': approval['version'], 'approved': True,
            'commandId': 'iteration-approval-' + round['id']})
        detail = original.ActualORXNativeFactoryTests.wait(self, {'completed', 'failed', 'unknown'}, 30)
        self.assertEqual(detail['job']['status'], 'completed', detail)
        return detail

    def assert_round_evidence(self, round, baseline, recipe):
        self.task_id = round['taskId']
        task = self.store.task(self.task_id, 'alice')
        plan = self.store.plan(task['plan_id'], 'alice')
        self.assertEqual((task['id'], task['plan_id'], task['run_id'], task['request_id']),
            (round['taskId'], round['planId'], round['runId'], round['requestId']))
        self.assertEqual(digest(plan), round['planSha256'])
        self.assertEqual(plan['applicationRef'], round['pins']['applicationRef'])
        self.assertEqual(plan['bindingManifest']['connections']['localExperiment']['ref'],
                         round['pins']['connectionRefs']['localExperiment'])
        self.assertTrue(task['terminal'])
        effects = self.store.effects(self.task_id)
        launches = [effect for effect in effects if effect['effect_key'] == task['run_id'] + ':' + LAUNCH_EFFECT_KEY]
        self.assertEqual(len(launches), 1)
        self.assertEqual(launches[0]['status'], 'DONE')
        result = launches[0]['result']
        observed = inspect_orx_experiment(self.store, 'alice', self.task_id)
        self.assertEqual({key: observed.get(key) for key in result}, result)
        self.assertTrue(result['stopEvidence']['allStopped'])
        self.assertEqual(result['provenance']['recipeIdentity'], recipe)
        self.assertEqual(result['provenance']['binarySha256'], self.binary_sha)
        self.assertEqual(result['provenance']['runtimePlatform'], 'linux')
        self.assertEqual(result['provenance']['runtimeImage'], RUNTIME_IMAGE)
        self.assertEqual(result['evaluation']['baseline']['value'], baseline)
        self.assertEqual(result['evaluation']['candidate']['value'], 0.0)
        self.assertEqual(result['evaluation']['metric'], 'mean_squared_error')
        _, native_rows = self.native_rows()
        self.assertEqual(len(native_rows), 1)
        self.assertEqual((native_rows[0]['id'], native_rows[0]['status']), (result['orxRunId'], 'done'))
        raw_artifacts = {}
        for key in ('sourceArtifact', 'artifact'):
            identifier, expected_sha = result[key + 'Id'], result[key + 'Sha256']
            metadata, raw = self.store.artifact(self.task_id, identifier)
            response = self.client.get('/api/factory/jobs/' + self.task_id + '/artifacts/' + identifier,
                headers={'Authorization': 'Bearer ' + self.auth._issue_native_token('alice'),
                         'X-Factory-Expected-Owner': 'alice'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected_sha)
            self.assertEqual(metadata['sha256'], expected_sha)
            raw_artifacts[key] = raw
        payload = json.loads(raw_artifacts['artifact'])
        self.assertEqual(payload['result'], {key: value for key, value in result.items()
                                           if key not in ('artifactId', 'artifactSha256')})
        with tarfile.open(fileobj=io.BytesIO(raw_artifacts['sourceArtifact']), mode='r:') as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(TOY_FILES))
            files = {}
            for member in archive:
                self.assertTrue(member.isfile())
                files[member.name] = archive.extractfile(member).read()
                self.assertEqual(hashlib.sha256(files[member.name]).hexdigest(), result['provenance']['fileSha256'][member.name])
        for name in ('candidate.py', 'dataset.json', 'evaluator.py'):
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), TOY_FILES[name])
        self.assertEqual(hashlib.sha256(files['baseline.py']).hexdigest(),
                         TOY_FILES['baseline.py' if baseline == 16.0 else 'candidate.py'])
        self.artifact_proofs.append({'taskId': task['id'], 'nativeRunId': task['run_id'], 'orxRunId': result['orxRunId'],
            'sourceArtifactId': result['sourceArtifactId'], 'sourceArtifactSha256': result['sourceArtifactSha256'],
            'evaluationArtifactId': result['artifactId'], 'evaluationArtifactSha256': result['artifactSha256'],
            'baselineMSE': baseline, 'candidateMSE': 0.0, 'fileSha256': result['provenance']['fileSha256']})
        return files, plan

    def test_actual_two_roots_promote_exact_candidate_bytes_then_stop_on_tie(self):
        presets = self.request('GET', '/research-iterations/presets')
        self.assertEqual([preset['id'] for preset in presets], [PROFILE_ID])
        body = self.start_body('actual-two-round-request')
        initial = self.request('POST', '/research-iterations', 201, body)
        activity = initial['activity']['id']
        first = initial['rounds'][0]
        self.assertEqual(initial['budget']['allocatedRounds'], 1)
        self.assertEqual(initial['budget']['heldToolCalls'], 8)
        self.approve_round(first)
        settled = self.wait_snapshot(activity, lambda value: value['rounds'][0]['state'] == 'SETTLED', timeout=15)
        first = settled['rounds'][0]
        self.assertEqual(first['decision'], 'improved')
        first_files, first_plan = self.assert_round_evidence(first, 16.0, SEED_IDENTITY)
        # The real coordinator may already have reserved the same successor.
        # Both explicit requests must converge on that single original root.
        def advance(index):
            return self.request('POST', '/research-iterations/' + activity + '/advance', body={
                'previousRoundId': first['id'], 'requestId': 'concurrent-advance-' + str(index)})
        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(advance, (1, 2)))
        self.assertEqual({reply['rounds'][1]['id'] for reply in replies}, {replies[0]['rounds'][1]['id']})
        second = replies[0]['rounds'][1]
        self.assertEqual(second['previousRoundId'], first['id'])
        self.assertEqual(second['pins'], first['pins'])
        self.assertEqual(second['deadline'], first['deadline'])
        self.assertEqual(second['baselineSource']['taskId'], first['taskId'])
        self.assertEqual(second['baselineSource']['sha256'], hashlib.sha256(first_files['candidate.py']).hexdigest())
        self.assertEqual(second['baselineSource']['artifactId'], first['observation']['sourcePin']['artifactId'])
        self.assertNotEqual(second['taskId'], first['taskId'])
        self.approve_round(second)
        final = self.wait_snapshot(activity, lambda value: value['activity']['status'] == 'stopped', timeout=15)
        self.assertEqual(final['activity']['stopReason'], 'tie')
        self.assertEqual(len(final['rounds']), 2)
        self.assertEqual(final['rounds'][1]['decision'], 'tie')
        second_files, second_plan = self.assert_round_evidence(final['rounds'][1], 0.0, PROMOTED_IDENTITY)
        self.assertEqual(second_files['baseline.py'], first_files['candidate.py'])
        for name in ('candidate.py', 'dataset.json', 'evaluator.py'):
            self.assertEqual(second_files[name], first_files[name])
        for key in ('applicationRef', 'materialRefs', 'executionBindings', 'budget'):
            self.assertEqual(second_plan[key], first_plan[key])
        self.assertEqual(final['budget']['allocatedRounds'], 2)
        self.assertEqual(final['budget']['heldToolCalls'], 0)
        self.assertEqual(final['budget']['settledToolCalls'], sum(r['settlement']['toolCalls'] for r in final['rounds']))
        self.assertGreater(final['budget']['settledToolCalls'], first['settlement']['toolCalls'])
        self.assertLessEqual(final['budget']['settledToolCalls'], body['caps']['toolCalls'])
        self.assertEqual(final['budget']['metering'], 'unavailable', 'No paid token/money compatibility claim')
        before = deepcopy(self.dispatches)
        self.assertEqual(len(before), 2)
        self.assertEqual(len({item['runId'] for item in before}), 2)
        self.assertEqual(self.request('GET', '/research-iterations/requests/' + body['requestId']), final)
        self.assertIn(final, self.request('GET', '/research-iterations')['items'])
        self.assertEqual(self.request('POST', '/research-iterations', 201, body), final)
        self.request('POST', '/research-iterations/' + activity + '/advance', 409,
            {'previousRoundId': second['id'], 'requestId': 'tie-must-not-continue'})
        self.assertEqual(self.dispatches, before)

    def test_lost_native_dispatch_ack_restart_recovers_original_without_relaunch(self):
        body = self.start_body('actual-native-ack-lost', rounds=1)
        self.lose_dispatch_once = True
        with self.assertRaisesRegex(TimeoutError, 'SYNTHETIC_ITERATION_NATIVE_ACK_LOST'):
            self.request('POST', '/research-iterations', 201, body)
        original = self.request('GET', '/research-iterations/requests/' + body['requestId'])
        activity, round = original['activity']['id'], original['rounds'][0]
        self.assertEqual(len(self.dispatches), 1)
        dispatched = deepcopy(self.dispatches)
        self.assertTrue(round['dispatchAttempted'])
        self.assertIn(round['state'], {'DISPATCH_UNKNOWN', 'UNKNOWN'})
        self.assertEqual(original['budget']['heldToolCalls'], 8)
        self.assertEqual(self.store.effects(round['taskId']), [])
        old_research = self.research
        self.close()
        self.open()
        self.assertTrue(old_research.closed)
        restored = self.request('GET', '/research-iterations/requests/' + body['requestId'])
        for key in ('id', 'taskId', 'planId', 'requestId', 'allocationId', 'intentSha256', 'pins', 'deadline'):
            self.assertEqual(restored['rounds'][0][key], round[key])
        def original_ack_recovered(value):
            self.assertEqual(self.dispatches, dispatched, 'Coordinator recovery must not submit again')
            return value['rounds'][0]['runId'] == dispatched[0]['runId']
        recovered = self.wait_snapshot(activity, original_ack_recovered, timeout=15)
        self.request('POST', '/research-iterations', 201, body)
        self.assertEqual(recovered['rounds'][0]['runId'], dispatched[0]['runId'])
        self.assertEqual(self.dispatches, dispatched)
        self.assertEqual(len(recovered['rounds']), 1)
        self.approve_round(recovered['rounds'][0])
        final = self.wait_snapshot(activity, lambda value: value['activity']['status'] == 'stopped', timeout=15)
        self.assertEqual(final['activity']['stopReason'], 'round_limit')
        self.assert_round_evidence(final['rounds'][0], 16.0, SEED_IDENTITY)
        self.assertEqual(self.dispatches, dispatched)
        self.assertEqual(final['budget']['allocatedRounds'], 1)
        self.assertEqual(final['budget']['heldToolCalls'], 0)


if __name__ == '__main__':
    unittest.main()
