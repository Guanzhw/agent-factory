"""Selected material closure is checked fresh without authorizing unrelated catalog rows."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from agent_factory.applications import ApplicationService
from agent_factory.store import digest


def material(identifier, dependencies=()):
    body = {'id': identifier, 'version': 1, 'kind': 'skill', 'content': 'Synthetic public fixture',
        'compatibility': ['agno:3.1.0'], 'dependencies': list(dependencies), 'published': True}
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


if __name__ == '__main__':
    unittest.main()
