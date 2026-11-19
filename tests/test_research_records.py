"""Research notes need neither command receipts nor a completed experiment."""
from copy import deepcopy
from contextvars import ContextVar
import json
from types import SimpleNamespace
import unittest
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine, select
from fastapi import HTTPException

from agent_factory.application_content import ApplicationContent, ContentPublication, ContentSource
from agent_factory.personal_tool_contract import ToolInvocationError
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from research.qa import ResearchQA
from research.session_research import ResearchSessionResearch


class ResearchRecords(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        self.session = {'id': 'session', 'body': {'goal': 'Review existing results', 'boundaries': ''}}
        self.context = SimpleNamespace(user_id='alice', session_id='task', run_id='run')
        sessions = SimpleNamespace(store=SimpleNamespace(engine=self.engine, task_for_context=lambda context: {'id': 'task'}),
            db=SimpleNamespace(read=self.engine.connect, write=self.engine.begin),
            record_sources=lambda context, sources: None,
            _execution=lambda conn, context: (self.session, None, None))
        self.publications = {}
        self.visibility = {}

        def publish(owner, publication, key):
            key = str(uuid5(NAMESPACE_URL, key))
            self.visibility[key] = publication.visibility
            self.publications.setdefault(key, deepcopy(publication.content))
            return {'id': key}

        self.research = ResearchSessionResearch(sessions, None, SimpleNamespace(publish=publish,
            readable_ids=lambda readers, identifiers: set(identifiers)))

    async def test_record_file_and_external_output_without_command_effects(self):
        values = {'observations': ['File reports 42 samples; external run reports one failure.'],
                  'evidenceIds': ['results/data.csv', 'https://example.org/results/1']}
        record = await self.research.invoke(self.context, 'note', 'research_record_experiment', values)
        repeated = await self.research.invoke(self.context, 'note', 'research_record_experiment', values)
        self.assertEqual(record, repeated)
        self.assertEqual(record['status'], 'recorded')
        self.assertEqual(set(self.visibility.values()), {'team'})
        self.assertEqual(record['observations'], values['observations'])
        self.assertEqual(len(self.publications), 1)
        self.assertEqual(next(iter(self.publications.values()))['verificationStatus'], 'unverified')
        with self.assertRaises(ToolInvocationError):
            await self.research.invoke(self.context, 'note', 'research_record_experiment',
                                       {**values, 'observations': ['Different request']})
        other = SimpleNamespace(user_id='bob', session_id='task', run_id='run')
        with self.assertRaises(ToolInvocationError):
            await self.research.invoke(other, 'read', 'research_experiment_result',
                                       {'experimentId': record['experimentId']})

    async def test_explicit_privacy_is_specific_to_this_revision(self):
        shared = await self.research.invoke(self.context, 'publish', 'research_record_experiment',
            {'visibility': 'team', 'observations': ['Published by request']})
        self.assertEqual(self.visibility[shared['terminalRecordId']], 'team')
        assessment = await self.research.invoke(self.context, 'note', 'research_assess',
            {'visibility': 'personal', 'experimentId': shared['experimentId'], 'assessment': 'Private interpretation'})
        self.assertEqual(self.visibility[assessment['recordId']], 'personal')

    async def test_unconfirmed_original_experiment_returns_identity_without_redispatch(self):
        values = {'hypothesis': 'A hypothesis', 'conditions': 'Existing input', 'goal': 'Inspect it'}
        row, _ = self.research._create(self.context, 'lost-child', 'research_experiment', values, self.session)
        self.research.store.sql = lambda *args, **kwargs: []
        result = await self.research.invoke(self.context, 'lost-child', 'research_experiment', values)
        self.assertEqual(result['experimentId'], row['id'])
        self.assertEqual(result['outcome'], 'unknown')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(self.publications, {})
        independent = await self.research.invoke(self.context, 'independent', 'research_assess',
                                                  {'assessment': 'Review available evidence while waiting.'})
        self.assertEqual(independent['verificationStatus'], 'agent_analysis')

    async def test_standalone_analysis_and_retry(self):
        values = {'assessment': 'The available results are inconclusive.',
                  'observations': ['Only one sample was supplied.'], 'evidenceIds': ['notes.txt']}
        result = await self.research.invoke(self.context, 'analysis', 'research_assess', values)
        self.assertEqual(result['verificationStatus'], 'agent_analysis')
        self.assertEqual(result['evidenceIds'], ['notes.txt'])
        self.assertEqual(self.research.reconcile(self.context, 'analysis', 'research_assess', values), result)
        self.assertEqual(await self.research.invoke(self.context, 'analysis', 'research_assess', values), result)
        self.assertEqual(len(self.publications), 1)
        row = self.research._row('alice', 'session', result['experimentId'])
        self.assertEqual(self.research._recover(row), result)
        stored = await self.research.invoke(self.context, 'read', 'research_experiment_result',
                                            {'experimentId': result['experimentId']})
        self.assertEqual(stored['status'], 'recorded')
        self.assertIn('run:analysis', stored['assessments'])

    async def test_result_only_projects_currently_readable_research(self):
        saved = await self.research.invoke(self.context, 'base', 'research_record_experiment',
                                           {'observations': ['Original private measurement']})
        source = '00000000-0000-4000-8000-000000000001'
        visible = {source}
        self.research.content.read = lambda owner, identifier: {'sourceContentIds': []}
        self.research.content.readable_ids = lambda readers, identifiers: (visible | self.publications.keys()).intersection(identifiers)
        self.session['body']['sharedSourceIds'] = [source]
        await self.research.invoke(self.context, 'derived', 'research_assess', {
            'experimentId': saved['experimentId'], 'assessment': 'Peer-dependent interpretation'})
        derived = await self.research.invoke(self.context, 'peer-note', 'research_record_experiment',
                                             {'observations': ['Peer-dependent measurement']})
        self.session['body']['sharedSourceIds'] = []
        visible.clear()
        base = await self.research.invoke(self.context, 'read-base', 'research_experiment_result',
                                          {'experimentId': saved['experimentId']})
        self.assertEqual(base['observations'], ['Original private measurement'])
        self.assertEqual(base['assessments'], {})
        result = await self.research.invoke(self.context, 'read-note', 'research_experiment_result',
                                            {'experimentId': derived['experimentId']})
        self.assertEqual(result, {'experimentId': derived['experimentId'], 'sourceUnavailable': True})
        with self.assertRaises(ToolInvocationError):
            await self.research.invoke(self.context, 'new-analysis', 'research_assess',
                {'experimentId': derived['experimentId'], 'assessment': 'Would inherit the old observations'})
        receipt = self.research.reconcile(self.context, 'derived', 'research_assess', {
            'experimentId': saved['experimentId'], 'assessment': 'Peer-dependent interpretation'})
        self.assertEqual(receipt, {'experimentId': saved['experimentId'], 'sourceUnavailable': True})
        visible.add(source)
        recorded = []
        self.research.sessions.record_sources = lambda context, sources: recorded.extend(sources)
        result = await self.research.invoke(self.context, 'again', 'research_experiment_result',
                                            {'experimentId': derived['experimentId']})
        self.assertEqual(result['observations'], ['Peer-dependent measurement'])
        self.assertEqual(recorded, [source])

    async def test_analysis_of_nonterminal_legacy_record_preserves_facts(self):
        table = self.research.experiments
        body = {'status': 'running', 'evidenceIds': ['old-child'], 'hypothesis': 'Legacy hypothesis',
                'conditions': 'Legacy conditions', 'toolName': 'research_experiment',
                'runId': 'old-run', 'callId': 'old-call', 'request': {}}
        with self.engine.begin() as conn:
            conn.execute(table.insert().values(id='legacy', owner_id='alice', session_id='session',
                                               task_id='old-task', body=body))
        result = await self.research.invoke(self.context, 'interim', 'research_assess', {
            'experimentId': 'legacy', 'assessment': 'Interim analysis, not a final result.',
            'evidenceIds': ['interim.csv'], 'observations': ['Trend is still uncertain.']})
        with self.engine.connect() as conn:
            stored = conn.execute(select(table.c.body).where(table.c.id == 'legacy')).scalar_one()
        self.assertEqual(stored['status'], 'running')
        self.assertEqual(stored['evidenceIds'], ['old-child'])
        self.assertNotIn('terminalRecordId', stored)
        self.assertEqual(result['evidenceIds'], ['interim.csv'])
        publication = next(iter(self.publications.values()))
        self.assertEqual(publication['evidenceIds'], ['interim.csv'])
        self.assertEqual(publication['observations'], ['Trend is still uncertain.'])


class FormalResearchSharing(unittest.IsolatedAsyncioTestCase):
    """Use the actual publication, ownership and colleague-Assistant search paths."""
    def setUp(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        store = Store.__new__(Store)
        store.engine, store._connection = engine, ContextVar('connection', default=None)
        store.task_for_context = lambda context: {'id': context.session_id}
        auth = SimpleNamespace(require_member=lambda owner: None)
        self.content = ApplicationContent(store, auth, ResourceSharing(store, auth))
        self.session = {'id': 'session', 'body': {'goal': 'private-draft-marker', 'boundaries': 'private-chat-marker'}}
        self.context = SimpleNamespace(user_id='alice', session_id='task', run_id='run')
        self.sessions = SimpleNamespace(store=store, db=SimpleNamespace(read=engine.connect, write=engine.begin),
            _execution=lambda conn, context: (self.session, None, None), record_sources=lambda *args: None)
        self.research = ResearchSessionResearch(self.sessions, None, self.content)
        self.qa = ResearchQA(store, None, None, None, self.content)

    def search(self, query=''):
        # A new colleague question uses both members' current read permissions.
        context = SimpleNamespace(user_id='bob', session_id=str(uuid5(NAMESPACE_URL, query)), run_id='qa-run')
        message = {'text': query or 'selected-marker', 'messageId': context.session_id,
                   'senderId': 'bob', 'recipientId': 'alice', 'hasReply': False}
        self.qa._original = lambda ctx: (message, {})
        return self.qa.context(context, query=query)['sources']

    async def record(self, call='formal', **values):
        return await self.research.invoke(self.context, call, 'research_record_experiment', values)

    async def test_formal_record_search_read_and_author_only_changes(self):
        record = await self.record(hypothesis='selected-marker hypothesis', conditions='selected-marker conditions',
            observations=['selected-marker conclusion'], evidenceIds=['selected.csv'])
        identifier = record['terminalRecordId']
        peer = self.content.read('bob', identifier)
        self.assertEqual(peer['visibility'], 'team')
        self.assertFalse(peer['isOwner'])
        self.assertEqual(peer['content']['conditions'], 'selected-marker conditions')
        self.assertEqual(peer['content']['evidenceIds'], ['selected.csv'])
        self.assertEqual(peer['artifacts'], [])
        self.assertEqual([item['id'] for item in self.search()], [identifier])
        self.assertNotIn('private-', json.dumps(peer))
        with self.assertRaises(HTTPException):
            self.content.artifact('bob', identifier, 'unselected-private-attachment')
        with self.assertRaises(HTTPException):
            self.content.set_visibility('bob', identifier, 'personal', 'peer-edit-attempt')
        with self.assertRaises(ToolInvocationError):
            await self.research.invoke(SimpleNamespace(user_id='bob', session_id='peer-task', run_id='peer-run'),
                'edit', 'research_assess', {'experimentId': record['experimentId'], 'assessment': 'Overwrite'})
        self.assertEqual(self.content.read('alice', identifier)['content'], peer['content'])

    async def test_private_record_and_existing_visibility_survive_reopen_and_retry(self):
        values = {'observations': ['private-result-marker'], 'evidenceIds': ['private-log.txt']}
        private = await self.record('old-private', visibility='personal', **values)
        # Reconstruct a pre-fix receipt whose omitted visibility meant personal.
        table = self.research.experiments
        with self.sessions.store.engine.begin() as conn:
            body = deepcopy(conn.execute(select(table.c.body).where(table.c.id == private['experimentId'])).scalar_one())
            body['request'] = values
            conn.execute(table.update().where(table.c.id == private['experimentId']).values(body=body))
        shared = await self.record(observations=['selected-marker'])
        self.research = ResearchSessionResearch(self.sessions, None, self.content)
        self.assertEqual(await self.record('old-private', **values), private)
        self.assertEqual(self.content.read('alice', private['terminalRecordId'])['visibility'], 'personal')
        self.assertEqual(self.content.read('bob', shared['terminalRecordId'])['visibility'], 'team')
        with self.assertRaises(HTTPException):
            self.content.read('bob', private['terminalRecordId'])
        results = self.search('private-result-marker')
        self.assertNotIn(private['terminalRecordId'], [item['id'] for item in results])
        self.assertNotIn('private-result-marker', json.dumps(results))

    async def test_assessments_publish_only_selected_content_and_follow_original_withdrawal(self):
        base = await self.record(observations=['selected-marker base'], evidenceIds=['base.csv', 'other-selected.csv'])
        assessment = await self.research.invoke(self.context, 'assessment', 'research_assess', {
            'experimentId': base['experimentId'], 'assessment': 'selected-marker interpretation',
            'evidenceIds': ['selected-review.csv']})
        published = self.content.read('bob', assessment['recordId'])
        self.assertEqual(published['content']['evidenceIds'], ['selected-review.csv'])
        self.assertEqual(published['content']['observations'], [])
        self.assertIn(base['terminalRecordId'], published['sourceContentIds'])
        private = await self.research.invoke(self.context, 'private-assessment', 'research_assess', {
            'experimentId': base['experimentId'], 'visibility': 'personal', 'assessment': 'private-analysis-marker'})
        with self.assertRaises(HTTPException):
            self.content.read('bob', private['recordId'])
        independent = await self.research.invoke(self.context, 'independent', 'research_assess',
            {'assessment': 'selected-marker independent'})
        self.content.set_visibility('alice', base['terminalRecordId'], 'personal', 'withdraw-formal-record')
        for identifier in (base['terminalRecordId'], assessment['recordId']):
            with self.assertRaises(HTTPException):
                self.content.read('bob', identifier)
        self.assertEqual([item['id'] for item in self.search('independent')], [independent['recordId']])
        self.assertEqual(self.content.team_evidence({'alice', 'bob'}, 'research',
            identifiers=[base['terminalRecordId'], assessment['recordId']])['items'], [])

    async def test_private_and_transitive_sources_never_enter_peer_search(self):
        private = await self.record('private-base', visibility='personal', observations=['private-base-marker'])
        derived = await self.research.invoke(self.context, 'derived-private', 'research_assess', {
            'experimentId': private['experimentId'], 'assessment': 'selected-marker based on private work'})
        self.assertEqual(self.content.read('alice', derived['recordId'])['content']['observations'], [])
        with self.assertRaises(HTTPException):
            self.content.read('bob', derived['recordId'])
        self.assertEqual(self.search(), [])
        root = self.content.publish('bob', ContentPublication(
            source=ContentSource(application='research', record='root', revision='1'),
            content={'text': 'selected-marker source'}, visibility='team'), 'publish-source-root')
        self.session['body']['sharedSourceIds'] = [root['id']]
        dependent = await self.record('dependent', observations=['selected-marker derived'])
        self.content.read('bob', dependent['terminalRecordId'])
        self.content.set_visibility('bob', root['id'], 'personal', 'withdraw-source-root')
        self.assertEqual(self.content.team_evidence({'alice', 'bob'}, 'research',
            identifiers=[dependent['terminalRecordId']])['items'], [])
        with self.assertRaises(HTTPException):
            self.content.read('alice', dependent['terminalRecordId'])


if __name__ == '__main__':
    unittest.main()
