"""The same command receipt contracts on owned PostgreSQL, never a shared DB."""
import os
import unittest

from sqlalchemy import create_engine

from pg_fixture import IsolatedPostgres
import test_model_command_recovery as recovery


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires independent disposable PostgreSQL')
class ModelCommandRecoveryPostgresTests(recovery.ModelCommandRecoveryTests):
    def make_engine(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        return create_engine(database.url)
