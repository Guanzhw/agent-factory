# pyright: reportMissingImports=false
"""Real PG lock/commit regression with synthetic authority and receipt fixtures.

This checks the original debit method and receipt critical section, not HTTP,
real authorization, native runtime or scientific execution acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import os
from threading import Event
from types import MethodType
import unittest
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, text

from agent_factory.delegation import DelegationService
from agent_factory.store import Store, canonical
from pg_fixture import IsolatedPostgres
from test_remote_scientific_origin import Fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ScientificDebitPostgresTests(unittest.TestCase):
    def setUp(self):
        self.db = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        self.engine = create_engine(self.db.url, pool_size=3, max_overflow=0)
        self.locks = create_engine(self.db.url, pool_size=2, max_overflow=0)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.locks.dispose)
        f = self.f = Fixture()
        with self.engine.begin() as conn:
            for query in (
                'CREATE TABLE af_remote_placements(task_id TEXT PRIMARY KEY,owner_id TEXT,target_ref TEXT,body JSONB)',
                'CREATE TABLE af_remote_scientific_receiver_runs(child_id TEXT PRIMARY KEY,receiver_task_id TEXT,native_run_id TEXT)',
                'CREATE TABLE af_remote_scientific_calls(child_id TEXT,call_id TEXT,fingerprint TEXT,body JSONB,PRIMARY KEY(child_id,call_id))',
                'CREATE TABLE af_delegation_tool_calls(task_id TEXT,call_id TEXT,root_id TEXT,tool_name TEXT,created_at TEXT,PRIMARY KEY(task_id,call_id))',
            ):
                conn.execute(text(query))
            conn.execute(text('INSERT INTO af_remote_placements VALUES(:id,:owner,:target,CAST(:body AS JSONB))'),
                {'id': f.child['id'], 'owner': 'alice', 'target': 'receiver-target', 'body': canonical(f.handoff_row['body'])})
        f.store.engine = self.engine
        f.store._connection = ContextVar('debit_fixture_connection', default=None)
        f.store.transaction = MethodType(Store.transaction, f.store)
        original_sql = f.store.sql
        real_tables = ('af_remote_placements', 'af_remote_scientific_receiver_runs',
                       'af_remote_scientific_calls', 'af_delegation_tool_calls')
        def sql(query, **params):
            if any(table in query for table in real_tables):
                return Store.sql(f.store, query, **params)
            return original_sql(query, **params)
        f.store.sql = sql
        f.store.root_lock_engine = lambda: self.locks
        f.delegation.store = f.store
        f.delegation._root_lock = MethodType(DelegationService._root_lock, f.delegation)

    def rows(self, table):
        return self.f.store.sql('SELECT * FROM ' + table)

    def test_duplicate_and_conflicting_first_native_are_atomic(self):
        f = self.f
        body = f.debit_body()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(f.service.consume_remote_tool, deepcopy(body)) for _ in range(2)]
            self.assertEqual(futures[0].result(timeout=10), futures[1].result(timeout=10))
        self.assertEqual(len(self.rows('af_delegation_tool_calls')), 1)
        self.assertEqual(len(self.rows('af_remote_scientific_calls')), 1)
        with self.assertRaises(HTTPException):
            f.service.consume_remote_tool({**body, 'nativeRunId': str(uuid4())})
        self.assertEqual(self.rows('af_remote_scientific_receiver_runs')[0]['native_run_id'], f.remote_run)

    def test_receipt_first_blocks_conflicting_pin(self):
        f = self.f
        entered = Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.engine.begin() as conn:
                conn.execute(text('SELECT * FROM af_remote_placements FOR UPDATE'))
                def debit():
                    entered.set()
                    return f.service.consume_remote_tool(f.debit_body())
                future = pool.submit(debit)
                self.assertTrue(entered.wait(5))
                receipt = deepcopy(f.handoff_row['body'])
                receipt['receipt']['remoteRunId'] = str(uuid4())
                conn.execute(text('UPDATE af_remote_placements SET body=CAST(:body AS JSONB)'), {'body': canonical(receipt)})
            with self.assertRaises(HTTPException): future.result(timeout=10)
        self.assertEqual(self.rows('af_remote_scientific_receiver_runs'), [])
        self.assertEqual(self.rows('af_delegation_tool_calls'), [])

    def test_pin_first_blocks_conflicting_receipt_check(self):
        f = self.f
        pinned, release, reader_started = Event(), Event(), Event()
        transaction = f.store.transaction
        @contextmanager
        def held_transaction():
            with transaction() as conn:
                yield conn
                pinned.set()
                if not release.wait(5): raise AssertionError('fixture release timeout')
        f.store.transaction = held_transaction
        def receipt_check():
            reader_started.set()
            with self.engine.begin() as conn:
                conn.execute(text('SELECT * FROM af_remote_placements FOR UPDATE'))
                f.service.validate_received_native('alice', f.child['id'],
                    {'remoteTaskId': f.remote_task, 'remoteRunId': str(uuid4())})
        with ThreadPoolExecutor(max_workers=2) as pool:
            debit = pool.submit(f.service.consume_remote_tool, f.debit_body())
            try:
                self.assertTrue(pinned.wait(5))
                reader = pool.submit(receipt_check)
                self.assertTrue(reader_started.wait(5))
            finally:
                release.set()
            debit.result(timeout=10)
            with self.assertRaises(HTTPException): reader.result(timeout=10)
        self.assertEqual(len(self.rows('af_delegation_tool_calls')), 1)
