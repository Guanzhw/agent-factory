"""Exact governed native tools for one original SSH process operation."""
from agno.tools.function import Function, FunctionCall

from .execution_bindings import AdapterRegistration
from .native_external_wait import factory_wait_operations
from .ssh_process_contract import (LAUNCH_ADAPTER_ID, LAUNCH_TOOL, REVISION,
                                   WAIT_ADAPTER_ID, WAIT_TOOL)


def ssh_tool_registrations(runtime):
    def configuration(value):
        if (type(value) is not dict or set(value) != {'targetRef'}
                or type(value['targetRef']) is not str or not 1 <= len(value['targetRef']) <= 128):
            raise ValueError('SSH_PROCESS_TOOL_CONFIGURATION_INVALID')

    def launch(binding):
        configuration(binding.spec['config'])
        expected = binding.run_context
        target = binding.spec['config']['targetRef']

        async def invoke(*, run_context, fc):
            if (not isinstance(fc, FunctionCall) or type(fc.call_id) is not str
                    or not 1 <= len(fc.call_id) <= 200 or not fc.call_id.isprintable()
                    or fc.function.name != LAUNCH_TOOL or fc.function._run_context is not run_context
                    or (run_context.user_id, run_context.session_id, run_context.run_id)
                    != (expected.user_id, expected.session_id, expected.run_id)):
                raise PermissionError('SSH_PROCESS_NATIVE_CONTEXT_REQUIRED')
            body = await runtime.launch(run_context, target, fc.call_id)
            return {'operationId': body['id'], 'closed': body['closed'],
                    'observation': body['observation']}

        return Function(name=LAUNCH_TOOL,
            description='Start the configured training operation once. Wait for its original operation ID with factory_wait_operations.',
            parameters={'type': 'object', 'properties': {}, 'additionalProperties': False},
            entrypoint=invoke, skip_entrypoint_processing=True)

    return (
        AdapterRegistration('tool', LAUNCH_ADAPTER_ID, REVISION, launch,
            tool_name=LAUNCH_TOOL, permissions=('ssh:execute',), validator=configuration),
        AdapterRegistration('tool', WAIT_ADAPTER_ID, REVISION, lambda binding: factory_wait_operations,
            tool_name=WAIT_TOOL, permissions=('ssh:execute',)),
    )
