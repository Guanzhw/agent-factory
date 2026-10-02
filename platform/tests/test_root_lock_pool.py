"""Bounded root advisory locks must precede and not consume metadata capacity."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, text

from agent_factory.delegation import DelegationService
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires owned loopback isolated PostgreSQL')
class RootLockPoolPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)

    def setUp(self):
        def bounded_engine(url, **kwargs):
            return create_engine(url, **{**kwargs, 'pool_size': 1, 'max_overflow': 0, 'pool_timeout': 2})
        with patch('agent_factory.store.create_engine', side_effect=bounded_engine), patch.object(Store, 'initialize'):
            self.store = Store(self.database.url, SimpleNamespace())
            self.store.root_lock_engine()
        self.addCleanup(self.store.engine.dispose)
        self.first = DelegationService(SimpleNamespace(), self.store, Mock(), Mock())
        self.second = DelegationService(SimpleNamespace(), self.store, Mock(), Mock())
        self.store.sql('CREATE TABLE IF NOT EXISTS af_lock_probe (id integer PRIMARY KEY, value integer NOT NULL)')
        self.store.sql('DELETE FROM af_lock_probe')
        self.store.sql('INSERT INTO af_lock_probe VALUES (1, 10)')

    def test_single_metadata_connection_supports_reads_and_writes_inside_root_lock(self):
        with self.first._root_lock('synthetic-root') as lock_connection:
            self.assertIsNot(lock_connection.engine, self.store.engine)
            self.assertEqual(self.store.engine.pool.checkedout(), 0)
            self.assertEqual(self.store.sql('SELECT value FROM af_lock_probe WHERE id=1')[0]['value'], 10)
            self.store.sql('UPDATE af_lock_probe SET value=20 WHERE id=1')
            with self.store.transaction():
                self.assertEqual(self.store.sql('SELECT value FROM af_lock_probe WHERE id=1')[0]['value'], 20)
        self.assertEqual(self.store.engine.pool.checkedout(), 0)
        self.assertEqual(self.store.root_lock_engine().pool.checkedout(), 0)

    def test_handles_share_one_bounded_lock_pool_and_dispose_it_with_store(self):
        engine = self.store.root_lock_engine()
        with self.first._root_lock('synthetic-first') as first:
            self.assertIs(first.engine, engine)
            self.assertEqual(engine.pool.checkedout(), 1)
        with self.second._root_lock('synthetic-second') as second:
            self.assertIs(second.engine, engine)
        self.assertEqual(engine.pool.size(), 1)
        # A simultaneous second checkout is explicitly rejected by the bound.
        from sqlalchemy.exc import TimeoutError as PoolTimeout
        with engine.connect():
            with self.assertRaises(PoolTimeout):
                engine.connect()
        with patch.object(engine, 'dispose', wraps=engine.dispose) as disposed:
            self.store.engine.dispose()
            disposed.assert_called_once()

    def test_metadata_transaction_cannot_enter_root_lock(self):
        with self.store.transaction():
            self.store.sql('UPDATE af_lock_probe SET value=30 WHERE id=1')
            with self.assertRaisesRegex(RuntimeError, 'Root lock must precede'):
                with self.first._root_lock('synthetic-root'):
                    self.fail('Reverse lock order was admitted')
            self.assertEqual(self.store.sql('SELECT value FROM af_lock_probe WHERE id=1')[0]['value'], 30)
        self.assertEqual(self.store.root_lock_engine().pool.checkedout(), 0)

    def test_exception_unlocks_root_without_rolling_back_committed_denial(self):
        signal = PermissionError('synthetic denial')
        with self.assertRaises(PermissionError) as raised:
            with self.first._root_lock('synthetic-root'):
                # A denial event is a committed metadata phase independent of
                # the session-lock connection's rollback/unlock cleanup.
                self.store.sql('INSERT INTO af_lock_probe VALUES (2, 403)')
                raise signal
        self.assertIs(raised.exception, signal)
        self.assertEqual(self.store.sql('SELECT value FROM af_lock_probe WHERE id=2')[0]['value'], 403)
        self.assertEqual(self.store.root_lock_engine().pool.checkedout(), 0)
        # Another PostgreSQL session proves that no advisory lock leaked.
        with self.store.engine.connect() as outsider:
            self.assertTrue(outsider.execute(text('SELECT pg_try_advisory_lock(hashtext(:key))'),
                {'key': 'delegation:synthetic-root'}).scalar_one())
            outsider.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': 'delegation:synthetic-root'})

    def test_budget_and_observer_take_root_before_metadata_without_deadlock(self):
        self.store.sql('CREATE TABLE IF NOT EXISTS af_delegation_roots (root_id text PRIMARY KEY, owner_id text NOT NULL)')
        self.store.sql('CREATE TABLE IF NOT EXISTS af_delegation_tool_calls '
            '(task_id text, call_id text, root_id text, tool_name text, created_at text)')
        self.store.sql('DELETE FROM af_delegation_tool_calls')
        task = {'id': 'synthetic-root', 'owner_id': 'alice', 'plan_id': 'synthetic-plan'}
        self.store.task = Mock(return_value=task)
        self.store.plan = Mock(return_value={'tools': ['inspect'], 'budget': {'toolCalls': 2}})
        self.store.require_current_policy = Mock()
        self.first._ancestry = Mock(return_value=('synthetic-root', []))
        self.first._descendants = Mock(return_value=[])
        self.first._mandate = Mock()
        acquired = threading.Event()
        budget_requested_root = threading.Event()
        original_lock = self.first._root_lock

        @contextmanager
        def budget_lock(root):
            budget_requested_root.set()
            with original_lock(root) as connection:
                yield connection

        def observer():
            with self.second._root_lock('synthetic-root'):
                acquired.set()
                if not budget_requested_root.wait(5):
                    raise AssertionError('Budget did not request root before its metadata transaction')
                self.assertEqual(self.store.engine.pool.checkedout(), 0)
                self.store.sql('UPDATE af_lock_probe SET value=40 WHERE id=1')

        def budget():
            if not acquired.wait(5):
                raise AssertionError('Observer did not acquire its root scope')
            return self.first.consume_tool_budget(SimpleNamespace(run_id='synthetic-run',
                session_id='synthetic-root', user_id='alice'), 'synthetic-call', 'inspect')

        with patch.object(self.first, '_root_lock', budget_lock), ThreadPoolExecutor(max_workers=2) as executor:
            observing = executor.submit(observer)
            charging = executor.submit(budget)
            observing.result(timeout=10)
            self.assertTrue(charging.result(timeout=10)['charged'])
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_delegation_tool_calls')[0]['n'], 1)
        self.assertEqual(self.store.sql('SELECT value FROM af_lock_probe WHERE id=1')[0]['value'], 40)
        self.assertEqual(self.store.engine.pool.checkedout(), 0)
        self.assertEqual(self.store.root_lock_engine().pool.checkedout(), 0)


if __name__ == '__main__':
    unittest.main()
