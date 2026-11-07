"""Exercise configuration upgrade with actual PostgreSQL and installed native pins."""
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_factory.assistant_messages import SendAssistantMessage
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.assistants import ConfigureAssistant, CreateAssistant
from research.qa_workflow import ResearchQAWorkflow
from research.setup import PrepareQASetup, PublishSetup


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class QAUpgradePostgresTests(unittest.TestCase):
    def test_new_question_upgrades_real_nested_transaction_once(self):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        directory = self.enterContext(TemporaryDirectory())
        settings = Settings(db_url=isolated.url, workspace=Path(directory), max_workers=1)
        old_workflow = ResearchQAWorkflow()
        old_workflow.registration = replace(old_workflow.registration, implementation_sha256='a' * 64)
        with patch('agent_factory_server.research.ResearchQAWorkflow', return_value=old_workflow):
            old_state = factory_state(create_app(settings))
        initialize_members(old_state['auth'])
        store = old_state['store']
        model = store.personal_models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic'}, 'upgrade-model')
        setup = old_state['research_setup']
        draft = setup.prepare_qa('alice', PrepareQASetup(requestId='original-draft', name='QA',
            modelConnectionRef=model['connectionRef']))
        published = setup.publish('alice', draft['id'], PublishSetup(requestId='original-publish'))
        service = old_state['research_assistants']
        identity = service.create('alice', CreateAssistant(requestId='original-identity'))
        configured = service.configure('alice', ConfigureAssistant(requestId='original-config', expectedRevision=0,
            applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs']))
        for engine in (store.engine, store.native_db.db_engine):
            engine.dispose()
        store.dispose_root_locks()
        state = factory_state(create_app(settings))
        current_store = state['store']
        self.addCleanup(current_store.engine.dispose)
        self.addCleanup(current_store.native_db.db_engine.dispose)
        self.addCleanup(current_store.dispose_root_locks)
        current = state['research_assistants']
        endpoint, original = current.question_target('bob', identity['id'],
            SendAssistantMessage(requestId='new-question', text='Evidence?'))
        self.assertIsNone(original)
        self.assertNotEqual(endpoint, configured['qa']['endpointId'])
        with current.db.read() as conn:
            row = current._identity(conn, identity['id'])
            self.assertEqual(row['configuration_revision'], 2)
            historical = current._configuration_row(conn, 'alice', configured['qa']['endpointId'])['body']
            upgraded = current._configuration_row(conn, 'alice', endpoint)['body']
        self.assertEqual(historical['applicationRef'], published['applicationRef'])
        self.assertIsNone(upgraded['budget']['deadline'])
        self.assertIsNone(upgraded['budget']['caps']['toolCalls'])
        second, _ = current.question_target('bob', identity['id'],
            SendAssistantMessage(requestId='another-question', text='More evidence?'))
        self.assertEqual(endpoint, second)
        self.assertFalse(state['assistant_endpoints'].owned('alice', configured['qa']['endpointId'])['enabled'])
        self.assertEqual(current_store.tasks('alice'), [])
