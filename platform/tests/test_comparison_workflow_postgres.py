# pyright: reportMissingImports=false
"""One governed native task and original bounded process per controlled pair."""
import asyncio
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import threading
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from agent_factory.comparison_fixture import fixture_limits, fixture_spec
from agent_factory.comparison_profile import (APPLICATION_ID, registrations, pricing_registration,
    publish_comparison_application)
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.process_enforcement import BoundedProcessAdapter
from agent_factory.process_provider import ProcessResourceProvider
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres


class ComparisonWorkflowFixture:
    """Reusable native fixture; browser runners may serve app without TestClient.

    All paths, SQL identities and process custody belong to this fixture. No
    actual host aggregate quota, live model or scientific validity is implied.
    """
    def __init__(self, database_url, *, start_client=True, public_origin=None):
        self.stack = ExitStack()
        self.client = None
        self.providers = {}
        try:
            database = self.stack.enter_context(IsolatedPostgres(database_url))
            self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='comparison-native-')))
            self.bootstrap = Store(database.url, Settings(db_url=database.url, workspace=self.root))
            self.stack.callback(self.bootstrap.engine.dispose)
            executable = Path(sys.executable).resolve()
            binary_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
            self.pool = ComputePool('comparison-pool', 1, 128, 1, max_leases=1, max_owner_leases=1)
            targets, choices = {}, {}
            for choice in ('linear-v1', 'failure-v1', 'long-running-v1'):
                root = self.root / choice; root.mkdir(mode=0o700)
                provider = ProcessResourceProvider(self.bootstrap, root,
                    fixture_spec(str(executable), binary_hash, choice), fixture_limits())
                reference = 'comparison-' + choice
                targets[reference] = RemoteTarget('Controlled paired evaluator', 'compute', frozenset({'alice'}),
                    provider=provider, synthetic_fixture=True, max_cpu=1, max_memory_mb=128,
                    max_disk_mb=1, max_seconds=5, capacity_pool=self.pool)
                choices[choice] = reference
                self.providers[reference] = provider
            self.settings = Settings(db_url=database.url, workspace=self.root, demo=True, max_workers=1,
                development_mock_login=public_origin is not None, development_public_origin=public_origin,
                max_tool_calls=1, temporary_policy='admin-review', runtime_tool_contract='bounded-process-v1',
                policy_revision=APPLICATION_ID, material_policy_revision=APPLICATION_ID,
                remote_targets=targets, runtime_adapters=registrations(), usage_pricing=(pricing_registration(),))
            self.app = create_app(self.settings)
            self.state = self.app.app.state.factory
            self.store, self.auth = self.state['store'], self.state['auth']
            self.stack.callback(self.store.engine.dispose)
            self.stack.callback(self.store.native_db.db_engine.dispose)
            reviewer = 'manager2' if public_origin is not None else 'bob'
            if public_origin is None:
                self.auth.authorization.unassign('bob', 'factory-user')
                self.auth.authorization.assign('bob', 'factory-manager')
            self.application = publish_comparison_application(self.state, choices, author='manager', reviewer=reviewer)
            if start_client:
                self.client = self.stack.enter_context(TestClient(self.app))  # pyright: ignore[reportArgumentType]
            self.stack.callback(self.cleanup_processes)
        except BaseException:
            self.stack.close()
            raise

    def cleanup_processes(self):
        for row in self.store.sql('SELECT body FROM af_process_allocations'):
            binding = row['body']['binding']
            provider = self.providers[binding['connectionRef']]
            asyncio.run(provider.cancel(binding['id'], binding['ownerId']))
            path = provider.root / binding['id'] / 'custody.sqlite'
            if path.exists() and row['body'].get('processPin'):
                adapter = BoundedProcessAdapter(path)
                observed = adapter.inspect(owner_id=binding['ownerId'])
                if observed.get('child') or observed.get('guardian'):
                    if not adapter.wait(owner_id=binding['ownerId'])['stoppedProof']:
                        raise AssertionError('Original comparison process cleanup unconfirmed')

    def close(self):
        self.stack.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def request(self, method, path, body=None, *, owner='alice', expected=200):
        assert self.client is not None
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner)})
        if response.status_code != expected:
            raise AssertionError(f'Fixture HTTP status {response.status_code}: ' + response.text)
        return response.json()

    def post(self, path, body=None, **kwargs):
        return self.request('POST', path, {'requestId': str(uuid4()), **(body or {})}, expected=201, **kwargs)

    def plan(self, choice='linear-v1'):
        proposal = self.post('/compositions/proposals', {'goal': 'Compare fixed synthetic paired predictors',
            'mode': choice, 'applicationRef': {key: self.application[key] for key in ('id', 'version', 'sha256')}})
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept')
        review = self.post('/plan-reviews', {'planId': plan['id']})
        self.request('POST', '/plan-reviews/' + review['id'] + '/decision',
            {'requestId': str(uuid4()), 'approved': True}, owner='manager')
        return plan

    def submit(self, plan):
        command = {'planId': plan['id'], 'requestId': str(uuid4())}
        return self.request('POST', '/instances', command, expected=202), command

    def until(self, probe, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = probe()
            if result:
                return result
            time.sleep(.04)
        raise AssertionError('Controlled comparison did not reach expected state')

    def detail(self, task):
        return self.request('GET', '/jobs/' + task)

    def settled(self, task):
        return self.until(lambda: (value if value['job']['status'] in {'completed', 'failed', 'cancelled', 'unknown'} else None)
            if (value := self.detail(task)) else None)

    def lease(self, task):
        rows = self.store.sql("SELECT body FROM af_leases WHERE body->>'localTaskId'=:id", id=task)
        return rows[0]['body'] if rows else None


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
    'Requires Linux controlled processes and isolated PostgreSQL')
class ComparisonWorkflowPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ComparisonWorkflowFixture(os.environ['FACTORY_TEST_DATABASE_URL'])
        self.addCleanup(self.fixture.close)


    def assert_original(self, task, plan, evidence):
        f = self.fixture
        original = f.store.task(task['id'], 'alice')
        lease = f.lease(task['id'])
        assert lease is not None
        self.assertEqual(lease['planId'], plan['id'])
        self.assertEqual(lease['nativeRunId'], original['run_id'])
        self.assertEqual(lease['localTaskId'], task['id'])
        self.assertEqual(evidence['nativeRunId'], original['run_id'])
        self.assertEqual(evidence['process']['leaseId'], lease['id'])
        self.assertEqual(evidence['process']['providerJobId'], lease['providerJobId'])
        self.assertEqual(len(f.store.sql('SELECT id FROM af_process_allocations')), 1)
        return lease

    def test_success_original_identity_artifacts_idempotency_owner_and_tamper(self):
        f = self.fixture
        catalog = f.request('GET', '/comparisons/catalog')
        self.assertIn('linear-v1', str(catalog))
        plan = f.plan()
        task, request = f.submit(plan)
        detail = f.settled(task['id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)
        evidence = detail['comparisonEvidence']
        self.assertEqual(evidence['status'], 'ready')
        self.assertTrue(evidence['executionVerified'])
        self.assertFalse(evidence['scientificConclusionVerified'])
        self.assert_original(task, plan, evidence)
        artifacts = {row['name']: row for row in detail['artifacts']}
        self.assertIn('comparison-output.json', artifacts)
        self.assertIn('comparison-report.json', artifacts)
        for name in ('comparison-output.json', 'comparison-report.json'):
            artifact = artifacts[name]
            metadata, raw = f.store.artifact(task['id'], artifact['id'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), metadata['sha256'])
            f.request('GET', '/jobs/' + task['id'] + '/artifacts/' + artifact['id'], owner='bob', expected=404)
        self.assertEqual(f.request('POST', '/instances', request, expected=202)['id'], task['id'])
        self.assertEqual(len(f.store.sql('SELECT id FROM af_process_allocations')), 1)
        f.request('GET', '/jobs/' + task['id'], owner='bob', expected=404)
        report = artifacts['comparison-report.json']
        f.store.sql('UPDATE af_artifacts SET content=:value WHERE id=:id', value=b'controlled corruption', id=report['id'])
        self.assertEqual(f.detail(task['id'])['comparisonEvidence']['status'], 'invalid')

    def test_failed_candidate_is_inconclusive_not_execution_failure_or_improvement(self):
        f = self.fixture
        plan = f.plan('failure-v1')
        task, _ = f.submit(plan)
        detail = f.settled(task['id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)
        evidence = detail['comparisonEvidence']
        self.assertEqual(evidence['status'], 'ready')
        self.assertTrue(evidence['executionVerified'])
        self.assertFalse(evidence['scientificConclusionVerified'])
        self.assert_original(task, plan, evidence)
        self.assertIn('inconclusive', str(evidence['assessment']))
        self.assertEqual(evidence['candidate']['status'], 'failed')
        self.assertIsNone(evidence['candidate']['value'])

    def test_actual_cancel_stops_only_original_process_and_never_reports_ready(self):
        f = self.fixture
        task, plan_request = f.submit(f.plan('long-running-v1'))
        lease = f.until(lambda: (value if value['state'] == 'RUNNING' else None) if (value := f.lease(task['id'])) else None)
        f.request('POST', '/jobs/' + task['id'] + '/cancel', {})
        stopped = f.until(lambda: (value if value['state'] == 'RECLAIMED' else None) if (value := f.lease(task['id'])) else None)
        self.assertEqual(stopped['id'], lease['id'])
        self.assertTrue(stopped['stopEvidence']['allStopped'])
        self.assertEqual(stopped['executionStatus'], 'CANCELLED')
        evidence = f.detail(task['id'])['comparisonEvidence']
        self.assertNotEqual(evidence['status'], 'ready')
        self.assertIsNone(evidence['assessment'])
        self.assertFalse(any(row['name'] == 'comparison-report.json' for row in f.store.artifacts(task['id'])))
        self.assertEqual(f.store.task(task['id'])['request_id'], plan_request['requestId'])

    def test_current_revocation_at_prelaunch_fence_has_no_spawn_or_report(self):
        f = self.fixture
        entered, release = threading.Event(), threading.Event()
        original = BoundedProcessAdapter.launch
        def paused(adapter, **kwargs):
            entered.set()
            if not release.wait(10):
                raise TimeoutError('Controlled prelaunch fence not released')
            return original(adapter, **kwargs)
        with patch.object(BoundedProcessAdapter, 'launch', paused), \
                patch('agent_factory.process_enforcement.subprocess.Popen') as spawn:
            task, _ = f.submit(f.plan())
            try:
                self.assertTrue(entered.wait(10))
                f.auth.authorization.unassign('alice', 'factory-user')
                release.set()
                f.until(lambda: f.store.native_db.get_job(f.store.task(task['id'])['run_id'])['status'] in {'failed', 'cancelled', 'completed'})
                spawn.assert_not_called()
                self.assertFalse(any(row['name'].startswith('comparison-') for row in f.store.artifacts(task['id'])))
            finally:
                release.set()
                f.auth.authorization.assign('alice', 'factory-user')

    def test_lost_launch_ack_recovers_original_identity_without_relaunch(self):
        f = self.fixture
        original = BoundedProcessAdapter.launch
        calls = []
        def lost(adapter, **kwargs):
            calls.append(str(adapter.path))
            original(adapter, **kwargs)
            raise TimeoutError('Synthetic launch acknowledgement lost')
        with patch.object(BoundedProcessAdapter, 'launch', lost):
            task, _ = f.submit(f.plan())
            f.settled(task['id'])
            lease = f.until(lambda: (value if value.get('providerJobId') else None) if (value := f.lease(task['id'])) else None)
        provider = f.providers[lease['connectionRef']]
        reopened = ProcessResourceProvider(f.bootstrap, provider.root, provider.spec, provider.limits)
        result = asyncio.run(reopened.inspect(lease['id'], 'alice'))
        self.assertEqual(result['providerJobId'], lease['providerJobId'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(f.store.sql('SELECT id FROM af_process_allocations')), 1)

    def test_unknown_launch_retains_original_hold_without_replay_or_report(self):
        f = self.fixture
        with patch('agent_factory.process_enforcement.subprocess.Popen', side_effect=OSError('Synthetic unknown dispatch')) as spawn:
            task, _ = f.submit(f.plan())
            f.until(lambda: spawn.call_count == 1)
            lease = f.until(lambda: (value if value.get('providerJobId') else None) if (value := f.lease(task['id'])) else None)
            provider = f.providers[lease['connectionRef']]
            reopened = ProcessResourceProvider(f.bootstrap, provider.root, provider.spec, provider.limits)
            observed = asyncio.run(reopened.inspect(lease['id'], 'alice'))
            self.assertEqual(observed['state'], 'UNKNOWN')
            self.assertTrue(observed['capacityHeld'])
            self.assertFalse(observed['allStopped'])
            self.assertEqual(observed['providerJobId'], lease['providerJobId'])
            self.assertFalse(any(row['name'].startswith('comparison-') for row in f.store.artifacts(task['id'])))
            self.assertEqual(spawn.call_count, 1)

    def test_current_revocation_before_report_persistence_retains_process_evidence_only(self):
        f = self.fixture
        entered, release = threading.Event(), threading.Event()
        comparisons = f.store.comparisons
        original = comparisons.persist
        async def paused(context, receipt):
            entered.set()
            if not await asyncio.to_thread(release.wait, 10):
                raise TimeoutError('Controlled report fence not released')
            return await original(context, receipt)
        with patch.object(comparisons, 'persist', paused):
            task, _ = f.submit(f.plan())
            try:
                self.assertTrue(entered.wait(10))
                f.auth.authorization.unassign('alice', 'factory-user')
                release.set()
                f.until(lambda: f.store.native_db.get_job(f.store.task(task['id'])['run_id'])['status'] in {'failed', 'cancelled', 'completed'})
                self.assertFalse(any(row['name'].startswith('comparison-') for row in f.store.artifacts(task['id'])))
                self.assertEqual(len(f.store.sql('SELECT id FROM af_process_allocations')), 1)
            finally:
                release.set()
                f.auth.authorization.assign('alice', 'factory-user')
