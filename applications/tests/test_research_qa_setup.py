"""Portable QA governance and native rejection; synthetic execution ports, no provider IO."""
from research.qa_workflow import ResearchQAWorkflow
from research.setup import ResearchSetup, PrepareQASetup, PublishSetup
from research.assistants import ConfigureAssistant, CreateAssistant, ResearchAssistants
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock, patch
import unittest
import asyncio
from fastapi import HTTPException
from agent_factory.assistant_messages import SendAssistantMessage
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
        self.assertEqual(self.setup.candidates('alice')['qaAvailable'], True)

    def test_configuration_needs_no_budget_or_expiry_and_replays_exact_request(self):
        qa, _, _, published = self.publish_qa(tool_calls=None)
        service, endpoints, scopes = self.assistant_service(qa)
        body = ConfigureAssistant(requestId='qa-without-budget', expectedRevision=0,
            applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs'])
        with patch.object(service, '_availability', return_value={'available': True}):
            saved = service.configure('alice', body)
            self.assertEqual(service.configure('alice', body), saved)
        self.assertEqual(saved['qa']['budget']['caps']['rounds'], None)
        self.assertEqual(saved['qa']['budget']['perQuestionCaps']['toolCalls'], None)
        self.assertEqual(saved['qa']['budget']['deadline'], None)
        scopes.create_scope.assert_called_once()
        endpoints.configure.assert_called_once()

    def test_legacy_small_expired_allowance_does_not_hide_available_assistant(self):
        qa, _, _, published = self.publish_qa(tool_calls=1)
        service, endpoints, scopes = self.assistant_service(qa)
        body = ConfigureAssistant(requestId='qa-legacy-budget', expectedRevision=0,
            applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs'],
            budget={'caps': {'rounds': 1, 'toolCalls': 1},
                    'perQuestionCaps': {'rounds': 1, 'toolCalls': 1}, 'deadline': 1.0})
        with patch.object(service, '_availability', return_value={'available': True}):
            saved = service.configure('alice', body)
        endpoints.resolve.return_value = {'applicationRef': published['applicationRef'],
            'defaults': {'connectionRefs': published['connectionRefs']},
            'automaticBudget': {'scopeId': saved['qa']['scopeId'], 'caps': saved['qa']['budget']['perQuestionCaps']}}
        self.assertTrue(service.me('alice')['assistant']['qa']['available'])
        scopes.inspect.assert_not_called()

    def test_answer_accepts_long_text_and_more_than_eight_citations(self):
        from research.qa_workflow import Answer
        answer = Answer(answer='Detailed result. ' * 1000, citations=[str(i) for i in range(30)],
                        evidenceLevel='agent_analysis')
        self.assertGreater(len(answer.answer), 2000)
        self.assertEqual(len(answer.citations), 30)

    def test_new_question_upgrades_old_pin_once_without_replaying_old_question(self):
        qa, _, _, published = self.publish_qa()
        service, endpoints, _ = self.assistant_service(qa)
        with patch.object(service, '_availability', return_value={'available': True}):
            saved = service.configure('alice', self.allowance(published))
        original_config = saved['qa']
        service.setup = self.setup
        self.pin['sha256'] = 'b' * 64
        endpoints.owned.return_value = {'enabled': True,
            'automaticBudget': {'scopeId': original_config['scopeId'], 'caps': original_config['budget']['perQuestionCaps']},
            'applicationRef': published['applicationRef'], 'defaults': {'connectionRefs': published['connectionRefs']}}
        endpoints.configure.return_value = {'id': 'upgraded-endpoint'}
        service.messages.request.side_effect = HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        service.messages.send = AsyncMock(return_value={'id': 'new-message'})
        body = SendAssistantMessage(requestId='new-after-upgrade', text='New question')
        with patch.object(service, '_availability', return_value={'available': True}):
            self.assertEqual(asyncio.run(service.question('bob', saved['id'], body)), {'id': 'new-message'})
        service.messages.send.assert_awaited_once_with('bob', 'upgraded-endpoint', body)
        with service.db.read() as conn:
            current = service._identity(conn, saved['id'])
            self.assertEqual(current['configuration_revision'], 2)
            old = service._configuration_row(conn, 'alice', 'original-qa-endpoint')['body']
            new = service._configuration_row(conn, 'alice', 'upgraded-endpoint')['body']
        self.assertEqual(old['applicationRef'], original_config['applicationRef'])
        self.assertEqual(self.apps.require_current(new['applicationRef'])['modes']['qa']['nativeComponent'], self.pin)
        asyncio.run(service.question('bob', saved['id'], body.model_copy(update={'requestId': 'second-new-question'})))
        self.assertEqual(service.messages.send.await_count, 2)
        self.assertEqual(endpoints.configure.call_count, 2)
        original = {'recipientId': 'alice', 'endpointId': 'original-qa-endpoint', 'text': 'Old question'}
        service.messages.request.side_effect = None
        service.messages.request.return_value = original
        old_body = SendAssistantMessage(requestId='old-request-id', text='Old question')
        self.assertEqual(asyncio.run(service.question('bob', saved['id'], old_body)), original)
        self.assertEqual(service.messages.send.await_count, 2)
        self.assertEqual(endpoints.configure.call_count, 2)

    def test_upgrade_does_not_reenable_a_disabled_assistant(self):
        qa, _, _, published = self.publish_qa()
        service, endpoints, _ = self.assistant_service(qa)
        with patch.object(service, '_availability', return_value={'available': True}):
            saved = service.configure('alice', self.allowance(published))
        service.setup = self.setup
        self.pin['sha256'] = 'b' * 64
        endpoints.owned.return_value = {'enabled': False}
        service.messages.request.side_effect = HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        with self.assertRaises(HTTPException) as denied:
            service.question_target('bob', saved['id'], SendAssistantMessage(requestId='new-question-id', text='Question'))
        self.assertEqual(denied.exception.detail, 'ASSISTANT_ENDPOINT_DISABLED')
        self.assertEqual(endpoints.configure.call_count, 1)

    def test_upgrade_does_not_publish_when_model_is_unavailable(self):
        qa, _, _, published = self.publish_qa()
        service, endpoints, _ = self.assistant_service(qa)
        with patch.object(service, '_availability', return_value={'available': True}):
            saved = service.configure('alice', self.allowance(published))
        service.setup = self.setup
        self.pin['sha256'] = 'b' * 64
        endpoints.owned.return_value = {'enabled': True}
        service.messages.request.side_effect = HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        with patch.object(self.connections, 'preflight', side_effect=HTTPException(409, 'MODEL_UNAVAILABLE')),                 patch.object(self.setup, 'prepare_qa') as prepare, self.assertRaises(HTTPException):
            service.question_target('bob', saved['id'], SendAssistantMessage(requestId='unavailable-model', text='Question'))
        prepare.assert_not_called()
        self.assertEqual(endpoints.configure.call_count, 1)
