"""Bounded read-only preview of the installed native cron clock.

No persistence, admission, timers or clock patching. The optional clock seam is
operator/test-only; public API requests must not supply it.
"""
from datetime import datetime, timezone as utc_timezone
import time

from croniter import croniter
from fastapi import HTTPException
import pytz

from agno.scheduler.cron import validate_cron_expr


def preview_schedule(cron: str, timezone: str, *, now_epoch: int | None = None) -> dict:
    if (type(cron) is not str or not 1 <= len(cron) <= 256 or not cron.isascii()
            or len(cron.split()) != 5 or type(timezone) is not str
            or not 1 <= len(timezone) <= 100 or timezone not in pytz.all_timezones_set):
        raise HTTPException(422, 'SCHEDULE_CLOCK_INVALID')
    expression = ' '.join(cron.split())
    current = int(time.time()) if now_epoch is None else now_epoch
    if type(current) is not int or not 0 <= current <= 253370764799:
        raise HTTPException(422, 'SCHEDULE_CLOCK_INVALID')
    try:
        if not validate_cron_expr(expression):
            raise ValueError('Invalid cron')
        zone = pytz.timezone(timezone)
        base = current
        runs = []
        for _ in range(3):
            # Match Agno compute_next_run: construct a new iterator each call.
            # Reusing one iterator changes repeated-hour DST behavior.
            local_base = datetime.fromtimestamp(base, tz=zone)
            next_date = croniter(expression, local_base).get_next(datetime)
            epoch = max(int(next_date.timestamp()), current + 1)
            if epoch <= base:
                raise ValueError('Non-monotonic cron')
            local = datetime.fromtimestamp(epoch, tz=zone)
            offset = local.utcoffset()
            if offset is None:
                raise ValueError('No timezone offset')
            runs.append({'epoch': epoch,
                         'utc': datetime.fromtimestamp(epoch, utc_timezone.utc).isoformat().replace('+00:00', 'Z'),
                         'local': local.isoformat(), 'utcOffsetSeconds': int(offset.total_seconds())})
            base = epoch
        return {'schema': 1, 'cron': expression, 'timezone': timezone,
                'previewedAtUtc': datetime.fromtimestamp(current, utc_timezone.utc).isoformat().replace('+00:00', 'Z'),
                'nextRuns': runs, 'semantics': {'clock': 'agno-3.1.0/croniter-6.2.4/pytz',
                    'missed': 'coalesce-no-catch-up', 'overlap': 'allowed-subject-to-owner-and-global-budgets',
                    'dst': 'native-croniter-pytz', 'previewOnly': True}}
    except (ValueError, TypeError, OverflowError, OSError):
        raise HTTPException(422, 'SCHEDULE_CLOCK_INVALID') from None
