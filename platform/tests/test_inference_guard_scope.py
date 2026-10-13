"""Guard scope declarations remove only same-boundary duplicate checks."""
from types import SimpleNamespace
import unittest

from agent_factory.store import Store


class GuardStore:
    register_execution_guard = Store.register_execution_guard
    require_plan_execution = Store.require_plan_execution

    def __init__(self, *, tools=()):
        self.tools = tuple(tools)
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
        return {'id': 'plan', 'tools': list(self.tools)}

    def has_failures(self, *args):
        return False


class StoreGuardScopeTests(unittest.TestCase):
    def test_reregistration_without_scope_clears_previous_declaration(self):
        store = GuardStore()
        def guard(*args):
            return None
        store.register_execution_guard('guard', guard, tool_independent=True)
        store.register_execution_guard('guard', guard)
        self.assertNotIn('guard', store.tool_independent_execution_guards)


    def test_plan_boundary_reports_each_exact_checked_callable(self):
        store, calls = GuardStore(tools=('fixed-tool',)), []
        def guard(owner, plan, context, tool):
            calls.append((owner, plan, context, tool))
        store.register_execution_guard('guard', guard, tool_independent=True)
        context = object()
        plan = store.plan()
        checked = store.require_plan_execution('owner', plan, run_context=context)
        self.assertEqual(calls, [('owner', plan, context, None)])
        self.assertIs(checked['guard'], guard)
        self.assertIs(store.tool_independent_execution_guards['guard'], guard)

    def test_guard_replaced_while_running_is_not_reported_as_checked(self):
        store, calls = GuardStore(), []
        def replacement(owner, plan, context, tool):
            calls.append('replacement')
            raise PermissionError('replacement requires a fresh check')
        def first(owner, plan, context, tool):
            calls.append('first')
            store.register_execution_guard('guard', replacement, tool_independent=True)
        store.register_execution_guard('guard', first, tool_independent=True)
        checked = store.require_plan_execution('owner', store.plan())
        self.assertIs(checked['guard'], first)
        self.assertIs(store.execution_guards['guard'], replacement)
        self.assertIs(store.tool_independent_execution_guards['guard'], replacement)
        with self.assertRaises(PermissionError):
            store.require_plan_execution('owner', store.plan())
        self.assertEqual(calls, ['first', 'replacement'])


if __name__ == '__main__':
    unittest.main()
