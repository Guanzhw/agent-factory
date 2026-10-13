"""The standalone core has no installed research runtime or implicit authority."""
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from fastapi import HTTPException

from agent_factory.control_commands import ControlCommands
from agent_factory.execution_bindings import default_bindings
from agent_factory.runtime_hooks import cancel_owned_runtime, effect_unresolved, native_ended_reason
from agent_factory.usage_ledger import default_zero_prices


class CoreRuntimeBoundaryTests(unittest.TestCase):
    def test_store_guard_tests_collect_and_run_without_application_packages(self):
        platform = Path(__file__).resolve().parents[1]
        code = '''
import importlib.abc, importlib.util, sys, unittest
sys.path[:0] = sys.argv[1:]
for name in ('agent_factory_research', 'agent_factory_server'):
    assert importlib.util.find_spec(name) is None, name
class NoApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'agent_factory_research', 'agent_factory_server'}:
            raise AssertionError('Core test imported application code: ' + fullname)
sys.meta_path.insert(0, NoApplication())
suite = unittest.defaultTestLoader.loadTestsFromName('test_inference_guard_scope')
assert not unittest.defaultTestLoader.errors, unittest.defaultTestLoader.errors
assert suite.countTestCases() == 3
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and not result.skipped
'''
        result = subprocess.run([sys.executable, '-I', '-S', '-c', code, str(platform),
            str(platform / 'tests'), sysconfig.get_path('purelib')],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_core_imports_without_loading_any_research_package(self):
        platform = Path(__file__).resolve().parents[1]
        code = '''
import agent_factory, importlib, importlib.abc, pkgutil, sys
class NoResearch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('agent_factory_research'):
            raise AssertionError('Core imported application code: ' + fullname)
sys.meta_path.insert(0, NoResearch())
for item in pkgutil.iter_modules(agent_factory.__path__):
    if item.name != '__main__':
        importlib.import_module('agent_factory.' + item.name)
assert not any(name.startswith('agent_factory_research') for name in sys.modules)
'''
        result = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'PYTHONPATH': str(platform)},
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_core_does_not_implicitly_install_adapters_seeds_or_free_models(self):
        registry = default_bindings(SimpleNamespace(demo=True), object())
        self.assertEqual(registry.describe(), [])
        self.assertEqual(registry.legacy_materials, ())
        self.assertEqual(registry.legacy_bindings, {})
        self.assertEqual(default_zero_prices(), ())

    def test_stop_requirement_is_bound_to_the_explicit_store(self):
        held = SimpleNamespace(runtime_effect_held=lambda effect: effect.get('result', {}).get('allStopped') is not True)
        unrelated = SimpleNamespace(runtime_effect_held=None)
        effect = {'status': 'DONE', 'result': {}}
        self.assertTrue(effect_unresolved(effect, held))
        self.assertFalse(effect_unresolved(effect, unrelated))
        self.assertFalse(effect_unresolved({**effect, 'result': {'allStopped': True}}, held))
        self.assertTrue(effect_unresolved({'status': 'UNKNOWN'}, unrelated))

    def test_missing_recovery_adapter_cannot_approve_an_old_launch(self):
        with self.assertRaises(HTTPException) as error:
            ControlCommands._approval_payload({}, {}, {})
        self.assertEqual(error.exception.status_code, 409)
        self.assertIn('APPROVED_RECOVERY_UNAVAILABLE', error.exception.detail)

    def test_workflow_custody_remains_independent_of_application_adapters(self):
        store = SimpleNamespace(runtime_ended_reason=None, workflow=SimpleNamespace(task_held=lambda task: task == 'original'))
        self.assertEqual(native_ended_reason(store, {'id': 'original'}), 'native-ended-unfinished-workflow')
        self.assertIsNone(native_ended_reason(store, {'id': 'other'}))


class CoreCancellationBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_preserves_original_task_and_workflow_scope(self):
        callback, workflow = AsyncMock(), AsyncMock()
        store = SimpleNamespace(runtime_cancel_owned=callback, workflow=SimpleNamespace(cancel_task=workflow))
        task = {'id': 'original', 'owner_id': 'alice'}
        await cancel_owned_runtime(store, task)
        callback.assert_awaited_once_with(task)
        workflow.assert_awaited_once_with('alice', 'original')

    async def test_uncertain_adapter_stop_does_not_proceed_as_success(self):
        callback, workflow = AsyncMock(side_effect=ValueError('stop unknown')), AsyncMock()
        store = SimpleNamespace(runtime_cancel_owned=callback, workflow=SimpleNamespace(cancel_task=workflow))
        with self.assertRaises(ValueError):
            await cancel_owned_runtime(store, {'id': 'original', 'owner_id': 'alice'})
        workflow.assert_not_awaited()
