"""Research handoff assembly preserves scope, stop proof and explicit ownership."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from agent_factory.remote_handoff import PreparedHandoffService, TrustedHandoffClient
from agent_factory.store import digest
from agent_factory_research.autoresearch_profile import APPLICATION_ID
from agent_factory_research.handoff_compatibility import (
    ResearchHandoffClient, ResearchPreparedHandoffService,
)
from test_remote_scientific_evidence import receipt, scope


class HandoffCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.receiver = object.__new__(ResearchPreparedHandoffService)
        self.receiver.scientific_service = Mock()

    def test_core_has_no_scientific_routes_or_implicit_service_authority(self):
        store = SimpleNamespace(sql=Mock(), require_plan_execution=Mock())
        core = PreparedHandoffService(store, Mock(), Mock(), {})
        application = ResearchPreparedHandoffService(store, Mock(), Mock(), {})
        core_paths = {route.path for route in core.router.routes}
        app_paths = {route.path for route in application.router.routes}
        self.assertEqual(app_paths - core_paths, {
            '/api/factory/remote-handoffs/scientific-projects/{project_id}/baseline',
            '/api/factory/remote-handoffs/{identifier}/scientific-drive',
        })
        with self.assertRaises(HTTPException):
            core._validate_placement({}, {})
        with self.assertRaises(HTTPException):
            application._validate_placement({}, {})
        row = {'body': {'scientificEnvelope': {'scope': scope()}}}
        with self.assertRaises(HTTPException):
            core._placement_stopped(row, {}, {'allStopped': True}, 'completed')
        client = TrustedHandoffClient(store, Mock(), {})
        with self.assertRaises(HTTPException):
            client._validate_placement_receipt(row, {'allStopped': True}, None)

    def delegated_fixture(self):
        original_scope = scope('preparation')
        source = {'application': APPLICATION_ID, 'applicationRef': {'id': APPLICATION_ID},
            'mode': 'remote-scientific-preparation', 'tools': ['research_preparation_verify'],
            'capabilities': ['research:read'], 'delegation': {
                'parentTaskId': original_scope['originParentTaskId'],
                'rootTaskId': original_scope['originParentTaskId'], 'depth': 1}}
        candidate = {'trainPy': '# synthetic candidate'}
        original_scope.update(sourceManifestSha256=digest(source), candidateSha256=digest(candidate))
        binding = {'receiptId': 'receipt', 'ownerId': 'receiver-alice',
            'projectId': 'fixture-project', 'scope': original_scope}
        phase = {'binding': binding, 'bindingSha256': digest(binding), 'candidate': candidate}
        root = {'ownerId': 'receiver-alice', 'remoteHandoff': {'receiptId': 'receipt'}}
        conn = Mock()
        conn.execute.return_value.mappings.return_value.first.return_value = {'body': phase}
        return conn, root, source, phase

    def test_delegated_import_preserves_phase_owner_receipt_source_and_candidate_pins(self):
        conn, root, source, phase = self.delegated_fixture()
        self.receiver.validate_delegated_root(conn, root, source)
        mutations = (
            lambda value: value['binding'].update(ownerId='different-owner'),
            lambda value: value['binding'].update(receiptId='different-receipt'),
            lambda value: value['binding'].update(scope={**value['binding']['scope'], 'sourceManifestSha256': 'f' * 64}),
            lambda value: value['candidate'].update(trainPy='different candidate'),
        )
        for mutate in mutations:
            changed = deepcopy(phase)
            mutate(changed)
            # Even a self-consistent row hash cannot authorize changed pins.
            changed['bindingSha256'] = digest(changed['binding'])
            conn.execute.return_value.mappings.return_value.first.return_value = {'body': changed}
            with self.assertRaises(HTTPException):
                self.receiver.validate_delegated_root(conn, root, source)

    def test_scientific_stop_requires_original_native_and_process_gpu_release(self):
        task = {'cancel_requested': True}
        row = {'id': 'receipt', 'state': 'ACCEPTED', 'body': {'scientificEnvelope': {'scope': scope()}}}
        def observed(released):
            value = receipt(released=released)
            value['native'] = {'run_id': value['remoteRunId'], 'session_id': value['remoteTaskId'],
                'user_id': value['remoteOwnerId'], 'agent_id': 'factory-executor', 'status': 'cancelled',
                'queue': {'id': value['remoteRunId'], 'session_id': value['remoteTaskId'],
                    'user_id': value['remoteOwnerId'], 'component_id': 'factory-executor',
                    'component_type': 'agent', 'status': 'cancelled'}}
            return value
        self.assertFalse(self.receiver._placement_stopped(row, task, observed(False), 'cancelled'))
        value = observed(True)
        self.assertTrue(self.receiver._placement_stopped(row, task, value, 'cancelled'))
        value['native']['queue']['id'] = 'foreign-run'
        self.assertFalse(self.receiver._placement_stopped(row, task, value, 'cancelled'))

    def test_authority_callbacks_bind_explicit_service_after_router_construction(self):
        client = ResearchHandoffClient(SimpleNamespace(sql=Mock(), require_plan_execution=Mock()), Mock(), {})
        call, custody = client.consume_scientific_tool, client.authorize_scientific_custody
        for callback in (call, custody):
            with self.assertRaises(HTTPException) as raised:
                callback({'original': 'binding'})
            self.assertEqual(raised.exception.status_code, 503)
        client.scientific_service = Mock()
        call({'original': 'binding'})
        custody({'original': 'binding'})
        client.scientific_service.consume_remote_tool.assert_called_once_with({'original': 'binding'})
        client.scientific_service.authorize_completed_custody.assert_called_once_with({'original': 'binding'})


if __name__ == '__main__':
    unittest.main()
