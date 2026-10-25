"""Portable research facts with fake execution ports, not native/GPU evidence."""
import asyncio
import hashlib
import json
from copy import deepcopy
from types import MethodType
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from agno.run import RunContext
from fastapi import HTTPException
from sqlalchemy import Column, JSON, LargeBinary, MetaData, String, Table, func, inspect, select
from sqlalchemy.exc import IntegrityError

from agent_factory.application_content import ApplicationContent, ContentPublication
from agent_factory.applications import GovernedStorage
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from research.projects import CreateProject, ProjectCommand, ResearchProjects, ReviseGoal
from research.records import ResearchRecords
from research.rounds import ResearchRounds
from research.runs import ResearchRuns
from research.workflow import Decision
import test_applications_composition as fixtures
from test_research_runs import executable_agreement


PIN = {'kind': 'workflow', 'id': 'research-round', 'revision': '1', 'sha256': 'b' * 64}


class ResearchRoundsFixture(fixtures.ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.store.transaction = MethodType(Store.transaction, self.store)
        self.content = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.endpoint = Mock()
        self.endpoint.db = GovernedStorage(self.store, 'fixture_endpoints')
        self.endpoint.configure.return_value = {'id': str(uuid4())}
        self.projects = ResearchProjects(self.store, self.auth, self.endpoint)
        self.native, self.scopes, self.apps = Mock(), Mock(), Mock()
        self.native.start = AsyncMock()
        self.apps.require_current.return_value = {'modes': {'literature': {'nativeComponent': PIN}}}
        self.legacy = ResearchRuns(self.projects, self.native, self.scopes, self.apps, ResearchRecords(self.content))
        self.events = Mock()
        self.events.db = GovernedStorage(self.store, 'fixture_events')
        self.events.emit.return_value = {'id': str(uuid4())}
        self.events.delivery_for_task.return_value = None
        self.custody, self.control = Mock(), Mock()
        self.service = ResearchRounds(self.legacy, events=self.events, endpoints=self.endpoint,
            custody=self.custody, control=self.control, pin=PIN)
        self.projects.execution = self.service
        self.project = self.projects.create('alice', CreateProject(requestId='round-project', title='Actual evidence'))['id']
        self.agreement = executable_agreement()
        self.projects.change('alice', self.project, 'revise', ReviseGoal(requestId='round-goal',
            expectedVersion=0, agreement=self.agreement))
        self.projects.change('alice', self.project, 'confirm', ProjectCommand(requestId='round-confirm', expectedVersion=1))
        self.task, self.run = str(uuid4()), str(uuid4())
        self.native.request.return_value = {'taskId': self.task, 'runId': self.run, 'state': 'accepted'}
        self.scopes.inspect.side_effect = self.scope
        self.custody.start = AsyncMock()

    def scope(self, *_):
        allocation = self.scopes.allocate.call_args.args[3] if self.scopes.allocate.called else 'none'
        return {'state': 'ACTIVE', 'deadline': self.agreement.execution.deadline,
            'caps': self.agreement.budget.model_dump(), 'allocatedRounds': 1,
            'heldToolCalls': 0, 'settledToolCalls': 1, 'usage': None,
            'allocations': [{'allocationId': allocation, 'taskId': self.task}]}

    def start(self):
        result = asyncio.run(self.service.start('alice', self.project, ProjectCommand(requestId='round-start', expectedVersion=1)))
        with self.projects.db.read() as conn:
            self.row = dict(conn.execute(select(self.service.rounds)).mappings().one())
        self.ctx = RunContext(run_id=self.run, session_id=self.task, user_id='alice',
            session_state={'factory_envelope': {'request_id': self.row['factory_request']}})
        return result

    def count(self, table):
        with self.projects.db.read() as conn:
            return conn.execute(select(func.count()).select_from(table)).scalar_one()

    def finish(self):
        task = {'id': self.task, 'owner_id': 'alice', 'request_id': self.row['factory_request'],
                'run_id': self.run, 'body': {'stoppedStatus': 'completed'}}
        with self.store.transaction() as conn:
            with self.service.finalization_context(conn, task) as complete:
                complete({'task': task, 'group': [task], 'settlement': {'state': 'SETTLED'}})


class ResearchRoundsTests(ResearchRoundsFixture):
    def test_start_replays_original_root_without_invented_experiment(self):
        result = self.start()
        self.assertEqual(self.start(), result)
        self.assertEqual(self.count(self.service.rounds), 1)
        self.assertEqual(self.count(self.legacy.experiments), 0)
        self.assertEqual(self.count(self.legacy.attempts), 0)
        self.scopes.allocate.assert_called_once()
        self.native.start.assert_not_awaited()
        value = self.service.context(self.ctx)
        self.assertEqual(value['agreement']['objective'], self.agreement.objective)
        self.assertEqual(value['evidenceIds'], [])
        self.assertNotIn('connectionRefs', str(value))
        self.assertEqual(self.service.list('alice', self.project)['rounds'][0]['taskId'], self.task)
        with self.assertRaises(HTTPException):
            self.service.list('bob', self.project)

    def test_original_custody_output_not_wait_text_controls_evidence(self):
        self.start()
        operation_id = str(uuid4())
        operation = {'id': operation_id, 'taskId': self.task, 'nativeRunId': self.run, 'closed': True,
                     'observation': {'state': 'COMPLETED', 'output': {'result': 'measured score 0.25'}}}
        self.custody.start.return_value = operation
        self.custody.read.return_value = operation
        chosen = Decision(action='experiment', reason='Need measurement', hypothesis='Try condition',
                          conditions='Fixed seed', goal='Measure score')
        first = asyncio.run(self.service.launch(self.ctx, chosen))
        self.assertEqual(first, operation)
        asyncio.run(self.service.launch(self.ctx, chosen))
        self.assertEqual(self.count(self.legacy.experiments), 1)
        self.assertEqual(self.count(self.legacy.attempts), 1)
        self.assertEqual(self.custody.start.await_args.args[4], {'goal': 'Measure score', 'mode': 'experiment'})
        result = self.service.results(self.ctx)
        self.assertEqual(result['operation']['output']['result'], 'measured score 0.25')
        self.assertEqual(result['evidenceIds'], [operation_id])
        with self.assertRaises(HTTPException):
            self.service.record_decision(self.ctx, {'action': 'continue', 'reason': 'Invented', 'evidenceIds': ['not-original']})
        self.service.record_decision(self.ctx, {'action': 'continue', 'reason': 'Try again', 'evidenceIds': [operation_id]})
        self.finish()
        self.finish()
        self.events.emit.assert_called_once()
        self.assertEqual(len(self.service.list('alice', self.project)['rounds'][0]['continuations']), 1)

    def test_stop_has_zero_child_and_transaction_failure_keeps_original_completion_pending(self):
        self.start()
        self.service.context(self.ctx)
        self.service.record_decision(self.ctx, Decision(action='stop', outcome='not_met', reason='No justified experiment').model_dump())
        original = self.content.publish
        def fail_after_publish(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('controlled publication failure')
        self.content.publish = fail_after_publish
        with self.assertRaises(RuntimeError):
            self.finish()
        self.assertEqual(self.count(self.content.contents), 0)
        self.assertIsNone(self.service.list('alice', self.project)['rounds'][0]['terminal'])
        self.content.publish = original
        self.finish()
        self.assertEqual(self.projects.read('alice', self.project)['ending']['outcome'], 'not_met')
        self.custody.start.assert_not_awaited()
        self.events.emit.assert_not_called()

    def test_ordinary_peer_message_cannot_authorize_research(self):
        self.start()
        forged = RunContext(run_id=self.run, session_id=self.task, user_id='alice',
            session_state={'factory_envelope': {'request_id': 'application-start:ordinary-message'}})
        with self.assertRaises(HTTPException) as denied:
            self.service.context(forged)
        self.assertEqual(denied.exception.detail['code'], 'RESEARCH_ORIGINAL_INTENT_REQUIRED')
        self.custody.start.assert_not_awaited()
        self.assertEqual(self.count(self.service.rounds), 1)

    def test_revoked_owner_does_not_publish_or_hold_domain_completion(self):
        self.start()
        self.service.context(self.ctx)
        self.auth.directory.set_disabled('alice', True)
        self.finish()
        with self.projects.db.read() as conn:
            row = conn.execute(select(self.service.rounds)).mappings().one()
            self.assertEqual(row['terminal']['sharing'], 'authorization_withdrawn')
            self.assertIsNone(row['terminal_record'])
        self.assertEqual(self.count(self.content.contents), 0)
        self.events.emit.assert_not_called()

    def test_scope_exhaustion_blocks_successor_without_scientific_met_claim(self):
        self.start()
        self.service.context(self.ctx)
        with self.projects.db.write() as conn:
            conn.execute(self.service.rounds.update().values(decision={'action': 'continue', 'reason': 'More evidence', 'evidenceIds': []}))
        original = self.scope()
        original['allocatedRounds'] = self.agreement.budget.rounds
        self.scopes.inspect.side_effect = None
        self.scopes.inspect.return_value = original
        self.finish()
        terminal = self.service.list('alice', self.project)['rounds'][0]['terminal']
        self.assertEqual(terminal['continuationBlocked'], 'LOCAL_BUDGET_EXHAUSTED')
        self.assertNotIn('outcome', terminal['decision'])
        self.events.emit.assert_not_called()

    def test_goal_revision_resumes_only_original_scope_event_once(self):
        self.start()
        self.service.context(self.ctx)
        revised = self.agreement.model_copy(update={'objective': 'Revised goal'})
        self.projects.change('alice', self.project, 'revise', ReviseGoal(
            requestId='round-revised', expectedVersion=1, agreement=revised))
        self.finish()
        self.projects.change('alice', self.project, 'confirm', ProjectCommand(requestId='round-reconfirmed', expectedVersion=2))
        command = ProjectCommand(requestId='round-resume', expectedVersion=2)
        receipt = asyncio.run(self.service.start('alice', self.project, command))
        self.assertEqual(asyncio.run(self.service.start('alice', self.project, command)), receipt)
        self.assertIn('eventId', receipt)
        self.scopes.allocate.assert_called_once()
        self.scopes.create_scope.assert_called_once()
        self.events.emit.assert_called_once()
        self.native.start.assert_not_awaited()
        self.assertEqual(self.count(self.service.rounds), 1)
        changed = deepcopy(revised.model_dump())
        changed['execution']['mode'] = 'other'
        with self.assertRaises(HTTPException) as denied:
            self.projects.change('alice', self.project, 'revise', ReviseGoal(
                requestId='round-reconfigure', expectedVersion=2, agreement=changed))
        self.assertEqual(denied.exception.detail['code'], 'RESEARCH_EXECUTION_FROZEN')

    def test_successor_binds_original_delivery_without_allocation_and_reads_private_actual_output(self):
        self.start()
        operation = {'id': str(uuid4()), 'taskId': self.task, 'nativeRunId': self.run, 'closed': True,
                     'observation': {'state': 'COMPLETED', 'output': {'result': 'private original measurement'}}}
        self.custody.start.return_value = operation
        self.custody.read.return_value = operation
        asyncio.run(self.service.launch(self.ctx, Decision(action='experiment', reason='Measure',
            hypothesis='Hypothesis', conditions='Controlled', goal='Measure')))
        self.service.record_decision(self.ctx, {'action': 'continue', 'reason': 'Another condition',
                                              'evidenceIds': [operation['id']]})
        self.finish()
        with self.projects.db.read() as conn:
            row = conn.execute(select(self.service.rounds)).mappings().one()
            trigger = row['continuations'][0]
        self.assertNotIn('private original measurement', str(self.content.read('bob', trigger['contentId'])))
        next_task, next_run = str(uuid4()), str(uuid4())
        self.events.delivery_for_task.return_value = {'deliveryId': str(uuid4()), 'eventId': trigger['eventId'],
            'contentId': trigger['contentId'], 'scopeId': row['scope_id'], 'allocationId': str(uuid4()),
            'rootId': trigger['eventId'], 'depth': 0}
        self.native.request.return_value = {'taskId': next_task, 'runId': next_run, 'state': 'accepted'}
        ctx = RunContext(run_id=next_run, session_id=next_task, user_id='alice',
            session_state={'factory_envelope': {'request_id': 'application-start:original-event-message'}})
        context = self.service.context(ctx)
        self.assertEqual(context['previousObservation']['output']['result'], 'private original measurement')
        self.assertEqual(self.service.context(ctx), context)
        self.assertEqual(self.count(self.service.rounds), 2)
        self.scopes.allocate.assert_called_once()
        self.native.start.assert_not_awaited()

    def test_original_wait_observation_reconciles_only_closed_operation(self):
        self.start()
        operation = {'id': str(uuid4()), 'taskId': self.task, 'nativeRunId': self.run,
                     'closed': False, 'handle': {'id': 'original'}, 'observation': {'state': 'RUNNING'}}
        self.custody.start.return_value = operation
        self.custody.read.return_value = operation
        asyncio.run(self.service.launch(self.ctx, Decision(action='experiment', reason='Measure',
            hypothesis='Hypothesis', conditions='Controlled', goal='Measure')))
        self.custody.inspect = AsyncMock(return_value=operation)
        self.control.snapshot = AsyncMock(return_value={'workflow': {'status': 'PAUSED', 'version': 'c' * 64,
            'requirements': [{'kind': 'external'}]}})
        self.control.receipt = AsyncMock(side_effect=HTTPException(404, 'NATIVE_WORKFLOW_COMMAND_NOT_FOUND'))
        self.control.submit = AsyncMock()
        task = {'id': self.task, 'owner_id': 'alice'}
        asyncio.run(self.service.observe_waits(None, task))
        self.control.submit.assert_not_awaited()
        closed = {**operation, 'closed': True, 'observation': {'state': 'COMPLETED'}}
        self.custody.inspect.return_value = closed
        asyncio.run(self.service.observe_waits(None, task))
        self.control.submit.assert_awaited_once()
        command = self.control.submit.await_args.args[2]
        self.assertEqual(command.commandId, 'research-reconcile:' + operation['id'])
        self.assertEqual(command.operationId, operation['id'])
        self.control.receipt.side_effect = None
        self.control.receipt.return_value = {'status': 'completed'}
        asyncio.run(self.service.observe_waits(None, task))
        self.control.submit.assert_awaited_once()

    def test_team_terminal_does_not_grant_original_private_artifact(self):
        self.start()
        metadata = MetaData()
        tasks = Table('af_tasks', metadata, Column('id', String, primary_key=True),
            Column('owner_id', String), Column('run_id', String))
        artifacts = Table('af_artifacts', metadata, Column('id', String, primary_key=True),
            Column('task_id', String), Column('body', JSON), Column('content', LargeBinary))
        metadata.create_all(self.store.engine)
        child_id, artifact_id = str(uuid4()), str(uuid4())
        canary = b'synthetic private research artifact canary'
        sha = hashlib.sha256(canary).hexdigest()
        artifact = {'id': artifact_id, 'jobId': child_id, 'name': 'private-fixture.txt',
                    'mediaType': 'text/plain', 'size': len(canary), 'sha256': sha, 'createdAt': 'fixture'}
        with self.store.transaction() as conn:
            conn.execute(tasks.insert().values(id=child_id, owner_id='alice', run_id=str(uuid4())))
            conn.execute(artifacts.insert().values(id=artifact_id, task_id=child_id, body=artifact, content=canary))
        # SQLite text queries return JSON strings; retain the production Store
        # owner/hash checks with only that portable driver conversion.
        def sql(store, statement, **params):
            rows = Store.sql(store, statement, **params)
            for row in rows:
                if isinstance(row.get('body'), str):
                    row['body'] = json.loads(row['body'])
            return rows
        self.store.sql = MethodType(sql, self.store)
        self.store.task = MethodType(Store.task, self.store)
        self.store.artifact = MethodType(Store.artifact, self.store)
        reference = {'taskId': child_id, 'artifactId': artifact_id, 'sha256': sha}
        personal = self.content.publish('alice', ContentPublication(
            source={'application': 'research', 'record': 'private-canary', 'revision': '1'},
            content={'description': 'Owner retained raw evidence'}, artifacts=[reference]), 'private-canary-original')
        self.assertEqual(self.content.artifact('alice', personal['id'], artifact_id)[1], canary)
        operation = {'id': str(uuid4()), 'taskId': self.task, 'nativeRunId': self.run, 'closed': True,
            'observation': {'state': 'COMPLETED', 'output': {'result': canary.decode(), 'artifacts': [reference]}}}
        self.custody.start.return_value = operation
        self.custody.read.return_value = operation
        asyncio.run(self.service.launch(self.ctx, Decision(action='experiment', reason='Measure',
            hypothesis='Hypothesis', conditions='Controlled', goal='Measure')))
        self.assertEqual(self.service.results(self.ctx)['operation']['output']['artifacts'], [reference])
        self.service.record_decision(self.ctx, {'action': 'stop', 'outcome': 'not_met',
            'reason': 'Insufficient evidence', 'evidenceIds': [operation['id']]})
        self.finish()
        terminal_id = self.service.list('alice', self.project)['rounds'][0]['terminalRecordId']
        team = self.content.read('bob', terminal_id)
        self.assertEqual(team['content']['kind'], 'research.round.terminal')
        self.assertEqual(team['artifacts'], [])
        self.assertNotIn(canary.decode(), str(team))
        with self.assertRaises(HTTPException) as denied:
            self.content.artifact('bob', terminal_id, artifact_id)
        self.assertEqual(denied.exception.detail, 'APPLICATION_CONTENT_ARTIFACT_NOT_FOUND')
        with self.assertRaises(HTTPException):
            self.content.artifact('bob', personal['id'], artifact_id)
        self.assertEqual(self.content.artifact('alice', personal['id'], artifact_id)[1], canary)


class ResearchRoundsMigrationTests(fixtures.ApplicationCompositionFixture):
    def test_existing_unique_rows_survive_first_migration_and_reopen(self):
        projects = ResearchProjects(self.store, self.auth, Mock())
        native, scopes, applications, records = Mock(), Mock(), Mock(), Mock()
        legacy = ResearchRuns(projects, native, scopes, applications, records)
        original_experiment = {'id': 'old-experiment', 'project_id': 'old-project', 'goal_version': 1,
            'hypothesis': 'Preserve original hypothesis', 'conditions': {'seed': 7}, 'created_at': 'original-time'}
        original_attempt = {'id': 'old-attempt', 'experiment_id': 'old-experiment',
                            'allocation_id': 'old-allocation', 'request': {'requestId': 'original-request'}}
        with projects.db.write() as conn:
            for table in (legacy.experiments, legacy.attempts):
                self.assertNotIn('round_id', {item['name'] for item in inspect(conn).get_columns(table.name)})
            conn.execute(legacy.experiments.insert().values(**original_experiment))
            conn.execute(legacy.attempts.insert().values(**original_attempt))
            for table, original in ((legacy.experiments, original_experiment), (legacy.attempts, original_attempt)):
                with self.assertRaises(IntegrityError):
                    with conn.begin_nested():
                        conn.execute(table.insert().values(**{**original, 'id': 'duplicate-before-migration'}))
        ports = {'events': Mock(), 'endpoints': Mock(), 'custody': Mock(), 'control': Mock(), 'pin': PIN}
        ResearchRounds(legacy, **ports)
        with projects.db.write() as conn:
            conn.execute(legacy.experiments.insert().values(**{**original_experiment, 'id': 'second-experiment'}))
            conn.execute(legacy.attempts.insert().values(**{**original_attempt, 'id': 'second-attempt'}))
        reopened = ResearchRuns(projects, native, scopes, applications, records)
        ResearchRounds(reopened, **ports)
        with projects.db.read() as conn:
            experiments = {row['id']: dict(row) for row in conn.execute(select(reopened.experiments)).mappings()}
            attempts = {row['id']: dict(row) for row in conn.execute(select(reopened.attempts)).mappings()}
        self.assertEqual(set(experiments), {'old-experiment', 'second-experiment'})
        self.assertEqual(set(attempts), {'old-attempt', 'second-attempt'})
        self.assertEqual(experiments['old-experiment'], {**original_experiment, 'round_id': None})
        self.assertEqual(attempts['old-attempt'], {**original_attempt, 'round_id': None, 'operation_id': None, 'selection': None})
