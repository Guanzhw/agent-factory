"""Summary state priority matches native detail without weakening stop proof."""
import unittest
from unittest.mock import Mock

from agent_factory.factory_api import status_of
from agent_factory.lifecycle_observer import FactoryLifecycleObserver


class HistorySummaryStatusTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.observer = FactoryLifecycleObserver(self.store, Mock(), Mock(), lambda: None)
        self.task = {'id': 'root', 'owner_id': 'alice', 'admission': 'accepted',
                     'run_id': 'run', 'cancel_requested': False}

    def test_native_status_and_unknown_effect_matrix_matches_detail(self):
        requirements = [{'tool_execution': {'requires_user_input': True}}]
        for raw in ('queued', 'running', 'paused', 'completed', 'failed', 'cancelled'):
            for uncertain in (False, True):
                for cancelled in (False, True):
                    with self.subTest(raw=raw, uncertain=uncertain, cancelled=cancelled):
                        task = {**self.task, 'cancel_requested': cancelled}
                        snapshot = {'queue': {'status': raw}, 'requirements': requirements}
                        effects = [{'status': 'UNKNOWN'}] if uncertain else []
                        expected = status_of(task, snapshot, effects, [])
                        ticket = {'status': raw, 'requirements': requirements}
                        self.assertEqual(self.observer._display_status(task, ticket, uncertain), expected)

    def test_running_unknown_effect_remains_running_without_releasing_capacity(self):
        self.store.task.return_value = self.task
        self.observer._group = Mock(return_value=([self.task], []))
        self.observer._observe_summaries(self.task, {'root': {
            'groupStopped': False, 'unknown': True, 'displayStatus': 'running'}})
        self.store.observe_summary.assert_called_once_with(self.task, 'running')
        self.store.observed.assert_not_called()

    def test_new_child_between_observation_and_projection_waits_for_next_tick(self):
        child = {**self.task, 'id': 'new-child'}
        self.store.task.return_value = self.task
        self.observer._group = Mock(return_value=([self.task, child], [
            {'parent_id': 'root', 'child_id': 'new-child'}]))
        self.observer._observe_summaries(self.task, {'root': {
            'groupStopped': False, 'unknown': False, 'displayStatus': 'completed'}})
        self.store.observe_summary.assert_called_once_with(self.task, 'unknown')
        self.store.observed.assert_not_called()
