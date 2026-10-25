"""Application assembly ordering and shared shutdown deadline, without a DB."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
import unittest

from agent_factory_server.application_composition import (
    ApplicationAssembly, application_lifespan, install_applications,
    release_applications, validate_applications)


class ApplicationCompositionTests(unittest.IsolatedAsyncioTestCase):
    def test_duplicate_owner_and_shared_claim_rejected_before_install(self):
        calls = []
        a = ApplicationAssembly('a', lambda state: calls.append('a'), shared_claims=('ssh.package',))
        b = ApplicationAssembly('b', lambda state: calls.append('b'), shared_claims=('ssh.package',))
        for apps in ((a, a), (a, b)):
            with self.assertRaises(ValueError):
                install_applications({}, validate_applications(apps))
        self.assertEqual(calls, [])

    def test_async_constructor_or_release_cannot_report_synchronous_success(self):
        async def callback(state):
            pass
        for application in (ApplicationAssembly('a', callback),
                            ApplicationAssembly('a', lambda state: None, shutdown=callback),
                            ApplicationAssembly('a', lambda state: None, abort=callback)):
            with self.assertRaisesRegex(ValueError, 'SYNC_CALLBACK_REQUIRED'):
                validate_applications((application,))

    def test_partial_install_aborts_all_started_owners_in_reverse(self):
        events, state = [], {'dependency': object()}
        dependency = state['dependency']
        def install_b(state):
            events.append('install-b')
            raise ValueError('original failure')
        def abort(name):
            def close(state):
                self.assertIs(state['dependency'], dependency)
                events.append(name)
                if name == 'abort-b':
                    raise RuntimeError('secondary cleanup error')
            return close
        apps = validate_applications((
            ApplicationAssembly('a', lambda state: events.append('install-a'), abort=abort('abort-a')),
            ApplicationAssembly('b', install_b, abort=abort('abort-b'))))
        with self.assertRaisesRegex(ValueError, 'original failure'):
            install_applications(state, apps)
        self.assertEqual(events, ['install-a', 'install-b', 'abort-b', 'abort-a'])

    async def test_all_owners_receive_one_deadline_and_release_after_contexts(self):
        events = []
        state = {'dependency': object()}
        app = SimpleNamespace(state=SimpleNamespace(factory=state))
        def owner(name):
            @asynccontextmanager
            async def lifespan(app):
                events.append(('start', name))
                try:
                    yield
                finally:
                    events.append(('close', name, app.state.factory['shutdown_deadline']))
                    await asyncio.sleep(0)
            return ApplicationAssembly(name, lambda state: None, lifespan,
                lambda state: events.append(('release', name)))
        apps = validate_applications((owner('a'), owner('b')))
        async with application_lifespan(apps)(app):
            # Core arms this once before any app context exits.
            state['shutdown_deadline'] = asyncio.get_running_loop().time() + 35
        release_applications(state, apps)
        deadline = state['shutdown_deadline']
        self.assertEqual(events, [('start', 'a'), ('start', 'b'),
            ('close', 'b', deadline), ('close', 'a', deadline), ('release', 'b'), ('release', 'a')])

    async def test_failed_second_lifespan_exits_first_without_releasing_graph(self):
        events = []
        @asynccontextmanager
        async def first(app):
            events.append('start-a')
            try:
                yield
            finally:
                events.append('close-a')
        @asynccontextmanager
        async def second(app):
            raise ValueError('startup failure')
            yield  # pragma: no cover
        apps = validate_applications((ApplicationAssembly('a', lambda state: None, first),
                                      ApplicationAssembly('b', lambda state: None, second)))
        app = SimpleNamespace(state=SimpleNamespace(factory={
            'begin_shutdown': lambda: events.append('guard-armed')}))
        with self.assertRaisesRegex(ValueError, 'startup failure'):
            async with application_lifespan(apps)(app):
                self.fail('startup did not fail')
        self.assertEqual(events, ['start-a', 'guard-armed', 'close-a'])


class StartupFailureProcessTests(unittest.TestCase):
    def test_partial_startup_blocking_cleanup_is_bounded_by_original_guard(self):
        probe = r"""
import asyncio, sys, threading, time
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from agent_factory_server import shutdown
from agent_factory_server.application_composition import ApplicationAssembly, application_lifespan
real_timer = threading.Timer
def accelerated(interval, function, args=None, kwargs=None):
    assert interval == 35
    print('ONE_ORIGINAL_GUARD', flush=True)
    return real_timer(.05, function, args=args, kwargs=kwargs)
shutdown.threading.Timer = accelerated
@asynccontextmanager
async def first(app):
    try:
        yield
    finally:
        assert app.state.factory['shutdown_deadline'] > 0
        print('PARTIAL_STARTUP_CLEANUP_BLOCKED', flush=True)
        time.sleep(10)
@asynccontextmanager
async def second(app):
    raise ValueError('second startup fails')
    yield
async def main():
    with ExitStack() as stack:
        state = {}
        def begin():
            if 'shutdown_deadline' not in state:
                state['shutdown_deadline'] = stack.enter_context(shutdown.shutdown_guard())
        state['begin_shutdown'] = begin
        app = SimpleNamespace(state=SimpleNamespace(factory=state))
        apps = (ApplicationAssembly('a', lambda state: None, first), ApplicationAssembly('b', lambda state: None, second))
        async with application_lifespan(apps)(app):
            raise AssertionError('unreachable')
asyncio.run(main())
"""
        project = Path(__file__).resolve().parents[4]
        environment = {key: os.environ[key] for key in
            ('SystemRoot', 'WINDIR', 'PATH', 'LANG', 'LC_ALL', 'TEMP', 'TMP', 'TMPDIR') if key in os.environ}
        process = subprocess.Popen([sys.executable, '-I', '-c', probe, str(project / 'deployment')],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            output, errors = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            output, errors = process.communicate(timeout=3)
            self.fail('Guard failed to bound partial-startup cleanup: ' + output + errors)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(output.count('ONE_ORIGINAL_GUARD'), 1)
        self.assertIn('PARTIAL_STARTUP_CLEANUP_BLOCKED', output)
        self.assertEqual(errors, '')
