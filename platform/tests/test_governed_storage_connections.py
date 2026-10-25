"""Nested application/material authority reads fit one metadata connection."""
from contextvars import ContextVar
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table, create_engine, select
from sqlalchemy.pool import QueuePool

from agent_factory.applications import GovernedStorage
from agent_factory.material_governance import MaterialGovernance


class GovernedStorageConnectionTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=QueuePool,
            pool_size=1, max_overflow=0, pool_timeout=.05)
        self.addCleanup(engine.dispose)
        metadata = MetaData()
        # Reflect the real governance tables while bounding the pool to one connection.
        Table("af_materials", metadata, Column("id", String, primary_key=True))
        Table("af_audit", metadata, Column("id", String, primary_key=True))
        metadata.create_all(engine)
        self.store = SimpleNamespace(engine=engine, settings=SimpleNamespace(),
            _connection=ContextVar("governed_read_fixture", default=None))
        self.governance = MaterialGovernance(self.store, None)
        self.applications = GovernedStorage(self.store, "application-read-fixture")

    def test_nested_material_read_uses_outer_connection(self):
        with self.applications.read() as outer:
            with self.governance._read() as inner:
                self.assertIs(inner, outer)
                self.assertEqual(inner.execute(select(self.governance.audit.c.id)).scalars().all(), [])
        self.assertIsNone(self.store._connection.get())
        self.assertEqual(self.store.engine.pool.checkedout(), 0)

    def test_failed_nested_read_releases_connection_and_rolls_back_write(self):
        with self.assertRaisesRegex(HTTPException, 'controlled read failure'):
            with self.applications.write() as outer:
                outer.execute(self.governance.audit.insert().values(id='rolled-back'))
                with self.governance._read() as inner:
                    self.assertIs(inner, outer)
                    raise HTTPException(409, 'controlled read failure')
        self.assertIsNone(self.store._connection.get())
        self.assertEqual(self.store.engine.pool.checkedout(), 0)
        with self.governance._read() as conn:
            self.assertEqual(conn.execute(select(self.governance.audit.c.id)).scalars().all(), [])

    def test_nested_read_keeps_outer_write_transaction_until_commit(self):
        with self.applications.write() as outer:
            outer.execute(self.governance.audit.insert().values(id="outer-write"))
            with self.applications.read() as inner:
                self.assertIs(inner, outer)
                with self.governance._read() as material_conn:
                    self.assertIs(material_conn, outer)
            self.assertIs(self.store._connection.get(), outer)
            with self.assertRaisesRegex(ValueError, "controlled nested read failure"):
                with self.applications.read() as inner:
                    self.assertIs(inner, outer)
                    with self.governance._read() as material_conn:
                        self.assertIs(material_conn, outer)
                    raise ValueError("controlled nested read failure")
            self.assertIs(self.store._connection.get(), outer)
        self.assertIsNone(self.store._connection.get())
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(self.governance.audit.c.id)).scalars().all(), ["outer-write"])
        self.assertEqual(self.store.engine.pool.checkedout(), 0)
