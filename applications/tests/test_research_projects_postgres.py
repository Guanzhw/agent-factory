"""Project persistence and conflicting goal revisions against isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest

from fastapi import HTTPException

from research.public import install
from research.projects import CreateProject, ReviseGoal
import test_applications_composition as fixtures
from test_research_projects import agreement


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ResearchProjectsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        install(self.fixture.state)

    def test_authenticated_http_goal_history_and_receipt_survive_restart(self):
        fixture = self.fixture
        fixture.login('alice')
        body = {'requestId': 'pg-project-original', 'title': '可恢复研究项目'}
        created = fixture.client.post('/api/factory/research/projects', json=body)
        self.assertEqual(created.status_code, 201, created.text)
        url = '/api/factory/research/projects/' + created.json()['id']
        goal = {'requestId': 'pg-goal-original', 'expectedVersion': 0,
                'agreement': agreement().model_dump()}
        revised = fixture.client.post(url + '/goals', json=goal)
        self.assertEqual(revised.status_code, 200, revised.text)
        confirmed = fixture.client.post(url + '/confirm', json={
            'requestId': 'pg-confirm-original', 'expectedVersion': 1})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        fixture.stop()
        fixture.start()
        install(fixture.state)
        fixture.login('alice')
        self.assertEqual(fixture.client.get(url).json(), confirmed.json())
        self.assertEqual(fixture.client.post('/api/factory/research/projects', json=body).json(), created.json())
        self.assertEqual(fixture.client.post(url + '/goals', json=goal).json(), revised.json())
        self.assertEqual(fixture.client.get(url).json(), confirmed.json())
        self.assertFalse(confirmed.json()['execution']['available'])
        fixture.login('bob')
        self.assertEqual(fixture.client.get(url).status_code, 404)
        self.assertEqual(fixture.client.post(url + '/goals', json=goal).status_code, 404)
        self.assertEqual(fixture.client.get('/api/factory/research/projects').json()['items'], [])

    def test_concurrent_goal_compare_and_swap_preserves_single_winner(self):
        service = self.fixture.state['research_projects']
        project = service.create('alice', CreateProject(requestId='pg-concurrent-project', title='并发研究约定'))
        barrier = Barrier(2)

        def revise(index):
            body = ReviseGoal(requestId=f'pg-competing-goal-{index}', expectedVersion=0,
                              agreement=agreement(f'Competing goal {index}'))
            barrier.wait(timeout=5)
            try:
                return service.change('alice', project['id'], 'revise', body)
            except HTTPException as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(revise, range(2)))
        failures = [result for result in results if isinstance(result, HTTPException)]
        winners = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(failures), 1, results)
        self.assertEqual(failures[0].status_code, 409)
        self.assertEqual(failures[0].detail['code'], 'RESEARCH_GOAL_VERSION_CONFLICT')
        current = service.read('alice', project['id'])
        self.assertEqual(current, winners[0])
        self.assertEqual(len(current['goals']), 1)
        self.assertEqual(current['currentGoalVersion'], 1)
