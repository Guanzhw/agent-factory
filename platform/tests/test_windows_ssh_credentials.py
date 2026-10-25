"""Portable scope/authority tests; OS calls are explicit fakes, not Windows evidence."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
import shutil
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import agent_factory
from agent_factory.windows_ssh_credentials import WindowsSSHCredentials, _Carrier
from agent_factory.ssh_exchange import SSHExchangeCleanupError


class WindowsCredentialScopeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.support = ModuleType('agent_factory.windows_ssh_support')
        self.support.directory = lambda p: p.mkdir()
        self.support.write_private = lambda p, data: p.write_bytes(data)
        self.support.server_pipe = lambda _: SimpleNamespace(Close=Mock())
        self.support.connect = lambda *args: None
        self.support.check_client = Mock()
        self.support.image = lambda _: 'base-python'
        self.support.win32api = SimpleNamespace(GetCurrentProcess=lambda: 1)
        self.reads = 0
        self.releases = 0
        self.password_in_environment = False
        def transfer(pipe, deadline, payload=None, **kwargs):
            if payload is not None:
                self.releases += 1
                self.password_in_environment = any(payload.decode() == value for value in self.processes[-1].env.values())
                return b''
            self.reads += 1
            return b'READY' if self.reads % 2 else b'RECEIVED'
        self.support.transfer = transfer
        self.stack.enter_context(patch.dict('sys.modules', {'agent_factory.windows_ssh_support': self.support}))
        self.stack.enter_context(patch.object(agent_factory, 'windows_ssh_support', self.support, create=True))
        self.vault = SimpleNamespace(authorize=Mock(return_value=True), resolve=Mock())
        self.manager = WindowsSSHCredentials(self.vault, max_agents=1, seconds=30)
        self.cleanup_failed_expected = False
        def cleanup():
            try:
                if self.cleanup_failed_expected:
                    with self.assertRaises(SSHExchangeCleanupError):
                        self.manager.close()
                else:
                    self.manager.close()
            finally:
                if self.manager.root.exists():
                    shutil.rmtree(self.manager.root)
        self.addCleanup(cleanup)
        self.binary = Path(self.temp) / 'synthetic-binary'
        self.binary.write_bytes(b'synthetic-installed-launcher\x00\xff')
        self.stack.enter_context(patch.object(self.manager, 'paths', return_value=(self.binary, self.binary)))
        self.key = SimpleNamespace(private_bytes=lambda *args: b'encrypted-synthetic-fixture')
        self.stack.enter_context(patch.object(self.manager, '_key', return_value=self.key))
        self.stack.enter_context(patch.object(self.manager, '_public', return_value='synthetic-public-key'))
        self.guard = Mock()
        self.server = SimpleNamespace(owner='alice', credential_ref='credential', credential_revision='one',
                                      host_key='synthetic-host-key', username='fixture', port=22, address='fixture.invalid')
        self.lease = self.manager.acquire(self.server, 'ssh://fixture.invalid', self.guard)
        self.processes = []
        outer = self
        class FakeProcess:
            pid = 2
            process_handle = 3
            def __init__(self, args, env, *, cwd=None):
                self.env = env
                self.cwd = cwd
                self.resumed = False
                self.killed = False
                self.closed = False
                outer.processes.append(self)
            def resume(self): self.resumed = True
            def kill(self): self.killed = True
            def close(self): self.closed = True
        self.stack.enter_context(patch('agent_factory.windows_ssh_process.WindowsSSHProcess', FakeProcess))

    def open(self, lease=None):
        return (lease or self.lease).open(self.server, 'fixed-command', deadline=time.monotonic() + 5)

    def test_missing_client_precedes_guard_and_vault_resolution(self):
        self.manager._key.reset_mock()
        self.guard.reset_mock()
        with patch.object(self.manager, 'paths', return_value=(Path(self.temp) / 'missing', self.binary)):
            self.assertEqual(self.manager.diagnostic(), 'SSH_SYSTEM_CLIENT_UNAVAILABLE')
            with self.assertRaisesRegex(Exception, 'SSH_SYSTEM_CLIENT_UNAVAILABLE'):
                self.manager.acquire(self.server, 'ssh://fixture.invalid', self.guard)
        self.guard.assert_not_called()
        self.manager._key.assert_not_called()
        self.vault.resolve.assert_not_called()
        self.assertFalse(self.processes)

    def test_revoked_guard_and_expiry_prevent_resolve_or_spawn(self):
        self.manager._key.reset_mock()
        self.guard.side_effect = RuntimeError('synthetic-revoked')
        with self.assertRaisesRegex(RuntimeError, 'synthetic-revoked'):
            with self.open(): pass
        self.guard.side_effect = None
        with self.assertRaisesRegex(Exception, 'SSH_CREDENTIAL_UNAVAILABLE'):
            with self.open(replace(self.lease, expires_at=time.monotonic() - 1)): pass
        self.manager._key.assert_not_called()
        self.assertFalse(self.processes)

    def test_normal_scope_releases_once_and_cleans_its_files(self):
        with self.open() as process:
            end = time.monotonic() + 1
            while self.reads < 2 and time.monotonic() < end:
                time.sleep(.001)
            self.assertTrue(process.resumed)
            helper = Path(process.cwd) / 'askpass.exe'
            self.assertEqual(helper.read_bytes(), self.binary.read_bytes())
            self.assertEqual(process.env['SSH_ASKPASS'], './askpass.exe')
            self.assertEqual(self.support.check_client.call_args.args[3], helper)
            self.assertEqual(self.releases, 1)
            self.assertFalse(self.password_in_environment)
        self.assertTrue(process.closed)
        self.assertFalse(self.manager.active)
        self.assertEqual(list(self.manager.root.iterdir()), [])

    def test_capacity_denies_second_carrier_before_resolve(self):
        with self.open():
            calls = self.manager._key.call_count
            with self.assertRaisesRegex(Exception, 'SSH_AGENT_CAPACITY'):
                with self.open(): pass
            self.assertEqual(self.manager._key.call_count, calls)
        self.assertEqual(len(self.processes), 1)

    def test_guard_rechecked_before_password_release(self):
        connected, proceed = threading.Event(), threading.Event()
        def connect(*args):
            connected.set()
            if not proceed.wait(2): raise TimeoutError('synthetic-barrier')
        self.support.connect = connect
        with self.assertRaisesRegex(Exception, 'SSH_CREDENTIAL_UNAVAILABLE'):
            with self.open() as process:
                self.assertTrue(connected.wait(1))
                self.vault.authorize.return_value = False
                proceed.set()
                end = time.monotonic() + 1
                while not process.killed and time.monotonic() < end:
                    time.sleep(.001)
        self.assertEqual(self.releases, 0)
        self.assertTrue(process.closed)
        self.assertFalse(self.manager.active)

    def test_close_racing_with_initialization_prevents_resume(self):
        entered, proceed = threading.Event(), threading.Event()
        failures = []
        def key(scope):
            entered.set()
            if not proceed.wait(2): raise TimeoutError('synthetic-barrier')
            return self.key
        self.manager._key.side_effect = key
        def use():
            try:
                with self.open(): self.fail('closed initialization resumed')
            except Exception as exc: failures.append(type(exc).__name__)
        user = threading.Thread(target=use)
        user.start()
        self.assertTrue(entered.wait(1))
        closer = threading.Thread(target=self.manager.close)
        closer.start()
        end = time.monotonic() + 1
        while not self.manager.closed and time.monotonic() < end:
            time.sleep(.001)
        self.assertTrue(self.manager.closed)
        proceed.set()
        user.join(2); closer.join(2)
        self.assertFalse(user.is_alive() or closer.is_alive())
        self.assertTrue(failures)
        self.assertTrue(all(not p.resumed and p.closed for p in self.processes))
        self.assertFalse(self.manager.active)

    def test_process_cleanup_failure_closes_admission_and_retains_failure(self):
        self.cleanup_failed_expected = True
        with self.assertRaisesRegex(SSHExchangeCleanupError, 'SSH_CARRIER_CLEANUP_INCOMPLETE'):
            with self.open() as process:
                process.close = Mock(side_effect=RuntimeError('synthetic-cleanup-failure'))
        self.assertTrue(self.manager.closed)
        self.assertEqual(len(self.manager.active), 1)
        self.assertTrue(next(iter(self.manager.active)).failed)
        self.manager._key.reset_mock()
        self.vault.resolve.reset_mock()
        process_count = len(self.processes)
        with self.assertRaisesRegex(Exception, 'SSH_CREDENTIAL_UNAVAILABLE'):
            with self.open(): pass
        with self.assertRaisesRegex(Exception, 'SSH_CREDENTIAL_UNAVAILABLE'):
            self.manager.acquire(self.server, 'ssh://fixture.invalid', self.guard)
        self.manager._key.assert_not_called()
        self.vault.resolve.assert_not_called()
        self.assertEqual(len(self.processes), process_count)
        with self.assertRaises(SSHExchangeCleanupError):
            self.manager.close()
        self.assertEqual(list(self.manager.root.iterdir()), [])

    def test_close_attempts_other_original_carriers_after_one_kill_fails(self):
        self.cleanup_failed_expected = True
        carriers = [_Carrier(), _Carrier()]
        self.manager.active.update(carriers)
        first, second = tuple(self.manager.active)
        for carrier in carriers:
            carrier.process = SimpleNamespace(kill=Mock())
            carrier.done = Mock()
            carrier.done.wait.return_value = True
        first.process.kill.side_effect = RuntimeError('synthetic-kill-failure')
        with self.assertRaises(SSHExchangeCleanupError):
            self.manager.close()
        first.process.kill.assert_called_once_with()
        second.process.kill.assert_called_once_with()
        first.done.wait.assert_called_once()
        second.done.wait.assert_called_once()
        self.assertTrue(first.cancelled.is_set() and second.cancelled.is_set())
        self.assertEqual(self.manager.active, {first})
        with self.assertRaises(SSHExchangeCleanupError):
            self.manager.close()
        first.process.kill.assert_called_once_with()
        second.process.kill.assert_called_once_with()

    def test_closed_manager_rejects_acquire_before_secret_resolution(self):
        self.manager.close()
        self.manager._key.reset_mock()
        with self.assertRaisesRegex(Exception, 'SSH_CREDENTIAL_UNAVAILABLE'):
            self.manager.acquire(self.server, 'ssh://fixture.invalid', self.guard)
        self.manager._key.assert_not_called()
        self.vault.resolve.assert_not_called()
