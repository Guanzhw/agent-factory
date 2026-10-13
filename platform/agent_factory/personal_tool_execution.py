"""Native Function registration for static, owner-scoped personal tool adapters.

The native run and FunctionCall identify one durable effect. Neither an unknown
acknowledgement nor a repeated native call may dispatch that effect again.
"""
from __future__ import annotations

import asyncio
import copy
from dataclasses import asdict, replace

from agno.exceptions import RunCancelledException
from agno.tools.function import Function, FunctionCall

from .execution_bindings import AdapterRegistration, BindingContext
from .input_schema import bounded_json, validate_input_values
from .personal_remote_provider import SecretLease, reject_credential_echo
from .personal_tool_contract import PersonalToolAdapter, ToolInvocation, ToolInvocationError
from .store import digest


def _configuration(config):
    if config:
        raise ValueError('PERSONAL_TOOL_CONFIGURATION_INVALID')


def _unknown():
    return ToolInvocationError('PERSONAL_TOOL_OUTCOME_UNKNOWN')


def _receipt(receipt):
    if not isinstance(receipt, dict):
        raise _unknown()
    if receipt.get('outcome') == 'completed' and 'output' in receipt:
        return receipt['output']
    if receipt.get('outcome') == 'failed':
        raise ToolInvocationError('PERSONAL_TOOL_FAILED', outcome='failed')
    if (receipt.get('outcome') == 'cancelled' and receipt.get('cancelled') is True
            and receipt.get('stopped') is True):
        raise RunCancelledException('PERSONAL_TOOL_CANCELLED')
    raise _unknown()


def personal_tool_registration(adapter: PersonalToolAdapter) -> AdapterRegistration:
    """Describe one operator-installed adapter without resolving owner secrets."""
    descriptor = replace(adapter.descriptor, input_schema=copy.deepcopy(dict(adapter.descriptor.input_schema)))
    fingerprint = digest(asdict(descriptor))

    def factory(binding: BindingContext):
        store = binding.store
        service = store.personal_tools
        handle = binding.connection
        expected = (binding.run_context.user_id, binding.run_context.session_id, binding.run_context.run_id)
        connection = dict(binding.spec['connection'])
        if (service.adapters.get(descriptor.adapter_id) is not adapter or handle.adapter is not adapter
                or handle.service is not service or handle.owner != expected[0]):
            raise PermissionError('PERSONAL_TOOL_BINDING_DENIED')

        async def invoke(*, run_context, fc, **arguments):
            # Agno injects both values, removing framework arguments supplied by
            # a model. Never infer or manufacture a replacement call identity.
            call_id = fc.call_id if isinstance(fc, FunctionCall) else None
            if (type(call_id) is not str or not 1 <= len(call_id) <= 200
                    or any(ord(char) < 32 for char in call_id)):
                raise PermissionError('PERSONAL_TOOL_CONTEXT_DENIED')

            def check_authorized():
                try:
                    if ((run_context.user_id, run_context.session_id, run_context.run_id) != expected
                            or fc.call_id != call_id or fc.function.name != descriptor.tool_name
                            or fc.function._run_context is not run_context
                            or service.adapters.get(descriptor.adapter_id) is not adapter
                            or handle.adapter is not adapter or handle.service is not service
                            or handle.owner != expected[0] or digest(asdict(adapter.descriptor)) != fingerprint):
                        raise PermissionError()
                    store.require_plan_execution(expected[0], binding.plan, run_context=run_context)
                    store.execution_bindings.recheck(binding.plan, run_context)
                    store.authorize_tool(run_context, descriptor.tool_name)
                    handle.check_authorized()
                except RunCancelledException:
                    raise RunCancelledException('PERSONAL_TOOL_CANCELLED') from None
                except Exception:
                    raise PermissionError('PERSONAL_TOOL_AUTHORIZATION_DENIED') from None

            await asyncio.to_thread(check_authorized)
            try:
                values = validate_input_values(descriptor.input_schema, arguments)
            except Exception:
                raise ValueError('PERSONAL_TOOL_INPUT_INVALID') from None
            effect_key = 'personal-tool:' + call_id
            request = {'ownerId': expected[0], 'taskId': expected[1], 'planId': binding.plan['id'],
                'adapterId': descriptor.adapter_id, 'descriptor': fingerprint, 'connection': connection,
                'callId': call_id, 'arguments': values}
            try:
                reservation = await asyncio.to_thread(store.effect_reserve, expected[2], effect_key, request)
            except Exception:
                raise _unknown() from None
            if reservation.get('status') == 'done':
                await asyncio.to_thread(check_authorized)
                return _receipt(reservation.get('result'))
            if reservation.get('status') != 'new':
                raise _unknown()

            leases: list[SecretLease] = []

            def resolve_credential():
                check_authorized()
                try:
                    lease = handle.resolve_credential()
                    if not isinstance(lease, SecretLease):
                        raise ValueError()
                except RunCancelledException:
                    raise RunCancelledException('PERSONAL_TOOL_CANCELLED') from None
                except Exception:
                    raise PermissionError('PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE') from None
                check_authorized()
                leases.append(lease)
                return lease

            invocation = ToolInvocation(owner_id=expected[0], connection_ref=connection['ref'],
                connection_revision=connection['revision'], call_id=call_id, arguments=values,
                run_context=run_context, check_authorized=check_authorized, resolve_credential=resolve_credential)
            try:
                # Adapters own finally cleanup and positive stop evidence. A
                # naked cancellation exception is not proof of remote stop.
                output = await adapter.invoke(invocation)
                output = bounded_json(output, maximum=descriptor.max_output_bytes)
                for lease in leases:
                    reject_credential_echo(output, lease)
                receipt = {'outcome': 'completed', 'output': output}
            except ToolInvocationError as error:
                if error.outcome == 'cancelled' and error.stopped is True:
                    receipt = {'outcome': 'cancelled', 'cancelled': True, 'stopped': True}
                elif error.outcome == 'failed':
                    receipt = {'outcome': 'failed'}
                else:
                    raise _unknown() from None
            except RunCancelledException:
                raise RunCancelledException('PERSONAL_TOOL_CANCELLED') from None
            except asyncio.CancelledError:
                raise asyncio.CancelledError() from None
            except Exception:
                raise _unknown() from None
            finally:
                leases.clear()
            try:
                await asyncio.to_thread(store.effect_complete, expected[2], effect_key, receipt)
            except Exception:
                raise _unknown() from None
            # Preserve a known completion even if authority was revoked during
            # execution, but do not disclose its result without current access.
            await asyncio.to_thread(check_authorized)
            return _receipt(receipt)

        return Function(name=descriptor.tool_name, description=descriptor.description,
            parameters=copy.deepcopy(dict(descriptor.input_schema)), entrypoint=invoke,
            skip_entrypoint_processing=True)

    setattr(factory, '_personal_tool_adapter', adapter)
    return AdapterRegistration(kind='tool', adapter_id=descriptor.adapter_id, revision=descriptor.revision,
        factory=factory, tool_name=descriptor.tool_name, connection_kind='tool',
        required_capabilities=descriptor.capabilities, permissions=(descriptor.permission,), validator=_configuration)


def register_personal_tools(bindings, service):
    """Explicit assembly helper; Settings can also consume the registrations."""
    for adapter in service.adapters.values():
        registration = personal_tool_registration(adapter)
        bindings.register(registration.kind, registration.adapter_id, registration.revision, registration.factory,
            tool_name=registration.tool_name, connection_kind=registration.connection_kind,
            required_capabilities=registration.required_capabilities, permissions=registration.permissions,
            validator=registration.validator)
