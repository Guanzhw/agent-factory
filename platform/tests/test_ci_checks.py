"""Daily selections cannot turn into full runs or accept empty/skipped coverage."""
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch
from uuid import uuid4

with patch.object(sys, 'path', [str(Path(__file__).resolve().parents[2] / 'scripts'), *sys.path]):
    import check_fast
    from check_postgres import run_checks


class FastCheckTests(unittest.TestCase):
    def fixture(self, python_body="calls.append('python')", *, python_decorator=''):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        restore = patch.object(sys, 'path', list(sys.path))
        restore.start(); self.addCleanup(restore.stop)
        module = 'test_fast_fixture_' + uuid4().hex
        self.addCleanup(sys.modules.pop, module, None)
        directory = Path(folder.name)
        source = f'''
            import unittest
            calls = []
            class PythonCase(unittest.TestCase):
                {python_decorator}
                def test_daily(self): {python_body}
            class PostgresCase(unittest.TestCase):
                def test_persistent(self): calls.append('postgres')
            class ManualCase(unittest.TestCase):
                def test_large_tree(self): calls.append('manual')
                def test_new_unlisted_behavior(self): calls.append('new')
        '''
        (directory / (module + '.py')).write_text(textwrap.dedent(source))
        selections = {'python': {'core': (module + '.PythonCase',)},
            'postgres': {'persistent': (module + '.PostgresCase',)}}
        return directory, module, selections

    def test_fast_executes_only_its_explicit_lane_and_full_keeps_every_case(self):
        directory, module, selections = self.fixture()
        for lane in ('python', 'postgres'):
            discovered, groups, coverage = check_fast.inventory(directory, selections)
            result, summary = check_fast.execute(lane, discovered, groups[lane], coverage, stream=io.StringIO())
            self.assertTrue(summary['accepted'], result.errors)
            self.assertFalse(summary['fullAcceptance'])
            self.assertEqual(result.testsRun, 1)
            self.assertEqual(sys.modules[module].calls[-1], lane)
            self.assertEqual(len(coverage['manualOnly']), 2)
        self.assertEqual(sys.modules[module].calls, ['python', 'postgres'])
        discovered, groups, coverage = check_fast.inventory(directory, selections)
        _, summary = run_checks(discovered, {**groups['python'], **groups['postgres']}, stream=io.StringIO())
        self.assertTrue(summary['accepted'])
        self.assertEqual(summary['testsRun'], len(coverage['full']))
        self.assertCountEqual(sys.modules[module].calls[2:], ['python', 'postgres', 'manual', 'new'])

    def test_empty_missing_and_overlapping_selections_fail(self):
        directory, module, selections = self.fixture()
        invalid = [
            {'python': {}, 'postgres': selections['postgres']},
            {'python': {'core': ()}, 'postgres': selections['postgres']},
            {'python': {'core': (module + '.Missing',)}, 'postgres': selections['postgres']},
            {'python': selections['python'], 'postgres': {'duplicate': (module + '.PythonCase',)}},
        ]
        for selection in invalid:
            with self.subTest(selection=selection), self.assertRaises(check_fast.CollectionError):
                check_fast.inventory(directory, selection)

    def test_selected_skip_and_expected_failure_cannot_satisfy_fast_acceptance(self):
        for body, decorator in (("self.skipTest('missing prerequisite')", ''),
                                ("self.fail('expected')", '@unittest.expectedFailure')):
            directory, _, selections = self.fixture(body, python_decorator=decorator)
            discovered, groups, coverage = check_fast.inventory(directory, selections)
            _, summary = check_fast.execute('python', discovered, groups['python'], coverage, stream=io.StringIO())
            self.assertFalse(summary['accepted'])
            self.assertTrue(summary['groups']['core']['notPassed'])

    def test_postgres_execution_cannot_succeed_without_a_database(self):
        with patch.dict('os.environ', {}, clear=True), patch('sys.stderr', io.StringIO()):
            self.assertEqual(check_fast.main(['--suite', 'postgres']), 1)

    def test_collect_only_does_not_report_execution_or_acceptance(self):
        directory, _, selections = self.fixture("self.fail('must not run')")
        discovered, groups, coverage = check_fast.inventory(directory, selections)
        output = io.StringIO()
        with patch.object(check_fast, 'configure_imports'), \
                patch.object(check_fast, 'inventory', return_value=(discovered, groups, coverage)), \
                patch('sys.stdout', output):
            self.assertEqual(check_fast.main(['--suite', 'python', '--collect-only']), 0)
        self.assertIn('"executed": false', output.getvalue())
        self.assertNotIn('"accepted"', output.getvalue())


if __name__ == '__main__':
    unittest.main()
