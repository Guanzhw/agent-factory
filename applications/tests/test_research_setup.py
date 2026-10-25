"""Actual portable governance/owner bindings; no provider or GPU calls."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.db.sqlite import SqliteDb
from fastapi import HTTPException
from sqlalchemy import select, func

from agent_factory.applications import ApplicationService
from agent_factory.auth import AuthService
from agent_factory.config import Settings
from agent_factory.connections import ConnectionService
from agent_factory.execution_bindings import ExecutionBindings
from agent_factory.material_governance import MaterialGovernance
from agent_factory.personal_models import PersonalModels
from test_applications_composition import PortableCompositionStore
from applications.research.setup import ResearchSetup, PrepareSetup, PublishSetup
from applications.research.workflow import FUNCTION_TOOLS, WORKFLOW_ID


class ResearchSetupTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db = self.database(directory.name)
        self.addCleanup(db.db_engine.dispose)
        settings = Settings(db_url='sqlite://', workspace=Path(directory.name))
        self.auth = AuthService(settings, db)
        self.auth.initialize_demo()
        self.store = PortableCompositionStore(db, settings)
        self.bindings = ExecutionBindings(settings, self.store)
        self.store.execution_bindings = self.bindings
        self.connections = ConnectionService(self.store, self.auth)
        self.bindings.connections = self.connections
        self.models = PersonalModels(self.store, self.auth, self.connections, None)
        self.connections.owner_models = self.models
        self.models.register(self.bindings)
        self.pin = {'kind': 'workflow', 'id': WORKFLOW_ID, 'revision': '1', 'sha256': 'a' * 64}
        self.store.native_workflows = SimpleNamespace(pin=lambda _: deepcopy(self.pin))
        self.controllers = []
        for name in [*FUNCTION_TOOLS, 'factory_wait_operations', 'synthetic_compute']:
            registration = self.bindings.register('tool', name.replace('_', '-') + '-v1', '1', self.no_dispatch,
                tool_name=name, permissions=('research:execute',))
            if name != 'synthetic_compute':
                self.controllers.append(registration)
        self.bindings.register('environment', 'synthetic-environment-v1', '1', self.no_dispatch)
        self.governance = MaterialGovernance(self.store, self.auth)
        self.store.material_governance = self.governance
        self.apps = ApplicationService(self.store, self.auth)
        self.store.applications = self.apps
        self.setup = ResearchSetup(self.store, self.auth, self.connections, self.models, controller_registrations=self.controllers)

    def database(self, directory):
        return SqliteDb(db_file=str(Path(directory) / 'setup.sqlite'))

    def no_dispatch(self, _):
        self.fail('Setup must never instantiate an execution adapter')

    def configure(self):
        self.model = self.models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic'}, 'configure-alice')
        tool = self.governance.create_draft('alice', {'kind': 'tool', 'name': 'Synthetic compute',
            'content': 'synthetic_compute', 'permissions': ['research:execute'],
            'runtimeBinding': {'adapterId': 'synthetic-compute-v1', 'revision': '1', 'config': {}}}, 'create-compute')
        self.governance.publish('alice', tool['id'], tool['version'], 'publish-compute')
        self.body = PrepareSetup(requestId='prepare-original', name='Research configuration',
            modelConnectionRef=self.model['connectionRef'], environment={'adapterId': 'synthetic-environment-v1', 'revision': '1'},
            experimentMaterialRefs=[self.apps.pin(tool)], budget={'toolCalls': 16})

    def counts(self):
        with self.store.engine.connect() as conn:
            return tuple(conn.execute(select(func.count()).select_from(table)).scalar()
                for table in (self.store.material_table, self.apps.versions, self.setup.drafts, self.setup.commands))

    def test_empty_read_does_not_seed_or_expose_credentials(self):
        before = self.counts()
        self.assertEqual(self.setup.candidates('alice')['models'], [])
        self.assertEqual(self.setup.candidates('alice')['experimentMaterials'], [])
        self.assertEqual(self.counts(), before)
        self.configure()
        candidates = self.setup.candidates('alice')
        self.assertEqual(candidates['models'][0]['connectionRef'], self.model['connectionRef'])
        self.assertEqual(candidates['connections'][0]['ref'], self.model['connectionRef'])
        self.assertNotIn('credentialRef', candidates['models'][0])

    def test_explicit_publish_recovery_and_two_owner_same_materials(self):
        self.configure()
        before = self.counts()
        draft = self.setup.prepare('alice', self.body)
        self.assertIsNone(draft['applicationRef'])
        self.assertEqual(self.counts()[:2], before[:2])
        self.assertEqual(self.setup.prepare('alice', self.body), draft)
        result = self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-original'))
        after = self.counts()
        fresh = ResearchSetup(self.store, self.auth, self.connections, self.models, controller_registrations=self.controllers)
        self.assertEqual(fresh.request_result('alice', 'publish-original'), result)
        self.assertEqual(fresh.publish('alice', draft['id'], PublishSetup(requestId='publish-original')), result)
        self.assertEqual(self.counts(), after)
        app = self.apps.require_current(result['applicationRef'])
        self.assertNotIn(self.model['connectionRef'], str(app))
        materials = self.apps.closure(app['modes']['research']['materialRefs'])
        self.assertNotIn(self.model['connectionRef'], str(materials))
        bob = self.models.configure('bob', {'provider': 'openai-compatible', 'baseURL': 'http://localhost:8899/v1',
            'model': 'synthetic-bob'}, 'configure-bob')
        for owner, ref in [('alice', self.model['connectionRef']), ('bob', bob['connectionRef'])]:
            pins = {'model': self.connections.preflight(owner, ref, 'model', required_capabilities=['model:invoke'])}
            self.assertEqual(self.bindings.preflight(materials, owner, pins), [])
        self.connections.revoke('bob', bob['connectionRef'], 'revoke-bob')
        self.assertTrue(self.bindings.preflight(materials, 'bob', pins))

    def test_cross_owner_changed_request_and_preview_are_rejected(self):
        self.configure()
        draft = self.setup.prepare('alice', self.body)
        for call in (lambda: self.setup.read('bob', draft['id']),
                lambda: self.setup.publish('bob', draft['id'], PublishSetup(requestId='publish-bob')),
                lambda: self.setup.prepare('alice', self.body.model_copy(update={'name': 'changed'}))):
            with self.assertRaises(HTTPException):
                call()
        self.pin['sha256'] = 'b' * 64
        before = self.counts()
        with self.assertRaisesRegex(HTTPException, 'RESEARCH_SETUP_PREVIEW_CHANGED'):
            self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-original'))
        self.assertEqual(self.counts(), before)

    def test_partial_publication_rolls_back_and_same_command_can_recover(self):
        self.configure()
        draft = self.setup.prepare('alice', self.body)
        before = self.counts()
        with patch.object(self.apps, 'publish', side_effect=HTTPException(409, 'synthetic failure')):
            with self.assertRaises(HTTPException):
                self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-original'))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.setup.read('alice', draft['id'])['state'], 'draft')
        self.assertEqual(self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-original'))['state'], 'published')

    def test_unavailable_real_environment_does_not_fall_back(self):
        self.configure()
        self.bindings.withdraw('environment', 'synthetic-environment-v1', '1')
        self.assertEqual(self.setup.candidates('alice')['environments'], [])
        before = self.counts()
        with self.assertRaisesRegex(HTTPException, 'RESEARCH_SETUP_ADAPTER_UNAVAILABLE'):
            self.setup.prepare('alice', self.body)
        self.assertEqual(self.counts(), before)

    def test_revoked_model_and_foreign_owner_ref_cannot_publish(self):
        self.configure()
        draft = self.setup.prepare('alice', self.body)
        before = self.counts()
        self.connections.revoke('alice', self.model['connectionRef'], 'revoke-alice')
        with self.assertRaises(HTTPException):
            self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-original'))
        self.assertEqual(self.counts(), before)
        with self.assertRaises(HTTPException):
            self.setup.prepare('bob', self.body)

    def test_environment_extra_configuration_is_not_silently_invented(self):
        self.configure()
        self.bindings.withdraw('environment', 'synthetic-environment-v1', '1')
        def validator(config):
            if 'runtime' not in config:
                raise ValueError('Explicit runtime configuration required')
        self.bindings.register('environment', 'synthetic-environment-v1', '1', self.no_dispatch, validator=validator)
        draft = self.setup.prepare('alice', self.body)
        before = self.counts()
        with self.assertRaises(HTTPException) as raised:
            self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-original'))
        self.assertEqual(raised.exception.detail['code'], 'RESEARCH_SETUP_BINDINGS_UNAVAILABLE')
        self.assertEqual(self.counts(), before)
