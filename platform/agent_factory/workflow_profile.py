"""Tools for a real registered agent to select workflow stages; no scripted model."""
import json

from agno.run import RunContext
from agno.tools import tool

from .execution_bindings import AdapterRegistration
from .workflow_contracts import workflow_fingerprint

TOOLS = ('workflow_read', 'workflow_choose', 'workflow_inspect', 'workflow_wait', 'workflow_finish')
PERMISSION = 'workflow:execute'


def registrations(definitions):
    def config(value):
        if (type(value) is not dict or set(value) != {'workflowId', 'workflowSha256'}
                or value['workflowId'] not in definitions
                or value['workflowSha256'] != workflow_fingerprint(definitions[value['workflowId']])):
            raise ValueError('WORKFLOW_PROFILE_INVALID')

    def factory(name):
        def build(ctx):
            config(dict(ctx.spec['config']))
            def service(run):
                if (any(getattr(run, key, None) != getattr(ctx.run_context, key, None)
                        for key in ('user_id', 'session_id', 'run_id'))
                        or ctx.plan.get('ownerId') != run.user_id
                        or not any(spec.get('toolName') == name and spec.get('config') == dict(ctx.spec['config'])
                            and spec.get('adapterId') == ctx.spec['adapterId']
                            for spec in ctx.plan.get('executionBindings', {}).get('tools', []))):
                    raise ValueError('WORKFLOW_CONTEXT_INVALID')
                ctx.store.authorize_tool(run, name)
                return ctx.store.workflow
            if name == 'workflow_read':
                @tool
                def workflow_read(run_context: RunContext, requestId: str) -> str:
                    """Read original workflow stages and immutable inputs; initialize once if needed."""
                    return json.dumps(service(run_context).open(run_context, requestId), allow_nan=False)
                return workflow_read
            if name == 'workflow_choose':
                @tool
                async def workflow_choose(run_context: RunContext, stageId: str, requestId: str) -> str:
                    """Choose one currently admissible stage using a stable original command ID."""
                    return json.dumps(await service(run_context).choose(run_context, stageId, requestId), allow_nan=False)
                return workflow_choose
            if name == 'workflow_inspect':
                @tool
                async def workflow_inspect(run_context: RunContext, stageId: str) -> str:
                    """Inspect an original handle without restarting any operation."""
                    return json.dumps(await service(run_context).inspect(run_context, stageId), allow_nan=False)
                return workflow_inspect
            if name == 'workflow_finish':
                @tool
                def workflow_finish(run_context: RunContext, requestId: str) -> str:
                    """Close this workflow only after every required stage or routed recovery completes."""
                    return json.dumps(service(run_context).finish(run_context, requestId), allow_nan=False)
                return workflow_finish
            @tool(external_execution=True)
            def workflow_wait(run_context: RunContext, stageId: str) -> str:
                """Pause this native run for the selected original stage or human decision."""
                raise ValueError('WORKFLOW_NATIVE_EXTERNAL_EXECUTION_REQUIRED')
            return workflow_wait
        return build
    return [AdapterRegistration('tool', 'workflow-' + name.removeprefix('workflow_') + '-v1', '1',
            factory(name), tool_name=name, permissions=(PERMISSION,), validator=config) for name in TOOLS]
