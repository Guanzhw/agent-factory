"""Opt-in unittest timings; acceptance remains owned by check_postgres.

Phase and fixture durations are inclusive and overlap: never sum them together.
Only names/IDs/timings are logged, never fixture arguments or returned values.
"""
import argparse
from contextlib import ExitStack
import functools
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

import check_postgres
from check_python import CollectionError, configure_imports


# Deliberately bounded to owned DB and real HTTP/process lifecycle boundaries.
# Modules must already have been imported by ordinary discovery.
FIXTURES = (
    ('pg_fixture', 'IsolatedPostgres', '__enter__'),
    ('pg_fixture', 'IsolatedPostgres', '__exit__'),
    ('test_governed_remote_process_postgres', 'OwnedServer', 'start'),
    ('test_governed_remote_process_postgres', 'OwnedServer', 'stop'),
    ('test_remote_process_runtime_postgres', 'ProcessRuntimeServer', 'start'),
    ('test_remote_process_runtime_postgres', 'RemoteProcessRuntimePair', 'start'),
    ('test_remote_process_runtime_postgres', 'RemoteProcessRuntimePair', 'close'),
)


class Profiler:
    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()
        self.active = None
        self.stack = ExitStack()
        self.result_types = []
        self.suite_frames = []

    def emit(self, kind, **values):
        with self.lock:
            self.stream.write(json.dumps({'kind': kind, **values}, sort_keys=True) + '\n')
            self.stream.flush()

    def result_class(self, base=check_postgres.AcceptanceResult):
        observer = self

        class ProfileResult(base):
            def startTest(self, test):
                super().startTest(test)
                observer.active = {'test': test, 'start': time.perf_counter(),
                    'phases': {}, 'depth': {}, 'outcome': 'unknown'}

            def stopTest(self, test):
                state = observer.active
                try:
                    if state is not None and state['test'] is test:
                        observer.emit('case', id=test.id(), seconds=time.perf_counter() - state['start'],
                            phases=state['phases'], outcome=state['outcome'])
                finally:
                    observer.active = None
                    super().stopTest(test)

            def addSubTest(self, test, subtest, err):
                if err is not None:
                    observer.outcome(test, 'failed' if issubclass(err[0], test.failureException) else 'error')
                super().addSubTest(test, subtest, err)

        for method, outcome in (
            ('addSuccess', 'passed'), ('addFailure', 'failed'), ('addError', 'error'),
            ('addSkip', 'skipped'), ('addExpectedFailure', 'expected-failure'),
            ('addUnexpectedSuccess', 'unexpected-success'),
        ):
            original = getattr(ProfileResult, method)

            def decorate(original, outcome):
                @functools.wraps(original)
                def call(result, test, *args, **kwargs):
                    self.outcome(test, outcome)
                    return original(result, test, *args, **kwargs)
                return call

            setattr(ProfileResult, method, decorate(original, outcome))
        self.result_types.append(ProfileResult)
        return ProfileResult

    def outcome(self, test, value):
        state = self.active
        # unittest reports skipped subtests via addSkip without addSuccess for
        # their parent. Preserve failure when another subtest skips or cleanup fails.
        parent = getattr(test, 'test_case', test)
        if state is not None and state['test'] is parent:
            priority = {'unknown': 0, 'passed': 1, 'skipped': 2, 'expected-failure': 2,
                'unexpected-success': 3, 'failed': 4, 'error': 5}
            if priority[value] > priority[state['outcome']]:
                state['outcome'] = value

    def phase_wrapper(self, original, phase):
        @functools.wraps(original)
        def call(test, *args, **kwargs):
            state = self.active
            if state is None or state['test'] is not test:
                return original(test, *args, **kwargs)
            depth = state['depth'].get(phase, 0)
            state['depth'][phase] = depth + 1
            started = time.perf_counter()
            try:
                return original(test, *args, **kwargs)
            finally:
                state['depth'][phase] -= 1
                if depth == 0:
                    state['phases'][phase] = state['phases'].get(phase, 0) + time.perf_counter() - started
        return call

    def fixture_wrapper(self, original, label):
        @functools.wraps(original)
        def call(*args, **kwargs):
            state = self.active
            owner = state['test'].id() if state is not None else None
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.emit('fixture', fixture=label, case=owner, seconds=time.perf_counter() - started)
        return call

    def suite_wrapper(self, original, phase):
        @functools.wraps(original)
        def call(suite, *args):
            result = args[-1]
            if not isinstance(result, tuple(self.result_types)):
                return original(suite, *args)
            previous = getattr(result, '_previousTestClass', None)
            current = type(args[0]) if len(args) == 2 and args[0] is not None else None
            if phase == 'class_setup':
                target = current
                changed = current is not previous
            elif phase == 'class_teardown':
                target = previous
                changed = previous is not None and previous is not current
            else:
                previous_module = getattr(previous, '__module__', None)
                current_module = getattr(current, '__module__', None)
                target = current_module if phase == 'module_setup' else previous_module
                changed = (current_module != previous_module if phase == 'module_setup'
                    else previous_module is not None)
            if not changed or target is None:
                return original(suite, *args)
            label = target if isinstance(target, str) else target.__module__ + '.' + target.__qualname__
            frame = {'nested': 0.0}
            self.suite_frames.append(frame)
            started = time.perf_counter()
            try:
                return original(suite, *args)
            finally:
                elapsed = time.perf_counter() - started
                self.suite_frames.pop()
                if self.suite_frames:
                    self.suite_frames[-1]['nested'] += elapsed
                # Module transition invokes previous-module teardown internally.
                # Remove that separately recorded hook from module setup time.
                self.emit('suite_fixture', phase=phase, fixture=label,
                    seconds=max(0.0, elapsed - frame['nested']))
        return call

    def __enter__(self):
        try:
            for cls in (unittest.TestCase, unittest.IsolatedAsyncioTestCase):
                for name, phase in (('_callSetUp', 'setup'), ('_callTestMethod', 'test'),
                    ('_callTearDown', 'teardown'), ('doCleanups', 'cleanup')):
                    if name in cls.__dict__:
                        self.stack.enter_context(patch.object(cls, name,
                            self.phase_wrapper(getattr(cls, name), phase)))
            for name, phase in (('_handleClassSetUp', 'class_setup'),
                ('_tearDownPreviousClass', 'class_teardown'),
                ('_handleModuleFixture', 'module_setup'),
                ('_handleModuleTearDown', 'module_teardown')):
                self.stack.enter_context(patch.object(unittest.TestSuite, name,
                    self.suite_wrapper(getattr(unittest.TestSuite, name), phase)))
            for module, name, method in FIXTURES:
                cls = getattr(sys.modules.get(module), name, None)
                if cls is not None and method in cls.__dict__:
                    label = f'{module}.{name}.{method}'
                    self.stack.enter_context(patch.object(cls, method,
                        self.fixture_wrapper(getattr(cls, method), label)))
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *exc):
        self.active = None
        return self.stack.__exit__(*exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--group', action='append', choices=tuple(check_postgres.REQUIRED_TESTS))
    args = parser.parse_args(argv)
    if not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('POSTGRES_REQUIRED: set FACTORY_TEST_DATABASE_URL to a disposable database', file=sys.stderr)
        return 1
    if sys.platform != 'linux' and (not args.group or 'research_candidate_postgres' in args.group):
        print('POSTGRES_REQUIRED: full/candidate acceptance requires Linux', file=sys.stderr)
        return 1
    configure_imports()
    requirements = ({group: check_postgres.REQUIRED_TESTS[group] for group in args.group}
        if args.group else check_postgres.REQUIRED_TESTS)
    started = time.perf_counter()
    try:
        discovered, required = check_postgres.collect(None, requirements)
    except CollectionError as error:
        print(f'POSTGRES_COLLECTION_FAILED: {error}', file=sys.stderr)
        return 1
    collection_seconds = time.perf_counter() - started
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'timings.jsonl').open('w', encoding='utf-8') as stream, Profiler(stream) as profiler:
        started = time.perf_counter()
        result, summary = check_postgres.run_checks(discovered, required,
            subset=bool(args.group), resultclass=profiler.result_class())
        summary = {**summary, 'wallSeconds': time.perf_counter() - started,
            'collectionSeconds': collection_seconds, 'profileObserver': 'owned-fixtures-v1',
            'timingsInclusive': True, 'successfulIds': sorted(result.successful_ids)}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary))
    return 0 if summary['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
