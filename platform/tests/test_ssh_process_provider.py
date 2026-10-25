import asyncio
import copy
from contextlib import contextmanager, nullcontext
import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest.mock import AsyncMock, patch
import hashlib
from types import SimpleNamespace
import unittest

from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
from agent_factory.resources import PersistentResourceService
from agent_factory.ssh_process_contract import PROTOCOL, MAX_REQUEST_BYTES, encoded
from agent_factory.ssh_process_provider import EFFECT, SSHProcessProvider, SSHProcessTransport
from agent_factory.ssh_exchange import SSHExchangeCleanupError


class SSHProcessProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        server = SimpleNamespace(validate=lambda: None, pin=lambda: 'a' * 64,
                                 scope_pin=lambda: 'b' * 64, host_key='synthetic-host-key', allowed_root='/private/runs')
        self.provider = SSHProcessProvider(server, target_ref='compute',
            spec=ProcessSpec('/bin/program', 'c' * 64, (), path_style='posix'), limits=ProcessLimits(),
            exchange=self.exchange, read_lease=lambda owner, key: copy.deepcopy(self.lease),
            archive_original=AsyncMock())
        self.lease = {'id': 'lease-1', 'ownerId': 'alice', 'localTaskId': 'task-1', 'nativeRunId': 'run-1',
            'planId': 'plan-1', 'planHash': 'd' * 64, 'requestId': 'request-1', 'fingerprint': 'e' * 64,
            'targetFingerprint': 'f' * 64, 'connectionRef': 'compute',
            'providerNamespace': self.provider.capacity_namespace, 'executionEffect': EFFECT,
            'executionGuard': {'operationId': 'operation-1'},
            'limits': {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 33}}
        self.state, self.stopped = 'RUNNING', False
        self.mutate = lambda result: result

    def exchange(self, sent, *, before_effect=None, cancelled=None):
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

    def test_direct_transport_async_guard_rejects_before_any_spawn(self):
        transport = SSHProcessTransport(self.provider.server,
            lambda action: SimpleNamespace(validate=lambda: None), interpreter='/python')
        async def guard():
            self.fail('async authority must never execute')
        with patch('agent_factory.ssh_process_provider.pinned_ssh') as spawn, \
             patch('agent_factory.ssh_process_provider.pipe_exchange') as exchange:
            with self.assertRaisesRegex(TypeError, 'SSH_PROCESS_SYNC_AUTHORITY_REQUIRED'):
                transport(self.provider._request(self.lease, 'submit'), before_effect=guard)
            spawn.assert_not_called()
            exchange.assert_not_called()

    def test_exchange_entry_failure_exits_original_scope_with_same_deadline(self):
        transport = SSHProcessTransport(self.provider.server,
            lambda action: SimpleNamespace(validate=lambda: None), interpreter='/python')
        entered, exited, deadlines = [], [], []
        process = object()
        @contextmanager
        def spawn(server, lease, folder, command, *, deadline):
            entered.append(process)
            deadlines.append(deadline)
            try:
                yield process
            finally:
                exited.append(process)
        failure = SSHExchangeCleanupError('controlled failure before exchange takes ownership')
        with patch('agent_factory.ssh_process_provider.pinned_ssh', side_effect=spawn), \
             patch('agent_factory.ssh_process_provider.pipe_exchange', side_effect=failure) as exchange:
            with self.assertRaises(SSHExchangeCleanupError) as caught:
                transport(self.provider._request(self.lease, 'submit'))
        self.assertIs(caught.exception, failure)
        self.assertEqual(entered, [process])
        self.assertEqual(exited, [process])
        self.assertIs(exchange.call_args.args[0], process)
        self.assertEqual(exchange.call_args.kwargs['deadline'], deadlines[0])

    async def test_cancelled_worker_cleanup_error_is_not_hidden_as_cancelled(self):
        entered, finished = threading.Event(), threading.Event()
        calls = []
        failure = SSHExchangeCleanupError('controlled cleanup failure')
        def exchange(value, *, before_effect=None, cancelled=None):
            calls.append(value['action'])
            entered.set()
            try:
                if not cancelled.wait(3):
                    raise AssertionError('Cancellation did not reach the original worker')
                raise failure
            finally:
                finished.set()
        self.provider.exchange = exchange
        task = asyncio.create_task(self.provider.allocate_bound(self.lease, before_effect=lambda: None))
        self.assertTrue(await asyncio.to_thread(entered.wait, 3))
        task.cancel()
        with self.assertRaises(SSHExchangeCleanupError) as caught:
            await task
        self.assertIs(caught.exception, failure)
        self.assertTrue(finished.is_set())
        self.assertEqual(calls, ['submit'])

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

    async def test_cancellation_while_transport_waits_never_finishes_submit(self):
        for pause_on in (1, 2):
            with self.subTest(pause_on=pause_on):
                self.provider.server.allowed_root = '/' + 'r' * 4000
                read_fd, write_fd = os.pipe()
                output_read, output_write = os.pipe()
                os.write(output_write, b'{}')
                os.close(output_write)
                process = SimpleNamespace(stdin=os.fdopen(write_fd, 'wb', buffering=0),
                    stdout=os.fdopen(output_read, 'rb', buffering=0),
                    poll=lambda: 0, wait=lambda **_: 0, kill=lambda: None)
                entered, release, finished = threading.Event(), threading.Event(), threading.Event()
                exchanges = []
                count = 0
                def gated_guard():
                    nonlocal count
                    count += 1
                    # First guard precedes spawn; the following guards precede
                    # the first and second actual pipe write respectively.
                    if count == pause_on + 1:
                        entered.set()
                        if not release.wait(3):
                            raise TimeoutError('fixture gate')
                transport = SSHProcessTransport(self.provider.server,
                    lambda action: SimpleNamespace(validate=lambda: None), interpreter='/python')
                def exchange(value, **kwargs):
                    exchanges.append(threading.get_ident())
                    try:
                        return transport(value, **kwargs)
                    finally:
                        finished.set()
                self.provider.exchange = exchange
                try:
                    with patch('agent_factory.ssh_process_provider.pinned_ssh', return_value=nullcontext(process)):
                        task = asyncio.create_task(self.provider.allocate_bound(
                            self.lease, before_effect=gated_guard))
                        self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                        task.cancel()
                        await asyncio.sleep(0)
                        self.assertFalse(task.done())
                        task.cancel()
                        await asyncio.sleep(0)
                        self.assertFalse(task.done(), 'Second cancellation abandoned the original worker')
                        self.assertFalse(finished.is_set())
                        release.set()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                        self.assertTrue(finished.is_set())
                        self.assertEqual(len(exchanges), 1)
                        self.assertTrue(await asyncio.to_thread(finished.wait, 3))
                    raw = os.read(read_fd, MAX_REQUEST_BYTES)
                    self.assertEqual(len(raw), 0 if pause_on == 1 else 4096)
                    self.assertLess(len(raw), len(encoded(self.provider._request(self.lease, 'submit'),
                                                         MAX_REQUEST_BYTES)))
                finally:
                    release.set()
                    os.close(read_fd)
                    process.stdin.close()
                    process.stdout.close()

    async def test_cancellation_waiting_for_stdout_reaps_original_process_before_return(self):
        with TemporaryDirectory() as folder:
            ready = Path(folder) / 'ready'
            processes = []
            finished = threading.Event()
            @contextmanager
            def spawn(*args, deadline):
                process = subprocess.Popen([sys.executable, '-c',
                    'import sys,time; from pathlib import Path; sys.stdin.buffer.read(); '
                    'Path(sys.argv[1]).write_text("received"); time.sleep(60)', str(ready)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                processes.append(process)
                try:
                    yield process
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=3)
                    process.stdin.close()
                    process.stdout.close()
            transport = SSHProcessTransport(self.provider.server,
                lambda action: SimpleNamespace(validate=lambda: None), interpreter='/python')
            def exchange(value, **kwargs):
                try:
                    return transport(value, **kwargs)
                finally:
                    finished.set()
            self.provider.exchange = exchange
            with patch('agent_factory.ssh_process_provider.pinned_ssh', side_effect=spawn):
                task = asyncio.create_task(self.provider.allocate_bound(self.lease, before_effect=lambda: None))
                try:
                    deadline = time.monotonic() + 3
                    while not ready.exists() and time.monotonic() < deadline:
                        await asyncio.sleep(.01)
                    self.assertTrue(ready.exists())
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertTrue(finished.is_set())
                    self.assertEqual(len(processes), 1)
                    self.assertIsNotNone(processes[0].poll())
                    self.assertTrue(processes[0].stdin.closed)
                    self.assertTrue(processes[0].stdout.closed)
                finally:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    for process in processes:
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=3)

    def test_host_aliases_share_capacity_but_keep_original_configuration(self):
        namespace = self.provider.capacity_namespace
        original = self.provider.configuration_fingerprint
        alias = copy.copy(self.provider.server)
        alias.owner = 'bob'
        alias.reference = 'other'
        alias.address, alias.port = 'forwarder', 2202
        alias.allowed_root = '/another/root'
        alias.scope_pin = lambda: '8' * 64
        alias.pin = lambda: '9' * 64
        other = SSHProcessProvider(alias, target_ref='other-target',
            spec=self.provider.spec, limits=self.provider.limits,
            exchange=self.exchange, read_lease=lambda owner, key: None)
        self.assertEqual(other.capacity_namespace, namespace)
        self.assertNotEqual(other.configuration_fingerprint, original)
        alias.host_key = 'different-host-key'
        self.assertNotEqual(other.capacity_namespace, namespace)

    async def test_inspect_confirms_original_release_intent_only_with_positive_stop(self):
        self.lease['releaseAck'] = 'unknown'
        running = await self.provider.inspect('lease-1', 'alice')
        self.assertEqual(running['state'], 'RUNNING')
        self.assertFalse(running['released'])
        self.state, self.stopped = 'COMPLETED', True
        released = await self.provider.inspect('lease-1', 'alice')
        self.assertEqual(released['state'], 'RECLAIMED')
        self.assertTrue(released['released'])

    async def test_every_release_path_requires_original_archive_without_output_recursion(self):
        self.state, self.stopped = 'COMPLETED', True
        self.lease['releaseAck'] = 'unknown'
        self.provider.archive_original = AsyncMock(side_effect=OSError('archive unavailable'))
        for action in (self.provider.reclaim, self.provider.inspect):
            with self.assertRaises(OSError):
                await action('lease-1', 'alice')
        self.assertEqual(self.provider.archive_original.await_count, 2)
        self.provider.archive_original = None
        with self.assertRaisesRegex(ValueError, 'SSH_PROCESS_ARCHIVE_REQUIRED'):
            await self.provider.inspect('lease-1', 'alice')
        self.provider.archive_original = AsyncMock()
        result = await self.provider.inspect('lease-1', 'alice')
        self.assertEqual(result['state'], 'RECLAIMED')
        self.provider.archive_original.assert_awaited_once_with('alice', 'lease-1')
        self.assertNotIn('submit', self.calls)
