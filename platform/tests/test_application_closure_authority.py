"""Selected material closure is checked fresh without authorizing unrelated catalog rows."""
import copy
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import Boolean, Column, Integer, JSON, MetaData, String, Table, create_engine, select

from agent_factory.applications import ApplicationService
from agent_factory.store import digest


def material(identifier, dependencies=()):
    body = {'id': identifier, 'version': 1, 'kind': 'skill', 'content': 'Synthetic public fixture',
        'compatibility': ['agno:3.1.0'], 'dependencies': list(dependencies), 'published': True,
        'permissions': []}
    body['sha256'] = digest({key: value for key, value in body.items() if key != 'published'})
    return body


def pin(value):
    return {key: value[key] for key in ('id', 'version', 'sha256')}


class ApplicationClosureAuthorityTests(unittest.TestCase):
    def fixture(self):
        leaf = material('selected-leaf')
        middle = material('selected-middle', [pin(leaf)])
        root = material('selected-root', [pin(middle)])
        # Deliberately invalid and irrelevant. Selected-closure validation must
        # neither follow this graph nor let it influence the selected mandate.
        unrelated = material('unselected-catalog')
        unrelated.update(content='changed-after-pin', dependencies=[{'invalid': True}])
        catalog = [root, middle, leaf, unrelated]
        governance = SimpleNamespace(require_materials_current=Mock(), filter_active=Mock(
            side_effect=AssertionError('Unselected catalog governance must not run')))

        def materials(published_only=False):
            values = copy.deepcopy(catalog)
            return governance.filter_active(values) if published_only else values

        store = SimpleNamespace(materials=Mock(side_effect=materials), material_governance=governance)
        service = ApplicationService.__new__(ApplicationService)
        service.store = store
        return service, store, catalog

    def test_checks_only_complete_selected_transitive_closure(self):
        service, store, catalog = self.fixture()
        result = service.closure([pin(catalog[0]), pin(catalog[1])])
        self.assertEqual([item['id'] for item in result], ['selected-leaf', 'selected-middle', 'selected-root'])
        store.materials.assert_called_once_with(published_only=False)
        store.material_governance.filter_active.assert_not_called()
        store.material_governance.require_materials_current.assert_called_once_with(
            {'materialRefs': [pin(catalog[index]) for index in (2, 1, 0)]})

    def test_selected_revocation_denies_next_call_without_cached_authority(self):
        service, store, catalog = self.fixture()
        revoked = set()

        def current(plan):
            if revoked & {item['id'] for item in plan['materialRefs']}:
                raise HTTPException(409, 'Synthetic selected material withdrawn')

        store.material_governance.require_materials_current.side_effect = current
        self.assertEqual(len(service.closure([pin(catalog[0])])), 3)
        revoked.add('selected-leaf')
        with self.assertRaises(HTTPException) as raised:
            service.closure([pin(catalog[0])])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(store.materials.call_count, 2)
        self.assertEqual(store.material_governance.require_materials_current.call_count, 2)
        store.material_governance.filter_active.assert_not_called()

    def test_unpublished_dependency_is_not_available_to_selected_closure(self):
        service, store, catalog = self.fixture()
        catalog[2]['published'] = False
        with self.assertRaises(HTTPException) as raised:
            service.closure([pin(catalog[0])])
        self.assertEqual(raised.exception.status_code, 409)
        store.material_governance.require_materials_current.assert_not_called()

    def test_missing_dependency_is_reloaded_and_denied_after_prior_success(self):
        service, store, catalog = self.fixture()
        reference = pin(catalog[0])
        service.closure([reference])
        catalog.pop(2)
        with self.assertRaises(HTTPException) as raised:
            service.closure([reference])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(store.materials.call_count, 2)
        self.assertEqual(store.material_governance.require_materials_current.call_count, 1)

    def test_selected_dependency_digest_tampering_is_denied(self):
        service, store, catalog = self.fixture()
        catalog[2]['content'] = 'Tampered synthetic bytes'
        with self.assertRaises(HTTPException) as raised:
            service.closure([pin(catalog[0])])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn('integrity', str(raised.exception.detail))
        store.material_governance.require_materials_current.assert_not_called()

    def test_dependency_cycle_remains_denied(self):
        service, store, catalog = self.fixture()
        # Isolate cycle traversal from cryptographic fixed-point impossibility;
        # digest tampering is exercised with the real hash in the previous test.
        root = catalog[0]
        root['sha256'] = 'a' * 64
        root['dependencies'] = [pin(root)]
        with patch('agent_factory.applications.digest', return_value='a' * 64):
            with self.assertRaises(HTTPException) as raised:
                service.closure([pin(root)])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn('cycle', str(raised.exception.detail))
        store.material_governance.require_materials_current.assert_not_called()


