"""Public revocation versus internal original cleanup; portable execution seam."""
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from agent_factory_research.research_iteration_coordinator import IterationCoordinator
import test_research_iterations as fixture


class IterationRetirementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.base = fixture.ResearchIterationsTests('runTest')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.service, self.driver, self.auth = self.base.service, self.base.driver, self.base.auth
        self.driver.observe_original = AsyncMock(side_effect=self.driver.observe)

    def disable(self):
        self.auth.require_member = Mock(side_effect=HTTPException(403, 'disabled'))

    async def test_disabled_original_settles_without_promoting_and_public_reads_stay_denied(self):
        first = await self.base.start()
        identity, round = first['activity']['id'], first['rounds'][0]
        self.driver.stopped(round)
        baseline = deepcopy(first['activity']['baselineSource'])
        self.disable()
        await IterationCoordinator(self.service)._one('alice', identity)
        value = self.service._inspect('alice', identity)
        self.assertEqual(value['activity']['status'], 'stopped')
        self.assertEqual(value['activity']['stopReason'], 'owner_unavailable')
        self.assertEqual(value['activity']['baselineSource'], baseline)
        self.assertEqual(value['rounds'][0]['state'], 'SETTLED')
        self.assertEqual(len(self.driver.dispatched), 1)
        self.assertEqual(len(value['rounds']), 1)
        with self.assertRaises(HTTPException):
            self.service.inspect('alice', identity)
        with self.assertRaises(HTTPException):
            self.service.round_for_task('alice', round['taskId'])
        with self.assertRaises(HTTPException):
            self.service._round_for_task('bob', round['taskId'])

    async def test_unknown_disabled_original_never_refunds_or_redispatches(self):
        self.driver.fail_dispatch = True
        with self.assertRaises(TimeoutError):
            await self.base.start()
        identity = self.driver.reserved[0]['activityId']
        self.disable()
        for _ in range(2):
            await IterationCoordinator(self.service)._one('alice', identity)
        value = self.service._inspect('alice', identity)
        self.assertEqual(value['activity']['status'], 'canceling')
        self.assertEqual(value['rounds'][0]['state'], 'UNKNOWN')
        self.assertTrue(value['rounds'][0]['dispatchAttempted'])
        self.assertEqual(len(self.driver.dispatched), 1)
        self.assertNotIn('settlement', value['rounds'][0])

    async def test_retirement_rejects_active_member_or_transient_auth_failure(self):
        first = await self.base.start()
        identity = first['activity']['id']
        with self.assertRaises(HTTPException) as caught:
            await self.service._retire_unavailable('alice', identity)
        self.assertEqual(caught.exception.detail, 'ITERATION_OWNER_AVAILABLE')
        self.auth.require_member = Mock(side_effect=HTTPException(503, 'unavailable'))
        with self.assertRaises(HTTPException) as caught:
            await IterationCoordinator(self.service)._one('alice', identity)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertFalse(self.service._inspect('alice', identity)['activity']['cancelRequested'])
        self.driver.observe_original.assert_not_awaited()
