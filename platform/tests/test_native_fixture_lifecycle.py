"""No-PG lifecycle ordering for the restartable native test fixture."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_personal_tool_native_postgres as native_fixture


class FixtureCase(unittest.TestCase):
    start = native_fixture.PersonalToolNativePostgresTests.start
    stop = native_fixture.PersonalToolNativePostgresTests.stop


class Engine:
    def __init__(self, events, name):
        self.events, self.name, self.disposals = events, name, 0

    def dispose(self):
        self.disposals += 1
        self.events.append(self.name + '.dispose')


class Client:
    def __init__(self, app, *, base_url, enter_failure=False, exit_failure=False):
        assert base_url == "https://testserver"
        self.app = app
        self.enter_failure, self.exit_failure = enter_failure, exit_failure

    def __enter__(self):
        self.app.events.append(self.app.name + '.enter')
        if self.enter_failure:
            raise RuntimeError('synthetic enter failure')
        return self

    def __exit__(self, *args):
        store = self.app.app.state.factory['store']
        if store.engine.disposals or store.native_db.db_engine.disposals:
            raise AssertionError('Engine disposed before lifespan exit')
        self.app.events.append(self.app.name + '.exit')
        if self.exit_failure:
            raise RuntimeError('synthetic exit failure')


def application(events, name):
    store = SimpleNamespace(engine=Engine(events, name + '.factory'),
        native_db=SimpleNamespace(db_engine=Engine(events, name + '.native')))
    return SimpleNamespace(name=name, events=events,
        app=SimpleNamespace(state=SimpleNamespace(factory={'store': store, 'auth': object()})))


class NativeFixtureLifecycleTests(unittest.TestCase):
    def fixture(self):
        self.enterContext(patch.object(native_fixture, 'initialize_members', autospec=True))
        fixture = FixtureCase()
        fixture.settings = object()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_restart_closes_each_generation_before_dispose_without_accumulating_callbacks(self):
        events = []
        first, second = application(events, 'first'), application(events, 'second')
        fixture = self.fixture()
        with patch.object(native_fixture, 'create_app', side_effect=[first, second]), \
                patch.object(native_fixture, 'TestClient', side_effect=Client):
            fixture.start()
            old_stack = fixture._generation_stack
            self.assertEqual(len(fixture._cleanups), 1)
            fixture.stop()
            self.assertEqual(len(old_stack._exit_callbacks), 0)
            self.assertIsNone(fixture.client)
            fixture.start()
            self.assertEqual(len(fixture._cleanups), 1)
            fixture.doCleanups()
            fixture.stop()
        self.assertEqual(events, ['first.enter', 'first.exit', 'first.native.dispose', 'first.factory.dispose',
                                  'second.enter', 'second.exit', 'second.native.dispose', 'second.factory.dispose'])

    def test_enter_failure_disposes_created_engines_and_allows_restart(self):
        events = []
        failed, next_app = application(events, 'failed'), application(events, 'next')
        fixture = self.fixture()
        def client(app, *, base_url):
            return Client(app, base_url=base_url, enter_failure=app is failed)
        with patch.object(native_fixture, 'create_app', side_effect=[failed, next_app]), \
                patch.object(native_fixture, 'TestClient', side_effect=client):
            with self.assertRaisesRegex(RuntimeError, 'enter failure'):
                fixture.start()
            self.assertIsNone(fixture.client)
            fixture.stop()
            fixture.start()
            fixture.doCleanups()
        self.assertEqual(events, ['failed.enter', 'failed.native.dispose', 'failed.factory.dispose',
                                  'next.enter', 'next.exit', 'next.native.dispose', 'next.factory.dispose'])

    def test_create_failure_has_safe_idempotent_cleanup(self):
        fixture = self.fixture()
        with patch.object(native_fixture, 'create_app', side_effect=RuntimeError('synthetic create failure')):
            with self.assertRaisesRegex(RuntimeError, 'create failure'):
                fixture.start()
        self.assertEqual(len(fixture._cleanups), 1)
        self.assertTrue(fixture.doCleanups())
        fixture.stop()
        self.assertIsNone(fixture.client)

    def test_replacing_store_does_not_change_generation_owned_engines(self):
        events = []
        original, reopened = application(events, 'original'), application(events, 'reopened')
        fixture = self.fixture()
        with patch.object(native_fixture, 'create_app', return_value=original), \
                patch.object(native_fixture, 'TestClient', side_effect=Client):
            fixture.start()
            fixture.state = reopened.app.state.factory
            fixture.store, fixture.auth = fixture.state['store'], fixture.state['auth']
            fixture.stop()
            fixture.stop()
            fixture.doCleanups()
        self.assertEqual(events, ['original.enter', 'original.exit', 'original.native.dispose', 'original.factory.dispose'])
        self.assertEqual(fixture.store.engine.disposals, 0)
        self.assertEqual(fixture.store.native_db.db_engine.disposals, 0)

    def test_exit_failure_still_disposes_engines_once(self):
        events = []
        app = application(events, 'failed-exit')
        fixture = self.fixture()
        with patch.object(native_fixture, 'create_app', return_value=app), \
                patch.object(native_fixture, 'TestClient', side_effect=lambda value, *, base_url: Client(value, base_url=base_url, exit_failure=True)):
            fixture.start()
            with self.assertRaisesRegex(RuntimeError, 'exit failure'):
                fixture.stop()
            fixture.stop()
            self.assertTrue(fixture.doCleanups())
        self.assertEqual(events, ['failed-exit.enter', 'failed-exit.exit',
                                  'failed-exit.native.dispose', 'failed-exit.factory.dispose'])
