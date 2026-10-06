"""Declared aggregate budgets are admitted before process or GPU dispatch."""
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from agent_factory.process_runtime import process_reservation


class ProcessReservationTests(unittest.TestCase):
    def provider(self, aggregate=None):
        return SimpleNamespace(limits=SimpleNamespace(address_space_mb=128,
            file_size_bytes=1048577, wall_seconds=1.1), aggregate_config=aggregate)

    def test_ordinary_budget_shape_is_unchanged(self):
        self.assertEqual(process_reservation(self.provider()),
            {'cpu': 1, 'memoryMb': 128, 'diskMb': 2, 'seconds': 2})

    def test_aggregate_cpu_and_memory_plus_swap_round_up_exactly(self):
        aggregate = SimpleNamespace(cpu_quota_us=200001, cpu_period_us=100000,
            memory_bytes=128 * 1024**2, swap_bytes=1024**2 + 1)
        self.assertEqual(process_reservation(self.provider(aggregate)),
            {'cpu': 3, 'memoryMb': 130, 'diskMb': 2, 'seconds': 2})

    def test_aggregate_never_reduces_single_process_floor(self):
        aggregate = SimpleNamespace(cpu_quota_us=50000, cpu_period_us=100000,
            memory_bytes=1024**2, swap_bytes=0)
        self.assertEqual(process_reservation(self.provider(aggregate)), process_reservation(self.provider()))

    def test_malformed_declared_budget_is_rejected(self):
        for field, value in (('cpu_quota_us', True), ('cpu_period_us', 0),
                             ('memory_bytes', 1.5), ('swap_bytes', -1)):
            with self.subTest(field=field):
                aggregate = SimpleNamespace(cpu_quota_us=100000, cpu_period_us=100000,
                    memory_bytes=128 * 1024**2, swap_bytes=0)
                setattr(aggregate, field, value)
                with self.assertRaises(HTTPException):
                    process_reservation(self.provider(aggregate))
        for field, value in (('address_space_mb', True), ('file_size_bytes', 0),
                             ('wall_seconds', float('nan')), ('wall_seconds', float('inf'))):
            with self.subTest(field=field, value=value):
                provider = self.provider()
                setattr(provider.limits, field, value)
                with self.assertRaises(HTTPException):
                    process_reservation(provider)
