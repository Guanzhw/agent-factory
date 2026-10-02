"""Isolated PostgreSQL contracts for fresh standalone reads and explicit transactions."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import os
import threading
import unittest

from sqlalchemy import create_engine, text

from agent_factory.store import Store
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires owned loopback isolated PostgreSQL')
class StoreReadPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)

    def setUp(self):
        # Exercise real Store methods using only a synthetic SQL probe table;
        # native workers and application/provider fixtures are unnecessary.
        self.store = Store.__new__(Store)
        self.store.engine = create_engine(self.database.url, pool_size=1, max_overflow=0, pool_timeout=2,
            isolation_level='REPEATABLE READ')
        self.store._connection = ContextVar('synthetic_store_test_connection', default=None)
        self.addCleanup(self.store.engine.dispose)
        self.other = create_engine(self.database.url, pool_size=1, max_overflow=0)
        self.addCleanup(self.other.dispose)
        with self.other.begin() as connection:
            connection.execute(text('CREATE TABLE IF NOT EXISTS af_read_probe (id integer PRIMARY KEY, value integer NOT NULL)'))
            connection.execute(text('DELETE FROM af_read_probe'))
            connection.execute(text('INSERT INTO af_read_probe VALUES (1, 10)'))

    def read(self):
        return self.store.sql('SELECT value FROM af_read_probe WHERE id=1')[0]['value']

    def test_standalone_read_observes_other_connection_commit(self):
        self.assertEqual(self.read(), 10)
        with self.other.begin() as connection:
            connection.execute(text('UPDATE af_read_probe SET value=20 WHERE id=1'))
        self.assertEqual(self.read(), 20)
        self.assertIsNone(self.store._connection.get())
        self.assertEqual(self.store.engine.pool.checkedout(), 0)

    def test_explicit_transaction_read_uses_update_and_rolls_back_on_failure(self):
        with self.assertRaisesRegex(PermissionError, 'synthetic denial'):
            with self.store.transaction() as connection:
                self.store.sql('UPDATE af_read_probe SET value=30 WHERE id=1')
                self.assertEqual(self.read(), 30)
                # A nested transaction must borrow the exact same connection.
                with self.store.transaction() as nested:
                    self.assertIs(nested, connection)
                    self.assertEqual(self.read(), 30)
                with self.other.connect() as outside:
                    self.assertEqual(outside.execute(text('SELECT value FROM af_read_probe WHERE id=1')).scalar_one(), 10)
                raise PermissionError('synthetic denial')
        self.assertEqual(self.read(), 10)
        self.assertIsNone(self.store._connection.get())

    def test_denial_write_commits_after_read_even_when_caller_raises(self):
        def denied_operation():
            self.assertEqual(self.read(), 10)
            # Represents a durable protected_denied event after checking facts.
            self.store.sql('INSERT INTO af_read_probe VALUES (2, 403)')
            raise PermissionError('synthetic denial')
        with self.assertRaises(PermissionError):
            denied_operation()
        with self.other.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT value FROM af_read_probe WHERE id=2')).scalar_one(), 403)
        self.assertEqual(self.store.engine.pool.checkedout(), 0)

    def test_single_connection_pool_released_between_two_thread_operations(self):
        read_finished = threading.Event()
        write_finished = threading.Event()

        def reader():
            first = self.read()
            read_finished.set()
            if not write_finished.wait(5):
                raise AssertionError('Writer could not acquire connection released by standalone read')
            return first, self.read()

        def writer():
            try:
                if not read_finished.wait(5):
                    raise AssertionError('Reader did not complete its standalone operation')
                self.store.sql('UPDATE af_read_probe SET value=40 WHERE id=1')
            finally:
                write_finished.set()

        # Event ordering, not a speed benchmark: the reader remains alive while
        # the writer must borrow the pool's sole connection and commit.
        with ThreadPoolExecutor(max_workers=2) as executor:
            reading = executor.submit(reader)
            writing = executor.submit(writer)
            writing.result(timeout=10)
            self.assertEqual(reading.result(timeout=10), (10, 40))
        self.assertEqual(self.store.engine.pool.checkedout(), 0)
        self.assertIsNone(self.store._connection.get())


if __name__ == '__main__':
    unittest.main()
