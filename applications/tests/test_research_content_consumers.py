"""Existing consumers receive full body objects; model context limits stay separate."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4

from agno.run import RunContext

from agent_factory.application_content import ContentPublication
from fixture_content_artifacts import artifact_ref, install_artifacts
from research.qa import ResearchQA
from research.qa_workflow import Answer
import test_research_associations as associations


class ResearchContentConsumerTests(unittest.TestCase):
    def test_long_chinese_body_reaches_qa_association_and_peer_round_inputs(self):
        fixture = associations.ResearchAssociationTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        _, run = install_artifacts(fixture.store)
        body = {'kind': 'research.experiment.start', 'hypothesis': 'measurement calibration',
                'objective': '目标' * 750, 'analysis': '分析' * 950}
        self.assertGreater(len(json.dumps(body).encode()), 16384)
        reference = artifact_ref(fixture.store, run, json.dumps(body, ensure_ascii=False).encode())
        peer = fixture.source('bob', 'measurement calibration')
        trigger = fixture.content.publish('alice', ContentPublication(source={
            'application': 'research', 'record': 'long-terminal', 'revision': '1'},
            contentArtifact=reference, visibility='team'), 'long-consumer-source')
        qa = ResearchQA(fixture.store, Mock(), Mock(), Mock(), fixture.content)
        selected = qa._select({'senderId': 'bob', 'recipientId': 'alice', 'text': 'measurement'})
        self.assertEqual(next(item['content'] for item in selected if item['id'] == trigger['id']), body)
        intent = fixture.prepare(trigger)
        ctx = RunContext(user_id='bob', session_id=str(uuid4()), run_id=str(uuid4()))
        message = {'senderId': 'alice', 'recipientId': 'bob', 'endpointId': fixture.configs['bob']['endpointId']}
        delivery = {'eventId': intent['event_id'], 'contentId': trigger['id'], 'deliveryId': str(uuid4())}
        context = fixture.service.context(ctx, message, delivery)
        self.assertEqual(next(item['content'] for item in context['sources'] if item['id'] == trigger['id']), body)
        fixture.service.record(ctx, delivery, Answer(answer='measurement calibration comparison',
            citations=[peer['id'], trigger['id']], relation='related', evidenceLevel='agent_analysis'))
        inputs = fixture.service.for_round('bob', 'next-round', 'project', SimpleNamespace(
            objective='measurement calibration', evaluation='measurement', stopConditions='done'))
        self.assertTrue(any(source['id'] == trigger['id'] and source['content'] == body
                            for item in inputs for source in item['sources']))
        fixture.content.set_visibility('alice', trigger['id'], 'personal', 'withdraw-full-body')
        self.assertFalse(fixture.sources.available('bob', fixture.sources.dependencies('next-round')))

    def test_body_above_qa_context_budget_is_not_claimed_as_model_input(self):
        fixture = associations.ResearchAssociationTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        _, run = install_artifacts(fixture.store)
        body = {'hypothesis': 'measurement', 'analysis': '分析' * 4000}
        reference = artifact_ref(fixture.store, run, json.dumps(body, ensure_ascii=False).encode())
        source = fixture.content.publish('alice', ContentPublication(source={
            'application': 'research', 'record': 'over-context', 'revision': '1'},
            contentArtifact=reference, visibility='team'), 'over-qa-context')
        qa = ResearchQA(fixture.store, Mock(), Mock(), Mock(), fixture.content)
        self.assertEqual(qa._select({'senderId': 'bob', 'recipientId': 'alice', 'text': 'measurement'}), [])
        self.assertEqual(fixture.content.read('bob', source['id'])['content'], body)
