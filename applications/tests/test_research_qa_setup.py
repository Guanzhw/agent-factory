"""Portable QA governance and native rejection; synthetic execution ports, no provider IO."""
import asyncio
from copy import deepcopy
import json
import httpx
from agent_factory.byok_model import OwnerChatModel
from research.qa_workflow import ResearchQAWorkflow
from research.qa import ResearchQA
from research.setup import ResearchSetup, PrepareQASetup, PublishSetup
from research.assistants import ConfigureAssistant, CreateAssistant, ResearchAssistants
from contextlib import nullcontext
from unittest.mock import Mock, patch
from fastapi import HTTPException
import unittest
from sqlalchemy import select
import test_research_setup as fixtures


class ResearchQASetupTests(unittest.TestCase):
    def setUp(self):
        fixtures.ResearchSetupTests.setUp(self)
        self.setup = ResearchSetup(self.store, self.auth, self.connections, self.models)

    database = fixtures.ResearchSetupTests.database
    no_dispatch = fixtures.ResearchSetupTests.no_dispatch

    def publish_qa(self, tool_calls=4):
        qa = ResearchQAWorkflow()
        self.setup.qa_workflow = qa
        for registration in (*qa.tool_registrations, qa.environment_registration):
            self.bindings.register(registration.kind, registration.adapter_id, registration.revision,
                self.no_dispatch, tool_name=registration.tool_name, permissions=registration.permissions)
        self.pin.update(id='research-qa')
        model = self.models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic'}, 'qa-model-config')
        draft = self.setup.prepare_qa('alice', PrepareQASetup(requestId='qa-prepare-original', name='QA',
            modelConnectionRef=model['connectionRef'], budget={'toolCalls': tool_calls}))
        result = self.setup.publish('alice', draft['id'], PublishSetup(requestId='qa-publish-original'))
        return qa, model, draft, result

    def assistant_service(self, qa):
        self.store.connections = self.connections
        endpoints, scopes = Mock(), Mock()
        endpoints.db.write.side_effect = lambda: nullcontext()
        endpoints.configure.return_value = {'id': 'original-qa-endpoint'}
        service = ResearchAssistants(self.store, self.auth, endpoints, Mock(), scopes,
            pin=self.pin, tool_registrations=qa.tool_registrations, environment_registration=qa.environment_registration)
        service.create('alice', CreateAssistant(requestId='create-budget-owner'))
        return service, endpoints, scopes

    @staticmethod
    def allowance(published):
        caps = {'rounds': 1, 'toolCalls': 2}
        return ConfigureAssistant(requestId='minimum-usable-qa', expectedRevision=0,
            applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs'],
            budget={'caps': caps, 'perQuestionCaps': caps, 'deadline': 9999999999.0})

    def test_publish_exact_qa_without_experiment_or_compute(self):
        qa, model, draft, result = self.publish_qa()
        app = self.apps.require_current(result['applicationRef'])
        self.assertEqual(set(app['modes']), {'qa'})
        mode = app['modes']['qa']
        self.assertEqual(mode['nativeComponent'], self.pin)
        self.assertEqual(set(mode['toolOrder']), {'research_qa_context', 'research_qa_record'})
        self.assertEqual(result['mode'], 'qa')
        self.assertEqual(self.setup.publish('alice', draft['id'], PublishSetup(requestId='qa-publish-original')), result)
        self.assertNotIn(model['connectionRef'], str(app))
        self.assertEqual(self.setup.candidates('alice')['qaMinimumToolCalls'], len(qa.tool_registrations))

    def test_configuration_rejects_insufficient_processing_budget_before_any_execution(self):
        qa, _, _, published = self.publish_qa(tool_calls=2)
        service, endpoints, scopes = self.assistant_service(qa)
        for total, per_question in ((1, 1), (2, 1)):
            with self.subTest(total=total, per_question=per_question):
                caps = {'rounds': 1, 'toolCalls': total}
                body = ConfigureAssistant(requestId=f'insufficient-{total}-{per_question}', expectedRevision=0,
                    applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs'],
                    budget={'caps': caps, 'perQuestionCaps': {**caps, 'toolCalls': per_question}, 'deadline': 9999999999.0})
                with self.assertRaises(HTTPException) as rejected:
                    service.configure('alice', body)
                self.assertEqual(rejected.exception.detail, 'RESEARCH_QA_BUDGET_INSUFFICIENT')
                scopes.create_scope.assert_not_called()
                endpoints.configure.assert_not_called()
        caps = {'rounds': 1, 'toolCalls': len(qa.tool_registrations)}
        body = ConfigureAssistant(requestId='minimum-usable-qa', expectedRevision=0,
            applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs'],
            budget={'caps': caps, 'perQuestionCaps': caps, 'deadline': 9999999999.0})
        with patch.object(service, '_availability', return_value={'available': True}):
            saved = service.configure('alice', body)
        self.assertEqual(saved['qa']['budget']['perQuestionCaps']['toolCalls'], len(qa.tool_registrations))
        self.assertEqual(saved['configurationRevision'], 1)
        scopes.create_scope.assert_called_once()
        endpoints.configure.assert_called_once()

    def test_legacy_one_call_configuration_is_unavailable_and_rejected_before_native_model(self):
        qa, _, _, published = self.publish_qa(tool_calls=2)
        service, endpoints, scopes = self.assistant_service(qa)
        allowance = self.allowance(published)
        with patch.object(service, '_availability', return_value={'available': True}):
            original = service.configure('alice', allowance)
        with service.db.write() as conn:
            row = service._configuration_row(conn, 'alice', 'original-qa-endpoint')
            legacy = deepcopy(row['body'])
            legacy['budget']['perQuestionCaps']['toolCalls'] = 1
            conn.execute(service.configurations.update().where(service.configurations.c.assistant_id == original['id'],
                service.configurations.c.revision == 1).values(body=legacy))
        endpoints.resolve.return_value = {'applicationRef': published['applicationRef'],
            'defaults': {'connectionRefs': published['connectionRefs']},
            'automaticBudget': {'scopeId': original['qa']['scopeId'], 'caps': legacy['budget']['perQuestionCaps']}}
        scopes.inspect.return_value = {'caps': legacy['budget']['caps'], 'allocatedRounds': 0,
                                      'heldToolCalls': 0, 'settledToolCalls': 0}
        self.assertEqual(service.me('alice')['assistant']['qa']['unavailableCode'], 'RESEARCH_QA_BUDGET_INSUFFICIENT')
        endpoints.configure.return_value = {'id': 'replacement-endpoint'}
        with patch.object(service, '_availability', return_value={'available': True}):
            replacement = service.configure('alice', allowance.model_copy(update={
                'requestId': 'replace-qa-configuration', 'expectedRevision': 1}))
        self.assertEqual(replacement['qa']['endpointId'], 'replacement-endpoint')
        endpoints.resolve.reset_mock()
        endpoints.resolve.side_effect = HTTPException(409, 'Old endpoint disabled after replacement')
        self.store.task = Mock(return_value={'plan_id': 'original-plan'})
        self.store.plan = Mock(return_value={'budget': {'toolCalls': 2}})
        runs, messages = Mock(), Mock()
        runs.request.return_value = {'taskId': 'original-task', 'runId': 'original-run'}
        messages.message_for_task.return_value = {'messageId': 'original-message', 'senderId': 'bob',
            'recipientId': 'alice', 'endpointId': 'original-qa-endpoint', 'text': 'Prior experience?'}
        messages.read.return_value = {'reply': None}
        consumer = ResearchQA(self.store, service, messages, runs, Mock())
        qa.bind(consumer)
        wire = Mock(return_value=httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'content': json.dumps({'answer': 'Insufficient shared evidence.',
                'citations': [], 'evidenceLevel': 'agent_analysis'})}}]}))
        qa.registration.component.steps[1].agent.model = OwnerChatModel({'provider': 'openai-compatible',
            'model': 'synthetic-qa', 'baseURL': 'http://localhost:8899/v1'}, lambda: None,
            transport_factory=lambda: httpx.MockTransport(wire))
        with patch.object(consumer, '_select') as select_sources:
            try:
                result = asyncio.run(qa.registration.component.arun({'goal': 'Prior experience?'},
                    user_id='alice', session_id='original-task', run_id='original-run',
                    session_state={'factory_envelope': {'request_id': 'application-start:original-question'}}))
            except Exception as error:
                self.assertIn('RESEARCH_QA_BUDGET_INSUFFICIENT', str(error))
            else:
                self.assertIn('RESEARCH_QA_BUDGET_INSUFFICIENT', str(result))
            select_sources.assert_not_called()
        wire.assert_not_called()
        messages.reply_for_task.assert_not_called()
        endpoints.resolve.assert_not_called()
        self.assertEqual(service.configuration_for_endpoint('alice', 'original-qa-endpoint'), {
            'id': original['id'], 'revision': 1, 'endpointId': 'original-qa-endpoint'})
        with consumer.db.read() as conn:
            self.assertEqual(conn.execute(select(consumer.inputs)).mappings().all(), [])
        with service.db.read() as conn:
            self.assertEqual(service._configuration_row(conn, 'alice', 'original-qa-endpoint')['body'], legacy)

    def test_original_plan_budget_is_checked_without_current_endpoint_or_budget_changes(self):
        qa, _, _, published = self.publish_qa(tool_calls=2)
        service, endpoints, _ = self.assistant_service(qa)
        with patch.object(service, '_availability', return_value={'available': True}):
            saved = service.configure('alice', self.allowance(published))
        self.store.task = Mock(return_value={'plan_id': 'original-plan'})
        self.store.plan = Mock(return_value={'budget': {'toolCalls': 1}})
        with self.assertRaises(HTTPException) as rejected:
            service.require_question_budget('alice', saved['qa']['endpointId'], 'original-task')
        self.assertEqual(rejected.exception.detail, 'RESEARCH_QA_BUDGET_INSUFFICIENT')
        self.store.plan.return_value['budget']['toolCalls'] = 2
        service.require_question_budget('alice', saved['qa']['endpointId'], 'original-task')
        endpoints.resolve.assert_not_called()
        self.store.task.assert_called_with('original-task', 'alice')
        self.store.plan.assert_called_with('original-plan', 'alice')
