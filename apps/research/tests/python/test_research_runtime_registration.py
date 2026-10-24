"""Portable exact research ownership tests; no database or external provider."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from agent_factory.application_runtime import ApplicationRuntimeRegistry
from agent_factory.execution_bindings import ExecutionBindings
from agent_factory_research.assembly import abort_research_application
from agent_factory_research.runtime_registration import (
    ResearchApplicationHooks, register_research_runtime, research_binding_keys,
)
from agent_factory_research.services import services_for, release_services


def factory():
    def build(context):
        return context
    build.__module__ = 'agent_factory_research.research_runtime_profile'
    return build


class ResearchRuntimeRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plans = {}
        self.store = SimpleNamespace(
            plan=lambda identifier, owner: self.plans[identifier], effects=lambda identifier: [],
            sql=Mock(return_value=[]), has_failures=Mock(return_value=False))
        self.bindings = self.store.execution_bindings = ExecutionBindings(None, self.store)
        self.registry = self.store.application_runtime = ApplicationRuntimeRegistry(self.store)
        self.bindings.register('tool', 'research-process-run-v1-bounded-fixture', '1', factory(), tool_name='research_process_run')
        self.bindings.register('model', 'local-synthetic-model-v1', '1', lambda context: context)
        self.bindings.register('tool', 'native-checksum-v1', '1', lambda context: context, tool_name='checksum')
        self.bindings.register('tool', 'second-tool-v1', '1', lambda context: context, tool_name='second_tool')

    def tearDown(self):
        release_services(self.store)

    def task(self, identifier, plan):
        self.plans[identifier] = plan
        return {'id': identifier, 'plan_id': identifier, 'owner_id': 'alice', 'run_id': 'run-' + identifier,
                'cancel_requested': False}

    def research_plan(self):
        return {'application': 'member-custom-title', 'applicationRef': {'id': 'member-published-new-app', 'version': 8},
                'executionBindings': {'tools': [{'adapterId': 'research-process-run-v1-bounded-fixture',
                    'revision': '1', 'toolName': 'research_process_run'}]}}

    def test_exact_installed_source_handles_dynamic_suffix_without_claiming_core(self):
        keys = research_binding_keys(self.bindings)
        self.assertEqual(keys, (('tool', 'research-process-run-v1-bounded-fixture', '1'),))
        # A lookalike string from an unrelated trusted adapter is not ownership.
        self.bindings.register('tool', 'research-process-run-v1-lookalike', '1', lambda context: context,
                               tool_name='unrelated')
        self.assertEqual(research_binding_keys(self.bindings), keys)

    def test_member_published_application_uses_exact_binding_without_new_gate(self):
        register_research_runtime(self.store)
        owned = self.task('research', self.research_plan())
        self.assertEqual([owner.identifier for owner in self.registry.owners(owned)], ['research'])
        core = self.task('core', {'applicationRef': {'id': 'member-core-app', 'version': 1},
            'executionBindings': {'model': {'adapterId': 'local-synthetic-model-v1', 'revision': '1'}}})
        self.assertEqual(self.registry.owners(core), ())
        self.assertFalse(self.registry.task_held(core))
        self.store.sql.assert_not_called()

    def test_legacy_mapping_does_not_override_present_unowned_bindings(self):
        register_research_runtime(self.store)
        legacy = self.task('old', {'application': 'research'})
        self.assertEqual([owner.identifier for owner in self.registry.owners(legacy)], ['research'])
        other = self.task('other', {'application': 'research', 'executionBindings': {
            'model': {'adapterId': 'local-synthetic-model-v1', 'revision': '1'}}})
        self.assertEqual(self.registry.owners(other), ())

    def test_duplicate_owner_and_exact_identity_rejected(self):
        register_research_runtime(self.store)
        with self.assertRaises(ValueError):
            register_research_runtime(self.store)
        with self.assertRaises(ValueError):
            self.registry.register('second', object(), bindings=research_binding_keys(self.bindings))

    async def test_second_application_never_invokes_research_projection_or_cancel(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                self.store.application_runtime = registry = ApplicationRuntimeRegistry(self.store)
                hooks = ResearchApplicationHooks()
                hooks.cancel = AsyncMock()
                hooks.mark_cancel = Mock()
                hooks.waiting_control = Mock(side_effect=AssertionError('research read for unrelated task'))
                hooks.project_detail = AsyncMock(side_effect=AssertionError('research projection for unrelated task'))
                hooks.observe_waits = AsyncMock(side_effect=AssertionError('research observer for unrelated task'))
                second = SimpleNamespace(cancel=AsyncMock(), mark_cancel=Mock())
                def add_research():
                    register_research_runtime(self.store, hooks=hooks)
                def add_second():
                    registry.register('second', second, bindings=(('tool', 'second-tool-v1', '1'),))
                for install in ((add_second, add_research) if reverse else (add_research, add_second)):
                    install()
                task = self.task('second', {'executionBindings': {'tools': [{
                    'adapterId': 'second-tool-v1', 'revision': '1', 'toolName': 'second_tool'}]}})
                self.assertEqual(registry.waiting_control(None, task, {}), ({}, False))
                self.assertEqual(await registry.project_detail(None, task, self.plans['second'], {}, [], {}, {}), ({}, None))
                await registry.observe_waits(None, task)
                registry.mark_cancel(task)
                await registry.cancel(task)
                second.cancel.assert_awaited_once_with(self.store, task)
                second.mark_cancel.assert_called_once_with(self.store, task['id'])
                hooks.cancel.assert_not_awaited()
                hooks.mark_cancel.assert_not_called()
                self.store.sql.assert_not_called()

    async def test_research_callbacks_keep_read_only_waits_and_original_control(self):
        register_research_runtime(self.store)
        task = self.task('research', self.research_plan())
        api = SimpleNamespace(store=self.store)
        self.assertEqual(self.registry.waiting_control(api, task, {}), ({'research': None}, False))
        self.assertTrue(all(call.args[0].startswith('SELECT') for call in self.store.sql.call_args_list))
        command = SimpleNamespace(store=self.store)
        requirement = {'tool_execution': {'tool_name': 'research_process_run'}}
        requirements = [requirement]
        runtime = SimpleNamespace(completion=AsyncMock(return_value={'allStopped': True}))
        services_for(self.store).research_runtime = runtime
        handler = self.registry.control(task, 'external_result', tool_name='research_process_run')
        self.assertIsNotNone(handler)
        result = await handler(command, task, requirement, requirements, {'approved': True})
        runtime.completion.assert_awaited_once_with(task, requirement)
        self.assertEqual(result['requirements'], requirements)
        self.assertIn('allStopped', requirement['tool_execution']['result'])

    def test_original_cancel_marker_runs_inside_callers_transaction(self):
        register_research_runtime(self.store)
        task = self.task('research', self.research_plan())
        active = False
        def mark(statement, **values):
            self.assertTrue(active)
            self.assertEqual(values['task'], task['id'])
            self.assertIn("state='STOPPING'", statement)
        self.store.sql.side_effect = mark
        active = True
        self.registry.mark_cancel(task)
        active = False
        self.store.sql.assert_called_once()

    def test_application_abort_keeps_core_dependencies_for_other_owners(self):
        self.store.application_environments = SimpleNamespace(close=Mock(side_effect=ValueError('original cleanup failure')))
        self.store.personal_ssh = SimpleNamespace(close=Mock())
        self.store.dispose_root_locks = Mock()
        self.store.engine = SimpleNamespace(dispose=Mock())
        original = services_for(self.store)
        abort_research_application({'store': self.store})
        self.store.application_environments.close.assert_called_once()
        self.store.personal_ssh.close.assert_not_called()
        self.store.dispose_root_locks.assert_not_called()
        self.store.engine.dispose.assert_not_called()
        self.assertIsNot(services_for(self.store), original)
