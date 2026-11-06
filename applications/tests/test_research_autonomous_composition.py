"""Retired controller reads cannot dispatch research; default composition uses Agent sessions."""
import asyncio
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import inspect, select

from agent_factory.config import Settings
from agent_factory_server import research
from research.history import ResearchHistory
from research.projects import ProjectCommand
from research.setup import ResearchSetup, PublishSetup, setup_router
import test_research_setup as setup_fixtures
import test_research_runs as run_fixtures
import test_research_rounds as round_fixtures


class ResearchAutonomousCompositionTests(unittest.TestCase):
    def test_default_deployment_does_not_register_round_workflow_or_controller_tools(self):
        settings = Settings(db_url='postgresql://unused', jwt_key='synthetic-signing-key-at-least-32bytes')
        with patch.object(research, 'create_deployment') as deployment, patch.object(research, 'install') as install:
            research.create_app(settings)
            configured = deployment.call_args.args[0]
            self.assertEqual([entry.component.id for entry in configured.native_workflows], ['research-qa'])
            names = {entry.tool_name for entry in configured.runtime_adapters}
            self.assertNotIn('research_launch', names)
            self.assertNotIn('research_record_decision', names)
            deployment.call_args.kwargs['applications'][0].install(object())
            self.assertNotIn('workflow', install.call_args.kwargs)
            self.assertIsNotNone(install.call_args.kwargs['session_tools'])

    def test_empty_history_neither_creates_round_schema_nor_dispatches(self):
        fixture = run_fixtures.ResearchRunsTests('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        history = ResearchHistory(fixture.runs, events=Mock(), custody=Mock())
        self.assertEqual(history.list('alice', fixture.project), {'items': [], 'rounds': []})
        self.assertFalse(inspect(fixture.store.engine).has_table('research_rounds'))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(history.start('alice', fixture.project,
                ProjectCommand(requestId='new-agent-session', expectedVersion=0)))
        self.assertEqual(error.exception.detail, 'RESEARCH_USE_AGENT_SESSION')
        fixture.native.start.assert_not_called()
        with self.assertRaises(HTTPException) as denied:
            history.list('bob', fixture.project)
        self.assertEqual(denied.exception.status_code, 404)

    def test_original_round_remains_readable_and_start_cannot_replay(self):
        fixture = round_fixtures.ResearchRoundsFixture('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.start()
        with fixture.projects.db.read() as conn:
            before = dict(conn.execute(select(fixture.service.rounds)).mappings().one())
        fixture.native.start.reset_mock()
        history = ResearchHistory(fixture.legacy, events=fixture.events, custody=fixture.custody)
        value = history.list('alice', fixture.project)
        self.assertEqual(value['rounds'][0]['id'], before['id'])
        self.assertEqual(value['rounds'][0]['taskId'], before['task_id'])
        with self.assertRaises(HTTPException):
            asyncio.run(history.start('alice', fixture.project,
                ProjectCommand(requestId='round-start', expectedVersion=1)))
        with fixture.projects.db.read() as conn:
            after = dict(conn.execute(select(fixture.service.rounds)).mappings().one())
        self.assertEqual(before, after)
        fixture.native.start.assert_not_called()


    def test_qa_only_setup_reads_resources_without_round_pin_and_rejects_new_fixed_drafts(self):
        fixture = setup_fixtures.ResearchSetupTests('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        setup = ResearchSetup(fixture.store, fixture.auth, fixture.connections, fixture.models,
                              qa_workflow=None)
        with patch.object(fixture.store.native_workflows, 'pin', side_effect=AssertionError('No round lookup')):
            self.assertIsNone(setup.candidates('alice')['workflowPin'])
            self.assertNotIn('/api/factory/research/setup/drafts',
                [route.path for route in setup_router(fixture.auth, setup).routes])

    def test_historical_fixed_draft_is_readable_but_cannot_be_published(self):
        fixture = setup_fixtures.ResearchSetupTests('runTest')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.configure()
        draft = fixture.setup.prepare('alice', fixture.body)
        before = fixture.counts()
        setup = ResearchSetup(fixture.store, fixture.auth, fixture.connections, fixture.models)
        self.assertEqual(setup.read('alice', draft['id']), draft)
        with self.assertRaises(HTTPException) as error:
            setup.publish('alice', draft['id'], PublishSetup(requestId='retired-controller-publish'))
        self.assertEqual(error.exception.detail, 'RESEARCH_USE_AGENT_SESSION')
        self.assertEqual(fixture.counts(), before)
