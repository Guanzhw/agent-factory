"""Real project write/reader lock ordering on disposable PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from threading import Event, current_thread
import unittest
from unittest.mock import patch

from sqlalchemy import text

from agent_factory.application_content import ContentPublication
from research.peer_sources import ResearchPeerSources
from research.projects import CreateProject, ReviseGoal
from research.public import install
from test_research_projects import agreement
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class ResearchSourceLocksTests(unittest.TestCase):
    def test_project_receipt_and_revision_take_admission_before_domain_in_both_directions(self):
        fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        state = fixture.state
        install(state)
        projects = state['research_projects']
        scopes = state['local_budget_scopes']
        sources = ResearchPeerSources(state['store'], state['application_content'], scopes)
        projects.peer_sources = sources
        command = CreateProject(requestId='lock-order-project', title='source-guard project')
        project = projects.create('alice', command)
        source = state['application_content'].publish('bob', ContentPublication(
            source={'application': 'research', 'record': 'lock-source', 'revision': '1'},
            content={'hypothesis': 'Original evidence'}, visibility='team'), 'lock-source-publication')
        sources.bind('lock-round', project['id'], [source['id']], [])

        def read_original():
            with sources.guard():
                return sources.content.read('alice', source['id'])

        operations = [
            (lambda: projects.create('alice', command), read_original),
            (read_original, lambda: projects.change('alice', project['id'], 'revise',
                ReviseGoal(requestId='lock-order-revise', expectedVersion=0, agreement=agreement()))),
        ]
        for first, second in operations:
            held, attempting = Event(), Event()
            original = scopes.admission_lock
            first_thread = []
            def admission(conn):
                if current_thread().name == first_thread[0]:
                    original(conn)
                    held.set()
                    self.assertTrue(attempting.wait(5), 'competing entry never reached admission')
                else:
                    attempting.set()
                    original(conn)
            def run_first():
                first_thread.append(current_thread().name)
                return first()
            @contextmanager
            def bounded_write():
                with state['store'].transaction() as conn:
                    conn.execute(text("SET LOCAL lock_timeout = '3s'"))
                    yield
            def run_second():
                self.assertTrue(held.wait(5))
                with bounded_write():
                    return second()
            with patch.object(scopes, 'admission_lock', side_effect=admission), ThreadPoolExecutor(max_workers=2) as workers:
                leading = workers.submit(run_first)
                competing = workers.submit(run_second)
                leading.result(timeout=10)
                competing.result(timeout=10)
        self.assertEqual(projects.read('alice', project['id'])['currentGoalVersion'], 1)
