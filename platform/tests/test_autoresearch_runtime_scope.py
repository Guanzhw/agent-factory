"""Scientific child authority failures stop leases without changing standalone guards."""
import unittest
from unittest.mock import Mock, patch

from agent_factory.autoresearch_scientific_child import adapter_id
from agent_factory.process_runtime import ProcessRuntimeService
from agent_factory.research_runtime import ResearchProcessRuntimeService


class ScientificRuntimeScopeTests(unittest.TestCase):
    def fixture(self, phase):
        store = Mock()
        task = {'id': 'task', 'owner_id': 'alice', 'run_id': 'run', 'plan_id': 'plan', 'request_id': 'request'}
        tool = 'bounded_process_run' if phase == 'preparation' else 'research_process_run'
        store.execution_bindings.manifest.return_value = {'tools': [{
            'adapterId': adapter_id(phase, 'tool'), 'toolName': tool,
            'config': {'presetId': 'preset', 'phase': phase}}]}
        return store, task

    def test_parent_expiry_becomes_stop_authority_for_all_three_phases(self):
        for phase in ('preparation', 'training', 'evaluation'):
            with self.subTest(phase=phase):
                store, task = self.fixture(phase)
                with patch('agent_factory.autoresearch_scientific_child.child_pin', side_effect=ValueError('expired')):
                    with self.assertRaisesRegex(PermissionError, 'AUTORESEARCH_CHILD_AUTHORITY_ENDED'):
                        if phase == 'preparation':
                            ProcessRuntimeService(store, Mock(), Mock()).validate_execution('alice', task, {}, 'target',
                                {'nativeRunId': 'run', 'effectKey': 'bounded-process-run-v1'})
                        else:
                            ResearchProcessRuntimeService(store, Mock(), Mock())._config(task, {})

    def test_maintenance_classifies_scientific_authority_loss_without_stop_claim(self):
        service = ProcessRuntimeService(Mock(), Mock(), Mock())
        service.guard_lease = Mock(side_effect=PermissionError('AUTORESEARCH_CHILD_AUTHORITY_ENDED'))
        from datetime import datetime, timedelta, timezone
        lease = {'deadlineAt': (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}
        task = {'cancel_requested': False, 'terminal': False}
        self.assertEqual(service._reason(lease, task, {'status': 'running'}), 'AUTHORITY_ENDED')


if __name__ == '__main__':
    unittest.main()
