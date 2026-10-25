"""Real PG identity/configuration atomicity; synthetic model, no model calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import time
from types import MethodType
import unittest
from unittest.mock import patch

from agno.db.postgres import PostgresDb
from fastapi import HTTPException
from sqlalchemy import func, select

from agent_factory.assistant_endpoints import AssistantEndpoints
from agent_factory.assistant_messages import AssistantMessages, SendAssistantMessage
from agent_factory.local_budget_scopes import LocalBudgetScopes
from agent_factory.store import Store
from agent_factory.usage_ledger import UsageLedger
from pg_fixture import IsolatedPostgres
from research.assistants import ConfigureAssistant, CreateAssistant, ResearchAssistants
from research.qa_workflow import ResearchQAWorkflow
from research.setup import PrepareQASetup, PublishSetup
import test_research_setup as fixtures


class Admission:
    def __init__(self):
        self.calls = []
        self.receipts = {}

    async def start(self, owner, body, **options):
        self.calls.append((owner, body, options))
        self.receipts[(owner, body.requestId)] = {'state': 'unknown', 'taskId': 'original-native-task', 'runId': None}

    def request(self, owner, request_id):
        if (owner, request_id) not in self.receipts:
            raise HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND')
        return self.receipts[(owner, request_id)]


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchAssistantsPostgresTests(unittest.TestCase):
    no_dispatch = fixtures.ResearchSetupTests.no_dispatch

    def database(self, _directory):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        return PostgresDb(db_url=isolated.url)

    def setUp(self):
        fixtures.ResearchSetupTests.setUp(self)
        self.store.transaction = MethodType(Store.transaction, self.store)
        self.store.sql = MethodType(Store.sql, self.store)
        Store.initialize(self.store)
        self.store.connections = self.connections
        self.scopes = LocalBudgetScopes(self.store, UsageLedger(self.store))
        self.store.local_budget_scopes = self.scopes
        self.endpoints = AssistantEndpoints(self.store, self.auth, self.apps)
        self.admission = Admission()
        self.messages = AssistantMessages(self.store, self.auth, self.endpoints, self.admission)
        qa = ResearchQAWorkflow()
        self.setup.qa_workflow = qa
        self.pin.update(id='research-qa')
        for registration in (*qa.tool_registrations, qa.environment_registration):
            self.bindings.register(registration.kind, registration.adapter_id, registration.revision,
                self.no_dispatch, tool_name=registration.tool_name, permissions=registration.permissions)
        model = self.models.configure('alice', {'provider': 'openai-compatible', 'baseURL': 'http://localhost:8899/v1',
            'model': 'synthetic'}, 'configure-qa-model')
        draft = self.setup.prepare_qa('alice', PrepareQASetup(requestId='prepare-qa-original', name='QA',
            modelConnectionRef=model['connectionRef'], budget={'toolCalls': 4}))
        published = self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-qa-original'))
        self.service = ResearchAssistants(self.store, self.auth, self.endpoints, self.messages, self.scopes,
            pin=self.pin, tool_registrations=qa.tool_registrations, environment_registration=qa.environment_registration)
        caps = {'rounds': 3, 'toolCalls': 12, 'tokenLimit': 300, 'amountMicros': 30, 'currency': 'USD'}
        self.configuration = ConfigureAssistant(requestId='configure-first', expectedRevision=0,
            applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs'],
            budget={'caps': caps, 'perQuestionCaps': {**caps, 'rounds': 1, 'toolCalls': 4, 'tokenLimit': 100, 'amountMicros': 10},
                'deadline': time.time() + 300})

    def counts(self):
        with self.store.engine.connect() as conn:
            return tuple(conn.execute(select(func.count()).select_from(table)).scalar() for table in
                (self.service.identities, self.service.configurations, self.endpoints.endpoints, self.scopes.scopes,
                 self.scopes.allocations, self.messages.messages))

    def test_unique_owner_creation_and_configuration_compare_and_swap(self):
        barrier = Barrier(2)
        def create(index):
            barrier.wait(timeout=5)
            return self.service.create('alice', CreateAssistant(requestId=f'create-assistant-{index}'))
        with ThreadPoolExecutor(max_workers=2) as pool:
            created = list(pool.map(create, range(2)))
        self.assertEqual(created[0]['id'], created[1]['id'])
        barrier = Barrier(2)
        def configure(index):
            barrier.wait(timeout=5)
            try:
                return self.service.configure('alice', self.configuration.model_copy(update={'requestId': f'configure-race-{index}'}))
            except HTTPException as error:
                return error
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(configure, range(2)))
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        failures = [value for value in results if isinstance(value, HTTPException)]
        self.assertEqual(failures[0].detail, 'RESEARCH_ASSISTANT_REVISION_CONFLICT')
        self.assertEqual(self.counts(), (1, 1, 1, 1, 0, 0))

    def test_new_configuration_rolls_back_scope_endpoint_and_old_enabled_state(self):
        self.service.create('alice', CreateAssistant(requestId='create-assistant'))
        first = self.service.configure('alice', self.configuration)
        before = self.counts()
        original = self.endpoints.set_enabled
        def fail_after_disable(*args, **kwargs):
            original(*args, **kwargs)
            raise HTTPException(409, 'synthetic failure after disable')
        second = self.configuration.model_copy(update={'requestId': 'configure-second', 'expectedRevision': 1})
        with patch.object(self.endpoints, 'set_enabled', side_effect=fail_after_disable):
            with self.assertRaises(HTTPException):
                self.service.configure('alice', second)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.service.me('alice')['assistant'], first)
        self.assertTrue(self.endpoints.resolve(first['qa']['endpointId'])['enabled'])
        self.assertEqual(self.service.configure('alice', second)['configurationRevision'], 2)

    def test_lost_question_receipt_survives_configuration_change_without_new_allocation(self):
        identity = self.service.create('alice', CreateAssistant(requestId='create-assistant'))
        first = self.service.configure('alice', self.configuration)
        body = SendAssistantMessage(requestId='original-question', text='What evidence is available?')
        message = asyncio.run(self.service.question('bob', identity['id'], body))
        self.service.configure('alice', self.configuration.model_copy(update={'requestId': 'configure-second', 'expectedRevision': 1}))
        before = self.counts()
        self.assertEqual(asyncio.run(self.service.question('bob', identity['id'], body)), message)
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(self.admission.calls), 1)
        self.assertEqual(message['endpointId'], first['qa']['endpointId'])
        self.assertEqual(self.service.configuration_for_endpoint('alice', message['endpointId'])['revision'], 1)
        self.assertFalse(self.endpoints.owned('alice', message['endpointId'])['enabled'])
        self.assertEqual(self.service.list('bob')['items'][0]['qaAvailable'], True)
        self.auth.directory.set_disabled('alice', True)
        self.assertEqual(asyncio.run(self.service.question('bob', identity['id'], body)), message)
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(self.admission.calls), 1)
        with self.assertRaises(HTTPException):
            self.service.configuration_for_endpoint('alice', message['endpointId'])
