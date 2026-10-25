"""Portable domain contracts with explicit fake native ports, not execution proof."""
import asyncio
import time
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from sqlalchemy import func, select

from research.projects import Agreement, CreateProject, EndProject, ProjectCommand, ResearchProjects, ReviseGoal
from research.runs import ResearchRuns
from research.records import ResearchRecords
from agent_factory.application_content import ApplicationContent
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from types import MethodType
from test_research_projects import agreement
import test_applications_composition as fixtures


def executable_agreement():
    return Agreement.model_validate({**agreement().model_dump(), 'execution': {
        'applicationRef': {'id': 'fixture-checksum', 'version': 1, 'sha256': 'a' * 64},
        'mode': 'literature', 'deadline': time.time() + 300,
        'perRoundCaps': {'rounds': 1, 'toolCalls': 2}}})


class ResearchRunsTests(fixtures.ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.projects = ResearchProjects(self.store, self.auth, Mock())
        self.native = Mock()
        self.native.start = AsyncMock()
        self.store.transaction = MethodType(Store.transaction, self.store)
        self.scopes = Mock()
        self.scopes.inspect.side_effect = lambda *_: {'allocations': [{
            'allocationId': self.scopes.allocate.call_args.args[3], 'taskId': 'original-task'}]}
        self.applications_port = Mock()
        self.applications_port.require_current.return_value = {'modes': {'literature': {}}}
        self.content = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.runs = ResearchRuns(self.projects, self.native, self.scopes, self.applications_port, ResearchRecords(self.content))
        self.project = self.projects.create('alice', CreateProject(requestId='runs-project-create', title='Research intent'))['id']

    def confirm(self, value=None):
        value = value or executable_agreement()
        self.projects.change('alice', self.project, 'revise', ReviseGoal(
            requestId='runs-goal-original', expectedVersion=0, agreement=value))
        self.projects.change('alice', self.project, 'confirm', ProjectCommand(requestId='runs-goal-confirm', expectedVersion=1))
        return value

    def start(self, key='runs-start-original', version=1):
        return asyncio.run(self.runs.start('alice', self.project, ProjectCommand(requestId=key, expectedVersion=version)))

    def test_unconfirmed_or_unconfigured_never_allocates_or_dispatches(self):
        with self.assertRaises(HTTPException):
            self.start(version=0)
        self.confirm(agreement())
        with self.assertRaises(HTTPException) as denied:
            self.start()
        self.assertEqual(denied.exception.detail['code'], 'RESEARCH_EXECUTION_CONFIGURATION_REQUIRED')
        self.assertEqual(self.projects.read('alice', self.project)['execution'], {
            'available': False, 'reason': 'RESEARCH_EXECUTION_CONFIGURATION_REQUIRED'})
        self.scopes.create_scope.assert_not_called()
        self.scopes.allocate.assert_not_called()
        self.native.start.assert_not_awaited()

    def test_original_unknown_receipt_never_dispatches_or_allocates_again(self):
        self.confirm()
        self.assertEqual(self.projects.read('alice', self.project)['execution'], {'available': True, 'reason': None})
        unknown = {'taskId': 'original-task', 'runId': None, 'state': 'unknown'}
        # Missing is represented by the real port's 404, never an invented task.
        self.native.request.side_effect = [HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND'), unknown]
        first = self.start()
        self.assertEqual(self.projects.read('alice', self.project)['execution'], {
            'available': False, 'reason': 'RESEARCH_ORIGINAL_ATTEMPT_REQUIRED'})
        self.native.request.side_effect = None
        self.native.request.return_value = unknown
        self.assertEqual(self.start(), first)
        self.native.start.assert_awaited_once()
        self.scopes.create_scope.assert_called_once()
        self.scopes.allocate.assert_called_once()
        with self.assertRaises(HTTPException) as denied:
            self.start('runs-start-different')
        self.assertEqual(denied.exception.detail['code'], 'RESEARCH_ORIGINAL_ATTEMPT_REQUIRED')
        listed = self.runs.list('alice', self.project)['items']
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['attempt']['execution'], unknown)
        with self.assertRaises(HTTPException) as hidden:
            self.runs.list('bob', self.project)
        self.assertEqual(hidden.exception.status_code, 404)

    def test_lost_ack_preserves_intent_and_end_blocks_unadmitted_recovery(self):
        self.confirm()
        self.native.request.side_effect = HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND')
        self.native.start.side_effect = TimeoutError('controlled missing native acknowledgement')
        with self.assertRaises(TimeoutError):
            self.start()
        with self.projects.db.read() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.runs.attempts)).scalar(), 1)
        self.projects.change('alice', self.project, 'end', EndProject(requestId='runs-end-original',
            expectedVersion=1, outcome='cancelled', reason='Stop new execution'))
        self.scopes.cancel.assert_called_once()
        with self.assertRaises(HTTPException) as stopped:
            self.start()
        self.assertEqual(stopped.exception.detail['code'], 'RESEARCH_PROJECT_ENDED')
        self.native.start.assert_awaited_once()

    def test_goal_revision_retains_project_commitment_and_original_evidence(self):
        value = self.confirm()
        self.native.request.return_value = {'taskId': 'original-task', 'runId': None, 'state': 'unknown'}
        self.start()
        revised = value.model_copy(update={'objective': 'Revised objective'})
        self.projects.change('alice', self.project, 'revise', ReviseGoal(
            requestId='runs-goal-revised', expectedVersion=1, agreement=revised))
        self.assertEqual(self.runs.list('alice', self.project)['items'][0]['goalVersion'], 1)
        changed = revised.model_copy(update={'budget': revised.budget.model_copy(update={'rounds': 9})})
        with self.assertRaises(HTTPException) as frozen:
            self.projects.change('alice', self.project, 'revise', ReviseGoal(
                requestId='runs-budget-reset', expectedVersion=2, agreement=changed))
        self.assertEqual(frozen.exception.detail['code'], 'RESEARCH_COMMITMENT_FROZEN')
        self.scopes.create_scope.assert_called_once()
        self.assertEqual(self.projects.read('alice', self.project)['currentGoalVersion'], 2)

    def test_complete_agreement_enters_native_goal_and_required_text_input(self):
        self.applications_port.require_current.return_value = {'modes': {'literature': {'inputSchema': {
            'type': 'object', 'properties': {'goal': {'type': 'string', 'maxLength': 2000}},
            'required': ['goal'], 'additionalProperties': False}}}}
        agreement = self.confirm()
        self.native.request.side_effect = [HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND'),
            {'taskId': 'original-task', 'runId': None, 'state': 'unknown'}]
        self.start()
        native = self.native.start.await_args.args[1]
        self.assertEqual(native.goal, agreement.execution_goal())
        self.assertEqual(native.inputValues, {'goal': agreement.execution_goal()})
        for text in (agreement.objective, agreement.evaluation, agreement.stopConditions):
            self.assertIn(text, native.goal)

    def test_incompatible_input_contract_never_allocates_or_dispatches(self):
        self.applications_port.require_current.return_value = {'modes': {'literature': {'inputSchema': {
            'type': 'object', 'properties': {'dataset': {'type': 'string'}}, 'required': ['dataset']}}}}
        self.confirm()
        with self.assertRaises(HTTPException) as denied:
            self.start()
        self.assertEqual(denied.exception.detail['code'], 'RESEARCH_TEXT_INPUT_INCOMPATIBLE')
        self.scopes.create_scope.assert_not_called()
        self.native.start.assert_not_awaited()

    def test_mismatched_original_task_receipt_fails_without_dispatch(self):
        self.confirm()
        self.native.request.return_value = {'taskId': 'different-task', 'runId': None, 'state': 'unknown'}
        with self.assertRaises(HTTPException) as denied:
            self.start()
        self.assertEqual(denied.exception.detail['code'], 'RESEARCH_ALLOCATION_TASK_MISMATCH')
        self.native.start.assert_not_awaited()
        self.scopes.bind_request.assert_called_once()
        native_request = self.scopes.bind_request.call_args.args[3]
        self.assertTrue(native_request.startswith('application-start:research:'))
