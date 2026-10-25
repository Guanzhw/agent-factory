"""Real sharing and source retention; synthetic event/admission ports."""
from types import MethodType, SimpleNamespace
import asyncio
import hashlib
import json
from unittest.mock import Mock
from uuid import uuid4

from agno.run import RunContext
from fastapi import HTTPException
from sqlalchemy import Column, JSON, LargeBinary, MetaData, String, Table, select

from agent_factory.application_content import ApplicationContent, ContentPublication
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from research.associations import ResearchAssociations
from research.peer_sources import ResearchPeerSources
from research.qa_workflow import Answer
from research.workflow import Decision
import test_applications_composition as fixtures
import test_research_rounds as round_fixtures


class ResearchAssociationTests(fixtures.ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.store.transaction = MethodType(Store.transaction, self.store)
        self.content = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.sources = ResearchPeerSources(self.store, self.content)
        self.assistants = Mock(auth=self.auth)
        self.configs = {owner: {'endpointId': str(uuid4()), 'associations': {'enabled': True, 'maxRecipients': 2},
                               'budget': {'deadline': 9999999999.0}} for owner in ('alice', 'bob')}
        self.assistants.association_configuration.side_effect = self.configs.get
        self.events = Mock()
        self.events.emit.side_effect = lambda *args, **kw: {'id': str(uuid4())}
        self.service = ResearchAssociations(self.sources, self.assistants, self.events)

    def source(self, owner, words, *, visibility='team'):
        return self.content.publish(owner, ContentPublication(source={'application': 'research',
            'record': str(uuid4()), 'revision': 'start'}, content={'kind': 'research.experiment.start',
            'hypothesis': words}, visibility=visibility), 'publish:' + str(uuid4()))

    def prepare(self, trigger):
        with self.sources.db.write() as conn:
            self.service.prepare(conn, trigger['ownerId'], trigger['id'])
            return dict(conn.execute(select(self.service.intents).where(
                self.service.intents.c.content_id == trigger['id'])).mappings().one())

    def pair(self):
        peer = self.source('bob', 'measurement calibration canary-original')
        trigger = self.source('alice', 'measurement calibration new attempt')
        intent = self.prepare(trigger)
        ctx = RunContext(user_id='bob', session_id=str(uuid4()), run_id=str(uuid4()))
        message = {'senderId': 'alice', 'recipientId': 'bob', 'endpointId': self.configs['bob']['endpointId']}
        delivery = {'eventId': intent['event_id'], 'contentId': trigger['id'], 'deliveryId': str(uuid4())}
        value = self.service.context(ctx, message, delivery)
        return peer, trigger, ctx, message, delivery, value

    def test_relevant_pair_single_original_event_no_broadcast_and_no_match_silent(self):
        self.source('bob', 'private calibration canary', visibility='personal')
        self.source('bob', 'astronomy telescopes')
        no_match = self.source('alice', 'measurement calibration')
        empty = self.prepare(no_match)
        self.assertEqual(empty['candidates'], [])
        self.events.emit.assert_not_called()
        match = self.source('bob', 'measurement calibration')
        self.prepare(no_match)
        self.events.emit.assert_not_called()  # A replay never expands an empty original choice.
        trigger = self.source('alice', 'measurement calibration')
        original = self.prepare(trigger)
        self.assertEqual([c['contentId'] for c in original['candidates']], [match['id']])
        self.assertEqual(self.prepare(trigger), original)
        self.assertEqual(self.events.emit.call_count, 1)
        self.assertEqual(self.events.emit.call_args.args[2].candidates, [self.configs['bob']['endpointId']])

    def test_derived_answer_records_all_inputs_replay_and_uncited_source_withdrawal(self):
        peer, trigger, ctx, message, delivery, value = self.pair()
        ids = [source['id'] for source in value['sources']]
        self.assertEqual(set(ids), {peer['id'], trigger['id']})
        with self.assertRaises(HTTPException):
            self.service.record(ctx, delivery, Answer(answer='Incomplete citations', citations=[peer['id']],
                relation='related', evidenceLevel='agent_analysis'))
        answer = Answer(answer='measurement canary analysis', citations=ids, relation='related', evidenceLevel='agent_analysis')
        result = self.service.record(ctx, delivery, answer)
        self.assertEqual(self.service.record(ctx, delivery, answer), result)
        self.assertIn('canary', self.service.read('alice', result['associationId'])['analysis']['answer'])
        self.content.set_visibility('bob', peer['id'], 'personal', 'revoke-peer')
        with self.assertRaises(HTTPException):
            self.service.read('alice', result['associationId'])
        self.assertEqual(self.service.list('alice')['items'], [])
        with self.assertRaises(HTTPException):
            self.service.context(ctx, message, delivery)
        self.assertEqual(self.events.emit.call_count, 1)

    def test_all_rich_fields_and_successor_union_retain_original_sources(self):
        peer, trigger, ctx, _, delivery, value = self.pair()
        result = self.service.record(ctx, delivery, Answer(answer='measurement calibration useful evidence',
            citations=[s['id'] for s in value['sources']], relation='related', evidenceLevel='agent_analysis'))
        agreement = SimpleNamespace(objective='measurement', evaluation='calibration', stopConditions='complete')
        selected = self.service.for_round('alice', 'round-one', 'project', agreement)
        self.assertEqual({item['id'] for item in selected}, {peer['id'], result['associationId']})
        full = self.sources.dependencies('round-one')
        self.assertEqual(set(full), {peer['id'], trigger['id']})
        body = {'kind': 'research.round.terminal', 'projectId': 'project', 'roundId': 'round-one',
                'hypothesis': 'canary hypothesis', 'conditions': 'canary conditions',
                'decision': {'goal': 'canary goal'}, 'experiment': {'output': 'canary output'},
                'ending': {'reason': 'canary ending'}, 'artifacts': [{'name': 'canary filename'}]}
        publication = self.sources.publication('alice', 'round-one', 'round-one', 'terminal', body)
        self.assertIn('canary', str(self.content.read('bob', publication)))
        self.service.for_round('alice', 'round-two', 'project', agreement)
        self.assertEqual(self.sources.dependencies('round-two'), full)
        self.content.set_visibility('bob', peer['id'], 'personal', 'withdraw-for-successor')
        with self.assertRaises(HTTPException):
            self.content.read('alice', publication)
        with self.assertRaises(HTTPException):
            self.service.for_round('alice', 'round-two', 'project', agreement)
        self.assertEqual(self.sources.dependencies('round-two'), full)

    def test_not_related_is_an_original_outcome_not_a_new_message(self):
        _, _, ctx, _, delivery, value = self.pair()
        result = self.service.record(ctx, delivery, Answer(answer='Conditions make this evidence irrelevant.',
            citations=[s['id'] for s in value['sources']], relation='not_related', evidenceLevel='agent_analysis'))
        self.assertEqual(result['state'], 'not_related')
        self.assertEqual(self.service.list('alice')['items'], [])
        self.assertEqual(self.events.emit.call_count, 1)

    def test_inherited_sources_are_not_truncated_to_the_display_window(self):
        originals = [self.source('bob', 'independent source ' + str(i))['id'] for i in range(10)]
        self.sources.bind('prior-round', 'long-project', originals, [])
        self.service.for_round('alice', 'next-round', 'long-project',
            SimpleNamespace(objective='unrelated', evaluation='criteria', stopConditions='bounded'))
        self.assertEqual(set(self.sources.dependencies('next-round')), set(originals))
        self.content.set_visibility('bob', originals[-1], 'personal', 'withdraw-last-not-first-eight')
        with self.assertRaises(HTTPException):
            self.service.for_round('alice', 'next-round', 'long-project',
                SimpleNamespace(objective='unrelated', evaluation='criteria', stopConditions='bounded'))

    def test_selected_artifact_uses_core_original_source_authority_not_owner_proxy(self):
        original = self.source('bob', 'measurement original source')
        self.sources.bind('artifact-round', 'artifact-project', [original['id']], [])
        metadata = MetaData()
        tasks = Table('af_tasks', metadata, Column('id', String, primary_key=True), Column('owner_id', String), Column('run_id', String))
        artifacts = Table('af_artifacts', metadata, Column('id', String, primary_key=True),
            Column('task_id', String), Column('body', JSON), Column('content', LargeBinary))
        metadata.create_all(self.store.engine)
        task, artifact = str(uuid4()), str(uuid4())
        raw = b'peer-derived selected artifact canary'
        sha = hashlib.sha256(raw).hexdigest()
        with self.store.transaction() as conn:
            conn.execute(tasks.insert().values(id=task, owner_id='alice', run_id=str(uuid4())))
            conn.execute(artifacts.insert().values(id=artifact, task_id=task, content=raw,
                body={'id': artifact, 'jobId': task, 'name': 'selected.txt', 'mediaType': 'text/plain',
                      'size': len(raw), 'sha256': sha, 'createdAt': 'fixture'}))
        def sql(store, statement, **params):
            rows = Store.sql(store, statement, **params)
            for row in rows:
                if isinstance(row.get('body'), str):
                    row['body'] = json.loads(row['body'])
            return rows
        self.store.sql = MethodType(sql, self.store)
        self.store.task = MethodType(Store.task, self.store)
        self.store.artifact = MethodType(Store.artifact, self.store)
        publication = self.sources.publication('alice', 'artifact-round', 'artifact-round', 'terminal',
            {'kind': 'research.round.terminal', 'roundId': 'artifact-round', 'analysis': 'canary'},
            artifacts=[{'taskId': task, 'artifactId': artifact, 'sha256': sha}])
        self.assertEqual(self.content.artifact('bob', publication, artifact)[1], raw)
        self.content.set_visibility('bob', original['id'], 'personal', 'revoke-artifact-source')
        with self.assertRaises(HTTPException):
            self.content.artifact('alice', publication, artifact)


class ResearchPeerConsumerTests(round_fixtures.ResearchRoundsFixture):
    def setUp(self):
        super().setUp()
        self.sources = ResearchPeerSources(self.store, self.content)
        assistants = Mock(auth=self.auth)
        assistants.association_configuration.return_value = None
        self.associations = ResearchAssociations(self.sources, assistants, self.events)
        self.service.associations, self.service.peer_sources = self.associations, self.sources
        self.projects.peer_sources = self.sources
        self.peer = self.content.publish('bob', ContentPublication(source={'application': 'research',
            'record': str(uuid4()), 'revision': '1'}, visibility='team',
            content={'kind': 'research.experiment.start', 'hypothesis': self.agreement.objective + ' canary'}), 'peer-original')
        self.association_id = str(uuid4())
        with self.sources.db.write() as conn:
            conn.execute(self.associations.analyses.insert().values(id=self.association_id, task_id=str(uuid4()),
                run_id=str(uuid4()), delivery_id=str(uuid4()), owner_id='bob', sender_id='alice',
                content_ids=[self.peer['id']], source_ids=[self.peer['id']], created_at='2026-10-25',
                answer={'answer': self.agreement.objective + ' use prior measurement', 'citations': [self.peer['id']],
                        'evidenceLevel': 'agent_analysis', 'relation': 'related'}))
        self.start()

    def chosen(self):
        return Decision(action='experiment', reason='Use the observed condition', evidenceIds=[self.peer['id']],
            hypothesis='canary hypothesis', conditions='canary condition', goal='canary-informed actual measurement',
            sourceAssessments=[{'contentId': self.peer['id'], 'disposition': 'reproduce',
                                'reason': 'Confirm under the new evaluation conditions'}])

    def test_source_to_decision_to_original_action_and_all_projections_on_withdrawal(self):
        context = self.service.context(self.ctx)
        self.assertEqual(context['peerEvidence'][0]['sources'][0]['id'], self.peer['id'])
        operation = {'id': str(uuid4()), 'taskId': self.task, 'nativeRunId': self.run, 'closed': True,
                     'observation': {'state': 'COMPLETED', 'output': {'result': 'canary actual output'}}}
        self.custody.start.return_value = operation
        self.custody.read.return_value = operation
        asyncio.run(self.service.launch(self.ctx, self.chosen()))
        self.assertEqual(self.custody.start.await_args.args[4]['goal'], self.chosen().goal)
        self.service.record_decision(self.ctx, {'action': 'stop', 'outcome': 'not_met', 'reason': 'canary ending',
            'evidenceIds': [operation['id']], 'sourceAssessments': [item.model_dump() for item in self.chosen().sourceAssessments]})
        self.finish()
        self.assertIn('canary', str([item for item in self.content.list('bob')['items'] if item['id'] != self.peer['id']]))
        self.assertIn('canary', str(self.service.list('alice', self.project)))
        self.content.set_visibility('bob', self.peer['id'], 'personal', 'revoke-consumed-evidence')
        self.assertNotIn('canary', str(self.service.list('alice', self.project)))
        self.assertNotIn('canary', str(self.projects.read('alice', self.project)))
        self.assertEqual(self.count(self.legacy.attempts), 1)

    def test_revoke_before_attempt_admission_prevents_new_effect(self):
        self.service.context(self.ctx)
        self.content.set_visibility('bob', self.peer['id'], 'personal', 'revoke-before-admission')
        with self.assertRaises(HTTPException):
            asyncio.run(self.service.launch(self.ctx, self.chosen()))
        self.custody.start.assert_not_awaited()
        self.assertEqual(self.count(self.legacy.attempts), 0)

    def test_direct_original_record_reaches_research_without_any_association(self):
        with self.sources.db.write() as conn:
            conn.execute(self.associations.analyses.delete())
        unrelated = self.content.publish('bob', ContentPublication(source={'application': 'research',
            'record': str(uuid4()), 'revision': '1'}, visibility='team',
            content={'hypothesis': 'astronomy telescope unrelated'}), 'unrelated-original')
        context = self.service.context(self.ctx)
        displayed = {source['id'] for item in context['peerEvidence'] for source in item['sources']}
        self.assertEqual(displayed, {self.peer['id']})
        self.assertNotIn(unrelated['id'], context['evidenceIds'])
        self.custody.start.return_value = {'id': str(uuid4())}
        asyncio.run(self.service.launch(self.ctx, self.chosen()))
        self.assertEqual(self.custody.start.await_args.args[4]['goal'], self.chosen().goal)

    def test_revoke_after_original_intent_admission_does_not_recall_authorized_operation(self):
        self.service.context(self.ctx)
        async def original_operation(*args):
            self.assertEqual(self.count(self.legacy.attempts), 1)
            self.content.set_visibility('bob', self.peer['id'], 'personal', 'revoke-after-admission')
            return {'id': str(uuid4())}
        self.custody.start.side_effect = original_operation
        result = asyncio.run(self.service.launch(self.ctx, self.chosen()))
        self.assertIsNotNone(result['id'])
        self.assertEqual(self.count(self.legacy.attempts), 1)
        self.custody.start.assert_awaited_once()
