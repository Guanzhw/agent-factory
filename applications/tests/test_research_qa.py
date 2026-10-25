"""Portable actual sharing boundaries; synthetic execution ports, no live model."""
import asyncio
import json

import httpx
from types import MethodType
from unittest.mock import Mock
from uuid import uuid4

from agno.run import RunContext
from fastapi import HTTPException

from agent_factory.byok_model import OwnerChatModel
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.application_content import ApplicationContent, ContentPublication
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from research.qa import ResearchQA
from research.qa_workflow import Answer, ResearchQAWorkflow
import test_applications_composition as fixtures


class ResearchQATests(fixtures.ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.store.transaction = MethodType(Store.transaction, self.store)
        self.content = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.assistants, self.messages, self.runs = Mock(), Mock(), Mock()
        self.task, self.run, self.message = (str(uuid4()) for _ in range(3))
        self.ctx = RunContext(user_id='alice', session_id=self.task, run_id=self.run,
            session_state={'factory_envelope': {'request_id': 'application-start:original-question'}})
        self.runs.request.return_value = {'taskId': self.task, 'runId': self.run}
        self.messages.message_for_task.return_value = {'messageId': self.message, 'senderId': 'bob',
            'recipientId': 'alice', 'endpointId': 'original-qa', 'text': 'measurement'}
        self.assistants.configuration_for_endpoint.return_value = {'id': 'stable', 'revision': 1, 'endpointId': 'original-qa'}
        self.service = ResearchQA(self.store, self.assistants, self.messages, self.runs, self.content)

    def source(self, name, *, visibility='team', application='research'):
        return self.content.publish('alice', ContentPublication(source={'application': application,
            'record': name, 'revision': '1'}, content={'conclusion': 'measurement ' + name}, visibility=visibility),
            'publish-' + name)

    def test_full_input_set_not_model_citations_controls_reply(self):
        a, b = self.source('first'), self.source('second')
        self.source('private-canary', visibility='personal')
        self.source('other-app-canary', application='other')
        ctx = self.service.context(self.ctx)
        self.assertEqual({x['id'] for x in ctx['sources']}, {a['id'], b['id']})
        self.assertNotIn('canary', str(ctx))
        self.source('new-after-original-context')
        self.assertEqual(self.service.context(self.ctx), ctx)
        self.service.record(self.ctx, Answer(answer='Analysis of measurement.', citations=[a['id']], evidenceLevel='agent_analysis'))
        args = self.messages.reply_for_task.call_args
        self.assertEqual(set(args.kwargs['content_ids']), {a['id'], b['id']})
        self.assertEqual(args.args[:2], ('alice', self.task))
        self.messages.send.assert_not_called()

    def test_replay_rechecks_uncited_source_and_foreign_run(self):
        source = self.source('revoked')
        self.service.context(self.ctx)
        self.content.set_visibility('alice', source['id'], 'personal', 'withdraw-original')
        with self.assertRaises(HTTPException):
            self.service.context(self.ctx)
        self.ctx.run_id = 'foreign'
        with self.assertRaises(HTTPException):
            self.service.record(self.ctx, Answer(answer='No evidence.', citations=[], evidenceLevel='agent_analysis'))
        self.messages.reply_for_task.assert_not_called()

    def test_empty_evidence_and_unknown_citation(self):
        self.assertTrue(self.service.context(self.ctx)['search']['insufficientEvidence'])
        with self.assertRaises(HTTPException):
            self.service.record(self.ctx, Answer(answer='Invented answer', citations=[str(uuid4())], evidenceLevel='agent_analysis'))
        self.messages.reply_for_task.assert_not_called()

    def test_non_message_task_is_rejected_before_context_or_reply(self):
        self.messages.message_for_task.return_value = None
        with self.assertRaises(HTTPException) as denied:
            self.service.context(self.ctx)
        self.assertEqual(denied.exception.detail, 'RESEARCH_QA_ORIGINAL_MESSAGE_REQUIRED')
        self.assistants.configuration_for_endpoint.assert_not_called()
        self.messages.reply_for_task.assert_not_called()

    def test_native_model_has_no_tools_or_structured_provider_requirement(self):
        workflow = ResearchQAWorkflow().registration.component
        steps = workflow.steps
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[1].agent.tools, [])
        self.assertIsNone(steps[1].agent.output_schema)
        self.assertIn('JSON', str(steps[1].agent.instructions))

    def test_actual_owner_model_text_wire_reaches_local_answer_validation(self):
        calls = []
        def wire(request):
            body = json.loads(request.content)
            calls.append(body)
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': json.dumps({'answer': 'Insufficient shared evidence.',
                    'citations': [], 'evidenceLevel': 'agent_analysis'})}}],
                'usage': {'prompt_tokens': 15, 'completion_tokens': 8, 'total_tokens': 23}})
        agent = ResearchQAWorkflow().registration.component.steps[1].agent
        agent.model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'synthetic-qa',
            'baseURL': 'http://localhost:8899/v1'}, lambda: SecretLease('api-key', 'synthetic-only'),
            transport_factory=lambda: httpx.MockTransport(wire))
        output = asyncio.run(agent.arun(json.dumps({'question': 'measurement', 'sources': []})))
        parsed = Answer.model_validate_json(output.content)
        self.assertEqual(parsed.citations, [])
        self.assertEqual(len(calls), 1)
        self.assertNotIn('response_format', calls[0])
        self.assertNotIn('tools', calls[0])
