"""Fresh bounded material authority reads on disposable PostgreSQL; no provider calls."""
from fixture_auth import initialize_members
import copy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from agno.db.postgres import PostgresDb
from fastapi import HTTPException
from sqlalchemy import event

from agent_factory.auth import AuthService
from fixture_settings import Settings
from agent_factory.execution_bindings import ExecutionBindings
from agent_factory.material_governance import MaterialGovernance
from agent_factory.store import Store, digest
from pg_fixture import IsolatedPostgres


def ref(body):
    return {key: body[key] for key in ('id', 'version', 'sha256')}


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class MaterialGovernanceBulkPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.workspace.name))
        self.store = Store(self.database.url, self.settings)
        self.addCleanup(self.store.engine.dispose)
        self.native = PostgresDb(db_url=self.database.url)
        self.addCleanup(self.native.db_engine.dispose)
        self.auth = AuthService(self.settings, self.native)
        initialize_members(self.auth)
        self.store.execution_bindings = ExecutionBindings(self.settings, self.store)
        self.service = MaterialGovernance(self.store, self.auth)

    def published(self, **changes):
        body = self.service.create_draft('alice', {'kind': 'prompt', 'name': 'Synthetic bulk fixture',
            'content': 'Original inert fixture.', **changes}, str(uuid4()))
        self.service.publish('alice', body['id'], body['version'], str(uuid4()))
        return body

    def require(self, *materials):
        return self.service.require_materials_current({'materialRefs': [ref(body) for body in materials]})

    def rewrite_fixture(self, body):
        """Deliberate DB corruption/graph fixture, never a publication API."""
        body = copy.deepcopy(body)
        body['sha256'] = digest({key: value for key, value in body.items() if key not in {'sha256', 'published', 'createdAt'}})
        with self.store.engine.begin() as conn:
            conn.execute(self.service.materials.update().where(self.service.materials.c.id == body['id']).values(body=body))
            conn.execute(self.service.versions.update().where(self.service.versions.c.material_id == body['id']).values(
                material_sha=body['sha256'], immutable_digest=self.service._immutable(body)))
        return body

    def test_thirty_pins_use_one_join_and_next_call_observes_withdrawal(self):
        materials = [self.published() for _ in range(30)]
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.store.engine, 'before_cursor_execute', capture)
        try:
            self.assertTrue(self.require(*materials)['allowed'])
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', capture)
        self.assertEqual(len(statements), 1, statements)
        self.assertIn('LEFT OUTER JOIN af_material_governance', statements[0])
        self.service.withdraw('alice', materials[-1]['id'], 1, str(uuid4()))
        with self.assertRaises(HTTPException) as denied:
            self.require(*materials)
        self.assertIn('INACTIVE_MATERIAL', str(denied.exception.detail))

    def test_exact_transitive_closure_digest_and_missing_rows(self):
        leaf = self.published()
        middle = self.published(dependencies=[ref(leaf)])
        root = self.published(dependencies=[ref(middle)])
        self.assertTrue(self.require(root, middle, leaf)['allowed'])
        with self.assertRaises(HTTPException) as omitted:
            self.require(root, middle)
        self.assertIn('omitted a pinned transitive', str(omitted.exception.detail))
        with self.assertRaises(HTTPException):
            self.require(root, middle, {**leaf, 'sha256': '0' * 64})
        with self.assertRaises(HTTPException):
            self.require(leaf, {**leaf, 'sha256': '0' * 64})
        with self.store.engine.begin() as conn:
            conn.execute(self.service.versions.delete().where(self.service.versions.c.material_id == leaf['id']))
        with self.assertRaises(HTTPException) as unreviewed:
            self.require(root, middle, leaf)
        self.assertEqual(unreviewed.exception.status_code, 409)
        self.assertIn('UNREVIEWED_MATERIAL', str(unreviewed.exception.detail))
        with self.store.engine.begin() as conn:
            conn.execute(self.service.materials.delete().where(self.service.materials.c.id == leaf['id']))
        with self.assertRaises(HTTPException) as missing:
            self.require(root, middle, leaf)
        self.assertEqual(missing.exception.status_code, 404)

    def test_material_and_governance_integrity_and_bootstrap_remain_enforced(self):
        material = self.published()
        with self.store.engine.begin() as conn:
            conn.execute(self.service.materials.update().where(self.service.materials.c.id == material['id']).values(
                body={**material, 'content': 'Tampered without matching digest'}))
        with self.assertRaises(HTTPException) as tampered:
            self.require(material)
        self.assertIn('Immutable material integrity', str(tampered.exception.detail))
        self.rewrite_fixture(material)
        with self.store.engine.begin() as conn:
            conn.execute(self.service.versions.update().where(self.service.versions.c.material_id == material['id']).values(immutable_digest='tampered'))
        with self.assertRaises(HTTPException) as immutable:
            self.require(material)
        self.assertIn('reviewed immutable', str(immutable.exception.detail))
        self.rewrite_fixture(material)
        with self.store.engine.begin() as conn:
            conn.execute(self.service.versions.update().where(self.service.versions.c.material_id == material['id']).values(bootstrap=True))
        with self.assertRaises(HTTPException) as bootstrap:
            self.require(material)
        self.assertIn('bootstrap', str(bootstrap.exception.detail))

    def test_dependency_depth_and_corrupted_cycle_are_rejected(self):
        chain = [self.published()]
        for _ in range(8):
            chain.append(self.published(dependencies=[ref(chain[-1])]))
        self.assertTrue(self.require(*chain)['allowed'])
        # A valid digest/immutable row with a ninth dependency edge exceeds the
        # same DFS depth limit. Build only this fault via the fixture writer.
        too_deep = self.rewrite_fixture({**self.published(), 'dependencies': [ref(chain[-1])]})
        with self.assertRaises(HTTPException) as depth:
            self.require(too_deep, *chain)
        self.assertIn('closure exceeds bounds', str(depth.exception.detail))
        # Content-addressed cycles cannot all retain valid SHA256 pins. Corrupt
        # the leaf into a back-edge and verify it is rejected before authority.
        leaf = chain[0]
        with self.store.engine.begin() as conn:
            conn.execute(self.service.materials.update().where(self.service.materials.c.id == leaf['id']).values(
                body={**leaf, 'dependencies': [ref(chain[-1])]}))
        with self.assertRaises(HTTPException):
            self.require(*chain)

    def test_runtime_adapter_withdrawal_and_permission_drift_are_fresh(self):
        registry = self.store.execution_bindings
        registry.register('tool', 'fixture-owned-tool', '1', lambda _: None,
            tool_name='fixture_owned_tool', permissions=('fixture:invoke',))
        material = self.published(kind='tool', content='fixture_owned_tool', permissions=['fixture:invoke'],
            runtimeBinding={'adapterId': 'fixture-owned-tool', 'revision': '1', 'config': {}})
        self.assertTrue(self.require(material)['allowed'])
        registry.withdraw('tool', 'fixture-owned-tool', '1')
        with self.assertRaises(HTTPException):
            self.require(material)
        registry.register('tool', 'fixture-owned-tool', '1', lambda _: None,
            tool_name='fixture_owned_tool', permissions=('fixture:changed',))
        with self.assertRaises(HTTPException):
            self.require(material)


class MaterialDependencyTraversalTests(unittest.TestCase):
    def test_cycle_guard_still_rejects_recursive_lookup_graph(self):
        # Real content-addressed cycles fail PostgreSQL integrity checks above.
        # Isolate the DFS guard here with already-validated lookup fixtures so
        # its explicit recursion protection remains independently exercised.
        first = {'id': 'first', 'version': 1, 'sha256': 'a' * 64}
        second = {'id': 'second', 'version': 1, 'sha256': 'b' * 64}
        materials = {
            ('first', 1): {'body': {**first, 'dependencies': [second]}},
            ('second', 1): {'body': {**second, 'dependencies': [first]}},
        }
        service = MaterialGovernance.__new__(MaterialGovernance)
        service._material = lambda conn, mid, version, **kwargs: materials[(mid, version)]
        service._active = lambda *args, **kwargs: None
        allowed = {(pin['id'], pin['version'], pin['sha256']) for pin in (first, second)}
        with self.assertRaises(HTTPException) as cycle:
            service._dependencies(None, {'dependencies': [first]}, None, allowed, materials=materials, versions={})
        self.assertIn('dependency cycle', str(cycle.exception.detail))
