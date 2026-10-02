"""Guard scope declarations remove only same-boundary duplicate checks."""
from types import SimpleNamespace
import unittest

from agent_factory.inference_wait import TOOL_NAMES, current
from agent_factory.store import Store


class GuardStore:
    register_execution_guard = Store.register_execution_guard
    require_plan_execution = Store.require_plan_execution

    def __init__(self):
        self.execution_guards = {}
        self.tool_independent_execution_guards = {}
        self.auth = self.plan_policy = None
        self.usage_ledger = SimpleNamespace(inspect=lambda *args: {'scopes': []})
        self.record = {'id': 'task', 'owner_id': 'owner', 'plan_id': 'plan',
                       'run_id': 'run', 'request_id': 'request', 'cancel_requested': False}

    def require_current_policy(self):
        pass

    def task(self, *args):
        return dict(self.record)

    def plan(self, *args):
        return {'id': 'plan', 'tools': list(TOOL_NAMES)}

    def has_failures(self, *args):
        return False


class InferenceGuardScopeTests(unittest.TestCase):
    def test_declared_full_plan_checks_run_once_but_custom_tools_are_checked(self):
        store, calls = GuardStore(), {}
        for name in ('materials', 'bindings', 'application', 'custom'):
            calls[name] = []
            store.register_execution_guard(name, lambda owner, plan, ctx, tool, name=name: calls[name].append(tool),
                tool_independent=name != 'custom')
        current(store, store.task())
        for name in ('materials', 'bindings', 'application'):
            self.assertEqual(calls[name], [None])
        self.assertEqual(calls['custom'], [None, TOOL_NAMES[1], TOOL_NAMES[2]])

    def test_next_observation_rechecks_and_denies_new_revocation(self):
        store, calls = GuardStore(), []
        def governance(owner, plan, ctx, tool):
            calls.append(tool)
            if len(calls) > 1:
                raise PermissionError('synthetic current revocation')
        store.register_execution_guard('governance', governance, tool_independent=True)
        current(store, store.task())
        with self.assertRaises(PermissionError):
            current(store, store.task())
        self.assertEqual(calls, [None, None])

    def test_replacement_does_not_inherit_old_tool_independent_declaration(self):
        store, calls = GuardStore(), []
        store.register_execution_guard('guard', lambda *args: None, tool_independent=True)
        def replacement(owner, plan, ctx, tool):
            calls.append(tool)
            if tool == TOOL_NAMES[2]:
                raise PermissionError('tool-specific denial')
        store.execution_guards['guard'] = replacement
        with self.assertRaises(PermissionError):
            current(store, store.task())
        self.assertEqual(calls, [None, TOOL_NAMES[1], TOOL_NAMES[2]])

    def test_guard_replaced_during_check_cannot_claim_prior_check(self):
        store, calls = GuardStore(), []
        def replacement(owner, plan, ctx, tool):
            calls.append(tool)
            raise PermissionError('replacement requires a fresh check')
        def first(owner, plan, ctx, tool):
            store.register_execution_guard('guard', replacement, tool_independent=True)
        store.register_execution_guard('guard', first, tool_independent=True)
        with self.assertRaises(PermissionError):
            current(store, store.task())
        self.assertEqual(calls, [TOOL_NAMES[1]])

    def test_reregistration_without_scope_clears_previous_declaration(self):
        store = GuardStore()
        def guard(*args):
            return None
        store.register_execution_guard('guard', guard, tool_independent=True)
        store.register_execution_guard('guard', guard)
        self.assertNotIn('guard', store.tool_independent_execution_guards)

    def test_guard_restored_after_policy_check_was_not_already_checked(self):
        store, calls = GuardStore(), []
        def denied(owner, plan, ctx, tool):
            calls.append('denied')
            raise PermissionError('restored guard denies')
        def intermediate(owner, plan, ctx, tool):
            calls.append('intermediate')
            store.register_execution_guard('guard', denied, tool_independent=True)
        store.register_execution_guard('guard', denied, tool_independent=True)
        store.require_current_policy = lambda: store.register_execution_guard('guard', intermediate)
        with self.assertRaises(PermissionError):
            current(store, store.task())
        self.assertEqual(calls, ['intermediate', 'denied'])


if __name__ == '__main__':
    unittest.main()
