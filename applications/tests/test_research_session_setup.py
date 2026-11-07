"""Optional session tools with real portable governance, without provider calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agno.db.sqlite import SqliteDb
from fastapi import HTTPException

from agent_factory.applications import ApplicationService
from agent_factory.auth import AuthService
from agent_factory.connections import ConnectionService
from agent_factory.execution_bindings import ExecutionBindings
from agent_factory.material_governance import MaterialGovernance
from agent_factory.personal_models import PersonalModels
from fixture_auth import initialize_members
from fixture_settings import Settings
from test_applications_composition import PortableCompositionStore
from research.session_setup import ResearchSessionSetup
from research.session_tools import ResearchSessionTools


class OptionalSessionToolsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.workspace = Path(directory)
        db = SqliteDb(db_file=str(self.workspace / 'setup.sqlite'))
        self.addCleanup(db.db_engine.dispose)
        settings = Settings(db_url='sqlite://', workspace=self.workspace)
        auth = AuthService(settings, db)
        initialize_members(auth)
        self.store = PortableCompositionStore(db, settings)
        bindings = ExecutionBindings(settings, self.store)
        self.store.execution_bindings = bindings
        self.connections = ConnectionService(self.store, auth)
        bindings.connections = self.connections
        self.models = PersonalModels(self.store, auth, self.connections, None)
        self.connections.owner_models = self.models
        self.models.register(bindings)
        self.store.material_governance = MaterialGovernance(self.store, auth)
        self.store.applications = ApplicationService(self.store, auth)
        self.tools = ResearchSessionTools(host_commands=False)
        for entry in [self.tools.environment_registration, *self.tools.tool_registrations]:
            bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                tool_name=entry.tool_name, permissions=entry.permissions, validator=entry.validator)
        self.setup = ResearchSessionSetup(self.store, self.connections, self.models, self.tools)
        self.model = self.models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic'}, 'configure-model')
        self.limits = {'maxTurns': 100, 'toolCallsPerTurn': 4, 'operationSeconds': 5}

    def prepare(self):
        result = self.setup.prepare('alice', self.model['connectionRef'], self.limits)
        app = self.store.applications.require_current(result['applicationRef'])
        mode = app['modes']['autonomous']
        materials = self.store.applications.closure(mode['materialRefs'])
        self.assertEqual(mode['toolOrder'], [item['content'] for item in materials if item['kind'] == 'tool'])
        return result, app, mode

    def test_conversation_without_workspace_has_evidence_but_no_file_or_command_tools(self):
        options = self.setup.options('alice')
        self.assertTrue(options['available'])
        self.assertIsNone(options['unavailableCode'])
        self.assertFalse(options['workspace']['configured'])
        result, _, mode = self.prepare()
        self.assertEqual(mode['toolOrder'], ['research_read_shared_evidence'])
        self.assertEqual(self.prepare()[0]['applicationRef'], result['applicationRef'])

    def test_workspace_and_commands_are_independently_optional_and_saved_definitions_stay_immutable(self):
        first, original, _ = self.prepare()
        self.tools.workspace_root = self.workspace
        second, _, mode = self.prepare()
        self.assertIn('research_read_file', mode['toolOrder'])
        self.assertIn('research_edit_file', mode['toolOrder'])
        self.assertNotIn('research_run', mode['toolOrder'])
        self.assertNotEqual(first['applicationRef'], second['applicationRef'])
        self.tools.host_commands = True
        third, _, mode = self.prepare()
        self.assertIn('research_run', mode['toolOrder'])
        self.assertNotEqual(second['applicationRef'], third['applicationRef'])
        self.tools.host_commands = False
        self.assertEqual(self.prepare()[0]['applicationRef'], second['applicationRef'])
        self.assertEqual(self.store.applications.require_current(first['applicationRef']), original)

    def test_model_only_selection_and_model_revocation_are_not_bypassed(self):
        self.tools.tool_registrations = ()
        _, _, mode = self.prepare()
        self.assertEqual(mode['toolOrder'], [])
        self.connections.revoke('alice', self.model['connectionRef'], 'revoke-model')
        with self.assertRaises(HTTPException):
            self.prepare()

    def test_revoked_saved_application_is_not_republished_by_capability_selection(self):
        first, _, _ = self.prepare()
        before = first['applicationRef']
        self.store.applications.withdraw('alice', before['id'], before['version'], 'withdraw-application')
        with self.assertRaises(HTTPException):
            self.prepare()
