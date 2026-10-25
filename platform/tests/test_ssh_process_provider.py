import copy
import hashlib
from types import SimpleNamespace
import unittest

from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
from agent_factory.resources import PersistentResourceService
from agent_factory.ssh_process_contract import PROTOCOL, MAX_REQUEST_BYTES, encoded
from agent_factory.ssh_process_provider import EFFECT, SSHProcessProvider


class SSHProcessProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        server = SimpleNamespace(validate=lambda: None, pin=lambda: 'a' * 64,
                                 scope_pin=lambda: 'b' * 64, allowed_root='/private/runs')
        self.provider = SSHProcessProvider(server, target_ref='compute',
            spec=ProcessSpec('/bin/program', 'c' * 64, ()), limits=ProcessLimits(),
            exchange=self.exchange, read_lease=lambda owner, key: copy.deepcopy(self.lease))
        self.lease = {'id': 'lease-1', 'ownerId': 'alice', 'localTaskId': 'task-1', 'nativeRunId': 'run-1',
            'planId': 'plan-1', 'planHash': 'd' * 64, 'requestId': 'request-1', 'fingerprint': 'e' * 64,
            'targetFingerprint': 'f' * 64, 'connectionRef': 'compute',
            'providerNamespace': self.provider.capacity_namespace, 'executionEffect': EFFECT,
            'executionGuard': {'operationId': 'operation-1'},
            'limits': {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 33}}
        self.state, self.stopped = 'RUNNING', False
        self.mutate = lambda result: result

    def exchange(self, sent, *, before_effect=None):
        if before_effect:
            before_effect()
        self.calls.append(sent['action'])
        result = {'protocol': PROTOCOL, 'binding': sent['binding'], 'observation': {
            'id': 'process-1', 'ownerId': 'alice', 'taskId': 'task-1', 'requestId': 'request-1',
            'identitySha256': '1' * 64, 'rootPin': {'directoryInode': 1, 'fileInode': 2},
            'specSha256': hashlib.sha256(encoded({'spec': sent['spec'], 'limits': sent['limits']},
                                               MAX_REQUEST_BYTES)).hexdigest(),
            'state': self.state, 'stoppedProof': self.stopped, 'exitCode': 0 if self.stopped else None,
            'stopReceipt': {'kind': 'original-group-stopped'} if self.stopped else None,
            'enforcement': {'cpu': 'per-process-RLIMIT_CPU', 'memory': 'per-process-RLIMIT_AS',
                'fileSize': 'per-file-RLIMIT_FSIZE', 'wall': 'cooperative-process-group-guardian',
                'aggregateQuota': False, 'hostileCodeSandbox': False, 'networkIsolation': False}}}
        return self.mutate(result)

    async def test_reservation_and_original_receipt_use_existing_resource_contract(self):
        checked = []
        receipt = await self.provider.allocate_bound(self.lease, before_effect=lambda: checked.append(True))
        self.assertEqual(checked, [True])
        self.assertEqual(self.calls, ['submit'])
        self.assertEqual(receipt['state'], 'RUNNING')
        self.lease.update(PersistentResourceService.process_snapshot(self.lease, receipt))
        self.state, self.stopped = 'COMPLETED', True
        observed = await self.provider.inspect('lease-1', 'alice')
        self.assertFalse(observed['released'])
        released = await self.provider.reclaim('lease-1', 'alice')
        self.assertEqual(released['state'], 'RECLAIMED')
        PersistentResourceService.process_snapshot(self.lease, released)
        self.assertEqual(self.calls, ['submit', 'inspect', 'reclaim'])

    async def test_unconfirmed_terminal_is_unknown_not_capacity_release(self):
        self.state = 'COMPLETED'
        result = await self.provider.reclaim('lease-1', 'alice')
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertFalse(result['released'])
        self.assertIsNone(result['exitCode'])

    async def test_bound_target_operation_budget_and_gpu_fail_before_dispatch(self):
        invalid = [dict(self.lease, executionEffect='unknown'), dict(self.lease, connectionRef='other'),
                   dict(self.lease, executionGuard={}), dict(self.lease, gpuBinding={'device': '0'}),
                   dict(self.lease, limits={**self.lease['limits'], 'memoryMb': 1})]
        for lease in invalid:
            with self.subTest(lease=lease), self.assertRaises(ValueError):
                await self.provider.allocate_bound(lease, before_effect=lambda: None)
        self.assertEqual(self.calls, [])

    async def test_fresh_authority_failure_does_not_send(self):
        def denied():
            raise PermissionError('revoked')
        with self.assertRaises(PermissionError):
            await self.provider.allocate_bound(self.lease, before_effect=denied)
        self.assertEqual(self.calls, [])

    async def test_changed_remote_identity_or_binding_is_rejected(self):
        first = await self.provider.inspect('lease-1', 'alice')
        self.lease.update(PersistentResourceService.process_snapshot(self.lease, first))
        def replace(result):
            result['observation']['id'] = 'replacement'
            return result
        self.mutate = replace
        with self.assertRaises(ValueError):
            await self.provider.inspect('lease-1', 'alice')
        self.assertNotIn('submit', self.calls)

    async def test_unknown_submit_acknowledgement_never_falls_back_to_resubmit(self):
        def unknown(sent, **_):
            self.calls.append(sent['action'])
            raise TimeoutError('acknowledgement unknown')
        self.provider.exchange = unknown
        with self.assertRaises(TimeoutError):
            await self.provider.allocate_bound(self.lease, before_effect=lambda: None)
        self.provider.exchange = self.exchange
        await self.provider.inspect('lease-1', 'alice')
        self.assertEqual(self.calls, ['submit', 'inspect'])
