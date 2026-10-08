# pyright: reportMissingImports=false
"""Native Agno 3.1 Workflow proof, not Factory or real ConvertD acceptance.

Synthetic Agent output selects a bounded Router branch. Native Condition routes a
returned domain FAILURE_JSON (not an exception) to recovery; native Parallel
joins two submissions before a supported step-level HumanReview. Native workflow
sessions/runs are the ONLY progress store. The fixture effect table is an append
witness, never a scheduler, replay guard, approval source or replacement engine.
No model network, real external job, GPU or physical-stop proof is claimed.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from uuid import uuid4
from typing import Any, cast

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.requirement import RunRequirement
from agno.tools import tool
from agno.workflow import Workflow
from agno.workflow.condition import Condition
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnReject, StepInput, StepOutput
from sqlalchemy import create_engine, text

from pg_fixture import IsolatedPostgres


class EnumModel(Model):
    """Fixed synthetic agent implementation, not a live inference claim."""
    def __init__(self, route):
        if route not in {'primary', 'failure'}: raise ValueError('FIXTURE_ROUTE_INVALID')
        super().__init__(id='native-workflow-enum-fixture', provider='controlled-local', retries=0)
        self.route = route
    def invoke(self, messages, **kwargs): return ModelResponse(role='assistant', content=json.dumps({'route': self.route}))
    async def ainvoke(self, messages, **kwargs): return self.invoke(messages, **kwargs)
    def invoke_stream(self, messages, **kwargs): yield self.invoke(messages, **kwargs)
    async def ainvoke_stream(self, messages, **kwargs): yield self.invoke(messages, **kwargs)
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response): return response


class WaitModel(EnumModel):
    def __init__(self): super().__init__('primary')
    def invoke(self, messages, **kwargs):
        if any(message.role == 'tool' for message in messages):
            return ModelResponse(role='assistant', content='Original synthetic receipts observed')
        return ModelResponse(role='assistant', tool_calls=[{'id': 'original-external-wait', 'type': 'function',
            'function': {'name': 'wait_original_operations', 'arguments': '{}'}}])


def build_workflow(db, engine, route, *, external_wait=False) -> Any:
    def effect(name, result):
        def execute(step_input: StepInput, run_context: RunContext) -> StepOutput:
            with engine.begin() as connection:
                connection.execute(text('INSERT INTO fixture_native_effects(stage,run_id) VALUES(:stage,:run)'),
                                   {'stage': name, 'run': run_context.run_id})
            return StepOutput(content=result)
        execute.__name__ = 'controlled_' + name
        return Step(name=name, executor=cast(Any, execute), max_retries=0)
    primary = effect('primary', {'status': 'OK'})
    failure = effect('failure', {'status': 'FAILURE_JSON', 'code': 'CONTROLLED_INVALID_INPUT'})
    def choose(step_input: StepInput):
        if not isinstance(step_input.previous_step_content, str): raise ValueError('FIXTURE_ROUTE_INVALID')
        decision = json.loads(step_input.previous_step_content)
        if type(decision) is not dict or set(decision) != {'route'} or decision['route'] not in {'primary', 'failure'}:
            raise ValueError('FIXTURE_ROUTE_INVALID')
        return [primary if decision['route'] == 'primary' else failure]
    def needs_recovery(step_input: StepInput):
        content = step_input.get_step_content('failure')
        return type(content) is dict and content.get('status') == 'FAILURE_JSON'
    review = effect('reviewed', {'approved': True})
    review.human_review = HumanReview(requires_confirmation=True, on_reject=OnReject.cancel)
    def submit(name):
        def execute(step_input: StepInput, run_context: RunContext) -> StepOutput:
            operation = str(uuid4())
            with engine.begin() as connection:
                connection.execute(text('INSERT INTO fixture_native_operations(operation_id,run_id,name,state) VALUES(:op,:run,:name,:state)'),
                    {'op': operation, 'run': run_context.run_id, 'name': name, 'state': 'RUNNING'})
            # The synthetic remote operation exists but its start acknowledgment
            # was lost. This stage retains the original ID; it does NOT retry.
            return StepOutput(content={'operationId': operation, 'state': 'UNKNOWN'})
        execute.__name__ = 'submit_' + name
        return Step(name=name, executor=cast(Any, execute), max_retries=0)
    @tool(external_execution=True)
    def wait_original_operations() -> str:
        """Await original externally owned receipts; never execute this body."""
        raise AssertionError('External execution body must not run')
    parallel = cast(Any, Parallel)(submit('left'), submit('right'), name='submission_join') if external_wait else cast(Any, Parallel)(
        effect('submit_left', {'submission': 'left'}), effect('submit_right', {'submission': 'right'}), name='submission_join')
    wait = Step(name='original_wait', max_retries=0, agent=Agent(id='original-receipt-reader',
        model=WaitModel(), tools=[wait_original_operations], telemetry=False)) if external_wait else review
    return Workflow(id='native-reuse-proof' , name='Native synthetic reuse proof', db=db, telemetry=False, steps=cast(Any, [
        Step(name='agent_decision', agent=Agent(id='synthetic-choice', model=EnumModel(route), telemetry=False), max_retries=0),
        Router(name='bounded_choice', selector=choose, choices=[primary, failure]),
        Condition(name='failure_recovery', evaluator=needs_recovery,
                  steps=[effect('recovery', {'status': 'RECOVERED'})]),
        parallel,
        wait,
        effect('final_report', {'evidenceMode': 'controlled-fixture', 'scientificConclusionVerified': False}),
    ]))


def status(value):
    return str(getattr(value.status, 'value', value.status)).lower()


def child_continue(payload):
    """Fresh-process native reload, no preexisting run object or Factory journal."""
    engine = create_engine(payload['database'])
    db = PostgresDb(db_url=payload['database'], id='native-reuse-db')
    try:
        workflow = build_workflow(db, engine, payload['route'], external_wait=payload.get('externalWait', False))
        paused = workflow.get_run_output(run_id=payload['runId'], session_id=payload['sessionId'])
        if paused is None or status(paused) != 'paused': raise ValueError('FIXTURE_ORIGINAL_PAUSE_REQUIRED')
        requirements = paused.active_step_requirements
        if len(requirements) != 1: raise ValueError('FIXTURE_ONE_REVIEW_REQUIRED')
        if payload.get('externalWait', False):
            requirement = requirements[0]
            if not requirement.requires_executor_input or len(requirement.executor_requirements or []) != 1:
                raise ValueError('FIXTURE_ORIGINAL_EXECUTOR_WAIT_REQUIRED')
            with engine.connect() as connection:
                rows = [dict(row) for row in connection.execute(text('SELECT operation_id,name,state FROM fixture_native_operations WHERE run_id=:run ORDER BY name'), {'run': payload['runId']}).mappings()]
            if len(rows) != 2 or any(row['state'] != 'COMPLETED' for row in rows):
                raise ValueError('FIXTURE_ORIGINAL_OPERATION_NOT_COMPLETE')
            raw = requirement.executor_requirements[0]
            original = RunRequirement.from_dict(raw) if isinstance(raw, dict) else raw
            original.set_external_execution_result(json.dumps({'originalOperations': rows, 'evidenceMode': 'controlled-fixture'}))
            requirement.executor_requirements = [original.to_dict()]
        else:
            requirements[0].confirm()
        completed = workflow.continue_run(run_id=payload['runId'], session_id=payload['sessionId'], step_requirements=requirements)
        if completed.run_id != payload['runId'] or status(completed) != 'completed':
            raise ValueError('FIXTURE_ORIGINAL_CONTINUATION_FAILED')
        print('NATIVE_REUSE_RESULT ' + json.dumps({'runId': completed.run_id, 'status': status(completed)}), flush=True)
    finally:
        db.db_engine.dispose(); engine.dispose()


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated loopback PostgreSQL')
class NativeWorkflowReusePostgresTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        database = self.stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        self.database = database.url
        self.engine = create_engine(self.database); self.stack.callback(self.engine.dispose)
        self.db = PostgresDb(db_url=self.database, id='native-reuse-db'); self.stack.callback(self.db.db_engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE fixture_native_effects (id BIGSERIAL PRIMARY KEY, stage TEXT NOT NULL, run_id TEXT NOT NULL)'))
            connection.execute(text('CREATE TABLE fixture_native_operations (operation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL)'))
    def effects(self):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(text('SELECT stage,run_id FROM fixture_native_effects ORDER BY id')).mappings()]
    def paused(self, route):
        session = str(uuid4()); workflow = build_workflow(self.db, self.engine, route)
        run = workflow.run('Choose a route using the synthetic bounded agent.', session_id=session, user_id='alice')
        self.assertEqual(status(run), 'paused')
        self.assertEqual(len(run.active_step_requirements), 1)
        self.assertEqual(run.active_step_requirements[0].step_name, 'reviewed')
        self.assertIsNotNone(workflow.get_session(session_id=session, user_id='alice'))
        return workflow, run, session
    def test_failure_route_parallel_join_and_fresh_process_same_run_continue(self):
        _, paused, session = self.paused('failure')
        before = self.effects()
        self.assertCountEqual([row['stage'] for row in before], ['failure', 'recovery', 'submit_left', 'submit_right'])
        self.assertTrue(all(row['run_id'] == paused.run_id for row in before))
        environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'LANG', 'LC_ALL') if key in os.environ}
        environment.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]), AGNO_TELEMETRY='false')
        process = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--continue-original'],
            input=json.dumps({'database': self.database, 'runId': paused.run_id, 'sessionId': session, 'route': 'failure'}),
            text=True, capture_output=True, timeout=60, env=environment)
        self.assertEqual(process.returncode, 0, process.stderr[-4000:])
        lines = [line for line in process.stdout.splitlines() if line.startswith('NATIVE_REUSE_RESULT ')]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0].split(' ', 1)[1]), {'runId': paused.run_id, 'status': 'completed'})
        after = self.effects()
        self.assertEqual(after[:len(before)], before)
        self.assertCountEqual([row['stage'] for row in after], ['failure', 'recovery', 'submit_left', 'submit_right', 'reviewed', 'final_report'])
        fresh = build_workflow(self.db, self.engine, 'failure')
        self.assertEqual(status(fresh.get_run_output(run_id=paused.run_id, session_id=session)), 'completed')
    def test_rejected_original_human_review_cancels_without_following_effects(self):
        _, paused, session = self.paused('primary')
        before = self.effects()
        self.assertCountEqual([row['stage'] for row in before], ['primary', 'submit_left', 'submit_right'])
        fresh = build_workflow(self.db, self.engine, 'primary')
        original = fresh.get_run_output(run_id=paused.run_id, session_id=session)
        self.assertIsNotNone(original)
        requirements = original.active_step_requirements
        requirements[0].reject()
        cancelled = fresh.continue_run(run_id=paused.run_id, session_id=session, step_requirements=requirements)
        self.assertEqual(cancelled.run_id, paused.run_id)
        self.assertEqual(status(cancelled), 'cancelled')
        self.assertEqual(self.effects(), before)


    def test_parallel_lost_ack_external_wait_fresh_process_lookup_without_resubmit(self):
        session = str(uuid4())
        flow = build_workflow(self.db, self.engine, 'primary', external_wait=True)
        paused = flow.run('synthetic bounded route', session_id=session, user_id='alice')
        self.assertEqual(status(paused), 'paused')
        self.assertTrue(paused.active_step_requirements[0].requires_executor_input)
        with self.engine.begin() as connection:
            before = [dict(row) for row in connection.execute(text('SELECT operation_id,run_id,name,state FROM fixture_native_operations ORDER BY name')).mappings()]
            self.assertEqual(len(before), 2)
            self.assertTrue(all(row['run_id'] == paused.run_id for row in before))
            connection.execute(text("UPDATE fixture_native_operations SET state='COMPLETED' WHERE run_id=:run"), {'run': paused.run_id})
        environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'LANG', 'LC_ALL') if key in os.environ}
        environment.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]), AGNO_TELEMETRY='false')
        completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--continue-original'],
            input=json.dumps({'database': self.database, 'runId': paused.run_id, 'sessionId': session, 'route': 'primary', 'externalWait': True}),
            text=True, capture_output=True, timeout=60, env=environment)
        self.assertEqual(completed.returncode, 0, completed.stderr[-4000:])
        with self.engine.connect() as connection:
            after = [dict(row) for row in connection.execute(text('SELECT operation_id,run_id,name,state FROM fixture_native_operations ORDER BY name')).mappings()]
        self.assertEqual(after, [{**row, 'state': 'COMPLETED'} for row in before])
        self.assertCountEqual([row['stage'] for row in self.effects()], ['primary', 'final_report'])
        fresh = build_workflow(self.db, self.engine, 'primary', external_wait=True)
        self.assertEqual(status(fresh.get_run_output(run_id=paused.run_id, session_id=session)), 'completed')


if __name__ == '__main__' and sys.argv[1:] == ['--continue-original']:
    child_continue(json.loads(sys.stdin.read(16384)))
