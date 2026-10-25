"""Exact governed native tools for one original SSH process operation."""
from copy import deepcopy

from agno.tools.function import Function, FunctionCall

from .execution_bindings import AdapterRegistration
from .native_external_wait import factory_wait_operations
from .ssh_process_contract import (LAUNCH_ADAPTER_ID, LAUNCH_TOOL, REVISION,
                                   WAIT_ADAPTER_ID, WAIT_TOOL)


def ssh_tool_registrations(runtime):
    def configuration(value):
        if (type(value) is not dict or set(value) != {'profileId', 'profileSha256'}
                or type(value['profileId']) is not str or not 1 <= len(value['profileId']) <= 128
                or type(value['profileSha256']) is not str or len(value['profileSha256']) != 64):
            raise ValueError('SSH_PROCESS_TOOL_CONFIGURATION_INVALID')

    def launch(binding):
        configuration({k: v for k, v in binding.spec['config'].items() if k != 'connectionName'})
        expected = binding.run_context
        profile = runtime.profiles.get(binding.spec['config']['profileId'])
        if profile is None or profile.fingerprint != binding.spec['config']['profileSha256']:
            raise ValueError('SSH_PROCESS_PROFILE_UNAVAILABLE')
        schema = deepcopy(profile.input_schema) if profile.input_schema is not None else {
            'type': 'object', 'properties': {}, 'additionalProperties': False}

        async def invoke(*, run_context, fc, **arguments):
            if (not isinstance(fc, FunctionCall) or type(fc.call_id) is not str
                    or not 1 <= len(fc.call_id) <= 200 or not fc.call_id.isprintable()
                    or fc.function.name != LAUNCH_TOOL or fc.function._run_context is not run_context
                    or (run_context.user_id, run_context.session_id, run_context.run_id)
                    != (expected.user_id, expected.session_id, expected.run_id)):
                raise PermissionError('SSH_PROCESS_NATIVE_CONTEXT_REQUIRED')
            if set(arguments) - {'inputs'} or profile.input_schema is not None and 'inputs' not in arguments:
                raise ValueError('SSH_PROCESS_INPUT_REQUIRED')
            checked, _ = profile.prepare(arguments.get('inputs', {}))
            body = await runtime.launch(run_context, fc.call_id, checked)
            return {'operationId': body['id'], 'closed': body['closed'],
                    'observation': body['observation']}

        return Function(name=LAUNCH_TOOL,
            description='Start the configured training operation once. Wait for its original operation ID with factory_wait_ssh_process.',
            parameters={'type': 'object', 'properties': {'inputs': schema}, 'additionalProperties': False,
                        **({'required': ['inputs']} if profile.input_schema is not None else {})},
            entrypoint=invoke, skip_entrypoint_processing=True)

    def wait(binding):
        function = factory_wait_operations.model_copy(deep=True)
        function.name = WAIT_TOOL
        return function

    return (
        AdapterRegistration('tool', LAUNCH_ADAPTER_ID, REVISION, launch,
            tool_name=LAUNCH_TOOL, permissions=('ssh:execute',), validator=configuration,
            connection_kind='environment', required_capabilities=('ssh:execute',),
            connection_adapter_ref='owner-ssh-server-v1'),
        AdapterRegistration('tool', WAIT_ADAPTER_ID, REVISION, wait,
            tool_name=WAIT_TOOL, permissions=('ssh:execute',)),
    )
