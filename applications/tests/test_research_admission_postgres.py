"""Real Research HTTP/native persistence; synthetic model, no cross-version execution claim."""
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select

from research.projects import Agreement, CreateProject, ProjectCommand, ReviseGoal
import test_research_workflow_postgres as native


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ResearchAdmissionPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = native.ResearchNativeWorkflowTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.state, self.client = self.base.state, self.base.client

    def prepare(self, mode='research'):
        projects = self.state['research_projects']
        project = projects.create('alice', CreateProject(requestId='admission-project', title='Fixed admission'))['id']
        agreement = Agreement.model_validate({'objective': 'no experiment is permitted', 'evaluation': 'Retain evidence',
            'stopConditions': 'Stop without a child', 'budget': {'rounds': 1, 'toolCalls': 32},
            'execution': {'applicationRef': self.base.ref, 'mode': mode, 'deadline': time.time() + 180,
                'perRoundCaps': {'rounds': 1, 'toolCalls': 32}}})
        projects.change('alice', project, 'revise', ReviseGoal(requestId='admission-goal', expectedVersion=0, agreement=agreement))
        projects.change('alice', project, 'confirm', ProjectCommand(requestId='admission-confirm', expectedVersion=1))
        self.url = '/api/factory/research/projects/' + project
        self.command = {'requestId': 'admission-start', 'expectedVersion': 1}
        return project

    def test_public_experiment_mode_rejected_without_scope_round_or_native_task(self):
        self.prepare('experiment')
        self.assertEqual(self.client.get(self.url).json()['execution'], {
            'available': False, 'reason': 'RESEARCH_NATIVE_COMPONENT_REQUIRED'})
        with patch.object(self.state['bridge'], 'submit', AsyncMock()) as submit:
            response = self.client.post(self.url + '/start', json=self.command)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()['code'], 'RESEARCH_NATIVE_COMPONENT_REQUIRED')
            submit.assert_not_called()
        rounds = self.state['research_rounds']
        with self.state['store'].engine.connect() as conn:
            for table in (rounds.rounds, rounds.legacy.commitments, rounds.legacy.experiments,
                          rounds.legacy.attempts, rounds.scopes.allocations, rounds.scopes.requests):
                self.assertEqual(conn.execute(select(func.count()).select_from(table)).scalar(), 0, table.name)
        self.assertEqual(self.state['store'].tasks('alice'), [])

    def test_original_unknown_survives_current_pin_change_and_end_without_redispatch(self):
        self.prepare()
        with patch.object(self.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('original unknown'))) as submit:
            response = self.client.post(self.url + '/start', json=self.command)
            self.assertEqual(response.status_code, 202, response.text)
            original = response.json()
            self.assertEqual(original['execution']['state'], 'unknown')
            self.assertEqual(submit.await_count, 1)
        rounds = self.state['research_rounds']
        original_pin = rounds.pin
        with patch.object(rounds, 'pin', {**original_pin, 'sha256': 'f' * 64}), \
                patch.object(self.state['bridge'], 'submit', AsyncMock()) as submit:
            repeated = self.client.post(self.url + '/start', json=self.command)
            self.assertEqual(repeated.json(), original)
            ended = self.client.post(self.url + '/end', json={'requestId': 'end-original', 'expectedVersion': 1,
                'outcome': 'cancelled', 'reason': 'Keep the original identity for cleanup'})
            self.assertEqual(ended.status_code, 200, ended.text)
            self.assertEqual(self.client.post(self.url + '/start', json=self.command).json(), original)
            self.assertEqual(self.client.get(self.url + '/experiments').status_code, 200)
            submit.assert_not_called()
        task = self.state['store'].task(original['execution']['taskId'], 'alice')
        plan = self.state['store'].plan(task['plan_id'], 'alice')
        self.assertEqual(plan['nativeComponent'], original_pin)
        scope = rounds.scopes.inspect('alice', original['scopeId'])
        self.assertEqual(scope['state'], 'CANCELLED')
        self.assertEqual(scope['allocations'][0]['taskId'], task['id'])
        self.assertEqual(len(self.state['store'].tasks('alice')), 1)
