"""Resume only original SSH operations through native Agent control receipts."""
from copy import deepcopy

from agno.run.requirement import RunRequirement
from fastapi import HTTPException

from .control_commands import ControlCommand
from .factory_api import native_requirements, requirement_version
from .ssh_process_contract import LAUNCH_ADAPTER_ID, WAIT_ADAPTER_ID, REVISION, WAIT_TOOL
from .store import canonical, digest


def require(value):
    if not value:
        raise HTTPException(409, 'SSH_OPERATION_WAIT_MISMATCH')


class SSHOperationWaits:
    def __init__(self, store, custody, operation_pin, *, commands, runs):
        self.store, self.custody = store, custody
        self.operation_pin = dict(operation_pin)
        self.commands, self.runs = commands, runs

    def _selected(self, task):
        plan = self.store.plan(task['plan_id'], task['owner_id'])
        if (plan.get('nativeComponent') or {}).get('kind') == 'workflow':
            return False
        tools = (plan.get('executionBindings') or {}).get('tools') or []
        pins = {(tool.get('adapterId'), tool.get('revision')) for tool in tools}
        return {(LAUNCH_ADAPTER_ID, REVISION), (WAIT_ADAPTER_ID, REVISION)} <= pins

    def _operations(self, task, requirement):
        tool = requirement.get('tool_execution') or {}
        require(tool.get('tool_name') == WAIT_TOOL and tool.get('external_execution_required') is True
                and tool.get('result') is None and tool.get('tool_call_id'))
        ids = (tool.get('tool_args') or {}).get('operationIds')
        require(type(ids) is list and 0 < len(ids) <= 16 and all(isinstance(value, str) for value in ids)
                and len(ids) == len(set(ids)))
        assert isinstance(ids, list)
        operations = [self.custody.read(task['owner_id'], identifier) for identifier in ids]
        require(all(op['taskId'] == task['id'] and op['nativeRunId'] == task['run_id']
                    and op['adapterPin'] == self.operation_pin for op in operations))
        return operations

    async def external_result(self, commands, task, requirement, requirements, decision):
        if not self._selected(task) or (requirement.get('tool_execution') or {}).get('tool_name') != WAIT_TOOL:
            return None
        require(decision['approved'] is True)
        operations = self._operations(task, requirement)
        require(all(op['closed'] and op['observation']['allStopped'] for op in operations))
        require(len(operations) == 1)
        result = self.runs.ssh_results(task['owner_id'], task['id'], task['run_id'])
        require(result['operationId'] == operations[0]['id'])
        observed = {'operationId': result['operationId'], 'state': operations[0]['observation']['state'],
            'allStopped': True, 'executionStatus': result['receipt']['executionStatus'],
            'exitCode': result['receipt']['exitCode'], 'output': result['output']}
        resolved = RunRequirement.from_dict(requirement)
        resolved.set_external_execution_result(canonical({'operations': [observed]}))
        updated = [resolved.to_dict() if row['id'] == requirement['id'] else deepcopy(row) for row in requirements]
        return {'requirements': updated, 'toolsSha256': digest([row.get('tool_execution', row) for row in updated])}

    async def observe_waits(self, observer, task):
        if task['terminal'] or task['cancel_requested'] or not task.get('run_id') or not self._selected(task):
            return
        commands = self.commands
        receipts, cursor = [], None
        while True:
            page = await commands.list(task['owner_id'], task['id'], after=cursor, outstanding=False)
            receipts.extend(page['items'])
            cursor = page['nextCursor']
            if cursor is None:
                break
        for receipt in receipts:
            if receipt['commandId'].startswith('ssh-wait:') and not receipt['decisionRecorded']:
                if receipt['canDispatch']:
                    await commands.dispatch(task['owner_id'], task['id'], receipt['commandId'])
                return  # DISPATCHING/UNKNOWN is observed by list, never sent again.
        snapshot = await commands.bridge.detail(task['run_id'], task['id'], task['owner_id'])
        status = (snapshot.get('queue') or {}).get('status') or snapshot.get('status')
        if str(status).lower() not in {'paused', 'runstatus.paused'}:
            return
        for requirement in native_requirements(snapshot):
            tool = requirement.get('tool_execution') or {}
            if tool.get('tool_name') != WAIT_TOOL or tool.get('result') is not None:
                continue
            if any(receipt['requirementId'] == requirement['id'] for receipt in receipts):
                return
            operations = self._operations(task, requirement)
            for operation in operations:
                if not operation['closed']:
                    observe = self.custody.lookup if operation['handle'] is None else self.custody.inspect
                    await observe(task['owner_id'], operation['id'])
            if not all(op['closed'] for op in self._operations(task, requirement)):
                return
            version = requirement_version(requirement)
            command_id = 'ssh-wait:' + digest({'task': task['id'], 'run': task['run_id'],
                'requirement': requirement['id'], 'toolCall': tool['tool_call_id'], 'version': version})
            await commands.submit(task['owner_id'], task['id'], ControlCommand(commandId=command_id,
                action='approve', requirementId=requirement['id'], version=version, approved=True))
            return
