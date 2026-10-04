"""Aggregate contracts with fake kernel effects and disposable SQLite only."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import sys
import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from agent_factory.aggregate_process import (aggregate_enforcement, aggregate_stopped,
    project_aggregate_evidence, validate_aggregate_evidence)
from agent_factory.delegated_cgroup import DelegatedCgroupBackend, DelegatedCgroupError
from agent_factory.process_enforcement import spec_contract
from agent_factory.process_provider import ProcessResourceProvider
from agent_factory.store import digest
import test_process_provider as existing  # pyright: ignore[reportMissingImports]
from test_delegated_cgroup import FakeFS, config  # pyright: ignore[reportMissingImports]


class AggregateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.config = config()
        self.fs = FakeFS(self.config)
        self.backend = DelegatedCgroupBackend(self.config, self.fs)
        self.ticket = self.backend.new_ticket({'ownerId': 'alice', 'nativeRunId': 'run'})
        self.enforcement = aggregate_enforcement(self.config)

    def persist(self, value):
        self.ticket = deepcopy(value)

    def call(self, method, *args):
        return getattr(self.backend, method)(self.ticket, *args, persist=self.persist, before_effect=lambda: None)

    def evidence(self):
        return project_aggregate_evidence(self.ticket, self.backend.inspect(self.ticket))

    def validate(self, value, previous=None):
        return validate_aggregate_evidence(value, self.ticket['bindingSha256'], self.enforcement, previous)

    def test_new_empty_and_removed_are_distinct_positive_proofs(self):
        fresh = self.evidence()
        self.assertEqual(fresh['state'], 'NEW')
        self.assertFalse(aggregate_stopped(fresh))
        self.call('prepare')
        empty = self.evidence()
        self.assertFalse(aggregate_stopped(empty))
        self.validate(empty, fresh)
        self.call('release')
        released = self.evidence()
        self.assertTrue(aggregate_stopped(released))
        self.assertFalse(released['limitsReadbackVerified'])
        self.validate(released, empty)
        for key, value in [('attached', True), ('state', 'UNKNOWN'), ('releasedProof', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate({**released, key: value}, released)

    def test_strict_schema_binding_and_no_operator_data(self):
        value = self.evidence()
        for key, bad in [('schema', True), ('attached', 1), ('populated', 0), ('ticketId', 'secret'),
                         ('bindingSha256', 'f' * 64), ('configSha256', 'a' * 64), ('operatorPath', '/private')]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '^AGGREGATE_EVIDENCE_INVALID$'):
                self.validate({**value, key: bad})
        self.assertNotIn(self.config.root_path, json.dumps(value))
        self.assertFalse(self.enforcement['hostileCodeSandbox'])
        self.assertFalse(self.enforcement['networkIsolation'])
        self.assertEqual(self.enforcement['aggregateScopes'], ['aggregate-cpu', 'aggregate-memory', 'aggregate-pids'])

    def test_original_pins_attached_history_and_readback_drift(self):
        self.call('prepare')
        self.call('attach_before_exec', {'pid': 7, 'start': '123', 'group': 7, 'bootId': self.config.boot_id})
        original = self.evidence()
        self.fs.values['cpu.max'] = '1 100000'
        drift = self.evidence()
        self.assertFalse(drift['limitsReadbackVerified'])
        self.assertTrue(drift['attached'])
        self.validate(drift, original)
        self.fs.root_changed = True
        unknown = self.evidence()
        self.assertEqual(unknown['state'], 'UNKNOWN')
        self.assertTrue(unknown['attached'])
        self.validate(unknown, original)
        for key, bad in [('groupPinSha256', None), ('rootPinSha256', 'f' * 64), ('attached', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate({**unknown, key: bad}, original)

    def test_lost_remove_ack_remains_unknown_after_reopen_without_retry(self):
        self.call('prepare')
        self.fs.fail = 'remove-ack'
        with self.assertRaises(DelegatedCgroupError):
            self.call('release')
        backend = DelegatedCgroupBackend(self.config, self.fs)
        self.assertFalse(aggregate_stopped(project_aggregate_evidence(self.ticket, backend.inspect(self.ticket))))
        with self.assertRaises(DelegatedCgroupError):
            backend.release(self.ticket, persist=self.persist, before_effect=lambda: None)
        self.assertEqual(self.fs.effects.count('remove'), 1)


class AggregateFakeProcess(existing.FakeProcess):
    backends = {}
    tickets = {}

    @classmethod
    def create(cls, path, *, aggregate_config, aggregate_binding, **kwargs):
        adapter = super().create(path, **kwargs)
        backend = DelegatedCgroupBackend(aggregate_config, FakeFS(aggregate_config))
        cls.backends[str(path)] = backend
        cls.tickets[str(path)] = backend.new_ticket(aggregate_binding)
        row = cls.records[str(path)]
        row['specSha256'] = hashlib.sha256(json.dumps(spec_contract(asdict(kwargs['spec']), asdict(kwargs['limits']), aggregate_config.to_dict()), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        row['enforcement'] = aggregate_enforcement(aggregate_config)
        return adapter

    def inspect(self, *, owner_id):
        result = super().inspect(owner_id=owner_id)
        if self.path in self.tickets:
            result['aggregateEvidence'] = project_aggregate_evidence(self.tickets[self.path], self.backends[self.path].inspect(self.tickets[self.path]))
        return result

    def launch(self, *, owner_id, before_effect):
        before_effect()
        backend = self.backends[self.path]
        def persist(value):
            self.tickets[self.path] = value
        backend.prepare(self.tickets[self.path], persist=persist, before_effect=before_effect)
        backend.attach_before_exec(self.tickets[self.path], {'pid': 7, 'start': '123', 'group': 7, 'bootId': backend.config.boot_id}, persist=persist, before_effect=before_effect)
        return super().launch(owner_id=owner_id, before_effect=before_effect)

    def cancel(self, *, owner_id):
        backend = self.backends[self.path]
        def persist(value):
            self.tickets[self.path] = value
        backend.kill(self.tickets[self.path], persist=persist, before_effect=lambda: None)
        backend.release(self.tickets[self.path], persist=persist, before_effect=lambda: None)
        self.records[self.path].update(state='CANCELLED', stoppedProof=True,
            stopReceipt={'kind': 'original-delegated-cgroup-released'})
        return self.inspect(owner_id=owner_id)


@unittest.skipUnless(sys.platform == 'linux', 'Provider uses Linux descriptor custody')
class AggregateProviderTests(unittest.IsolatedAsyncioTestCase):
    store: Any
    root: Any
    spec: Any
    limits: Any
    lease: Any
    mapping = existing.ProcessProviderTests.mapping
    count = existing.ProcessProviderTests.count
    allocate = existing.ProcessProviderTests.allocate

    def setUp(self):
        existing.ProcessProviderTests.setUp(self)
        self.config = config()
        self.provider = ProcessResourceProvider(self.store, self.root, self.spec, self.limits, aggregate_config=self.config)
        AggregateFakeProcess.records = {}; AggregateFakeProcess.created = 0; AggregateFakeProcess.launched = 0
        AggregateFakeProcess.fail_launch_ack = False; AggregateFakeProcess.backends = {}; AggregateFakeProcess.tickets = {}
        patch('agent_factory.process_provider.BoundedProcessAdapter', AggregateFakeProcess).start()
        self.admission = patch('agent_factory.process_provider.DelegatedCgroupBackend.validate').start()

    def reopened(self):
        return ProcessResourceProvider(self.store, self.root, self.spec, self.limits, aggregate_config=self.config)

    async def test_native_binding_lost_launch_ack_reopen_never_replays(self):
        AggregateFakeProcess.fail_launch_ack = True
        await self.allocate()
        current = await self.allocate(self.reopened())
        self.assertEqual(current['processBinding']['nativeRunId'], 'run1')
        self.assertEqual(AggregateFakeProcess.created, 1)
        self.assertEqual(AggregateFakeProcess.launched, 1)
        self.assertTrue(current['capacityHeld'])
        self.assertEqual(current['aggregateEvidence']['bindingSha256'], digest(self.provider._binding(self.lease)))
        with self.assertRaises(ValueError):
            await self.provider.allocate_bound({**self.lease, 'nativeRunId': 'other'}, before_effect=lambda: None)

    async def test_cancel_original_recovery_requires_positive_removed_proof(self):
        await self.allocate()
        stopped = await self.reopened().cancel('lease1', 'alice')
        self.assertTrue(stopped['stopEvidence']['allStopped'])
        self.assertTrue(stopped['aggregateEvidence']['releasedProof'])
        self.assertTrue(stopped['capacityHeld'])
        released = await self.reopened().reclaim('lease1', 'alice')
        self.assertEqual(released['state'], 'RECLAIMED')
        self.assertFalse(released['capacityHeld'])
        self.assertEqual(AggregateFakeProcess.launched, 1)

    async def test_capability_failure_and_revocation_deny_without_cooperative_fallback(self):
        self.admission.side_effect = ValueError('synthetic unavailable')
        with self.assertRaises(ValueError):
            await self.allocate()
        self.assertEqual(self.count(), 0)
        self.assertEqual(AggregateFakeProcess.created, 0)
        self.admission.side_effect = None
        def denied():
            raise PermissionError('synthetic revoked')
        with self.assertRaises(PermissionError):
            await self.provider.allocate_bound(self.lease, before_effect=denied)
        self.assertEqual(AggregateFakeProcess.launched, 0)

    async def test_fractional_cpu_memory_plus_swap_budget_rejected_before_create(self):
        for changed in [replace(self.config, cpu_quota_us=100001),
                        replace(self.config, memory_bytes=128 * 1024 * 1024, swap_bytes=1)]:
            with self.subTest(config=changed.fingerprint):
                provider = ProcessResourceProvider(self.store, self.root, self.spec, self.limits, aggregate_config=changed)
                with self.assertRaises(ValueError):
                    await self.allocate(provider)
        self.assertEqual(AggregateFakeProcess.created, 0)
        self.assertEqual(self.count(), 0)

    def test_opt_in_fingerprint_and_capability_do_not_claim_verified_enforcement(self):
        cooperative = ProcessResourceProvider(self.store, self.root, self.spec, self.limits)
        self.assertNotEqual(cooperative.configuration_fingerprint, self.provider.configuration_fingerprint)
        self.assertEqual(cooperative.capacity_namespace, self.provider.capacity_namespace)
        report = self.provider.isolation_capabilities()
        self.assertFalse(report['aggregateEnforcementVerified'])
        self.assertTrue(report['configuredPrerequisitesAvailable'])
        self.assertEqual(report['backend'], 'delegated-cgroup-v2')


class GuardianAbsenceTests(unittest.TestCase):
    def test_only_positive_absence_permits_recovery(self):
        from agent_factory.process_enforcement import guardian_absent
        identity = {'pid': 7, 'start': '123', 'group': 7, 'bootId': config().boot_id}
        fields = ['S', '1', '7'] + ['0'] * 16 + ['123']
        alive = '7 (synthetic) ' + ' '.join(fields)
        with patch('agent_factory.process_enforcement.boot_id', return_value=config().boot_id):
            for response, expected in [(PermissionError(), False), (FileNotFoundError(), True),
                    ('malformed', False), (alive, False), (alive.replace(') S ', ') Z '), True),
                    (alive[:-3] + '456', True)]:
                with self.subTest(expected=expected):
                    options: dict[str, Any] = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
                    with patch('agent_factory.process_enforcement.Path.read_text', **options):
                        self.assertIs(guardian_absent(identity), expected)
        self.assertTrue(guardian_absent(None))


class AggregateRuntimeReservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ceil_aggregate_reservation_and_original_resume_never_allocate_twice(self):
        from agent_factory.process_runtime import ProcessRuntimeService
        from agent_factory.process_enforcement import ProcessLimits
        context = SimpleNamespace(session_id='task', user_id='alice', run_id='native')
        aggregate = replace(config(), cpu_quota_us=100001,
            memory_bytes=128 * 1024 * 1024, swap_bytes=1)
        provider = SimpleNamespace(limits=ProcessLimits(), aggregate_config=aggregate)
        lease = {'id': 'lease', 'connectionRef': 'receiver-pool', 'state': 'RECLAIMED', 'executionStatus': 'COMPLETED'}
        resources = SimpleNamespace(_authorize=Mock(return_value='target'), _provider=Mock(return_value=provider),
            allocate=AsyncMock(return_value=lease), inspect=Mock(return_value=lease))
        service = ProcessRuntimeService.__new__(ProcessRuntimeService)
        service.store = SimpleNamespace(authorize_tool=Mock(), task=Mock(return_value={'id': 'task', 'plan_id': 'plan'}),
            plan=Mock(return_value={'id': 'plan'}))
        service.resources = resources
        with patch.object(service, 'validate_execution'), patch.object(service, '_original', return_value=None), \
                patch.object(service, 'observe_lease', AsyncMock(return_value=lease)), \
                patch.object(service, '_receipt', return_value={'artifactId': 'original'}):
            result = await service.run(context, {'targetRef': 'receiver-pool'})
        self.assertEqual(result['artifactId'], 'original')
        args = resources.allocate.await_args.args
        self.assertEqual(args[:3], ('alice', 'receiver-pool', 'task'))
        self.assertEqual(args[4]['cpu'], 2)
        self.assertEqual(args[4]['memoryMb'], 129)
        self.assertEqual(resources.allocate.await_args.kwargs['execution']['nativeRunId'], 'native')
        original = {'native_run_id': 'native', 'owner_id': 'alice', 'lease_id': 'lease'}
        with patch.object(service, 'validate_execution'), patch.object(service, '_original', return_value=original), \
                patch.object(service, 'observe_lease', AsyncMock(return_value=lease)), \
                patch.object(service, '_receipt', return_value={'artifactId': 'original'}):
            self.assertEqual(await service.run(context, {'targetRef': 'receiver-pool'}), result)
        resources.allocate.assert_awaited_once()
        resources.inspect.assert_called_once_with('alice', 'lease')
