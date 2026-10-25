"""First research root through real PG admission and synthetic native execution."""
from concurrent.futures import ThreadPoolExecutor
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from core_native_fixture import FixtureModel

import test_applications_composition as fixtures
from research.public import install
from research.projects import ProjectCommand
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

    def test_concurrent_start_one_native_root_and_restart_original_receipt(self):
        fixture = self.fixture
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

    def test_preparation_failure_rolls_back_scope_allocation_and_domain_intent(self):
        fixture = self.fixture
        scopes = fixture.store.local_budget_scopes
        runs = fixture.state['research_runs']
        bind = scopes.bind_request

        def fail_after_bind(*args):
            bind(*args)
            raise RuntimeError('controlled failure before research intent commit')

        with patch.object(scopes, 'bind_request', fail_after_bind), \
                patch.object(fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            with self.assertRaisesRegex(RuntimeError, 'controlled failure'):
                fixture.client.post(self.url + '/start', json=self.body)
            submit.assert_not_awaited()
        with fixture.store.transaction(read_only=True) as conn:
            for table in (scopes.scopes, scopes.allocations, scopes.requests, runs.commitments, runs.experiments, runs.attempts):
                self.assertEqual(conn.execute(select(func.count()).select_from(table)).scalar(), 0, table.name)

    def test_prepared_research_request_cannot_bypass_scope_via_public_core_start(self):
        fixture = self.fixture
        runs = fixture.state['research_runs']
        project_id = self.url.rsplit('/', 1)[-1]
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
