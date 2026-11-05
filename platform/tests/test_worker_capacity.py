"""Operator capacity is passed to native admission without a second ceiling."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.job_queue import QueueConfig

from agent_factory.config import Settings
from agent_factory.scheduling import SchedulingService


class WorkerCapacityTests(unittest.TestCase):
    def settings(self, **changes):
        return Settings(db_url='postgresql://unused/unused', jwt_key='synthetic-capacity-key-' * 2, **changes)

    def test_default_and_operator_selected_positive_integer(self):
        self.assertEqual(self.settings().max_workers, 2)
        for workers in (1, 8, 32):
            self.assertEqual(self.settings(max_workers=workers).max_workers, workers)
        for workers in (0, -1, True, False, 1.5, '8', None):
            with self.subTest(workers=workers), self.assertRaisesRegex(ValueError, 'positive integer'):
                self.settings(max_workers=workers)

    def test_environment_capacity_reaches_native_queue_and_schedule_poller(self):
        with patch.dict(os.environ, {'FACTORY_DATABASE_URL': 'postgresql://unused/unused',
                'FACTORY_JWT_KEY': 'synthetic-capacity-key-' * 2, 'FACTORY_MAX_WORKERS': '8'}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(QueueConfig(durable=True, max_concurrency=settings.max_workers).max_concurrency, 8)
        store = SimpleNamespace(engine=SimpleNamespace(url=settings.db_url))
        with patch('agent_factory.scheduling.create_engine'):
            service = SchedulingService(settings, store, object(), object(), object())
        self.assertEqual(service.poller.max_concurrent, 8)


if __name__ == '__main__':
    unittest.main()
