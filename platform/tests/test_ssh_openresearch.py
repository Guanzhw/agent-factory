"""Security boundary tests; live local SSH acceptance is a separate fixture."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import os
import socket
import sys
import unittest
from unittest.mock import patch

from agent_factory.ssh_openresearch import SSHServer, SSHAgentLease, SSHOpenResearchPackage
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
