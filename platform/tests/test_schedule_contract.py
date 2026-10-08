"""Deterministic actual native-clock comparison; no poller, DB or wall waits."""
from datetime import datetime
from unittest.mock import patch
import unittest
from typing import Any

from agno.scheduler.cron import compute_next_run
from fastapi import HTTPException

from agent_factory.schedule_contract import preview_schedule


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


class ScheduleClockTests(unittest.TestCase):
    def compare(self, cron, zone, at):
        now = epoch(at)
        result = preview_schedule(cron, zone, now_epoch=now)
        base = now
        with patch('agno.scheduler.cron.time.time', return_value=now):
            for row in result['nextRuns']:
                base = compute_next_run(cron, zone, after_epoch=base)
                self.assertEqual(row['epoch'], base)
                self.assertEqual(epoch(row['local']), base)
                self.assertEqual(epoch(row['utc']), base)
        return result

    def test_native_utc_and_nonhour_iana_offset_three_runs(self):
        result = self.compare('0 9 * * MON-FRI', 'Asia/Kathmandu', '2026-10-02T04:00:00+00:00')
        self.assertEqual([row['utc'] for row in result['nextRuns']],
                         ['2026-10-05T03:15:00Z', '2026-10-06T03:15:00Z', '2026-10-07T03:15:00Z'])
        self.assertTrue(all(row['utcOffsetSeconds'] == 20700 for row in result['nextRuns']))
        self.compare('*/15 * * * *', 'UTC', '2026-10-04T12:00:00+00:00')

    def test_spring_missing_0230_is_shifted_to_0300_by_installed_native_clock(self):
        result = self.compare('30 2 * * *', 'America/New_York', '2026-03-07T12:00:00+00:00')
        self.assertEqual([row['local'] for row in result['nextRuns']],
                         ['2026-03-08T03:00:00-04:00', '2026-03-09T02:30:00-04:00', '2026-03-10T02:30:00-04:00'])

    def test_fall_repeated_0130_occurs_twice_with_distinct_utc_offsets(self):
        result = self.compare('30 1 * * *', 'America/New_York', '2026-10-31T12:00:00+00:00')
        self.assertEqual([row['local'] for row in result['nextRuns']],
                         ['2026-11-01T01:30:00-04:00', '2026-11-01T01:30:00-05:00', '2026-11-02T01:30:00-05:00'])
        self.assertEqual(result['nextRuns'][1]['epoch'] - result['nextRuns'][0]['epoch'], 3600)
        self.compare('30 1 * * *', 'America/New_York', '2026-11-01T05:31:00+00:00')

    def test_boundary_is_exclusive_and_clock_is_captured_once(self):
        now = epoch('2026-10-04T12:00:00+00:00')
        with patch('agent_factory.schedule_contract.time.time', return_value=now) as clock:
            result = preview_schedule('* * * * *', 'UTC')
            self.assertEqual(clock.call_count, 1)
        self.assertEqual(result['nextRuns'][0]['epoch'], now + 60)
        self.assertEqual(result['previewedAtUtc'], '2026-10-04T12:00:00Z')

    def test_historical_native_after_epoch_is_not_a_clock_override(self):
        now = epoch('2026-10-04T12:00:00+00:00')
        old = epoch('2026-01-01T00:00:00+00:00')
        with patch('agno.scheduler.cron.time.time', return_value=now):
            self.assertEqual(compute_next_run('0 0 * * *', 'UTC', after_epoch=old), now + 1)
        result = preview_schedule('0 0 * * *', 'UTC', now_epoch=old)
        self.assertEqual(result['nextRuns'][0]['utc'], '2026-01-02T00:00:00Z')

    def test_rejects_macros_seconds_year_offsetzones_and_impossible_dates(self):
        values: list[tuple[Any, Any]] = [('@daily', 'UTC'), ('0 0 * * * *', 'UTC'),
            ('0 0 * * * * 2026', 'UTC'), ('0 0 31 2 *', 'UTC'), ('60 * * * *', 'UTC'),
            ('* * * * *', '+08:00'), ('* * * * *', 'Unknown/Place'), ('* * * * *', None),
            (None, 'UTC'), ('* ' * 200, 'UTC'), ('零 0 * * *', 'UTC')]
        for cron, zone in values:
            with self.subTest(cron=cron, zone=zone), self.assertRaises(HTTPException) as error:
                preview_schedule(cron, zone, now_epoch=0)
            self.assertEqual(error.exception.status_code, 422)
            self.assertEqual(error.exception.detail, 'SCHEDULE_CLOCK_INVALID')
        for value in (True, -1, 1.5, 10 ** 20):
            with self.assertRaises(HTTPException):
                preview_schedule('* * * * *', 'UTC', now_epoch=value)  # type: ignore[arg-type]

    def test_declares_preview_only_native_missed_and_overlap_contract(self):
        result = preview_schedule('  0   9 * * * ', 'UTC', now_epoch=0)
        self.assertEqual(result['cron'], '0 9 * * *')
        self.assertEqual(result['semantics']['missed'], 'coalesce-no-catch-up')
        self.assertEqual(result['semantics']['overlap'], 'allowed-subject-to-owner-and-global-budgets')
        self.assertTrue(result['semantics']['previewOnly'])


if __name__ == '__main__':
    unittest.main()
