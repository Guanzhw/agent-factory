"""Actual PG lease/accounting integration with controlled native/provider wires.

The native task binding/authorization callbacks are controlled here; this test
proves persisted ResourceService and UsageLedger behavior, not live OS isolation
or a provider bill. Native pause/command integration is tested separately.
"""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.config import Settings
from agent_factory.managed_orx_profile import MODEL_ADAPTER, PROVIDER, request_guard
from agent_factory.process_runtime import ProcessRuntimeService
from agent_factory.resources import ComputePool, PersistentResourceService, RemoteTarget
from agent_factory.store import Store, digest, now
from agent_factory.usage_ledger import PricingRevision, UsageLedger, UsagePolicy, native_response_usage
from pg_fixture import IsolatedPostgres
from test_managed_orx_attachment import ManagedFixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ManagedORXPostgresTests(unittest.TestCase):
    def test_resource_lease_and_shared_ledger_preserve_original_session(self):
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, TemporaryDirectory() as folder:
            settings = Settings(db_url=database.url, workspace=Path(folder))
            store = Store(database.url, settings)
            self.addCleanup(store.engine.dispose)
            self.addCleanup(store.dispose_root_locks)
            active = {'allowed': True}
            def authorized(*args, **kwargs):
                if not active['allowed']: raise HTTPException(403, 'Controlled original grant revoked')
            store.auth = SimpleNamespace(require=authorized)
            store.require_plan_execution = authorized
            store.authorize_tool = authorized
            store.connections = SimpleNamespace(preflight=authorized)
            f = ManagedFixture(store)
            price = PricingRevision(MODEL_ADAPTER, '1', PROVIDER, 'deepseek-flash', 'controlled-managed-pricing-v1',
                input_micros_per_million=1_000_000, output_micros_per_million=1_000_000,
                per_attempt_input_tokens=4096, per_attempt_output_tokens=32,
                usage_reader=native_response_usage, request_guard=request_guard,
                accounting_basis='operator-nominal-not-invoice')
            store.usage_ledger = UsageLedger(store, [price], UsagePolicy(revision='managed-controlled-policy-v1',
                task_token_limit=5000, task_amount_micros=5000, user_token_limit=5000, user_amount_micros=5000))
            model = {'adapterId': MODEL_ADAPTER, 'revision': '1', 'config': {'targetRef': 'managed-target'}}
            manifest = {'model': model, 'tools': [{'toolName': 'bounded_process_run', 'config': {'targetRef': 'managed-target'}}]}
            manifest['sha256'] = digest(manifest)
            store.execution_bindings = SimpleNamespace(manifest=lambda plan, context=None: plan['executionBindings'])
            pool = ComputePool('managed-pool', 1, 128, 1, max_leases=1, max_owner_leases=1)
            target = RemoteTarget('Controlled managed attachment', 'compute', frozenset({'alice'}), provider=f.provider,
                max_cpu=1, max_memory_mb=128, max_disk_mb=1, max_seconds=30,
                max_leases=1, capacity_pool=pool, synthetic_fixture=True)
            resources = PersistentResourceService(store, store.auth, {'managed-target': target})
            store.process_runtime = ProcessRuntimeService(store, store.auth, resources)
            plan = {'id': str(uuid4()), 'ownerId': 'alice', 'status': 'ready',
                'normalizedGoal': 'One approved text-only native turn', 'createdAt': now(),
                'executionBindings': manifest, 'inputValues': {'managedAttachment': f.provider.contract},
                'tools': ['bounded_process_run'], 'budget': {'toolCalls': 2, 'outputBytes': 65536},
                'policy': 'bounded-synthetic', 'syntheticFixture': True}
            plan['usageBudget'] = store.usage_ledger.commitment_for(plan)
            plan['fingerprint'] = digest(plan)
            store.save_plan(plan)
            task, _ = store.reserve_task(plan, str(uuid4()))
            run_id = str(uuid4()); store.accept(task['id'], run_id)
            store.lifecycle_observer = SimpleNamespace(_binding=lambda _: {
                'id': run_id, 'status': 'paused', 'persistedRunStatus': 'paused'})
            async def execute():
                lease = await resources.allocate('alice', 'managed-target', task['id'], 'managed-original-allocation',
                    {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 30},
                    execution={'nativeRunId': run_id, 'effectKey': 'bounded-process-run-v1'})
                self.assertEqual(lease['state'], 'COMPLETED', lease)
                self.assertEqual((f.messages, f.provider_calls, f.credential_calls), (1, 1, 1))
                usage = store.usage_ledger.inspect('alice', task['id'])
                self.assertFalse(usage['hasUnknown'])
                self.assertEqual(len(usage['attempts']), 1)
                self.assertEqual(usage['attempts'][0]['state'], 'SETTLED')
                self.assertEqual(store.sql('SELECT settled_tokens FROM af_usage_accounts WHERE id=:id',
                    id='task:' + task['id'])[0]['settled_tokens'], 19)
                # Same persisted request never replays allocation/session/provider.
                same = await resources.allocate('alice', 'managed-target', task['id'], 'managed-original-allocation',
                    {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 30},
                    execution={'nativeRunId': run_id, 'effectKey': 'bounded-process-run-v1'})
                self.assertEqual(same['id'], lease['id'])
                self.assertEqual(f.provider_calls, 1)
                active['allowed'] = False
                # Existing original process custody still reclaims after revoke.
                released = await store.process_runtime.observe_lease(lease['id'])
                self.assertEqual(released['state'], 'RECLAIMED', released)
                self.assertFalse(released['capacityHeld'])
                self.assertTrue(released['stopEvidence']['allStopped'])
                self.assertEqual(f.provider_calls, 1)
                artifacts = store.artifacts(task['id'])
                result = next(a for a in artifacts if a['provenance'].get('evidenceKind') == 'native-session-response')
                _, raw = store.artifact(task['id'], result['id'])
                self.assertIn(b'Controlled text', raw)
            asyncio.run(execute())
