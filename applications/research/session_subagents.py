"""Research children reuse platform delegation and Agno's original native wait."""
from copy import deepcopy
import json

from agno.run.requirement import RunRequirement
from fastapi import HTTPException

from agent_factory.control_commands import ControlCommand
from agent_factory.factory_api import native_requirements, requirement_version
from agent_factory.store import canonical, digest


SPAWN = 'research_delegate'
WAIT = 'research_wait_child'


class ResearchSubagents:
    def __init__(self, sessions):
        self.sessions, self.store = sessions, sessions.store
        self.commands = sessions.runs.factory.commands

    def root_task(self, owner, task, plan):
        if not plan.get('delegation'):
            return task
        links = self.store.sql('SELECT * FROM af_delegation_links WHERE owner_id=:owner AND child_id=:child',
            owner=owner, child=task['id'])
        if len(links) != 1 or links[0]['parent_id'] != links[0]['root_id']:
            raise PermissionError('RESEARCH_CHILD_ORIGINAL_ROOT_REQUIRED')
        link = links[0]
        if (link['plan_id'] != task['plan_id'] or plan['delegation'] != {
                'parentTaskId': link['parent_id'], 'rootTaskId': link['root_id'], 'depth': link['depth']}):
            raise PermissionError('RESEARCH_CHILD_ORIGINAL_ROOT_REQUIRED')
        return self.store.task(link['root_id'], owner)

    async def start(self, context, call_id, goal):
        self.sessions.authorize_tool(context, SPAWN)
        with self.sessions.db.read() as conn:
            row, turn, task = self.sessions._execution(conn, context)
        inputs = {'sessionId': row['id'], 'turnId': turn['id'], 'sessionContext': json.dumps({
            'goal': row['body']['goal'], 'boundaries': row['body']['boundaries'], 'subtask': goal})}
        result = await self.store.delegation.create(context.user_id, task['id'], goal, 'autonomous',
            'research-child:' + digest({'run': context.run_id, 'call': call_id}), input_values=inputs)
        child = result['childTask']
        group = await self.store.lifecycle_observer.inspect_subtree(context.user_id, child['id'])
        return self._projection(child, group)

    def _projection(self, child, group):
        facts = group['parent']
        status = ('unknown' if group['unknown'] else 'canceling' if child['cancel_requested'] and not group['allStopped']
                  else 'failed' if facts['failed'] else facts['nativeStatus'] or 'unknown')
        result = (facts.get('content') if group['allStopped'] and status == 'completed'
                  and facts.get('persistedRunStatus') == 'completed' else None)
        if result is not None and not isinstance(result, str):
            result = canonical(result)
        return {'childTaskId': child['id'], 'runId': child.get('run_id'),
                'goal': self.store.plan(child['plan_id'], child['owner_id'])['normalizedGoal'],
                'status': status, 'result': result}

    async def children(self, task):
        result = []
        links = self.store.sql('SELECT * FROM af_delegation_links WHERE owner_id=:owner AND parent_id=:parent '
            'ORDER BY created_at', owner=task['owner_id'], parent=task['id'])
        for link in links:
            if link['child_id'] is None:
                continue
            child = self.store.task(link['child_id'], task['owner_id'])
            group = await self.store.lifecycle_observer.inspect_subtree(task['owner_id'], child['id'])
            result.append(self._projection(child, group))
        return result

    def _linked(self, task, requirement):
        tool = requirement.get('tool_execution') or {}
        if (tool.get('tool_name') != WAIT or not tool.get('external_execution_required')
                or tool.get('result') is not None or not tool.get('tool_call_id')):
            raise HTTPException(409, 'RESEARCH_CHILD_WAIT_REQUIRED')
        child_id = (tool.get('tool_args') or {}).get('childTaskId')
        links = self.store.sql('SELECT * FROM af_delegation_links WHERE owner_id=:owner '
            'AND parent_id=:parent AND child_id=:child', owner=task['owner_id'], parent=task['id'], child=child_id)
        if len(links) != 1:
            raise HTTPException(409, 'RESEARCH_CHILD_WAIT_LINK_MISMATCH')
        return self.store.task(child_id, task['owner_id'])

    async def external_result(self, commands, task, requirement, requirements, decision):
        if (requirement.get('tool_execution') or {}).get('tool_name') != WAIT:
            return None
        if decision.get('approved') is not True:
            raise HTTPException(409, 'RESEARCH_CHILD_WAIT_CANCEL_INSTEAD')
        child = self._linked(task, requirement)
        group = await self.store.lifecycle_observer.inspect_subtree(task['owner_id'], child['id'])
        if not group['allStopped'] or group['unknown']:
            raise HTTPException(409, 'RESEARCH_CHILD_RESULT_NOT_CONFIRMED')
        output = self._projection(child, group)
        resolved = RunRequirement.from_dict(requirement)
        resolved.set_external_execution_result(canonical(output))
        updated = [resolved.to_dict() if item['id'] == requirement['id'] else deepcopy(item) for item in requirements]
        ticket = self.store.native_db.get_job(task['run_id'])
        if not ticket or ticket['status'] != 'paused':
            raise HTTPException(409, 'RESEARCH_CHILD_WAIT_NOT_PAUSED')
        return {'requirements': updated, 'toolsSha256': digest([item.get('tool_execution', item) for item in updated]),
                'researchChildWait': {'pausedAttempt': ticket['attempt'], 'childTaskId': child['id'],
                    'childRunId': child['run_id'], 'requirementId': requirement['id'],
                    'toolCallId': requirement['tool_execution']['tool_call_id']}}

    def permits_continuation(self, task, ticket):
        continuation = (ticket.get('payload') or {}).get('continue') or {}
        proof = ((continuation.get('kwargs') or {}).get('metadata') or {}).get('factoryControlCommand') or {}
        if not proof.get('commandId'):
            return False
        try:
            command = self.commands.row(task['owner_id'], task['id'], proof['commandId'])
        except HTTPException:
            return False
        body = command['body']
        wait = body.get('researchChildWait') or {}
        if (command['state'] != 'DISPATCHING' or command['action'] != 'approve'
                or proof != {'commandId': command['command_id'], 'fingerprint': command['fingerprint']}
                or body['binding'] != self.commands._binding(task)
                or body['decision'].get('approved') is not True
                or body['decision'].get('requirementId') != wait.get('requirementId')
                or type(wait.get('pausedAttempt')) is not int or ticket['attempt'] != wait['pausedAttempt'] + 1
                or digest(continuation.get('updated_tools')) != body.get('toolsSha256')):
            return False
        tools = continuation.get('updated_tools') or []
        return any(item.get('tool_name') == WAIT and item.get('tool_call_id') == wait.get('toolCallId')
            and (item.get('tool_args') or {}).get('childTaskId') == wait.get('childTaskId')
            for item in tools)

    async def observe_waits(self, observer, task):
        if task['terminal'] or task['cancel_requested'] or not task.get('run_id'):
            return
        ticket = self.store.native_db.get_job(task['run_id'])
        if not ticket or ticket['status'] != 'paused':
            return
        snapshot = await self.commands.bridge.detail(task['run_id'], task['id'], task['owner_id'])
        for requirement in native_requirements(snapshot):
            if (requirement.get('tool_execution') or {}).get('tool_name') != WAIT:
                continue
            child = self._linked(task, requirement)
            group = await observer.inspect_subtree(task['owner_id'], child['id'])
            if not group['allStopped'] or group['unknown']:
                return
            await self.commands.submit(task['owner_id'], task['id'], ControlCommand(
                commandId='research-child-wait:' + digest({'run': task['run_id'], 'requirement': requirement['id']}),
                action='approve', requirementId=requirement['id'], version=requirement_version(requirement), approved=True))
            return