class BoundedApplicationClosureTests(unittest.TestCase):
    """Real bounded SQL on synthetic SQLite rows; not PostgreSQL acceptance."""
    def fixture(self, unrelated=0, *, selected=None):
        if selected is None:
            leaf = material('selected-leaf')
            middle = material('selected-middle', [pin(leaf)])
            root = material('selected-root', [pin(middle)])
            selected = [root, middle, leaf]
        catalog = [*selected, *(material('unrelated-' + str(index)) for index in range(unrelated))]
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        table = Table('af_materials', MetaData(), Column('id', String, primary_key=True),
                      Column('version', Integer, primary_key=True), Column('body', JSON), Column('published', Boolean))
        table.create(engine)
        with engine.begin() as conn:
            conn.execute(table.insert(), [{'id': row['id'], 'version': row['version'],
                'body': copy.deepcopy(row), 'published': row['published']} for row in catalog])
        fetched = []

        def read_rows(conn, statement):
            rows = conn.execute(statement).mappings().all()
            fetched.append(len(rows))
            return rows

        @contextmanager
        def read():
            with engine.connect() as conn:
                # Count rows actually returned by SQL, not a Python filter over
                # an already-fetched catalog. Preserve the real tuple-IN query.
                yield SimpleNamespace(execute=lambda statement: SimpleNamespace(
                    mappings=lambda: read_rows(conn, statement)))

        def materials(*, published_only=False):
            self.assertFalse(published_only)
            with engine.connect() as conn:
                return [{**row['body'], 'published': row['published']}
                        for row in read_rows(conn, select(table.c.body, table.c.published))]

        governance = SimpleNamespace(materials=table, require_materials_current=Mock())
        store = SimpleNamespace(materials=Mock(side_effect=materials), material_governance=governance,
            settings=SimpleNamespace(max_tool_calls=8, experiment_timeout_seconds=8, experiment_output_bytes=65536))
        service = ApplicationService.__new__(ApplicationService)
        service.store, service.db = store, SimpleNamespace(read=read)
        return SimpleNamespace(service=service, store=store, selected=selected, catalog=catalog,
                               engine=engine, table=table, fetched=fetched)

    def plan(self, fixture):
        refs = [pin(item) for item in fixture.selected]
        budget = {'toolCalls': 8, 'maxDepth': 2, 'maxChildren': 4,
                  'experimentSeconds': 8, 'outputBytes': 65536}
        reference = {'id': 'synthetic-app', 'version': 1, 'sha256': 'a' * 64}
        application = {'id': reference['id'], 'modes': {'direct': {
            'materialRefs': [refs[0]], 'materialChoices': {}, 'toolOrder': [],
            'capabilities': [], 'budget': budget, 'config': {'experimentDurationSeconds': 8}}}}
        anchor = {'applicationRef': reference, 'mode': 'direct', 'materialRefs': refs,
                  'materialChoices': {}, 'executionBindingsSha256': None}
        anchor['sha256'] = digest(anchor)
        plan = {'applicationRef': reference, 'application': reference['id'], 'mode': 'direct',
                'materialRefs': refs, 'bindingManifest': anchor, 'budget': {**budget, 'depth': 0},
                'tools': [], 'capabilities': [], 'normalizedGoal': 'Synthetic closure check',
                'config': {'toolOrder': [], 'sample': 'Synthetic closure check', 'experimentDurationSeconds': 8}}
        fixture.service.require_current = Mock(return_value=application)
        return plan, application

    def test_selected_rows_stay_constant_as_unrelated_catalog_grows(self):
        for unrelated in (0, 100, 1000):
            with self.subTest(unrelated=unrelated):
                f = self.fixture(unrelated)
                roots, candidates = [pin(f.selected[0])], [pin(item) for item in f.selected]
                original = f.service.closure(roots)
                bounded = f.service.closure(roots, candidate_refs=candidates)
                self.assertEqual(bounded, original)
                self.assertEqual([item['id'] for item in bounded], ['selected-leaf', 'selected-middle', 'selected-root'])
                self.assertEqual(f.fetched, [3 + unrelated, 3])
                self.assertEqual(f.store.materials.call_count, 1)
                self.assertEqual(f.store.material_governance.require_materials_current.call_count, 2)

    def test_execution_guard_uses_complete_plan_pins_without_catalog_scan(self):
        f = self.fixture(1000)
        plan, application = self.plan(f)
        self.assertEqual(f.service.require_plan_current(plan), application)
        self.assertEqual(f.fetched, [3])
        f.store.materials.assert_not_called()
        f.store.material_governance.require_materials_current.assert_called_once_with(
            {'materialRefs': [pin(item) for item in reversed(f.selected)]})

    def test_execution_guard_rejects_incomplete_or_excess_pins_even_with_matching_anchor(self):
        for extra in (False, True):
            with self.subTest(extra=extra):
                f = self.fixture(1)
                plan, _ = self.plan(f)
                if extra:
                    plan['materialRefs'].append(pin(f.catalog[-1]))
                else:
                    plan['materialRefs'].pop()
                anchor = plan['bindingManifest']
                anchor['sha256'] = digest({key: value for key, value in anchor.items() if key != 'sha256'})
                with self.assertRaises(HTTPException):
                    f.service.require_plan_current(plan)
                f.store.materials.assert_not_called()
                f.store.material_governance.require_materials_current.assert_not_called()

    def test_fresh_selected_withdrawal_is_denied_after_success(self):
        f = self.fixture()
        plan, _ = self.plan(f)
        f.service.require_plan_current(plan)
        f.store.material_governance.require_materials_current.side_effect = HTTPException(409, 'Selected leaf withdrawn')
        with self.assertRaises(HTTPException) as raised:
            f.service.require_plan_current(plan)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(f.fetched, [3, 3])
        self.assertEqual(f.store.material_governance.require_materials_current.call_count, 2)

    def test_fresh_deleted_unpublished_or_tampered_leaf_is_denied(self):
        for mutation in ('delete', 'unpublish', 'tamper'):
            with self.subTest(mutation=mutation):
                f = self.fixture()
                plan, _ = self.plan(f)
                f.service.require_plan_current(plan)
                leaf = copy.deepcopy(f.selected[-1])
                with f.engine.begin() as conn:
                    if mutation == 'delete':
                        conn.execute(f.table.delete().where(f.table.c.id == leaf['id']))
                    elif mutation == 'unpublish':
                        conn.execute(f.table.update().where(f.table.c.id == leaf['id']).values(published=False))
                    else:
                        leaf['content'] = 'Tampered synthetic bytes'
                        conn.execute(f.table.update().where(f.table.c.id == leaf['id']).values(body=leaf))
                with self.assertRaises(HTTPException) as raised:
                    f.service.require_plan_current(plan)
                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(f.fetched, [3, 2 if mutation == 'delete' else 3])
                self.assertEqual(f.store.material_governance.require_materials_current.call_count, 1)
                f.store.materials.assert_not_called()

    def test_missing_extra_or_changed_candidate_pins_are_rejected_without_fallback(self):
        for mutation in ('missing', 'extra', 'digest', 'version'):
            with self.subTest(mutation=mutation):
                f = self.fixture(1)
                candidates = [pin(item) for item in f.selected]
                if mutation == 'missing':
                    candidates.pop()
                elif mutation == 'extra':
                    candidates.append(pin(f.catalog[-1]))
                else:
                    candidates[-1][mutation if mutation == 'version' else 'sha256'] = 2 if mutation == 'version' else 'b' * 64
                with self.assertRaises(HTTPException):
                    f.service.closure([pin(f.selected[0])], candidate_refs=candidates)
                f.store.materials.assert_not_called()
                f.store.material_governance.require_materials_current.assert_not_called()
                self.assertEqual(len(f.fetched), 1)

    def test_unbounded_or_malformed_candidates_are_rejected_before_query(self):
        f = self.fixture()
        for candidates in ([], [pin(f.selected[0])] * 31, [{'id': 'missing-version'}], 'not-pins'):
            with self.subTest(candidates=candidates), self.assertRaises(HTTPException):
                f.service.closure([pin(f.selected[0])], candidate_refs=candidates)
        self.assertEqual(f.fetched, [])
        f.store.materials.assert_not_called()

    def test_bounded_lookup_preserves_dependency_depth_limit(self):
        nodes = [material('depth-leaf')]
        for depth in range(8):
            nodes.insert(0, material('depth-' + str(depth), [pin(nodes[0])]))
        f = self.fixture(selected=nodes)
        for options in ({}, {'candidate_refs': [pin(item) for item in nodes]}):
            with self.subTest(bounded=bool(options)), self.assertRaises(HTTPException) as raised:
                f.service.closure([pin(nodes[0])], **options)
            self.assertIn('depth/count', str(raised.exception.detail))
        f.store.material_governance.require_materials_current.assert_not_called()

    def test_thirty_material_boundary_preserves_dfs_order(self):
        leaves = [material('count-leaf-' + str(index)) for index in range(29)]
        root = material('count-root', [pin(leaf) for leaf in leaves])
        f = self.fixture(selected=[root, *leaves])
        candidates = [pin(item) for item in f.selected]
        self.assertEqual(f.service.closure([pin(root)], candidate_refs=candidates), [*leaves, root])
        self.assertEqual(f.fetched, [30])

    def test_bounded_lookup_preserves_cycle_check(self):
        root = material('cycle-root')
        root['sha256'] = 'a' * 64
        root['dependencies'] = [pin(root)]
        f = self.fixture(selected=[root])
        with patch('agent_factory.applications.digest', return_value='a' * 64):
            with self.assertRaises(HTTPException) as raised:
                f.service.closure([pin(root)], candidate_refs=[pin(root)])
        self.assertIn('cycle', str(raised.exception.detail))
        f.store.material_governance.require_materials_current.assert_not_called()

    def test_bounded_lookup_preserves_archive_and_compatibility_checks(self):
        for field, value in (('archived', True), ('compatibility', ['other:1']), ('kind', 'unsupported')):
            with self.subTest(field=field):
                leaf = material('leaf')
                leaf[field] = value
                leaf['sha256'] = digest({key: item for key, item in leaf.items() if key not in {'sha256', 'published'}})
                f = self.fixture(selected=[leaf])
                with self.assertRaises(HTTPException) as raised:
                    f.service.closure([pin(leaf)], candidate_refs=[pin(leaf)])
                self.assertEqual(raised.exception.status_code, 409)
                f.store.material_governance.require_materials_current.assert_not_called()


if __name__ == '__main__':
    unittest.main()
