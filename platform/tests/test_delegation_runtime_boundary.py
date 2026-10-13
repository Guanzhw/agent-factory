"""Default delegation refuses uninstalled placement without allocating work."""
from pathlib import Path
import subprocess
import sys
import sysconfig
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from agent_factory.delegation import DelegationService


class CoreDelegationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.parent = {'id': 'parent', 'plan_id': 'parent-plan'}
        self.store = SimpleNamespace(task=Mock(return_value=self.parent),
            require_current_policy=Mock(), sql=Mock(), reserve_task=Mock())
        self.auth = SimpleNamespace(require=Mock())
        self.bridge = SimpleNamespace(submit=AsyncMock())
        self.service = DelegationService(None, self.store, self.auth, self.bridge)

    async def test_uninstalled_placement_is_rejected_before_any_reservation(self):
        with self.assertRaises(HTTPException) as caught:
            await self.service.create('alice', 'parent', 'child goal', 'mode',
                'request-001', placement={'targetRef': 'uninstalled'})
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail, 'Delegation placement is unavailable')
        self.auth.require.assert_called_once_with('alice', 'run')
        self.store.require_current_policy.assert_called_once_with()
        self.store.task.assert_called_once_with('parent', 'alice')
        self.store.sql.assert_not_called()
        self.store.reserve_task.assert_not_called()
        self.bridge.submit.assert_not_awaited()

    async def test_uninstalled_dispatch_cannot_fall_through_to_native_submission(self):
        with self.assertRaises(HTTPException) as caught:
            await self.service._dispatch_placement('alice', self.parent, {}, {},
                {'targetRef': 'uninstalled'}, 'delegation:original')
        self.assertEqual(caught.exception.status_code, 409)
        self.bridge.submit.assert_not_awaited()

    async def test_unsubmitted_task_has_no_default_placement_cancellation(self):
        self.assertFalse(await self.service._cancel_placement('alice', self.parent))
        self.store.sql.assert_not_called()

    async def test_local_request_keeps_original_fingerprint_input(self):
        self.assertEqual(self.service._creation_request('alice', self.parent,
            '  child goal  ', 'mode', None),
            {'owner': 'alice', 'parent': 'parent', 'goal': 'child goal', 'mode': 'mode'})


class CoreDelegationIsolationTests(unittest.TestCase):
    def test_default_delegation_runs_with_application_packages_unavailable(self):
        platform = Path(__file__).resolve().parents[1]
        code = '''
import importlib.abc, importlib.util, sys, unittest
sys.path[:0] = sys.argv[1:]
for name in ('agent_factory_research', 'agent_factory_server'):
    assert importlib.util.find_spec(name) is None, name
class NoApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'agent_factory_research', 'agent_factory_server'}:
            raise AssertionError('Core delegation imported application code: ' + fullname)
sys.meta_path.insert(0, NoApplication())
suite = unittest.defaultTestLoader.loadTestsFromName(
    'test_delegation_runtime_boundary.CoreDelegationTests')
assert not unittest.defaultTestLoader.errors, unittest.defaultTestLoader.errors
assert suite.countTestCases() == 4
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and not result.skipped
'''
        result = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(platform),
            str(platform / 'tests'), sysconfig.get_path('purelib')],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
