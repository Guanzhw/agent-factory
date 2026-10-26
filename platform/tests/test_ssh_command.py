"""Pinned command parsing with existing synthetic public files; never connects to SSH."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_factory.ssh_identity import pinned_ssh


class SSHCommandTests(unittest.TestCase):
    def test_posix_space_and_quote_paths_keep_exact_identity_agent_and_pin(self):
        ssh = shutil.which('ssh')
        self.assertIsNotNone(ssh, 'System OpenSSH is required for the configuration parser regression')
        parent_cwd = os.getcwd()
        server = SimpleNamespace(host_key='synthetic-public-host-key', username='fixture',
                                 port=2244, address='fixture.invalid')
        with TemporaryDirectory() as temporary:
            local = Path(temporary) / "private space 'quote'"
            local.mkdir()
            lease = SimpleNamespace(public_key='synthetic-public-client-key',
                                    socket=str(local / "agent space 'quote'.sock"))
            with patch('agent_factory.ssh_identity.sys.platform', 'linux'), \
                    patch('agent_factory.ssh_identity.subprocess.Popen', return_value=Mock()) as launch:
                with pinned_ssh(server, lease, local, 'fixed-command', deadline=time.monotonic() + 30):
                    pass
            args, options = launch.call_args.args[0], launch.call_args.kwargs
            # Existing identity file matters: OpenSSH ignores a missing -i and then adds its defaults.
            parsed = subprocess.run([ssh, '-G', *args[1:]], cwd=options.get('cwd'),
                                    env=os.environ | options['env'], capture_output=True, text=True, timeout=5)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            values = parsed.stdout.splitlines()
            self.assertEqual([line for line in values if line.startswith('identityfile ')],
                             ['identityfile identity.pub'])
            self.assertIn('identityagent SSH_AUTH_SOCK', values)
            self.assertIn('userknownhostsfile known_hosts', values)
            self.assertIn('globalknownhostsfile none', values)
            self.assertIn('stricthostkeychecking true', values)
            self.assertIn('identitiesonly yes', values)
            self.assertEqual(options['env'], {'PATH': '/usr/local/bin:/usr/bin:/bin', 'SSH_AUTH_SOCK': lease.socket})
            self.assertEqual(Path(options['cwd']), local)
            self.assertEqual(os.getcwd(), parent_cwd)
            self.assertEqual((local / 'known_hosts').read_text(), 'factory-pinned ' + server.host_key + '\n')
            self.assertEqual((local / 'identity.pub').read_text(), lease.public_key + '\n')
