"""Synthetic unittest fixtures for required coverage; no database or provider IO."""
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from uuid import uuid4


SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    SPEC = importlib.util.spec_from_file_location('factory_postgres_checks', SCRIPTS / 'check_postgres.py')
    assert SPEC and SPEC.loader
    checks = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(checks)


class PostgresCheckTests(unittest.TestCase):
    def fixture(self, source, groups=None, *, extra_files=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        directory = Path(folder.name)
        module = 'test_pg_fixture_' + uuid4().hex
        (directory / (module + '.py')).write_text('import unittest\n' + textwrap.dedent(source))
        for name, content in (extra_files or {}).items():
            (directory / name).write_text(content)
        self.addCleanup(sys.modules.pop, module, None)
        requirements = {group: tuple(module + '.' + selector for selector in selectors)
            for group, selectors in (groups or {'critical': ('Case',)}).items()}
        with patch.object(sys, 'path', [str(directory), *sys.path]):
            discovered, required = checks.collect(directory, requirements)
        return module, discovered, required

    def run_fixture(self, source, groups=None, *, subset=False):
        module, discovered, required = self.fixture(source, groups)
        result, summary = checks.run_checks(discovered, required, subset=subset, stream=io.StringIO())
        return module, result, summary

    def test_new_cases_and_overlapping_groups_run_once_without_fixed_counts(self):
        module, result, summary = self.run_fixture('''
            calls = []
            class Case(unittest.TestCase):
                def test_original(self): calls.append('original')
                def test_added(self): calls.append('added')
            class Optional(unittest.TestCase):
                def test_other(self): calls.append('other')
        ''', {'first': ('Case',), 'second': ('Case.test_original',)})
        self.assertTrue(summary['accepted'])
        self.assertEqual(result.testsRun, 3)
        self.assertEqual(sys.modules[module].calls, ['added', 'original', 'other'])
        self.assertEqual(summary['groups']['first']['requiredCases'], 2)
        self.assertEqual(summary['groups']['second']['requiredCases'], 1)

    def test_subset_uses_discovered_instances_and_inherited_test_ids(self):
        module, result, summary = self.run_fixture('''
            calls = []
            class Base(unittest.TestCase):
                def test_inherited(self): calls.append(type(self).__name__)
            class Child(Base): pass
            class Optional(unittest.TestCase):
                def test_other(self): raise AssertionError('not selected')
        ''', {'critical': ('Child',)}, subset=True)
        self.assertTrue(summary['accepted'])
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.successful_ids, {module + '.Child.test_inherited'})
        self.assertEqual(sys.modules[module].calls, ['Child'])

    def test_completed_case_can_be_collected_before_the_next_case_runs(self):
        _, discovered, required = self.fixture('''
            import gc
            import weakref
            completed = []
            class Case(unittest.TestCase):
                def test_1_finish(self):
                    self.application_state = bytearray(1024 * 1024)
                    self.cycle = self
                    completed.append(weakref.ref(self))
                def test_2_collect_previous(self):
                    gc.collect()
                    self.assertIsNone(completed[0](), 'Runner retained a completed test instance')
        ''')
        expected_ids = set(discovered)
        result, summary = checks.run_checks(discovered, required, stream=io.StringIO())
        self.assertTrue(summary['accepted'], result.failures)
        self.assertEqual(discovered, {})
        self.assertEqual(result.successful_ids, expected_ids)

    def test_missing_exact_test_empty_selector_and_import_error_fail_collection(self):
        for source, selector, files in [
            ('class Case(unittest.TestCase):\n    def test_other(self): pass\n', 'Case.test_required', None),
            ('class Case(unittest.TestCase): pass\n', 'Case', None),
            ('class Case(unittest.TestCase):\n    def test_required(self): pass\n', 'Case',
             {'test_broken_import.py': 'raise ImportError("synthetic missing dependency")\n'}),
        ]:
            with self.subTest(selector=selector, files=files), self.assertRaises(checks.CollectionError):
                self.fixture(source, {'critical': (selector,)}, extra_files=files)
        with self.assertRaisesRegex(checks.CollectionError, 'no required selectors'):
            self.fixture('class Case(unittest.TestCase): pass\n', {'critical': ()})
        with self.assertRaisesRegex(checks.CollectionError, 'No required groups'):
            checks.collect(Path('/unused'), {})

    def test_required_case_excluded_by_discovery_fails_collection(self):
        with self.assertRaisesRegex(checks.CollectionError, 'absent from discovery'):
            self.fixture('''
                class Case(unittest.TestCase):
                    def test_required(self): pass
                def load_tests(loader, standard, pattern):
                    return unittest.TestSuite()
            ''')

    def test_optional_platform_skip_is_allowed_but_required_skip_is_not(self):
        source = '''
            class Case(unittest.TestCase):
                def test_pass(self): pass
            @unittest.skip('synthetic other platform')
            class Optional(unittest.TestCase):
                def test_skip(self): pass
        '''
        _, result, summary = self.run_fixture(source)
        self.assertTrue(summary['accepted'])
        self.assertEqual(len(result.skipped), 1)
        module, _, summary = self.run_fixture(source, {'critical': ('Optional.test_skip',)})
        self.assertFalse(summary['accepted'])
        self.assertEqual(summary['groups']['critical']['notPassed'], [module + '.Optional.test_skip'])

    def test_class_module_and_subtest_skips_cannot_satisfy_required_success(self):
        sources = [
            '''
            class Case(unittest.TestCase):
                @classmethod
                def setUpClass(cls): raise unittest.SkipTest('synthetic class skip')
                def test_required(self): pass
            ''',
            '''
            def setUpModule(): raise unittest.SkipTest('synthetic module skip')
            class Case(unittest.TestCase):
                def test_required(self): pass
            ''',
            '''
            class Case(unittest.TestCase):
                def test_required(self):
                    with self.subTest(value=1): self.skipTest('synthetic subtest skip')
            ''',
        ]
        for source in sources:
            with self.subTest(source=source):
                module, result, summary = self.run_fixture(source)
                self.assertTrue(result.wasSuccessful())
                self.assertFalse(summary['accepted'])
                self.assertEqual(summary['groups']['critical']['notPassed'], [module + '.Case.test_required'])

    def test_required_expected_failure_is_not_a_pass(self):
        _, result, summary = self.run_fixture('''
            class Case(unittest.TestCase):
                @unittest.expectedFailure
                def test_required(self): self.fail('synthetic expected failure')
        ''')
        self.assertTrue(result.wasSuccessful())
        self.assertFalse(summary['accepted'])

    def test_any_test_failure_error_or_unexpected_success_blocks_acceptance(self):
        for body in ["self.fail('synthetic failure')", "raise RuntimeError('synthetic error')"]:
            with self.subTest(body=body):
                _, _, summary = self.run_fixture(f'''
                    class Case(unittest.TestCase):
                        def test_required(self): pass
                    class Optional(unittest.TestCase):
                        def test_other(self): {body}
                ''')
                self.assertFalse(summary['accepted'])
                self.assertEqual(summary['groups']['critical']['notPassed'], [])
        _, _, summary = self.run_fixture('''
            class Case(unittest.TestCase):
                def test_required(self): pass
            class Optional(unittest.TestCase):
                @unittest.expectedFailure
                def test_other(self): pass
        ''')
        self.assertFalse(summary['accepted'])

    def test_missing_database_stops_before_discovery(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(checks, 'collect') as collect, \
                patch('sys.stderr', io.StringIO()):
            self.assertEqual(checks.main([]), 1)
        collect.assert_not_called()
