"""Bounded observation bookkeeping; synthetic identities and inert fixture only."""
import os
import unittest
from unittest.mock import patch

from agent_factory import research_environment_observer as module
from agent_factory.research_interpreter import COMPLETE_PROFILE, inventory_bounds
import test_research_package_paths as journey  # pyright: ignore[reportMissingImports]


class ObservationBoundsTests(unittest.TestCase):
    def test_complete_24204_unique_files_and_duplicate_reads_remain_all_present(self):
        maximum = inventory_bounds(COMPLETE_PROFILE)[3] + 16
        observations = module._Observations(maximum)
        expected = []
        for index in range(24204):
            item = (f'/synthetic/site/file-{index}', False, (index, 17, 23))
            observations.append(item); observations.append(item)
            expected.append(item)
        self.assertEqual(len(observations), 24204)
        self.assertEqual(list(observations), expected)

    def test_same_path_drift_or_file_directory_change_rejected_not_overwritten(self):
        for changed in (('/synthetic/file', False, (1, 3)), ('/synthetic/file', True, (1, 2))):
            with self.subTest(directory=changed[1]):
                observations = module._Observations(2)
                original = ('/synthetic/file', False, (1, 2))
                observations.append(original)
                with self.assertRaises(ValueError): observations.append(changed)
                self.assertEqual(list(observations), [original])

    def test_exact_cap_accepts_duplicate_but_rejects_additional_unique_entry(self):
        observations = module._Observations(16384)
        for index in range(16384): observations.append((str(index), False, (index,)))
        observations.append(('0', False, (0,)))
        with self.assertRaises(ValueError): observations.append(('overflow', False, (0,)))
        self.assertEqual(len(observations), 16384)


@unittest.skipUnless(os.name == 'posix', 'Inert descriptor fixture requires POSIX')
class ObserverDedupJourneyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = journey.CompletePackagePathJourneyTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def test_complete_profile_repeated_reads_verify_original_closure(self):
        _, observer, request = self.fixture.complete()
        self.assertEqual(observer._max_observations, 65536 + 16)
        original_read = module._read
        def repeated_read(path, pin, **kwargs):
            result = original_read(path, pin, **kwargs)
            observations = kwargs.get('observations')
            if observations is not None:
                last = list(observations)[-1]
                for _ in range(17000): observations.append(last)
            return result
        with patch.object(module, '_read', side_effect=repeated_read):
            self.assertEqual(observer(request)['status'], 'VERIFIED')
        self.fixture.case.write(self.fixture.case.site / journey.ORDINARY[0], b'changed after capture')
        self.assertEqual(observer(request)['status'], 'UNKNOWN')

    def test_unique_observations_still_all_reopened_at_final_fence(self):
        _, observer, request = self.fixture.complete()
        original_open = module._open
        opened = []
        def observe_open(path, **kwargs):
            opened.append(str(path))
            return original_open(path, **kwargs)
        with patch.object(module, '_open', side_effect=observe_open):
            self.assertEqual(observer(request)['status'], 'VERIFIED')
        for name in journey.ORDINARY:
            self.assertGreaterEqual(opened.count(str(self.fixture.case.site / name)), 2)
