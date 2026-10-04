"""Synthetic contract tests; no real cgroup filesystem is mutated."""
from copy import deepcopy
import unittest
from typing import Any
from unittest.mock import Mock, patch

from agent_factory.delegated_cgroup_fs import LinuxDelegatedCgroupFS

from agent_factory.delegated_cgroup import DelegatedCgroupBackend, DelegatedCgroupConfig, DelegatedCgroupError


def config():
    return DelegatedCgroupConfig('/operator/delegated', 1, 2, '12345678-1234-1234-1234-123456789abc',
                                 100000, 100000, 33554432, 0, 8)


class FakeFS:
    def __init__(self, configuration):
        self.config = configuration
        self.pin: Any = None
        self.values = {'cgroup.type': 'domain', 'cgroup.events': 'populated 0'}
        self.effects = []
        self.fail: str | None = None
        self.foreign = False
        self.root_changed = False

    def validate(self):
        pass

    def root_identity(self):
        return {'device': 1, 'inode': 99 if self.root_changed else 2, 'bootId': self.config.boot_id}

    def create(self, name):
        assert self.pin is None
        self.effects.append('create')
        self.pin = dict(name=name, device=1, inode=3, bootId=self.config.boot_id, configSha256=self.config.fingerprint)
        return deepcopy(self.pin)

    def read(self, pin, name):
        assert pin == self.pin
        return self.values[name]

    def write(self, pin, name, value):
        assert pin == self.pin
        self.effects.append(name)
        if name == self.fail:
            raise OSError('synthetic')
        if name == 'cgroup.kill':
            self.values['cgroup.events'] = 'populated 0'
        else:
            self.values[name] = value

    def attach(self, pin, identity):
        assert pin == self.pin
        self.effects.append('attach')
        self.values['cgroup.events'] = 'populated 1'

    def remove(self, pin):
        assert pin == self.pin
        assert not self.foreign
        assert self.values['cgroup.events'] == 'populated 0'
        self.effects.append('remove')
        self.pin = None
        if self.fail == 'remove-ack':
            raise OSError('synthetic lost acknowledgement')

    def absent(self, pin):
        return self.pin is None


class DelegatedContractTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeFS(config())
        self.backend = DelegatedCgroupBackend(config(), self.fs)
        self.ticket = self.backend.new_ticket({'ownerId': 'alice', 'taskId': 'task', 'requestId': 'request'})
        self.history = []

    def persist(self, ticket):
        self.history.append(deepcopy(ticket))
        self.ticket = ticket

    def call(self, method, *args):
        return getattr(self.backend, method)(self.ticket, *args, persist=self.persist, before_effect=lambda: None)

    def test_full_lifecycle_and_released_original_proofs(self):
        self.call('prepare')
        self.assertEqual(self.history[0]['state'], 'CREATE_INTENT')
        self.assertTrue(self.ticket['limitsVerified'])
        self.call('attach_before_exec', {'pid': 7, 'start': '123', 'group': 7, 'bootId': config().boot_id})
        self.call('kill')
        self.call('release')
        proof = self.backend.inspect(self.ticket)
        self.assertTrue(proof['releasedProof'])
        self.assertTrue(proof['attached'])
        self.assertFalse(proof['limitsReadbackVerified'])
        self.fs.pin = {'replacement': True}
        self.assertFalse(self.backend.inspect(self.ticket)['releasedProof'])

    def test_drift_then_release_does_not_restore_current_limit_verification(self):
        self.call('prepare')
        self.assertTrue(self.ticket['limitsVerified'])
        self.assertTrue(self.backend.inspect(self.ticket)['limitsReadbackVerified'])
        self.fs.values['memory.max'] = '67108864'
        self.assertFalse(self.backend.inspect(self.ticket)['limitsReadbackVerified'])
        self.call('release')
        proof = self.backend.inspect(self.ticket)
        self.assertTrue(proof['releasedProof'])
        self.assertFalse(proof['capacityHeld'])
        self.assertFalse(proof['limitsReadbackVerified'])
        # Historical setup observation stays separate from current readback.
        self.assertTrue(self.ticket['limitsVerified'])

    def test_partial_prepare_keeps_pin_and_can_release_empty(self):
        self.fs.fail = 'memory.max'
        with self.assertRaises(DelegatedCgroupError):
            self.call('prepare')
        self.assertIsNotNone(self.ticket['pin'])
        self.assertEqual(self.ticket['state'], 'UNKNOWN')
        with self.assertRaises(DelegatedCgroupError):
            self.call('prepare')
        self.call('release')
        self.assertTrue(self.backend.inspect(self.ticket)['releasedProof'])
        self.assertFalse(self.backend.inspect(self.ticket)['limitsReadbackVerified'])

    def test_unknown_kill_readback_recovers_without_repeating_effect(self):
        self.call('prepare')
        self.fs.values['cgroup.events'] = 'populated 1'
        self.fs.fail = 'cgroup.kill'
        with self.assertRaises(DelegatedCgroupError):
            self.call('kill')
        with self.assertRaises(DelegatedCgroupError):
            self.call('kill')
        self.fs.values['cgroup.events'] = 'populated 0'
        self.assertEqual(self.backend.inspect(self.ticket)['state'], 'EMPTY')
        self.call('release')
        self.assertEqual(self.fs.effects.count('cgroup.kill'), 1)

    def test_lost_remove_ack_is_not_positive_release(self):
        self.call('prepare')
        self.fs.fail = 'remove-ack'
        with self.assertRaises(DelegatedCgroupError):
            self.call('release')
        self.assertFalse(self.backend.inspect(self.ticket)['releasedProof'])
        with self.assertRaises(DelegatedCgroupError):
            self.call('release')
        self.assertEqual(self.fs.effects.count('remove'), 1)

    def test_root_drift_and_child_replacement_hold(self):
        self.call('prepare')
        self.fs.root_changed = True
        self.assertTrue(self.backend.inspect(self.ticket)['capacityHeld'])
        with self.assertRaises(DelegatedCgroupError):
            self.call('release')
        self.fs.root_changed = False
        self.fs.pin['inode'] = 999
        self.assertIsNone(self.backend.inspect(self.ticket)['populated'])

    def test_no_release_live_or_foreign_group(self):
        self.call('prepare')
        self.fs.values['cgroup.events'] = 'populated 1'
        with self.assertRaises(DelegatedCgroupError):
            self.call('release')
        self.fs.values['cgroup.events'] = 'populated 0'
        self.fs.foreign = True
        with self.assertRaises(DelegatedCgroupError):
            self.call('release')
        self.assertNotIn('remove', self.fs.effects)

    def test_async_guard_or_persist_never_creates_group(self):
        async def invalid(*args):
            pass
        for options in ({'persist': self.persist, 'before_effect': invalid},
                        {'persist': invalid, 'before_effect': lambda: None}):
            with self.assertRaises(DelegatedCgroupError):
                self.backend.prepare(self.ticket, **options)
        self.assertEqual(self.fs.effects, [])

    def test_attach_once_and_explicit_config_roundtrip(self):
        self.assertEqual(DelegatedCgroupConfig.from_dict(config().to_dict()), config())
        self.call('prepare')
        self.call('attach_before_exec', {'pid': 7, 'bootId': config().boot_id})
        with self.assertRaises(DelegatedCgroupError):
            self.call('attach_before_exec', {'pid': 8, 'bootId': config().boot_id})
        self.assertEqual(self.fs.effects.count('attach'), 1)


    def test_real_port_pid_reuse_rejects_before_kernel_write(self):
        port = object.__new__(LinuxDelegatedCgroupFS)
        expected = {'pid': 7, 'start': '123', 'group': 7, 'bootId': config().boot_id}
        with patch.object(port, 'process_identity', return_value=dict(expected, start='999')), \
                patch.object(port, 'write') as write:
            with self.assertRaises(DelegatedCgroupError):
                port.attach({}, expected)
        write.assert_not_called()

    def test_real_port_creation_is_exclusive_never_adopts_existing_name(self):
        port = object.__new__(LinuxDelegatedCgroupFS)
        port.config = config()
        with patch.object(port, '_root', return_value=4), patch.object(port, '_prerequisites'), \
                patch('agent_factory.delegated_cgroup_fs.os.mkdir', side_effect=FileExistsError), \
                patch('agent_factory.delegated_cgroup_fs.os.close'), \
                patch('agent_factory.delegated_cgroup_fs.os.open') as opened:
            with self.assertRaises(FileExistsError):
                port.create('af-' + 'a' * 32)
        opened.assert_not_called()

    def test_authority_revoked_after_intent_blocks_real_effect(self):
        checks = Mock(side_effect=[None, PermissionError('synthetic revoked')])
        with self.assertRaises(DelegatedCgroupError):
            self.backend.prepare(self.ticket, persist=self.persist, before_effect=checks)
        self.assertEqual(self.ticket['state'], 'UNKNOWN')
        self.assertTrue(self.ticket['createAttempted'])
        self.assertEqual(self.fs.effects, [])


if __name__ == '__main__':
    unittest.main()
