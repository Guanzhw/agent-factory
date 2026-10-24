"""Timing observation preserves nested runner and required-result semantics."""
import asyncio
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    import check_postgres
    import profile_tests


class ProfileTests(unittest.TestCase):
    def run_profile(self, case):
        log = io.StringIO()
        discovered = {case.id(): case}
        with profile_tests.Profiler(log) as profiler:
            result, summary = check_postgres.run_checks(discovered,
                {'critical': {case.id()}}, stream=io.StringIO(), resultclass=profiler.result_class())
        return result, summary, [json.loads(line) for line in log.getvalue().splitlines()]

    def test_nested_runner_keeps_outer_case_and_cleanup_ownership(self):
        events = []

        class Inner(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                events.append('inner class setup')

            @classmethod
            def tearDownClass(cls):
                events.append('inner class teardown')

            def runTest(self):
                events.append('inner')

        class Outer(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                events.append('outer class setup')

            @classmethod
            def tearDownClass(cls):
                events.append('outer class teardown')

            def setUp(self):
                self.addCleanup(events.append, 'cleanup')

            def runTest(self):
                inner = Inner()
                result, summary = check_postgres.run_checks({inner.id(): inner},
                    {'inner': {inner.id()}}, stream=io.StringIO())
                self.assertTrue(summary['accepted'])
                self.assertEqual(result.testsRun, 1)

            def tearDown(self):
                events.append('teardown')

        outer = Outer()
        result, summary, records = self.run_profile(outer)
        self.assertTrue(summary['accepted'])
        self.assertEqual(result.successful_ids, {outer.id()})
        self.assertEqual(events, ['outer class setup', 'inner class setup', 'inner',
            'inner class teardown', 'teardown', 'cleanup', 'outer class teardown'])
        cases = [record for record in records if record['kind'] == 'case']
        self.assertEqual([record['id'] for record in cases], [outer.id()])
        self.assertEqual(set(cases[0]['phases']), {'setup', 'test', 'teardown', 'cleanup'})
        self.assertEqual(cases[0]['outcome'], 'passed')
        fixtures = [record for record in records if record['kind'] == 'suite_fixture']
        class_fixtures = [record for record in fixtures if record['phase'].startswith('class_')]
        self.assertEqual([record['phase'] for record in class_fixtures], ['class_setup', 'class_teardown'])
        self.assertTrue(all(record['fixture'].endswith('.Outer') for record in class_fixtures))
        self.assertEqual([record['phase'] for record in fixtures if record['phase'].startswith('module_')],
            ['module_setup', 'module_teardown'])

    def test_failed_subtest_preserves_required_failure_and_profile_status(self):
        class Failing(unittest.TestCase):
            def runTest(self):
                with self.subTest(value=1):
                    self.fail('synthetic failure')
                with self.subTest(value=2):
                    self.skipTest('synthetic skip after failure')

        case = Failing()
        result, summary, records = self.run_profile(case)
        self.assertFalse(summary['accepted'])
        self.assertEqual(summary['groups']['critical']['notPassed'], [case.id()])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual([record['outcome'] for record in records if record['kind'] == 'case'], ['failed'])

    def test_wrappers_restore_when_body_raises(self):
        original = {(cls, name): getattr(cls, name)
            for cls in (unittest.TestCase, unittest.IsolatedAsyncioTestCase)
            for name in ('_callSetUp', '_callTestMethod', '_callTearDown', 'doCleanups')}
        result_class = check_postgres.AcceptanceResult
        suite_original = {name: getattr(unittest.TestSuite, name) for name in (
            '_handleClassSetUp', '_tearDownPreviousClass', '_handleModuleFixture', '_handleModuleTearDown')}
        with self.assertRaisesRegex(RuntimeError, 'synthetic interruption'):
            with profile_tests.Profiler(io.StringIO()):
                self.assertIsNot(unittest.TestCase._callSetUp, original[unittest.TestCase, '_callSetUp'])
                raise RuntimeError('synthetic interruption')
        for (cls, name), value in original.items():
            self.assertIs(getattr(cls, name), value)
        for name, value in suite_original.items():
            self.assertIs(getattr(unittest.TestSuite, name), value)
        self.assertIs(check_postgres.AcceptanceResult, result_class)

    def test_async_phases_include_awaited_cleanup_without_double_counting(self):
        events = []

        class AsyncCase(unittest.IsolatedAsyncioTestCase):
            async def asyncSetUp(self):
                events.append('setup')
                self.addAsyncCleanup(self.finish)

            async def runTest(self):
                await asyncio.sleep(0)
                events.append('test')

            async def asyncTearDown(self):
                events.append('teardown')

            async def finish(self):
                await asyncio.sleep(0)
                events.append('cleanup')

        result, summary, records = self.run_profile(AsyncCase())
        self.assertTrue(summary['accepted'])
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(events, ['setup', 'test', 'teardown', 'cleanup'])
        case = next(row for row in records if row['kind'] == 'case')
        self.assertEqual(set(case['phases']), {'setup', 'test', 'teardown', 'cleanup'})
        self.assertLessEqual(sum(case['phases'].values()), case['seconds'])

    def test_module_transition_separates_teardown_and_preserves_setup_failure(self):
        clock = [0.0]

        def advance(seconds, *, fail=False):
            def hook():
                clock[0] += seconds
                if fail:
                    raise RuntimeError('synthetic module setup failure')
            return hook

        first = ModuleType('profile_fixture_first')
        second = ModuleType('profile_fixture_second')
        first.setUpModule = advance(2)
        first.tearDownModule = advance(3)
        second.setUpModule = advance(5, fail=True)
        first_case = type('First', (unittest.TestCase,),
            {'__module__': first.__name__, 'runTest': lambda self: None})()
        second_case = type('Second', (unittest.TestCase,),
            {'__module__': second.__name__, 'runTest': lambda self: None})()
        original = unittest.TestSuite._handleModuleFixture
        stream = io.StringIO()
        with patch.dict(sys.modules, {first.__name__: first, second.__name__: second}):
            with patch.object(profile_tests, 'time', SimpleNamespace(perf_counter=lambda: clock[0])):
                with profile_tests.Profiler(stream) as profiler:
                    result, summary = check_postgres.run_checks(
                        {case.id(): case for case in (first_case, second_case)},
                        {'critical': {first_case.id(), second_case.id()}},
                        stream=io.StringIO(), resultclass=profiler.result_class())
        self.assertIs(unittest.TestSuite._handleModuleFixture, original)
        self.assertFalse(summary['accepted'])
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(summary['groups']['critical']['notPassed'], [second_case.id()])
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        durations = {(row['fixture'], row['phase']): row['seconds']
            for row in rows if row['kind'] == 'suite_fixture'}
        self.assertEqual(durations[first.__name__, 'module_setup'], 2)
        self.assertEqual(durations[first.__name__, 'module_teardown'], 3)
        self.assertEqual(durations[second.__name__, 'module_setup'], 5)
