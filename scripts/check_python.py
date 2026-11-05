"""Discover the standalone core test tree for ordinary and PostgreSQL checks."""
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('platform', 'deployment', 'applications', 'platform/tests')
TEST_DIRECTORIES = (ROOT / 'platform/tests', ROOT / 'applications/tests')


class CollectionError(ValueError):
    pass


def cases(suite):
    """Keep discovery order and unittest's inherited method identities."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def configure_imports():
    """Give this process and fixture subprocesses the same application roots."""
    roots = [str(ROOT / path) for path in SOURCES]
    sys.path[:] = [*roots, *(path for path in sys.path if path not in roots)]
    inherited = os.environ.get('PYTHONPATH', '').split(os.pathsep)
    os.environ['PYTHONPATH'] = os.pathsep.join(dict.fromkeys([*roots, *(path for path in inherited if path)]))


def discover_tests(test_directories=None, *, loader=None):
    """Collect unique full IDs, rejecting ambiguous imports before execution."""
    if test_directories is None:
        test_directories = TEST_DIRECTORIES
    elif isinstance(test_directories, (str, Path)):
        test_directories = (test_directories,)
    directories = list(dict.fromkeys(Path(path).resolve() for path in test_directories))
    if not directories:
        raise CollectionError('No test directories configured')
    modules = {}
    for directory in directories:
        if not directory.is_dir():
            raise CollectionError(f'Test directory does not exist: {directory}')
        for source in sorted(directory.rglob('*.py')):
            parts = source.relative_to(directory).with_suffix('').parts
            if '__pycache__' in parts or not all(part.isidentifier() for part in parts):
                continue
            if parts[-1] == '__init__':
                parts = parts[:-1]
            if not parts:
                continue
            module = '.'.join(parts)
            previous = modules.get(module)
            if previous is not None and previous != source:
                raise CollectionError(f'Ambiguous test/fixture module {module}: {previous} and {source}; '
                    'give the modules distinct import names')
            modules[module] = source
    roots = [str(path) for path in directories]
    sys.path[:] = [*roots, *(path for path in sys.path if path not in roots)]
    loader = loader or unittest.TestLoader()
    discovered = {}
    errors = []
    for directory in directories:
        try:
            suite = loader.discover(str(directory), top_level_dir=str(directory))
        except (ImportError, OSError) as error:
            errors.append(f'{directory}: {error}')
            continue
        for case in cases(suite):
            identity = case.id()
            if identity in discovered:
                errors.append(f'Duplicate test ID {identity}; use distinct test identities instead of discarding cases')
            else:
                discovered[identity] = case
    if loader.errors or errors:
        raise CollectionError('\n'.join([*loader.errors, *errors]))
    return discovered


def report_test_failures(result):
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        for case, traceback in [*result.failures, *result.errors]:
            message = f'{case.id()}\n{traceback}'
            message = message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print(f'::error::{message}')


def main():
    configure_imports()
    try:
        discovered = discover_tests()
    except CollectionError as error:
        print(f'PYTHON_COLLECTION_FAILED: {error}', file=sys.stderr)
        return 1
    suite = unittest.TestSuite(discovered.values())
    discovered.clear()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report_test_failures(result)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
