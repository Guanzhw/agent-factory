"""Original research finalization with real SQLite content/artifacts; fake native ports."""
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select

from fixture_content_artifacts import install_artifacts
from research.workflow import Decision
from test_research_rounds import ResearchRoundsFixture


class ResearchPublicationTests(ResearchRoundsFixture):
    def setUp(self):
        super().setUp()
        self.agreement.objective = '目标' * 750
        with self.projects.db.write() as conn:
            conn.execute(self.projects.goals.update().values(agreement=self.agreement.model_dump()))
        self.start()
        install_artifacts(self.store, task_id=self.task, run_id=self.run)
        self.service.context(self.ctx)
        self.decision = Decision(action='stop', outcome='not_met', reason='分析' * 950).model_dump()
        self.service.record_decision(self.ctx, self.decision)

    def test_valid_chinese_terminal_preserves_complete_original_body(self):
        self.finish()
        self.finish()
        row = self.service.list('alice', self.project)['rounds'][0]
        self.assertIsNotNone(row['terminal'])
        content = self.content.read('bob', row['terminalRecordId'])
        self.assertEqual(content['content']['decision'], self.decision)
        self.assertEqual(content['content']['agreement']['objective'], self.agreement.objective)
        self.assertEqual(content['artifacts'], [])
        self.assertEqual(len(self.store.artifacts(self.task)), 1)
        self.events.emit.assert_not_called()

    def test_artifact_and_publication_failures_rollback_then_original_retry_finishes(self):
        for phase in ('artifact', 'publication'):
            target, method = (self.store, 'artifact_write') if phase == 'artifact' else (self.content, 'publish')
            original = getattr(target, method)
            def fail(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError('controlled post-write failure')
            with patch.object(target, method, side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, 'controlled post-write failure'):
                    self.finish()
            self.assertEqual(self.store.artifacts(self.task), [])
            self.assertEqual(self.store.events(self.task), [])
            self.assertEqual(self.content.list('alice')['items'], [])
            self.assertIsNone(self.service.list('alice', self.project)['rounds'][0]['terminal'])
        self.finish()
        self.assertEqual(len(self.store.artifacts(self.task)), 1)
        self.assertEqual(len(self.content.list('alice')['items']), 1)

    def test_true_body_budget_failure_preserves_decision_and_no_successor(self):
        self.store.settings.experiment_output_bytes = 1024
        self.finish()
        row = self.service.list('alice', self.project)['rounds'][0]
        self.assertEqual(row['terminal']['sharing'], 'publication_failed')
        self.assertEqual(row['decision'], self.decision)
        self.assertIsNone(row['terminalRecordId'])
        self.assertEqual(self.store.artifacts(self.task), [])
        self.assertEqual(self.projects.read('alice', self.project)['ending']['outcome'], 'not_met')
        self.events.emit.assert_not_called()

    def test_successor_context_reads_complete_previous_artifact_body(self):
        self.finish()
        with self.projects.db.write() as conn:
            prior = dict(conn.execute(select(self.service.rounds)).mappings().one())
            prior_id = str(uuid4())
            conn.execute(self.service.rounds.insert().values(**{
                **prior, 'id': prior_id, 'allocation_id': str(uuid4()),
                'factory_request': 'prior-original', 'task_id': str(uuid4())}))
            conn.execute(self.service.rounds.update().where(self.service.rounds.c.id == self.row['id'])
                         .values(predecessor_id=prior_id))
        previous = self.service.context(self.ctx)['sources'][0]
        self.assertEqual(previous['content']['decision'], self.decision)
        self.assertEqual(previous['content']['agreement']['objective'], self.agreement.objective)
