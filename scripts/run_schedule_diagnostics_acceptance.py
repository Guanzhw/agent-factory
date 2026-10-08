#!/usr/bin/env python3
"""Reproduce controlled schedule-diagnostics browser acceptance from this checkout.

Requires built frontend assets, project dependencies, Playwright Chromium, and an
explicit authorized loopback PostgreSQL server with CREATE DATABASE permission.
Only a generated disposable database is mutated/deleted; the supplied database's
tables are never changed. Creates temporary loopback HTTPS with no host trust
changes. Real native claims are driven by the fixture, not a production timer.
No live model/retrieval call or production control endpoint is introduced.

Example (synthetic local database credentials only):
  python scripts/run_schedule_diagnostics_acceptance.py \
    --fixture-database-url postgresql+psycopg://localhost/factory_test \
    --output-dir ./acceptance-output

The ordinary accept_schedule_diagnostics_browser.py CLI remains available for an
already prepared isolated Factory. This orchestrator prepares its own fixtures.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'SCHEDULE_DIAGNOSTICS_ARGUMENTS_INVALID\n')


def run(database_url, output, evidence):
    # Import project/test acceptance helpers from Git, never a scratch directory.
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'platform'), str(root / 'platform' / 'tests')]
    from playwright.sync_api import sync_playwright
    from agent_factory.config import Settings
    from agent_factory.main import create_app
    from agent_factory.development_tls import temporary_development_tls
    from pg_fixture import IsolatedPostgres
    from accept_browser_auth import listener, serve
    from accept_schedule_diagnostics_browser import scenario
    from agno.db.schemas.scheduler import Schedule
    from fastapi import HTTPException
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    database_config = make_url(database_url)
    if (database_config.drivername not in {'postgresql', 'postgresql+psycopg'}
            or database_config.host not in {'127.0.0.1', 'localhost', '::1'}
            or not database_config.database or database_config.query):
        raise ValueError('SCHEDULE_DIAGNOSTICS_DATABASE_INVALID')

    with ExitStack() as stack:
        database = stack.enter_context(IsolatedPostgres(database_url))
        workspace = Path(stack.enter_context(TemporaryDirectory(prefix='schedule-diagnostics-')))
        sock = listener(); stack.callback(sock.close)
        origin = 'https://127.0.0.1:' + str(sock.getsockname()[1])
        cert, key = stack.enter_context(temporary_development_tls(origin))
        settings = Settings(db_url=database.url, workspace=workspace, demo=True,
                            temporary_policy='admin-review', development_mock_login=True,
                            development_public_origin=origin, max_workers=1)
        settings.schedule_poll_seconds = 3600  # Fixture-only explicit claim driver, not a timer test.
        app = create_app(settings)
        state = app.app.state.factory
        stack.callback(state['store'].engine.dispose)
        stack.callback(state['store'].native_db.db_engine.dispose)
        serve(stack, app, sock, cert, key)
        service, store, auth = state['schedules'], state['store'], state['auth']
        def counts():
            return [store.sql('SELECT count(*) AS n FROM ' + table)[0]['n']
                    for table in ('af_tasks', 'af_schedule_occurrences', 'ai.agno_jobs')]
        def prepare(schedule):
            identifier = schedule['id']
            before = counts()
            def claim():
                service.set_enabled('manager', identifier, True)
                service.manager.update(identifier, user_id='manager', next_run_at=int(time.time()) - 1)
                row = service.db.claim_due_schedule('browser-diagnostic-' + uuid4().hex)
                assert row and row['id'] == identifier
                return Schedule.from_dict(row)
            def denied(claimed, status):
                try:
                    asyncio.run(service.execute(claimed, service.db))
                except HTTPException as error:
                    assert error.status_code == status
                else:
                    raise AssertionError('CONTROLLED_CLAIM_WAS_NOT_REJECTED')
            claimed = claim()
            auth.authorization.unassign('manager', 'factory-manager')
            try:
                denied(claimed, 403)
            finally:
                auth.authorization.assign('manager', 'factory-manager')
            claimed = claim()
            with store.engine.connect() as holder:
                lock_key = 'af_schedule:' + identifier
                holder.execute(text('SELECT pg_advisory_lock(hashtext(:key))'), {'key': lock_key})
                holder.commit()
                try:
                    denied(claimed, 409)
                    first = service.diagnostics.page('manager', identifier)
                    denied(claimed, 409)
                    assert service.diagnostics.page('manager', identifier) == first
                finally:
                    holder.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'), {'key': lock_key})
                    holder.commit()
            service.db.release_schedule(identifier, next_run_at=int(time.time()) + 3600)
            claimed = claim()
            service.set_enabled('manager', identifier, False)
            denied(claimed, 409)
            claimed = claim()
            service.update('manager', identifier, '0 1 2 1 *')
            denied(claimed, 409)
            service.set_enabled('manager', identifier, False)
            assert counts() == before
            store.audit('manager', 'schedule.denied', identifier,
                        {'detail': 'UNTRUSTED_PROVIDER_DETAIL_TEST_ONLY'})
            rows = service.diagnostics.page('manager', identifier)['items']
            assert len(rows) == 4 and all(row['source'] == 'native' for row in rows)
            expected = {'AUTHORIZATION_DENIED', 'CLOCK_BUSY', 'PAUSED', 'CLAIM_CHANGED'}
            assert {row['reasonCode'] for row in rows} == expected
            return {'method': 'controlled-native-admission-not-ui-timer',
                    'reasonCodes': sorted(expected), 'tasksCreated': 0,
                    'occurrencesCreated': 0, 'nativeJobsCreated': 0,
                    'realAdvisoryLock': True, 'duplicateClaimStable': True,
                    'legacyUnsafeAuditExcluded': True}

        fixture_executor = stack.enter_context(ThreadPoolExecutor(max_workers=1))
        def prepare_offloop(schedule):
            return fixture_executor.submit(prepare, schedule).result(timeout=30)
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(headless=True); stack.callback(browser.close)
        for name, viewport in (('desktop', {'width': 1440, 'height': 1000}),
                               ('mobile', {'width': 390, 'height': 844})):
            evidence['screens'].append(scenario(browser, origin, output, name, viewport, prepare=prepare_offloop))
            assert counts() == [0, 0, 0]
        evidence['finalNativeEffects'] = {'tasks': 0, 'occurrences': 0, 'nativeJobs': 0}
        evidence['ok'] = True
    evidence['cleanupComplete'] = True


def main(argv=None):
    parser = _Arguments(description=__doc__)
    parser.add_argument('--fixture-database-url', required=True,
                        help='Explicit authorized loopback PostgreSQL; creates a separate disposable database')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='New directory for finite evidence and screenshots; must not already exist')
    args = parser.parse_args(argv)
    # Discard inherited provider/auth variables without reading or printing them.
    allowed = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'PYTHONPATH', 'VIRTUAL_ENV',
               'PLAYWRIGHT_BROWSERS_PATH', 'LD_LIBRARY_PATH', 'SYSTEMROOT'}
    for name in tuple(os.environ):
        if name not in allowed:
            del os.environ[name]
    evidence = {'evidenceMode': 'controlled-fixture', 'liveProviderVerified': False,
                'productionSchedule': False, 'screens': [], 'ok': False,
                'cleanupComplete': False}
    try:
        args.output_dir.mkdir(parents=True, exist_ok=False)
    except Exception:
        print('SCHEDULE_DIAGNOSTICS_OUTPUT_INVALID', file=sys.stderr)
        return 2
    try:
        run(args.fixture_database_url, args.output_dir, evidence)
    except Exception:
        # Failure is deliberately conservative about cleanup; no raw exception,
        # connection URL, headers, provider values or browser state is emitted.
        evidence['ok'] = False
    try:
        (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    except Exception:
        print('SCHEDULE_DIAGNOSTICS_EVIDENCE_WRITE_FAILED', file=sys.stderr)
        return 1
    print(json.dumps({'ok': evidence['ok'], 'cleanupComplete': evidence['cleanupComplete'],
                      'screens': len(evidence['screens'])}))
    return 0 if evidence['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
