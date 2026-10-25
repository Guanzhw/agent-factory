"""Original delegated custody against real PostgreSQL and native queue.

The model is deterministic; lifecycle, child tools and stored identities are real.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
import time
from pathlib import Path
import tempfile
from unittest import mock
import unittest
from uuid import uuid4

from agno.run import RunContext
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fixture_settings import Settings
from agent_factory.store import digest
from core_native_fixture import create_fixture_app
from pg_fixture import IsolatedPostgres
import test_delegation_postgres as delegation_fixture

PIN = {'adapterId': 'native-delegated-operations-v1', 'revision': '1', 'configFingerprint': digest({})}


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class DelegatedOperationsPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.app = create_fixture_app(Settings(db_url=cls.database.url, workspace=Path(cls.workspace.name),
            max_workers=1, max_user_tasks=8, max_tool_calls=32))
        cls.state = cls.app.app.state.factory
        cls.store, cls.auth, cls.bridge = (cls.state[key] for key in ('store', 'auth', 'bridge'))
        cls.service = cls.store.delegation
        cls.adapter = cls.store.workflow.runtimes[tuple(PIN.values())]
        cls.addClassCleanup(cls.store.engine.dispose)
        cls.addClassCleanup(cls.store.native_db.db_engine.dispose)
        cls.client = TestClient(cls.app, base_url="https://testserver").__enter__()
        cls.addClassCleanup(cls.client.__exit__, None, None, None)

    setUp = delegation_fixture.DelegationPostgresTests.setUp
    tearDown = delegation_fixture.DelegationPostgresTests.tearDown
    call = delegation_fixture.DelegationPostgresTests.call
    parent = delegation_fixture.DelegationPostgresTests.parent
    wait_native = delegation_fixture.DelegationPostgresTests.wait_native
    wait_group = delegation_fixture.DelegationPostgresTests.wait_group

    def operation(self, parent, goal='a sufficiently long actual checksum input'):
        ctx = RunContext(run_id=parent['run_id'], session_id=parent['id'], user_id='alice',
            session_state={'factory_envelope': {'plan_ref': parent['plan_id'], 'user_id': 'alice',
                'task_id': parent['id'], 'request_id': parent['request_id']}})
        return self.call(self.store.workflow.start, ctx, 'delegated-test', str(uuid4()), PIN,
            {'goal': goal, 'mode': 'literature'})

    def child(self, record):
        rows = self.store.sql('SELECT * FROM af_delegation_links WHERE parent_id=:parent AND request_id=:request',
            parent=record['taskId'], request='operation:' + record['id'])
        self.assertEqual(len(rows), 1)
        return self.store.task(rows[0]['child_id'], 'alice')

    def test_actual_child_result_and_original_lookup_after_lost_ack(self):
        parent = self.parent()
        original = self.service.create
        async def lost_ack(*args, **kwargs):
            await original(*args, **kwargs)
            raise TimeoutError('synthetic response loss after actual submit')
        with mock.patch.object(self.service, 'create', side_effect=lost_ack) as create:
            record = self.operation(parent)
            self.assertIsNone(record['observation'])
            child = self.child(record)
            self.wait_native(child['id'], {'completed'})
            recovered = self.call(self.store.workflow.lookup, 'alice', record['id'])
            repeated = self.call(self.store.workflow.lookup, 'alice', record['id'])
            self.assertEqual(create.call_count, 1)
        self.assertTrue(recovered['closed'])
        self.assertEqual(repeated['handle'], recovered['handle'])
        output = recovered['observation']['output']
        self.assertIn('synthetic-complete', output['result'])
        self.assertEqual(output['taskId'], child['id'])
        self.assertEqual(len(output['artifacts']), 1)
        self.assertFalse(self.store.workflow.task_held(parent['id']))
        self.assertEqual(self.store.sql('SELECT count(*) AS n FROM ai.agno_jobs WHERE session_id=:id', id=child['id'])[0]['n'], 1)

    def test_revoked_member_can_cancel_original_child_but_cannot_create(self):
        parent = self.parent()
        record = self.operation(parent, goal='sort')
        child = self.child(record)
        self.wait_native(child['id'], {'paused'})
        observer = self.store.lifecycle_observer
        self.call(observer.stop)
        self.addCleanup(self.call, observer.start)
        self.auth.directory.set_disabled('alice', True)
        with self.assertRaises(HTTPException):
            self.call(self.service.create, 'alice', parent['id'], 'another child', 'literature', str(uuid4()))
        with mock.patch.object(observer, '_cancel_bound', side_effect=ConnectionError('synthetic original cleanup unavailable')):
            with self.assertRaises(HTTPException) as failed:
                self.call(self.store.workflow.cancel, 'alice', record['id'])
            self.assertEqual(failed.exception.status_code, 503)
        pending = self.store.workflow._load('alice', record['id'])
        self.assertTrue(pending['cancelRequested'])
        self.assertFalse(pending['closed'])
        self.assertEqual(pending['handle'], record['handle'])
        stopped = self.call(self.store.workflow.cancel, 'alice', record['id'])
        self.wait_native(child['id'], {'cancelled'})
        if not stopped['closed']:
            stopped = self.call(self.store.workflow.cancel, 'alice', record['id'])
        self.assertTrue(stopped['closed'])
        self.assertEqual(stopped['observation']['state'], 'CANCELLED')
        self.assertEqual(len(self.store.sql('SELECT child_id FROM af_delegation_links WHERE parent_id=:id', id=parent['id'])), 1)

    def test_missing_link_lookup_does_not_create_and_cancel_stays_unknown(self):
        parent = self.parent()
        with mock.patch.object(self.service, 'create', side_effect=TimeoutError('before dispatch')):
            record = self.operation(parent)
        with mock.patch.object(self.service, 'create', side_effect=AssertionError('lookup dispatched')):
            observed = self.call(self.store.workflow.lookup, 'alice', record['id'])
            cancelled = self.call(self.store.workflow.cancel, 'alice', record['id'])
        self.assertEqual(observed['observation']['state'], 'UNKNOWN')
        self.assertFalse(cancelled['closed'])
        with mock.patch.object(self.bridge, 'submit', wraps=self.bridge.submit) as submit:
            response = self.client.post('/api/factory/jobs/' + parent['id'] + '/children', json={
                'goal': 'a sufficiently long actual checksum input', 'mode': 'literature',
                'requestId': 'operation:' + record['id']})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn('DELEGATED_OPERATION_REQUEST_RESERVED', response.text)
            submit.assert_not_called()
        self.assertEqual(self.store.sql('SELECT child_id FROM af_delegation_links WHERE parent_id=:id', id=parent['id']), [])
        # This test deliberately leaves UNKNOWN custody. Cleanup must not invent
        # a stop proof; exclude it from the helper's positive-stop assertion.
        self.roots.remove(parent['id'])
        self.store.request_cancel(parent['id'])
        self.call(self.store.lifecycle_observer.cancel_subtree, 'alice', parent['id'])

    def test_cancel_create_root_lock_interleavings(self):
        for creation_first in (False, True):
            with self.subTest(creation_first=creation_first):
                parent = self.parent()
                with mock.patch.object(self.service, 'create', side_effect=TimeoutError('before create')):
                    record = self.operation(parent)
                context = self.store.workflow._context(record)
                entered, release = threading.Event(), threading.Event()
                lock = self.service._root_lock

                @contextmanager
                def held(root_id):
                    if threading.current_thread().name.startswith('original-create'):
                        if not creation_first:
                            entered.set()
                            if not release.wait(10):
                                raise AssertionError('creation barrier was not released')
                        with lock(root_id) as conn:
                            yield conn
                            if creation_first:
                                entered.set()
                                if not release.wait(10):
                                    raise AssertionError('creation barrier was not released')
                    else:
                        with lock(root_id) as conn:
                            yield conn

                with mock.patch.object(self.service, '_root_lock', side_effect=held):
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='original-create') as creators, \
                            ThreadPoolExecutor(max_workers=1, thread_name_prefix='original-cancel') as cancellers:
                        created = creators.submit(asyncio.run, self.adapter.start(context, record['id'],
                            {'goal': 'a sufficiently long actual checksum input', 'mode': 'literature'}))
                        try:
                            self.assertTrue(entered.wait(10), 'create did not reach root lock barrier')
                            cancelled = cancellers.submit(asyncio.run, self.store.workflow.cancel('alice', record['id']))
                            deadline = time.monotonic() + 10
                            while time.monotonic() < deadline:
                                if self.store.workflow._load('alice', record['id'])['cancelRequested']:
                                    break
                                time.sleep(.01)
                            else:
                                self.fail('original cancellation did not persist')
                            if not creation_first:
                                self.assertFalse(cancelled.result(10)['closed'])
                        finally:
                            release.set()
                        with self.assertRaises(HTTPException):
                            created.result(10)
                        cancelled.result(10)
                links = self.store.sql('SELECT child_id FROM af_delegation_links WHERE parent_id=:id', id=parent['id'])
                self.assertEqual(len(links), int(creation_first))
                for link in links:
                    child = self.store.task(link['child_id'], 'alice')
                    self.assertEqual(child['admission'], 'rejected')
                    self.assertIsNone(child['run_id'])
                if not creation_first:
                    self.roots.remove(parent['id'])
                    self.store.request_cancel(parent['id'])
                    self.call(self.store.lifecycle_observer.cancel_subtree, 'alice', parent['id'])

    def test_subtree_observation_waits_for_inflight_descendant_link(self):
        parent = self.parent()
        record = self.operation(parent, goal='sort')
        child = self.child(record)
        self.wait_native(child['id'], {'paused'})
        entered, release, inspecting = threading.Event(), threading.Event(), threading.Event()
        reserve, root_lock = self.store.reserve_task, self.service._root_lock

        def held_reserve(*args, **kwargs):
            if threading.current_thread().name.startswith('descendant-create'):
                entered.set()
                if not release.wait(10):
                    raise AssertionError('descendant creation barrier was not released')
            return reserve(*args, **kwargs)

        @contextmanager
        def observed_lock(root_id):
            if threading.current_thread().name.startswith('asyncio_'):
                inspecting.set()
            with root_lock(root_id) as conn:
                yield conn

        with mock.patch.object(self.store, 'reserve_task', side_effect=held_reserve), \
                mock.patch.object(self.service, '_root_lock', side_effect=observed_lock):
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='descendant-create') as creators, \
                    ThreadPoolExecutor(max_workers=1, thread_name_prefix='subtree-read') as readers:
                created = creators.submit(asyncio.run, self.service.create('alice', child['id'], 'sort', 'literature', str(uuid4())))
                try:
                    self.assertTrue(entered.wait(10))
                    observed = readers.submit(asyncio.run, self.store.lifecycle_observer.inspect_subtree('alice', child['id']))
                    self.assertTrue(inspecting.wait(10), 'subtree observation did not attempt original root lock')
                    self.assertFalse(observed.done(), 'subtree read escaped the creation root lock')
                finally:
                    release.set()
                descendant = created.result(10)['childTask']
                group = observed.result(10)
        self.assertEqual([fact['taskId'] for fact in group['children']], [descendant['id']])
        self.assertFalse(group['allStopped'])
        self.assertTrue(group['children'][0]['unknown'] or not group['children'][0]['stopped'])
