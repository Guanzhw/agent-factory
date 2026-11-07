"""Command handles are original Agno Workflow children, never a second scheduler."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, cast

from agno.exceptions import RunCancelledException, StopAgentRun
from agno.run import RunContext
from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnError, StepInput, StepOutput

from agent_factory.native_workflows import NativeWorkflowRegistration
from agent_factory.input_schema import input_model
from agent_factory.personal_tool_contract import ToolInvocationError
from agent_factory.store import canonical, digest
from agent_factory.tool_output import DEFAULT_OUTPUT_TOKENS


WORKFLOW_ID = 'research-command'
MODE = 'command'
READ_PROCESS = 'research_read_process'
EFFECT_KEY = 'research-command-process'


def command_output(directory, budget):
    """Read a bounded preview from the complete on-disk streams."""
    paths = [directory / (channel + '.txt') for channel in ('stdout', 'stderr')]
    sizes = [path.stat().st_size if path.exists() else 0 for path in paths]
    total = sum(sizes)
    allocations = sizes if total <= budget else [budget * sizes[0] // total, budget - budget * sizes[0] // total]
    result = {}
    for channel, path, size, allocation in zip(('stdout', 'stderr'), paths, sizes, allocations):
        if not size:
            result[channel] = ''
            continue
        with path.open('rb') as stream:
            if size <= allocation:
                result[channel] = stream.read(allocation).decode(errors='replace')
            else:
                left, right = allocation // 2, allocation - allocation // 2
                prefix = stream.read(left).decode(errors='ignore')
                stream.seek(-right, 2)
                suffix = stream.read(right).decode(errors='ignore') if right else ''
                result[channel] = prefix + f'\n…{(size - allocation + 3) // 4} tokens truncated…\n' + suffix
    if total > budget:
        result.update(truncated=True, originalTokenCount=(total + 3) // 4)
    return result


class ResearchCommandWorkflow:
    def __init__(self, tools):
        self.tools = tools

        async def research_run(step_input: StepInput, run_context: RunContext):
            if self.tools.commands is None:
                raise RuntimeError('RESEARCH_COMMAND_WORKFLOW_UNAVAILABLE')
            result = await self.tools.commands.execute(run_context)
            return StepOutput(content=canonical(result))

        from .session_setup import COMMAND_INPUT_SCHEMA
        workflow = Workflow(id=WORKFLOW_ID, name='Research command', input_schema=input_model(COMMAND_INPUT_SCHEMA),
            steps=cast(Any, [Step(name='research_run', step_id='research_run',
                                 executor=cast(Any, research_run), max_retries=0, human_review=HumanReview(on_error=OnError.fail))]), telemetry=False)
        self.registration = NativeWorkflowRegistration(workflow, '1', ('research_run',),
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


class ResearchCommands:
    def __init__(self, tools, sessions):
        self.tools, self.sessions, self.store = tools, sessions, sessions.store

    def _directory(self, execution, child_id):
        return self.tools._workspace(execution) / ('.command-process-' + digest(child_id))

    async def start(self, context, call_id, values):
        self.sessions.authorize_tool(context, 'research_run')
        with self.sessions.db.read() as conn:
            row, turn, task = self.sessions._execution(conn, context)
        command = {key: value for key, value in values.items() if key != 'yield_time_ms'}
        inputs = {'sessionId': row['id'], 'turnId': turn['id'], 'sessionContext': canonical(command)}
        child = (await self.store.delegation.create(context.user_id, task['id'],
            'Run command: ' + ' '.join(values['argv']), MODE,
            'research-command:' + digest({'run': context.run_id, 'call': call_id}), input_values=inputs))['childTask']
        # The parent operation is dispatching this durable child, not owning its
        # process. Save that handoff before yielding: cancellation during the
        # first wait must not strand an UNKNOWN parent effect after child stop.
        self.store.effect_complete(context.run_id, 'research-session-tool:' + call_id,
            {'outcome': 'completed', 'output': {'processId': child['id'], 'childTaskId': child['id'],
                'status': 'queued', 'stopped': False, 'stdout': '', 'stderr': ''}})
        wait_ms = min(30000, max(250, values.get('yield_time_ms', 10000)))
        if sys.platform == 'win32':
            wait_ms = max(10000, wait_ms)
        deadline = asyncio.get_running_loop().time() + wait_ms / 1000
        while True:
            result = await self.read(context, {'processId': child['id'],
                'max_output_tokens': values.get('max_output_tokens', DEFAULT_OUTPUT_TOKENS)},
                execution_tool='research_run')
            if result['status'] not in {'queued', 'running'} or asyncio.get_running_loop().time() >= deadline:
                return result
            await asyncio.sleep(.1)

    async def read(self, context, values, *, execution_tool=READ_PROCESS):
        execution = self.sessions.authorize_tool(context, execution_tool)
        child = self.store.task(values['processId'], context.user_id)
        plan = self.store.plan(child['plan_id'], context.user_id)
        if (plan.get('mode') != MODE or plan.get('nativeComponent') != self.store.native_workflows.pin(WORKFLOW_ID)
                or (plan.get('inputValues') or {}).get('sessionId') != execution['id']
                or not plan.get('delegation')):
            raise PermissionError('RESEARCH_COMMAND_HANDLE_MISMATCH')
        # A handle refers to the same persisted task on every read and after restart.
        effects = self.store.effects(child['id'])
        original = next((item for item in effects if item['effect_key'].endswith(':' + EFFECT_KEY)), None)
        facts, ticket = {}, None
        if not original or original['status'] not in {'DONE', 'CANCELLED'}:
            group = await self.store.lifecycle_observer.inspect_subtree(context.user_id, child['id'])
            facts = group['parent']
            # Admission and process completion can advance while observation awaits.
            # Read the current binding, then the receipt after the native ticket:
            # a terminal ticket must not be paired with an earlier in-flight receipt.
            child = self.store.task(values['processId'], context.user_id)
            ticket = self.store.native_db.get_job(child['run_id']) if child.get('run_id') else None
            original = next((item for item in self.store.effects(child['id'])
                if item['effect_key'].endswith(':' + EFFECT_KEY)), None)
        directory = self._directory(execution, child['id'])
        output: dict[str, Any] = command_output(directory, values.get('max_output_tokens', DEFAULT_OUTPUT_TOKENS) * 4)
        if original and original['status'] in {'DONE', 'CANCELLED'}:
            receipt = original.get('result') or {}
            result = receipt.get('output') or {}
            status = 'cancelled' if receipt.get('cancelled') else 'completed' if receipt.get('outcome') == 'completed' and result.get('exitCode', 0) == 0 else 'failed'
            output = {**output, **{key: value for key, value in result.items()
                if key not in {'stdout', 'stderr', 'truncated', 'originalTokenCount'}}, 'status': status}
        else:
            native_status = str(facts.get('nativeStatus') or '').lower()
            # Unknown original execution is never restarted by this read path.
            unknown = bool(child.get('admission') == 'unknown' or native_status in {'failed', 'error'}
                or original and (not ticket or ticket.get('status') != 'running' or ticket.get('attempt', 1) > 1))
            stopped = bool(facts.get('stopped'))
            missing_receipt = native_status in {'completed', 'done'} and not original
            status = ('unknown' if unknown or missing_receipt else
                'cancelled' if native_status in {'cancelled', 'canceled'} and stopped else
                'unknown' if native_status in {'cancelled', 'canceled'} else
                'failed' if child.get('admission') == 'rejected' else
                'queued' if not original else 'running')
            output.update(status=status, stopped=stopped)
        workspace = self.tools._workspace(execution)
        output.update(processId=child['id'], childTaskId=child['id'],
            stdoutPath=(directory / 'stdout.txt').relative_to(workspace).as_posix(),
            stderrPath=(directory / 'stderr.txt').relative_to(workspace).as_posix())
        return output

    async def execute(self, context):
        execution = self.sessions.authorize_tool(context, 'research_run')
        plan = self.store.plan(self.store.task(context.session_id, context.user_id)['plan_id'], context.user_id)
        values = json.loads(plan['inputValues']['sessionContext'])
        request = {'taskId': context.session_id, 'ownerId': context.user_id, 'command': values}
        reserved = self.store.effect_reserve(context.run_id, EFFECT_KEY, request)
        if reserved['status'] == 'done':
            return reserved['result']['output']
        if reserved['status'] != 'new':
            raise StopAgentRun('RESEARCH_COMMAND_ORIGINAL_OUTCOME_UNKNOWN')
        directory = self._directory(execution, context.session_id)
        directory.mkdir(exist_ok=False)
        for channel in ('stdout', 'stderr'):
            (directory / (channel + '.txt')).touch(exist_ok=False)
        def guard():
            return self.sessions.authorize_tool(context, 'research_run')
        try:
            from types import SimpleNamespace
            result = await self.tools._run(self.tools._workspace(execution), values, guard,
                self.tools._environment(SimpleNamespace(plan=plan)), execution, output_directory=directory)
            receipt = {'outcome': 'completed', 'output': result}
        except ToolInvocationError as error:
            if error.stopped and error.outcome in {'cancelled', 'failed'}:
                receipt = {'outcome': error.outcome, 'stopped': True,
                    'cancelled': error.outcome == 'cancelled',
                    'output': {'code': error.code, 'stopped': True}}
            else:
                raise StopAgentRun('RESEARCH_COMMAND_ORIGINAL_OUTCOME_UNKNOWN') from None
        self.store.effect_complete(context.run_id, EFFECT_KEY, receipt)
        if receipt.get('cancelled'):
            raise RunCancelledException('RESEARCH_COMMAND_CANCELLED')
        return receipt['output']
