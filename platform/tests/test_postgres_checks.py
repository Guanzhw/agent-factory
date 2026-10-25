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
    def fixture_trees(self, *trees):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        restore_path = patch.object(sys, 'path', list(sys.path))
        restore_path.start()
        self.addCleanup(restore_path.stop)
        directories = []
        for index, files in enumerate(trees):
            directory = Path(folder.name) / str(index)
            directory.mkdir()
            directories.append(directory)
            for name, source in files.items():
                (directory / (name + '.py')).write_text(textwrap.dedent(source))
                self.addCleanup(sys.modules.pop, name, None)
        return directories

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

    def test_two_trees_preserve_ids_requirements_and_cross_tree_fixture_imports(self):
        suffix = uuid4().hex
        core, app = 'test_core_' + suffix, 'test_app_' + suffix
        core_fixture, app_fixture = 'core_fixture_' + suffix, 'app_fixture_' + suffix
        directories = self.fixture_trees({
            core_fixture: "VALUE = 'core'\n",
            core: f'''
                import unittest
                from {app_fixture} import VALUE
                class Case(unittest.TestCase):
                    def test_cross_tree(self): self.assertEqual(VALUE, 'app')
            ''',
        }, {
            app_fixture: "VALUE = 'app'\n",
            app: f'''
                import unittest
                from {core_fixture} import VALUE
                class Case(unittest.TestCase):
                    def test_cross_tree(self): self.assertEqual(VALUE, 'core')
            ''',
        })
        expected = {name + '.Case.test_cross_tree' for name in (core, app)}
        ordinary = checks.discover_tests(directories)
        discovered, required = checks.collect(directories, {'critical': (core + '.Case', app + '.Case')})
        self.assertEqual(set(ordinary), expected)
        self.assertEqual(set(discovered), expected)
        self.assertEqual(required['critical'], expected)
        result, summary = checks.run_checks(discovered, required, stream=io.StringIO())
        self.assertTrue(summary['accepted'], result.errors)
        self.assertEqual(result.successful_ids, expected)

    def test_ordinary_entrypoint_keeps_all_import_roots_for_fixture_subprocesses(self):
        discovery = sys.modules[checks.discover_tests.__module__]
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        suffix = uuid4().hex
        imports = []
        for index, relative in enumerate(discovery.SOURCES):
            directory = root / relative
            directory.mkdir(parents=True, exist_ok=True)
            module = f'fixture_root_{index}_{suffix}'
            (directory / (module + '.py')).write_text('VALUE = True\n')
            imports.append(module)
        command = '; '.join('import ' + name for name in imports)
        trees = [root / 'platform/tests']
        modules = []
        for index, directory in enumerate(trees):
            module = f'test_entrypoint_{index}_{suffix}'
            modules.append(module)
            self.addCleanup(sys.modules.pop, module, None)
            (directory / (module + '.py')).write_text(textwrap.dedent(f'''
                import subprocess
                import sys
                import unittest
                calls = []
                class Case(unittest.TestCase):
                    def test_subprocess_imports(self):
                        subprocess.run([sys.executable, '-c', {command!r}], check=True, capture_output=True)
                        calls.append('ran')
            '''))
        with patch.object(discovery, 'ROOT', root), patch.object(discovery, 'TEST_DIRECTORIES', trees), \
                patch.object(sys, 'path', list(sys.path)), patch.dict('os.environ', {'PYTHONPATH': ''}), \
                patch('sys.stderr', io.StringIO()):
            self.assertEqual(discovery.main(), 0)
        for module in modules:
            self.assertEqual(sys.modules[module].calls, ['ran'])

    def test_loader_errors_from_both_trees_are_reported(self):
        suffix = uuid4().hex
        directories = self.fixture_trees(
            {'test_core_' + suffix: "raise ImportError('missing core fixture')\n"},
            {'test_app_' + suffix: "raise ImportError('missing app fixture')\n"},
        )
        with self.assertRaises(checks.CollectionError) as raised:
            checks.discover_tests(directories)
        self.assertIn('missing core fixture', str(raised.exception))
        self.assertIn('missing app fixture', str(raised.exception))

    def test_ambiguous_test_and_fixture_module_names_fail_before_import(self):
        for prefix in ('test_duplicate_', 'shared_fixture_'):
            with self.subTest(prefix=prefix):
                module = prefix + uuid4().hex
                directories = self.fixture_trees(
                    {module: "raise AssertionError('must not be imported')\n"},
                    {module: "raise AssertionError('must not be imported')\n"},
                )
                with self.assertRaisesRegex(checks.CollectionError, 'Ambiguous test/fixture module') as raised:
                    checks.discover_tests(directories)
                for directory in directories:
                    self.assertIn(str(directory.resolve()), str(raised.exception))
                self.assertNotIn(module, sys.modules)

    def test_duplicate_full_ids_are_rejected_instead_of_dropping_distinct_cases(self):
        with self.assertRaisesRegex(checks.CollectionError, 'Duplicate test ID'):
            self.fixture('''
                class Case(unittest.TestCase):
                    def id(self): return 'same.identity'
                    def test_first(self): pass
                    def test_second(self): pass
            ''')

    def test_missing_test_tree_cannot_silently_reduce_coverage(self):
        directories = self.fixture_trees({})
        with self.assertRaisesRegex(checks.CollectionError, 'does not exist'):
            checks.discover_tests([*directories, directories[0] / 'missing'])
        with self.assertRaisesRegex(checks.CollectionError, 'No test directories'):
            checks.discover_tests([])

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
