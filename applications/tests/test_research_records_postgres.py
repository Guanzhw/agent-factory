"""Atomic curated start records on PostgreSQL; synthetic native execution only."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest
from unittest.mock import patch

from sqlalchemy import func, select

from research.projects import ProjectCommand
import test_research_runs_postgres as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ResearchRecordsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.ResearchRunsPostgresTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.fixture = self.base.fixture
        self.service = self.fixture.state['research_runs']
        self.project_id = self.base.url.rsplit('/', 1)[1]
        self.command = ProjectCommand.model_validate(self.base.body)

    def test_concurrent_intent_one_team_snapshot_without_project_or_resource_access(self):
        fixture = self.fixture
        self.base.seed_history()
        with ThreadPoolExecutor(max_workers=2) as pool:
            intents = list(pool.map(lambda _: self.service._prepare('alice', self.project_id, self.command), range(2)))
        self.assertEqual(intents[0], intents[1])
        identifier = intents[0]['startRecordId']
        fixture.login('bob')
        response = fixture.client.get('/api/factory/application-content/' + identifier)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['content']['state'], 'pending_admission')
        self.assertEqual(response.json()['verificationStatus'], 'unverified')
        self.assertNotIn('resourceRefs', response.text)
        self.assertNotIn('connectionRefs', response.text)
        self.assertNotIn('existing-model-reference', response.text)
        self.assertEqual(fixture.client.get(self.base.url).status_code, 404)
        denied = fixture.client.post('/api/factory/application-content/' + identifier + '/sharing',
            json={'requestId': 'bob-change-record', 'visibility': 'personal'})
        self.assertEqual(denied.status_code, 404, denied.text)
        fixture.login('alice')
        started = fixture.client.post(self.base.url + '/start', json=self.base.body)
        self.assertEqual(started.status_code, 202, started.text)
        self.assertEqual(started.json()['startRecordId'], identifier)
        task_id = started.json()['execution']['taskId']
        detail = fixture.wait_job(task_id)
        self.assertEqual(detail['job']['status'], 'completed', detail)
        self.assertEqual(fixture.store.application_runtime.owners(fixture.store.task(task_id)), ())
        content = fixture.state['application_content']
        self.assertEqual(content.read('alice', identifier)['content']['state'], 'pending_admission')
        with fixture.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(content.contents)).scalar(), 1)
        self.assertEqual(fixture.store.sql('SELECT id FROM af_assistant_events'), [])

    def test_current_round_binding_failure_rolls_back_scope_allocation_and_intent(self):
        import test_research_workflow_postgres as native
        from research.projects import Agreement, CreateProject, ReviseGoal
        import time
        base = native.ResearchNativeWorkflowTests('runTest')
        self.addCleanup(base.doCleanups)
        base.setUp()
        rounds, projects = base.state['research_rounds'], base.state['research_projects']
        project = projects.create('alice', CreateProject(requestId='rollback-project', title='Current round'))['id']
        agreement = Agreement.model_validate({**self.base.agreement, 'execution': {
            'applicationRef': base.ref, 'mode': 'research', 'deadline': time.time() + 120,
            'perRoundCaps': {'rounds': 1, 'toolCalls': 4}}})
        projects.change('alice', project, 'revise', ReviseGoal(requestId='rollback-goal', expectedVersion=0, agreement=agreement))
        projects.change('alice', project, 'confirm', ProjectCommand(requestId='rollback-confirm', expectedVersion=1))
        command = ProjectCommand(requestId='rollback-start', expectedVersion=1)
        original = rounds.scopes.bind_request
        def failed(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('synthetic post-binding failure')
        with patch.object(rounds.scopes, 'bind_request', side_effect=failed):
            with self.assertRaisesRegex(RuntimeError, 'post-binding failure'):
                rounds._prepare('alice', project, command)
        scopes, content = rounds.scopes, rounds.content
        with base.state['store'].engine.connect() as conn:
            for table in (rounds.legacy.commitments, rounds.rounds, rounds.legacy.experiments, rounds.legacy.attempts,
                          scopes.scopes, scopes.allocations, scopes.requests, content.contents, content.commands):
                self.assertEqual(conn.execute(select(func.count()).select_from(table)).scalar(), 0, table.name)
        self.assertEqual(base.state['store'].tasks('alice'), [])
        intent = rounds._prepare('alice', project, command)
        self.assertEqual(rounds._prepare('alice', project, command), intent)
