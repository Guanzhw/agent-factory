"""Security boundary tests; live local SSH acceptance is a separate fixture."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import os
import socket
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from agent_factory.ssh_openresearch import SSHServer, SSHAgentLease, SSHOpenResearchPackage, SSHOpenResearchConfig
from agent_factory.platform_openresearch import PlatformOpenResearchConfig
from agent_factory.runtime_packages.openresearch_v1.ssh_install import directory
from agent_factory.runtime_packages.openresearch_v1.ssh_agent import SSHSupervisor, ForwardedBroker


@unittest.skipUnless(sys.platform == 'linux', 'Linux SSH custody')
class SSHOpenResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.root.chmod(0o700)
        self.agent = socket.socket(socket.AF_UNIX)
        self.agent.bind(str(self.root / 'agent.sock')); (self.root / 'agent.sock').chmod(0o600)
        self.addCleanup(self.agent.close)
        self.revoked = False
        def check():
            if self.revoked: raise ValueError('REVOKED')
        self.lease = SSHAgentLease(str(self.root / 'agent.sock'), 'ssh-ed25519 ' + 'A' * 68, check)
        self.server = SSHServer('mine', 'alice', '1', 'My server', '127.0.0.1', 2234, 'agent',
            'ssh-ed25519 ' + 'B' * 68, str(self.root), 'agent-binding', '1')
        self.package = object.__new__(SSHOpenResearchPackage)
        self.package.config = SimpleNamespace(servers=(self.server,), credentials=lambda **_: self.lease)
        self.package.personal_servers = None

    def test_foreign_server_path_traversal_long_socket_and_revoked_agent_fail_closed(self):
        self.server.validate(); self.lease.validate()
        selected = self.package.selection('alice', 'mine', str(self.root / 'work'))
        self.assertEqual(selected['serverPin'], self.server.pin())
        for owner, target, path in [('bob', 'mine', str(self.root / 'work')),
                ('alice', 'foreign', str(self.root / 'work')), ('alice', 'mine', '/etc/work'),
                ('alice', 'mine', str(self.root / 'other/../work')),
                ('alice', 'mine', str(self.root / ('a' * 80))),
                ('alice', 'mine', str(self.root / 'work,other'))]:
            with self.subTest(owner=owner, path=path), self.assertRaises(ValueError):
                self.package.selection(owner, target, path)
        self.revoked = True
        with self.assertRaises(ValueError): self.package.selection('alice', 'mine', str(self.root / 'work'))

    def test_pinned_ssh_has_no_implicit_credentials_config_or_security_downgrade(self):
        process = SimpleNamespace(stdin=object(), stdout=object())
        with patch('agent_factory.ssh_openresearch.subprocess.Popen', return_value=process) as popen:
            self.package._ssh(self.server, self.lease, self.root, 'fixed-command')
        args, kwargs = popen.call_args
        command = args[0]
        self.assertEqual(command[:5], ['ssh', '-F', 'none', '-a', '-T'])
        for policy in ['StrictHostKeyChecking=yes', 'GlobalKnownHostsFile=/dev/null', 'IdentitiesOnly=yes',
                'BatchMode=yes', 'PasswordAuthentication=no', 'KbdInteractiveAuthentication=no',
                'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no', 'PermitLocalCommand=no']:
            self.assertIn(policy, command)
        self.assertNotIn('SSH_AUTH_SOCK', kwargs['env'])
        self.assertEqual((self.root / 'known_hosts').read_text(), 'factory-pinned ' + self.server.host_key + '\n')

    def test_owned_rpc_requires_exact_body_and_fresh_scope_and_revocation_before_send(self):
        self.package.version = 'fixture-version'
        body = {'id': 'fixture', 'ownerId': 'alice', 'packageVersion': self.package.version,
            **self.package.selection('alice', 'mine', str(self.root / 'work'))}
        scope_calls = []
        revoke_after_model_check = [False]
        def owned_check():
            self.package._scope(body); scope_calls.append('scope')
            if revoke_after_model_check[0]: self.revoked = True
        broker = SimpleNamespace(capability='synthetic', authorized=lambda token: token == 'synthetic',
            handle=SimpleNamespace(check=owned_check))
        channel = Mock(); channel.call.return_value = True
        self.package.live = {'fixture': {'body': body, 'broker': broker, 'lease': self.lease, 'channel': channel}}
        self.assertTrue(self.package.check(dict(body)))
        self.assertEqual(scope_calls, ['scope'])
        channel.reset_mock(); scope_calls.clear()
        for key, changed in [('ownerId', 'bob'), ('serverPin', 'changed'), ('packageVersion', 'stale')]:
            tampered = {**body, key: changed}
            self.assertFalse(self.package.check(tampered))
            with self.assertRaises(ValueError): self.package.request(tampered, 'GET', '/api/health')
        channel.call.assert_not_called(); self.assertEqual(scope_calls, [])
        revoke_after_model_check[0] = True
        self.assertFalse(self.package.check(body))
        channel.call.assert_not_called()
        with self.assertRaises(ValueError): self.package.request(body, 'POST', '/api/chat/sessions', {})
        channel.call.assert_not_called()

    def test_private_installer_refuses_symlink_foreign_directory_and_preserves_external_bytes(self):
        outside = self.root / 'outside'; outside.mkdir(mode=0o700)
        proof = outside / 'proof'; proof.write_text('UNCHANGED')
        (self.root / 'link').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): directory(str(self.root), str(self.root / 'link'))
        with self.assertRaises(ValueError): directory(str(self.root), str(self.root / '../escape'))
        directory(str(self.root), str(self.root / 'owned/new'))
        self.assertEqual(proof.read_text(), 'UNCHANGED')
        outside.chmod(0o755)
        with self.assertRaises(ValueError): directory(str(self.root), str(outside))

    def test_restart_attests_saved_forward_mount_before_stopping_original_container(self):
        supervisor = object.__new__(SSHSupervisor)
        original = self.root / 'connections' / ('a' * 24) / 'broker.sock'
        current = self.root / 'connections' / ('b' * 24) / 'broker.sock'
        supervisor.forwarded = ForwardedBroker('c' * 32, current, 60)
        supervisor.scope = 'scope'
        root = self.root / 'data'
        receipt = {'name': 'factory-orx-' + 'd' * 32, 'bodyHash': 'body', 'brokerSocket': str(original)}
        value = {'Name': '/' + receipt['name'], 'Config': {'User': f'{os.getuid()}:{os.getgid()}',
            'Labels': {'factory.orx.runtime': receipt['name'], 'factory.environment.scope': 'scope',
                'factory.environment.body': 'body'}},
            'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False},
            'Mounts': [{'RW': True, 'Source': str(root), 'Destination': '/session'},
                {'RW': False, 'Source': str(original), 'Destination': '/trusted/model-broker.sock'}]}
        supervisor._docker = lambda *_: json.dumps([value])
        self.assertEqual(supervisor._inspect(receipt, root), value)
        value['Mounts'][1]['Source'] = '/foreign/broker.sock'
        with self.assertRaises(ValueError): supervisor._inspect(receipt, root)

    def test_disconnect_cleanup_fences_a_new_process_and_nested_stop_does_not_deadlock(self):
        supervisors = []
        for _ in range(2):
            supervisor = object.__new__(SSHSupervisor)
            supervisor.root, supervisor.lock, supervisor.capacity_depth = self.root, threading.RLock(), 0
            supervisor.forwarded = SimpleNamespace(path=self.root / 'broker.sock')
            supervisor.live = {'fixture': {'generation': 'owned'}}
            supervisor._root = lambda body: self.root
            supervisor._receipt = lambda root, body: {'name': 'owned', 'brokerSocket': str(self.root / 'broker.sock')}
            supervisors.append(supervisor)
        old, new = supervisors
        admitted, attempted, release, replacement = (threading.Event() for _ in range(4))
        order = []
        def original_stop(supervisor, body):
            if body['nested']:
                order.append('original-receipt-committed'); return True
            admitted.set(); self.assertTrue(release.wait(3))
            return supervisor.stop({'id': 'fixture', 'nested': True})
        def cleanup(): old.stop({'id': 'fixture', 'nested': False})
        def prepare():
            self.assertTrue(admitted.wait(3)); attempted.set()
            with new._capacity(): order.append('replacement-receipt-read'); replacement.set()
        first, second = threading.Thread(target=cleanup), threading.Thread(target=prepare)
        with patch('agent_factory.runtime_packages.openresearch_v1.ssh_agent.OpenResearchSupervisor.stop',
                autospec=True, side_effect=original_stop):
            first.start(); second.start()
            try:
                self.assertTrue(attempted.wait(3)); self.assertFalse(replacement.wait(0.05))
            finally:
                release.set(); first.join(3); second.join(3)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(order, ['original-receipt-committed', 'replacement-receipt-read'])
        self.assertEqual((old.capacity_depth, new.capacity_depth), (0, 0))

    def test_replacement_prepare_first_then_old_close_and_timer_preserve_new_generation(self):
        from agent_factory.runtime_packages.openresearch_v1.supervisor import digest
        root = self.root / 'runtime'; root.mkdir(mode=0o700)
        brokers = []
        for nonce in ('a' * 24, 'b' * 24):
            parent = self.root / 'connections' / nonce; parent.mkdir(mode=0o700, parents=True)
            channel = socket.socket(socket.AF_UNIX); channel.bind(str(parent / 'broker.sock'))
            (parent / 'broker.sock').chmod(0o600); self.addCleanup(channel.close)
            brokers.append(ForwardedBroker('c' * 32, parent / 'broker.sock', 120))
        config = PlatformOpenResearchConfig('/synthetic/orx', '/synthetic/opencode', 'sha256:' + 'a' * 64)
        with patch.object(PlatformOpenResearchConfig, 'validate'):
            old, new = [SSHSupervisor(config, root, 'synthetic-version', broker) for broker in brokers]
            body = {'id': 'env-' + 'd' * 32, 'packageVersion': new.version, 'projectId': 'synthetic-project'}
            data = old._root(body); old_name = 'factory-orx-' + 'e' * 32
            old._save(data, {'name': old_name, 'bodyHash': digest(body), 'removed': False})
            old.live[body['id']] = {'generation': old_name, 'timer': Mock(), 'broker': brokers[0],
                'body': body, 'root': data, 'hardDeadline': 0}
            removed = []
            new._remove_stopped = lambda receipt, path: removed.append(receipt['name']) or True
            new._verify_idle = lambda path: None
            new._command = lambda *args: ['docker', 'create', '--network', 'none', '--env', 'PATH']
            new._docker = lambda *args, **kwargs: b''
            new.check = lambda body: True
            with patch('agent_factory.runtime_packages.openresearch_v1.supervisor.subprocess.run',
                    return_value=SimpleNamespace(returncode=0, stdout=('f' * 64).encode())):
                new.prepare(body, brokers[1])
            self.addCleanup(new.live[body['id']]['timer'].cancel)
            receipt_path = new._control(data) / 'runtime.json'; original = receipt_path.read_bytes()
            replacement = json.loads(original)
            self.assertNotEqual(replacement['name'], old_name)
            self.assertEqual(replacement['brokerSocket'], str(brokers[1].path))
            # The new prepare actually completed first. Both delayed cleanup
            # paths still hold the old generation, even after taking the flock.
            old_generation = old.live[body['id']]
            with patch.object(old, '_remove_stopped') as stale_remove:
                old.close(); stale_remove.assert_not_called()
                self.assertEqual(receipt_path.read_bytes(), original)
                # Exercise a distinct delayed timer with old custody still
                # present, rather than a callback after close retired it.
                old.live[body['id']] = old_generation
                old._lease_due(body, generation=old_name)
                stale_remove.assert_not_called()
            self.assertEqual(receipt_path.read_bytes(), original)
            self.assertIn(body['id'], new.live); self.assertNotIn(body['id'], old.live)
            self.assertTrue(brokers[1].authorized(brokers[1].capability))
            self.assertEqual(removed, [old_name])
            # A canceled timer already waiting on this same process's lock
            # cannot reclaim its later replacement either.
            with patch.object(new, 'stop') as stop:
                new._lease_due(body, generation=old_name); stop.assert_not_called()

    def test_runtime_limits_and_original_license_notices_are_frozen_into_package_identity(self):
        binary = self.root / 'synthetic-binary'; binary.write_bytes(b'SYNTHETIC-NOT-EXECUTED')
        runtime = PlatformOpenResearchConfig(str(binary), str(binary), 'sha256:' + 'a' * 64)
        with patch.object(PlatformOpenResearchConfig, 'validate'):
            config = SSHOpenResearchConfig(runtime, (self.server,), lambda **_: self.lease)
            original = SSHOpenResearchPackage(config, self.root / 'package')
            changed = SSHOpenResearchPackage(SSHOpenResearchConfig(
                PlatformOpenResearchConfig(str(binary), str(binary), runtime.image, max_active_seconds=43200),
                (self.server,), config.credentials), self.root / 'other-package')
        self.assertNotEqual(original.version, changed.version)
        for name in ('ORX-LICENSE.txt', 'OPENCODE-LICENSE.txt', 'FACTORY-LICENSE.txt'):
            self.assertIn(name, original.code_pins)
            self.assertIn('Permission is hereby granted', original.files[name].read_text())
        self.assertIn('THIRD_PARTY_NOTICES.md', original.code_pins)
