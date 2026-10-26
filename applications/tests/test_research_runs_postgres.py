"""Persisted historical intents through real PG recovery; no old Workflow executor claim."""
from concurrent.futures import ThreadPoolExecutor
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from core_native_fixture import FixtureModel

import test_applications_composition as fixtures
from research.public import install
from research.projects import Agreement, ProjectCommand
from research_history_fixture import seed_legacy_intent
from agent_factory.store import digest
from test_research_projects import agreement


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ResearchRunsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        install(self.fixture.state)
        fixture = self.fixture
        app = fixture.publish_http()
        fixture.login('alice')
        created = fixture.client.post('/api/factory/research/projects', json={
            'requestId': 'pg-runs-project', 'title': '真实原生首轮合成验收'})
        self.assertEqual(created.status_code, 201, created.text)
        self.url = '/api/factory/research/projects/' + created.json()['id']
        self.agreement = {**agreement().model_dump(), 'execution': {
            'applicationRef': fixtures.pin(app), 'mode': 'literature',
            'deadline': time.time() + 300, 'perRoundCaps': {'rounds': 1, 'toolCalls': 4}}}
        goal = fixture.client.post(self.url + '/goals', json={'requestId': 'pg-runs-goal',
            'expectedVersion': 0, 'agreement': self.agreement})
        self.assertEqual(goal.status_code, 200, goal.text)
        confirm = fixture.client.post(self.url + '/confirm', json={
            'requestId': 'pg-runs-confirm', 'expectedVersion': 1})
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.body = {'requestId': 'pg-runs-start', 'expectedVersion': 1}

    def seed_history(self):
        return seed_legacy_intent(self.fixture.state['research_runs'], 'alice', self.url.rsplit('/', 1)[1],
            ProjectCommand.model_validate(self.body), Agreement.model_validate(self.agreement))

    def test_concurrent_start_one_native_root_and_restart_original_receipt(self):
        fixture = self.fixture
        self.seed_history()
        observed_inputs = []
        response = FixtureModel._response

        def observe(model, messages):
            observed_inputs.extend(str(message.content) for message in messages)
            return response(model, messages)

        model_patch = patch.object(FixtureModel, '_response', autospec=True, side_effect=observe)
        model_patch.start()
        self.addCleanup(model_patch.stop)
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock(wraps=fixture.state['bridge'].submit)) as submit:
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies = list(pool.map(lambda _: fixture.client.post(self.url + '/start', json=self.body), range(2)))
            for reply in replies:
                self.assertEqual(reply.status_code, 202, reply.text)
            self.assertEqual(submit.await_count, 1)
        self.assertEqual(replies[0].json()['attemptId'], replies[1].json()['attemptId'])
        original = replies[0].json()
        task_id = original['execution']['taskId']
        detail = fixture.wait_job(task_id)
        self.assertEqual(detail['job']['status'], 'completed', detail)
        self.assertTrue(detail['artifacts'])
        visible = '\n'.join(observed_inputs)
        for field in ('objective', 'evaluation', 'stopConditions'):
            self.assertIn(self.agreement[field], visible)
        scope = fixture.store.local_budget_scopes.inspect('alice', original['scopeId'])
        self.assertEqual(scope['allocatedRounds'], 1)
        self.assertEqual(scope['allocations'][0]['taskId'], task_id)
        fixture.stop()
        fixture.start()
        install(fixture.state)
        fixture.login('alice')
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            replay = fixture.client.post(self.url + '/start', json=self.body)
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(replay.json()['execution']['taskId'], task_id)
            submit.assert_not_awaited()
        self.assertEqual(len(fixture.client.get(self.url + '/experiments').json()['items']), 1)
        fixture.login('bob')
        self.assertEqual(fixture.client.get(self.url + '/experiments').status_code, 404)

    def test_lost_dispatch_ack_is_unknown_and_end_never_replays(self):
        fixture = self.fixture
        self.seed_history()
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('controlled missing acknowledgement'))) as submit:
            first = fixture.client.post(self.url + '/start', json=self.body)
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(first.json()['execution']['state'], 'unknown')
            self.assertEqual(submit.await_count, 1)
        ended = fixture.client.post(self.url + '/end', json={'requestId': 'pg-runs-end',
            'expectedVersion': 1, 'outcome': 'cancelled', 'reason': 'Stop original pending research'})
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertEqual(ended.json()['ending']['resourceCleanup'], 'not_observed')
        scope = fixture.store.local_budget_scopes.inspect('alice', first.json()['scopeId'])
        self.assertEqual(scope['state'], 'CANCELLED')
        self.assertEqual(scope['allocations'][0]['state'], 'BOUND')
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            replay = fixture.client.post(self.url + '/start', json=self.body)
            self.assertEqual(replay.status_code, 202, replay.text)
            self.assertEqual(replay.json()['execution']['taskId'], first.json()['execution']['taskId'])
            self.assertEqual(replay.json()['execution']['state'], 'unknown')
            submit.assert_not_awaited()

    def test_without_workflow_new_start_is_unavailable_and_creates_no_intent(self):
        fixture = self.fixture
        scopes = fixture.store.local_budget_scopes
        runs = fixture.state['research_runs']
        self.assertEqual(fixture.client.get(self.url).json()['execution'], {
            'available': False, 'reason': 'RESEARCH_NATIVE_COMPONENT_REQUIRED'})
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            reply = fixture.client.post(self.url + '/start', json=self.body)
            self.assertEqual(reply.status_code, 409, reply.text)
            self.assertEqual(reply.json()['code'], 'RESEARCH_NATIVE_COMPONENT_REQUIRED')
            submit.assert_not_awaited()
        with fixture.store.transaction(read_only=True) as conn:
            for table in (scopes.scopes, scopes.allocations, scopes.requests, runs.commitments, runs.experiments, runs.attempts):
                self.assertEqual(conn.execute(select(func.count()).select_from(table)).scalar(), 0, table.name)

    def test_without_workflow_round_commands_recover_original_receipts_and_resume_result(self):
        fixture = self.fixture
        runs = fixture.state['research_runs']
        # Persist the historical command shape explicitly, without supplying an old executor.
        old = self.seed_history()
        project = old['projectId']
        stored = {key: old[key] for key in ('projectId', 'goalVersion', 'scopeId', 'allocationId', 'request')}
        stored['roundId'] = 'original-round'
        with runs.projects.db.write() as conn:
            conn.execute(runs.projects.commands.update().where(runs.projects.commands.c.actor_id == 'alice',
                runs.projects.commands.c.request_id == self.body['requestId']).values(action='research.round.start',
                    fingerprint=digest({'action': 'round.start', 'project': project, 'expectedVersion': 1}), result=stored))
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock(side_effect=TimeoutError('original unknown'))) as submit:
            first = fixture.client.post(self.url + '/start', json=self.body)
            self.assertEqual(first.status_code, 202, first.text)
            self.assertEqual(first.json()['roundId'], 'original-round')
            self.assertEqual(first.json()['execution']['state'], 'unknown')
            self.assertEqual(submit.await_count, 1)
        fixture.stop(); fixture.start(); install(fixture.state); fixture.login('alice')
        runs = fixture.state['research_runs']
        resume = {'projectId': project, 'goalVersion': 1, 'eventId': 'original-event', 'contentId': 'original-content'}
        with runs.projects.db.write() as conn:
            runs.projects.db.record(conn, runs.projects.commands, 'alice', 'original-resume',
                digest({'action': 'round.start', 'project': project, 'expectedVersion': 1}), 'research.round.resume', resume)
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            repeated = fixture.client.post(self.url + '/start', json=self.body)
            self.assertEqual(repeated.json(), first.json())
            result = fixture.client.post(self.url + '/start', json={'requestId': 'original-resume', 'expectedVersion': 1})
            self.assertEqual(result.json(), resume)
            changed = fixture.client.post(self.url + '/start', json={**self.body, 'expectedVersion': 2})
            self.assertEqual(changed.status_code, 409)
            submit.assert_not_awaited()
        self.assertEqual(len(fixture.store.tasks('alice')), 1)

    def test_prepared_research_request_cannot_bypass_scope_via_public_core_start(self):
        fixture = self.fixture
        runs = fixture.state['research_runs']
        project_id = self.url.rsplit('/', 1)[-1]
        self.seed_history()
        intent = runs._prepare('alice', project_id, ProjectCommand.model_validate(self.body))
        self.assertEqual(len(fixture.store.tasks('alice')), 0)
        ended = fixture.client.post(self.url + '/end', json={'requestId': 'pg-prepared-end',
            'expectedVersion': 1, 'outcome': 'cancelled', 'reason': 'Cancel before original dispatch'})
        self.assertEqual(ended.status_code, 200, ended.text)
        with patch.object(fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            # The public port has no allocation keyword. Persisted original
            # request binding must still enforce the cancelled research scope.
            attempted = fixture.client.post('/api/factory/application-interface/v1/starts', json=intent['request'])
            self.assertEqual(attempted.status_code, 409, attempted.text)
            submit.assert_not_awaited()
        self.assertEqual(len(fixture.store.tasks('alice')), 0)
        scope = fixture.store.local_budget_scopes.inspect('alice', intent['scopeId'])
        self.assertIsNone(scope['allocations'][0]['taskId'])
