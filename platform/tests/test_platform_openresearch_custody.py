"""Controlled deployment receipts: no Docker daemon, native goal or model IO."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from agent_factory.platform_openresearch import PlatformOpenResearchPackage, PACKAGE_VERSION
from agent_factory.store import digest


@unittest.skipUnless(sys.platform == 'linux', 'Private platform package uses Linux custody')
class PlatformOpenResearchCustodyTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.package = package = object.__new__(PlatformOpenResearchPackage)
        package.root = Path(self.folder.name)
        package.config = SimpleNamespace(validate=lambda: None, max_active=2, lease_seconds=1800,
            max_active_seconds=21600,
            image='sha256:' + 'a' * 64, orx_path='/synthetic/orx', opencode_path='/synthetic/opencode')
        package.live = {}; package.lock = threading.RLock()
        package.scope = 'synthetic-scope'
        self.body = {'id': 'env-' + 'a' * 32, 'ownerId': 'synthetic-owner', 'applicationId': 'openresearch',
            'packageVersion': PACKAGE_VERSION, 'projectId': str(uuid4()),
            'modelReference': 'synthetic-model', 'modelRevision': 'synthetic-revision'}
        self.root = package._root(self.body)
        self.data = self.root / 'retained.txt'; self.data.write_text('Synthetic original data')
        self.receipt = {'name': 'factory-orx-' + 'b' * 32, 'bodyHash': digest(self.body), 'removed': False}
        package._save(self.root, self.receipt)

    def test_missing_create_intent_recovers_explicit_prepare_without_dispatch(self):
        package = self.package
        broker = Mock(capability='synthetic-capability-0123456789012345')
        command = ['docker', 'create', '--network', 'none', '--env', 'PATH']
        with patch.object(package, '_docker', return_value=b'') as docker, \
                patch.object(package, 'check', return_value=True), \
                patch.object(package, 'request', side_effect=AssertionError('Research dispatch is forbidden')) as request, \
                patch('agent_factory.platform_openresearch.OwnerRuntimeBroker', return_value=broker), \
                patch('agent_factory.platform_openresearch.build_command', side_effect=lambda *args: command[:]), \
                patch('agent_factory.platform_openresearch.subprocess.run', side_effect=[
                    SimpleNamespace(returncode=1, stdout=b''), SimpleNamespace(returncode=0, stdout=b'c' * 64)]) as create:
            with self.assertRaisesRegex(ValueError, 'ENVIRONMENT_PREPARATION_UNCONFIRMED'):
                package.prepare(self.body, SimpleNamespace(check=lambda: None))
            self.assertTrue(package._receipt(self.root, self.body)['removed'])
            package.prepare(self.body, SimpleNamespace(check=lambda: None))
            self.assertEqual(create.call_count, 2)
            self.addCleanup(package.live[self.body['id']]['timer'].cancel)
            saved = package._receipt(self.root, self.body)
            self.assertEqual(saved['containerId'], 'c' * 64)
            self.assertEqual(self.data.read_text(), 'Synthetic original data')
            request.assert_not_called()
            self.assertTrue(any(call.args[:3] == ('container', 'ls', '--all') for call in docker.call_args_list))

    def test_failed_inventory_is_not_absence_and_cannot_replace_unknown_creation(self):
        package = self.package
        with patch.object(package, '_docker', side_effect=ValueError('Synthetic daemon unavailable')), \
                patch('agent_factory.platform_openresearch.subprocess.run') as create:
            self.assertFalse(package.stop(self.body))
            with self.assertRaises(ValueError): package.prepare(self.body, SimpleNamespace(check=lambda: None))
            create.assert_not_called()
        self.assertFalse(package._receipt(self.root, self.body)['removed'])
        self.assertEqual(self.data.read_text(), 'Synthetic original data')

    def test_lease_keeps_original_active_work_but_stops_idle_and_enforces_fixed_budget(self):
        package = self.package
        (self.root / 'orx').mkdir(mode=0o700)
        live = {'root': self.root, 'body': self.body, 'hardDeadline': 200, 'timer': Mock()}
        package.live[self.body['id']] = live
        with patch('agent_factory.platform_openresearch.time.monotonic', return_value=100), \
                patch('agent_factory.platform_openresearch.verify_no_startup_dispatch', side_effect=ValueError('Synthetic active turn')), \
                patch('agent_factory.platform_openresearch.threading.Timer') as timer, \
                patch.object(package, 'stop') as stop, patch.object(package, 'prepare') as prepare, \
                patch.object(package, 'request') as request:
            package._lease_due(self.body)
            stop.assert_not_called(); prepare.assert_not_called(); request.assert_not_called()
            timer.assert_called_once(); self.assertEqual(timer.call_args.args[0], 100)
            timer.return_value.start.assert_called_once()
            self.assertIs(package.live[self.body['id']], live)
        with patch('agent_factory.platform_openresearch.time.monotonic', return_value=100), \
                patch('agent_factory.platform_openresearch.verify_no_startup_dispatch', return_value=None), \
                patch.object(package, 'stop') as stop:
            package._lease_due(self.body); stop.assert_called_once_with(self.body)
        with patch('agent_factory.platform_openresearch.time.monotonic', return_value=201), \
                patch('agent_factory.platform_openresearch.verify_no_startup_dispatch') as inspect, \
                patch.object(package, 'stop') as stop:
            package._lease_due(self.body); stop.assert_called_once_with(self.body); inspect.assert_not_called()

    def test_removed_container_lost_final_receipt_reconciles_only_saved_stop_proof(self):
        package = self.package
        self.receipt['containerId'] = 'c' * 64; package._save(self.root, self.receipt)
        current = {'Id': 'c' * 64, 'State': {'Running': False, 'Paused': False, 'Status': 'exited',
            'Dead': False, 'ExitCode': 0, 'FinishedAt': '2026-10-10T00:00:00Z'}}
        save = package._save
        def interrupted(root, receipt):
            if receipt.get('removed'): raise OSError('Synthetic crash after rm')
            save(root, receipt)
        with patch.object(package, '_inspect', return_value=current), \
                patch.object(package, '_docker', return_value=b'') as docker, \
                patch.object(package, '_save', side_effect=interrupted):
            self.assertFalse(package.stop(self.body))
            docker.assert_called_once_with('rm', 'c' * 64)
        saved = package._receipt(self.root, self.body)
        self.assertFalse(saved['removed']); self.assertEqual(saved['removalIntent']['containerId'], 'c' * 64)
        with patch.object(package, '_docker', return_value=b''), \
                patch.object(package, '_inspect', side_effect=AssertionError('Missing container must not be inspected')):
            self.assertTrue(package.stop(self.body))
        self.assertTrue(package._receipt(self.root, self.body)['removed'])
        self.assertEqual(self.data.read_text(), 'Synthetic original data')
