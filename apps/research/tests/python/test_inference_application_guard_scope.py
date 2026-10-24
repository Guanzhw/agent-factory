"""Research inference observation retains fresh Store and per-tool guard proofs."""
import unittest

from agent_factory_research.inference_wait import TOOL_NAMES, current
from test_inference_guard_scope import GuardStore


class InferenceApplicationGuardScopeTests(unittest.TestCase):
    def test_declared_full_plan_checks_run_once_but_custom_tools_are_checked(self):
        store, calls = GuardStore(tools=TOOL_NAMES), {}
        for name in ('materials', 'bindings', 'application', 'custom'):
            calls[name] = []
            store.register_execution_guard(name, lambda owner, plan, ctx, tool, name=name: calls[name].append(tool),
                tool_independent=name != 'custom')
        current(store, store.task())
        for name in ('materials', 'bindings', 'application'):
            self.assertEqual(calls[name], [None])
        self.assertEqual(calls['custom'], [None, TOOL_NAMES[1], TOOL_NAMES[2]])


    def test_next_observation_rechecks_and_denies_new_revocation(self):
        store, calls = GuardStore(tools=TOOL_NAMES), []
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
        store, calls = GuardStore(tools=TOOL_NAMES), []
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
        store, calls = GuardStore(tools=TOOL_NAMES), []
        def replacement(owner, plan, ctx, tool):
            calls.append(tool)
            raise PermissionError('replacement requires a fresh check')
        def first(owner, plan, ctx, tool):
            store.register_execution_guard('guard', replacement, tool_independent=True)
        store.register_execution_guard('guard', first, tool_independent=True)
        with self.assertRaises(PermissionError):
            current(store, store.task())
        self.assertEqual(calls, [TOOL_NAMES[1]])


    def test_guard_restored_after_membership_check_was_not_already_checked(self):
        store, calls = GuardStore(tools=TOOL_NAMES), []
        def denied(owner, plan, ctx, tool):
            calls.append('denied')
            raise PermissionError('restored guard denies')
        def intermediate(owner, plan, ctx, tool):
            calls.append('intermediate')
            store.register_execution_guard('guard', denied, tool_independent=True)
        store.register_execution_guard('guard', denied, tool_independent=True)
        store.auth.require_member = lambda owner: store.register_execution_guard('guard', intermediate)
        with self.assertRaises(PermissionError):
            current(store, store.task())
        self.assertEqual(calls, ['intermediate', 'denied'])



if __name__ == '__main__':
    unittest.main()
