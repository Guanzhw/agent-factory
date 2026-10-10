"""Durable platform custody on a disposable PG database; synthetic package only."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from agent_factory.application_environments import ApplicationEnvironments
from pg_fixture import IsolatedPostgres
import test_application_environments as custody_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL') and sys.platform == 'linux',
    'Requires disposable PostgreSQL and Linux platform custody fences')
class ApplicationEnvironmentPostgresTests(unittest.TestCase):
    def test_restart_reads_committed_custody_without_replaying_preparation_or_research(self):
        fixture = custody_fixture.ApplicationEnvironmentTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database:
            from sqlalchemy import create_engine
            engine = create_engine(database.url)
            self.addCleanup(engine.dispose)
            original = fixture.service
            store = SimpleNamespace(engine=engine,
                settings=SimpleNamespace(workspace=Path(fixture.folder.name)))
            def reopen():
                return ApplicationEnvironments(store, original.auth, original.models,
                    original.connections, {'openresearch': fixture.package})
            service = reopen()
            ready = service.prepare('alice', 'openresearch', 'pg-first-prepare')
            environment = ready['environment']
            self.assertEqual(ready['state'], 'ready')
            self.assertEqual(len(fixture.prepares), 1)
            service = reopen()
            self.assertEqual(service.request('alice', 'pg-first-prepare'), ready)
            self.assertEqual(service.prepare('alice', 'openresearch', 'pg-first-prepare'), ready)
            self.assertEqual(len(fixture.prepares), 1)
            self.assertEqual(service.stop('alice', environment['id'], 'pg-stop')['state'], 'stopped')
            service = reopen()
            self.assertEqual(service.inspect('alice', environment['id'])['state'], 'stopped')
            restarted = service.prepare('alice', 'openresearch', 'pg-explicit-restart')
            self.assertEqual(restarted['environment']['projectId'], environment['projectId'])
            self.assertEqual(restarted['environment']['modelRevision'], environment['modelRevision'])
            self.assertEqual(len(fixture.allocations), 1)
            self.assertEqual(fixture.research, [])
            with self.assertRaises(HTTPException) as foreign:
                service.request('bob', 'pg-first-prepare')
            self.assertEqual(foreign.exception.status_code, 404)
            engine.dispose()
