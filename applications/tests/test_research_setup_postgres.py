"""Disposable PostgreSQL publication transaction and original-command races."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest

from agno.db.postgres import PostgresDb
from pg_fixture import IsolatedPostgres
import test_research_setup as portable
from research.setup import PublishSetup


@unittest.skipUnless(os.environ.get('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchSetupPostgresTests(unittest.TestCase):
    setUp = portable.ResearchSetupTests.setUp
    no_dispatch = portable.ResearchSetupTests.no_dispatch
    configure = portable.ResearchSetupTests.configure
    counts = portable.ResearchSetupTests.counts
    test_partial_publication_rolls_back_and_same_command_can_recover = portable.ResearchSetupTests.test_partial_publication_rolls_back_and_same_command_can_recover
    test_explicit_publish_recovery_and_two_owner_same_materials = portable.ResearchSetupTests.test_explicit_publish_recovery_and_two_owner_same_materials

    def database(self, _directory):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        return PostgresDb(db_url=isolated.url)

    def test_concurrent_publish_returns_one_original_application(self):
        self.configure()
        draft = self.setup.prepare('alice', self.body)
        barrier = Barrier(2)
        def publish(_):
            barrier.wait(timeout=5)
            return self.setup.publish('alice', draft['id'], PublishSetup(requestId='publish-concurrent'))
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(publish, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.counts()[1:], (1, 1, 2))
