"""Research notes need neither command receipts nor a completed experiment."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from sqlalchemy import create_engine, select

from agent_factory.personal_tool_contract import ToolInvocationError
from research.session_research import ResearchSessionResearch


class ResearchRecords(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        self.session = {'id': 'session', 'body': {'goal': 'Review existing results', 'boundaries': ''}}
        self.context = SimpleNamespace(user_id='alice', session_id='task', run_id='run')
        sessions = SimpleNamespace(store=SimpleNamespace(engine=self.engine, task_for_context=lambda context: {'id': 'task'}),
            db=SimpleNamespace(read=self.engine.connect, write=self.engine.begin),
            _execution=lambda conn, context: (self.session, None, None))
        self.publications = {}

        def publish(owner, publication, key):
            self.publications.setdefault(key, deepcopy(publication.content))
            return {'id': key}

        self.research = ResearchSessionResearch(sessions, None, SimpleNamespace(publish=publish))

    async def test_record_file_and_external_output_without_command_effects(self):
        values = {'observations': ['File reports 42 samples; external run reports one failure.'],
                  'evidenceIds': ['results/data.csv', 'https://example.org/results/1']}
        record = await self.research.invoke(self.context, 'note', 'research_record_experiment', values)
        repeated = await self.research.invoke(self.context, 'note', 'research_record_experiment', values)
        self.assertEqual(record, repeated)
        self.assertEqual(record['status'], 'recorded')
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


if __name__ == '__main__':
    unittest.main()
