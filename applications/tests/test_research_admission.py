"""Current admission and persisted old identities; portable fake execution ports."""
import asyncio
from copy import deepcopy

from fastapi import HTTPException

from agent_factory.store import digest
from research.projects import EndProject, ProjectCommand
from research_history_fixture import seed_legacy_intent
from test_research_rounds import ResearchRoundsFixture


class ResearchAdmissionTests(ResearchRoundsFixture):
    def command(self, key='original-command'):
        return ProjectCommand(requestId=key, expectedVersion=1)

    def test_new_nonresearch_mode_is_unavailable_and_never_allocates(self):
        self.apps.require_current.return_value = {'modes': {'literature': {}}}
        self.assertEqual(self.projects.read('alice', self.project)['execution'], {
            'available': False, 'reason': 'RESEARCH_NATIVE_COMPONENT_REQUIRED'})
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(self.service.start('alice', self.project, self.command()))
        self.assertEqual(caught.exception.detail['code'], 'RESEARCH_NATIVE_COMPONENT_REQUIRED')
        self.scopes.allocate.assert_not_called()
        self.native.start.assert_not_awaited()
        self.assertEqual(self.count(self.legacy.experiments), 0)
        self.assertEqual(self.count(self.service.rounds), 0)

    def test_no_workflow_cannot_create_a_new_legacy_intent(self):
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(self.legacy.start('alice', self.project, self.command()))
        self.assertEqual(caught.exception.detail['code'], 'RESEARCH_NATIVE_COMPONENT_REQUIRED')
        self.scopes.create_scope.assert_not_called()
        self.native.start.assert_not_awaited()

    def test_original_round_receipt_survives_changed_pin_and_unavailable_catalog(self):
        original = self.start()
        self.service.pin = {**self.service.pin, 'sha256': 'c' * 64}
        self.apps.require_current.side_effect = HTTPException(404, 'original application unavailable')
        self.native.request.return_value = {**original['execution'], 'state': 'unknown'}
        expected = {**original, 'execution': self.native.request.return_value}
        self.assertEqual(self.start(), expected)
        self.assertEqual(self.projects.read('alice', self.project)['execution']['reason'], 'RESEARCH_ORIGINAL_ATTEMPT_REQUIRED')
        self.scopes.allocate.assert_called_once()
        self.native.start.assert_not_awaited()

    def test_original_legacy_command_is_not_reclassified_as_a_round(self):
        command = self.command()
        original = seed_legacy_intent(self.legacy, 'alice', self.project, command, self.agreement)
        for service in (self.service, self.legacy):
            result = asyncio.run(service.start('alice', self.project, command))
            self.assertEqual(result['attemptId'], original['attemptId'])
        self.scopes.allocate.assert_called_once()
        self.native.start.assert_not_awaited()
        self.assertEqual(self.count(self.service.rounds), 0)

    def test_no_workflow_returns_original_round_start_and_resume_commands(self):
        original = self.start()
        command = ProjectCommand(requestId='round-start', expectedVersion=1)
        self.assertEqual(asyncio.run(self.legacy.start('alice', self.project, command)), original)
        resumed = {'projectId': self.project, 'goalVersion': 1, 'eventId': 'original-event', 'contentId': 'original-content'}
        resume = self.command('round-resume')
        with self.projects.db.write() as conn:
            self.projects.db.record(conn, self.projects.commands, 'alice', resume.requestId,
                digest({'action': 'round.start', 'project': self.project, 'expectedVersion': 1}),
                'research.round.resume', resumed)
        self.assertEqual(asyncio.run(self.legacy.start('alice', self.project, resume)), resumed)
        self.native.start.assert_not_awaited()

    def test_original_intent_recovery_preserves_request_and_cancel_blocks_unadmitted(self):
        command = self.command()
        original = seed_legacy_intent(self.legacy, 'alice', self.project, command, self.agreement)
        request = deepcopy(original['request'])
        self.native.request.side_effect = [HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND'),
            {'taskId': self.task, 'runId': None, 'state': 'unknown'}]
        recovered = asyncio.run(self.service.start('alice', self.project, command))
        self.assertEqual(self.native.start.await_args.args[1].model_dump(), request)
        self.assertEqual(self.native.start.await_args.kwargs, {'allocation_id': original['allocationId']})
        self.projects.change('alice', self.project, 'end', EndProject(requestId='end-original', expectedVersion=1,
            outcome='cancelled', reason='Stop original work'))
        self.native.request.side_effect = None
        self.native.request.return_value = recovered['execution']
        self.assertEqual(asyncio.run(self.service.start('alice', self.project, command)), recovered)
        self.native.request.side_effect = HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND')
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(self.service.start('alice', self.project, command))
        self.assertEqual(denied.exception.detail['code'], 'RESEARCH_PROJECT_ENDED')
        self.native.start.assert_awaited_once()
        self.scopes.cancel.assert_called_once()

    def test_original_command_cannot_change_owner_project_version_or_action(self):
        original = self.start()
        for owner, project, command in [('bob', self.project, self.command('round-start')),
                ('alice', 'other-project', self.command('round-start')),
                ('alice', self.project, ProjectCommand(requestId='round-start', expectedVersion=2)),
                ('alice', self.project, self.command('round-confirm'))]:
            with self.subTest(owner=owner, project=project, command=command), self.assertRaises(HTTPException):
                asyncio.run(self.service.start(owner, project, command))
        self.assertEqual(self.start(), original)
        self.scopes.allocate.assert_called_once()
        self.native.start.assert_not_awaited()
