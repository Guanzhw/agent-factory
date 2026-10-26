"""Portable curated snapshots; mocked budgets/native ports do not prove admission."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import func, select

from research.projects import ProjectCommand
from research_history_fixture import seed_legacy_intent
import test_research_runs as fixtures


class ResearchRecordsTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.ResearchRunsTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.agreement = self.base.confirm()
        self.command = ProjectCommand(requestId='record-original-start', expectedVersion=1)

    def prepare(self):
        if not hasattr(self, 'original'):
            self.original = seed_legacy_intent(self.base.runs, 'alice', self.base.project, self.command, self.agreement)
        return self.base.runs._prepare('alice', self.base.project, self.command)

    def test_start_snapshot_is_curated_team_readable_and_replay_preserves_revocation(self):
        base = self.base
        intent = self.prepare()
        record = base.content.read('bob', intent['startRecordId'])
        self.assertEqual(record['visibility'], 'team')
        self.assertEqual(record['verificationStatus'], 'unverified')
        self.assertEqual(record['content'], {'kind': 'research.experiment.start', 'state': 'pending_admission',
            'projectId': base.project, 'goalVersion': 1, 'experimentId': intent['experimentId'],
            'attemptId': intent['attemptId'], 'objective': self.agreement.objective,
            'conditions': {'evaluation': self.agreement.evaluation, 'stopConditions': self.agreement.stopConditions}})
        self.assertNotIn('existing-model-reference', str(record))
        self.assertNotIn('execution', record['content'])
        with self.assertRaises(HTTPException):
            base.projects.read('bob', base.project)
        with self.assertRaises(HTTPException):
            base.content.set_visibility('bob', record['id'], 'personal', 'peer-edit')
        base.content.set_visibility('alice', record['id'], 'personal', 'author-revoke')
        self.assertEqual(self.prepare(), intent)
        with self.assertRaises(HTTPException):
            base.content.read('bob', record['id'])
        with base.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(base.content.contents)).scalar(), 1)
        base.native.start.assert_not_called()

    def test_new_round_binding_failure_rolls_back_domain_intent(self):
        from test_research_rounds import ResearchRoundsFixture
        base = ResearchRoundsFixture('runTest')
        self.addCleanup(base.doCleanups)
        base.setUp()
        with patch.object(base.scopes, 'bind_request', side_effect=RuntimeError('synthetic binding failure')):
            with self.assertRaisesRegex(RuntimeError, 'binding failure'):
                base.start()
        with base.store.engine.connect() as conn:
            for table in (base.legacy.commitments, base.service.rounds, base.legacy.experiments,
                          base.legacy.attempts, base.content.contents, base.content.commands):
                self.assertEqual(conn.execute(select(func.count()).select_from(table)).scalar(), 0)
        base.native.start.assert_not_called()
        self.assertIsNotNone(base.start()['roundId'])
