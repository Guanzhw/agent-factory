"""One six-case cross-module observation; original bodies/deadlines unchanged.

Coordinator-only experiment, not executed by its author. Run externally bounded
(e.g. timeout --kill-after=5s 180s); exit 124 is inconclusive, never a pass.
Requires --with-pg-predecessor and an existing disposable DB environment.
No retry loop. Derived from the preserved suite-review diagnostic.

Run from the cloud-main checkout with its normal Python environment. No DB,
provider, credential or payload values are logged. Never auto-retry a case.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd() / 'scripts'))
import check_python
check_python.configure_imports()
import test_personal_orx_projects as cases

__unittest = True
START = time.monotonic()
OUTPUT_LOCK = threading.Lock()
FUTURES = []


def emit(event, **fields):
    with OUTPUT_LOCK:
        print(json.dumps({'event': event, 'elapsedSeconds': time.monotonic() - START,
                          **fields}, sort_keys=True), flush=True)


def snapshot():
    """Bounded, non-atomic, read-only observation; no locals or exception text."""
    try:
        futures = [{'index': index, 'done': future.done(), 'running': future.running(),
                    'cancelled': future.cancelled()} for index, future in enumerate(FUTURES[:4])]
        frames = sys._current_frames()
        threads = []
        for identifier, frame in sorted(frames.items())[:32]:
            labels = []
            for _ in range(16):
                if frame is None:
                    break
                labels.append({'file': Path(frame.f_code.co_filename).name,
                               'function': frame.f_code.co_name, 'line': frame.f_lineno})
                frame = frame.f_back
            threads.append({'threadId': identifier, 'frames': labels, 'truncated': frame is not None})
        emit('gate_failure_snapshot', futures=futures, threads=threads,
             threadsTruncated=len(frames) > 32, nonAtomic=True)
    except Exception as error:
        emit('diagnostic_error', exceptionType=type(error).__name__)


class ObservedEvent:
    def __init__(self, label):
        self.label = label
        self.event = threading.Event()

    def set(self):
        emit('event_set', gate=self.label)
        return self.event.set()

    def wait(self, timeout=None):
        started = time.monotonic()
        emit('wait_enter', gate=self.label, timeoutSeconds=timeout)
        value = self.event.wait(timeout)
        emit('wait_return', gate=self.label, signaled=value,
             seconds=time.monotonic() - started)
        if self.label == 'entered' and not value:
            snapshot()
        return value

    def is_set(self):
        return self.event.is_set()


class ObservedPool(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        emit('future_submit')
        def execute():
            emit('worker_enter', threadId=threading.get_ident())
            try:
                return fn(*args, **kwargs)
            finally:
                emit('worker_exit', threadId=threading.get_ident())
        future = super().submit(execute)
        FUTURES.append(future)
        def completed(done):
            if done.cancelled():
                emit('future_completion', outcome='cancelled')
                return
            error = done.exception()
            if error is not None:
                emit('future_completion', outcome='exception', exceptionType=type(error).__name__)
            else:
                value = done.result()
                state = value.get('state') if isinstance(value, dict) else None
                emit('future_completion', outcome='returned',
                     state=state if state in {'acknowledged', 'ack_unknown'} else 'other')
        future.add_done_callback(completed)
        return future

    def __exit__(self, *args):
        emit('pool_exit_enter', futures=[{'done': f.done(), 'running': f.running()} for f in FUTURES[:4]])
        try:
            return super().__exit__(*args)
        finally:
            emit('pool_exit_return')


class Result(unittest.TestResult):
    def stopTest(self, test):
        emit('case_stop_after_cleanup', case=test.id())
        super().stopTest(test)

    def startTest(self, test):
        emit('case_start', case=test.id())
        super().startTest(test)

    def addSuccess(self, test):
        emit('case_success', case=test.id())
        super().addSuccess(test)

    def addFailure(self, test, err):
        emit('case_failure', case=test.id(), exceptionType=err[0].__name__)
        super().addFailure(test, err)

    def addError(self, test, err):
        emit('case_error', case=test.id(), exceptionType=err[0].__name__)
        super().addError(test, err)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-pg-predecessor', action='store_true')
    args = parser.parse_args()
    if not args.with_pg_predecessor or not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        parser.error('Explicit --with-pg-predecessor and disposable FACTORY_TEST_DATABASE_URL required')
    import test_personal_orx_postgres as predecessor
    target = cases.ProjectTests('test_double_click_concurrent_reservation_dispatches_once')
    original_run = target.run
    def observed_run(result=None):
        with ExitStack() as patches:
            names = iter(('entered', 'release'))
            # Replace only the target test module reference; executor/event-loop
            # internals retain the real threading module and ordinary Events.
            proxy = SimpleNamespace(Event=lambda: ObservedEvent(next(names)))
            patches.enter_context(patch.object(cases, 'threading', proxy))
            patches.enter_context(patch.object(cases, 'ThreadPoolExecutor', ObservedPool))
            return original_run(result)
    target.run = observed_run
    suite = unittest.TestSuite([
        predecessor.PersonalOrxPostgresTests(
            'test_native_orx_attach_governed_multiturn_interrupt_and_unknown_restart'),
        cases.ProjectAPITests('test_owner_ingress_strict_decision_and_no_direct_dispatch'),
        cases.ProjectTests('test_cancel_and_changed_disclosure_never_dispatch'),
        cases.ProjectTests('test_clone_existing_empty_directory_discloses_actual_write_scope'),
        cases.ProjectTests('test_configuration_revision_and_secret_revocation_during_post_dns_prevent_send'),
        target,
    ])
    result = Result()
    suite.run(result)
    emit('summary', testsRun=result.testsRun, failures=len(result.failures), errors=len(result.errors),
         skipped=len(result.skipped), accepted=result.wasSuccessful() and not result.skipped,
         originalDeadlines=True, observerOverhead=True, modelLive=False)
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
