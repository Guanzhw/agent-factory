"""Native Function registration for owner-scoped CLI/MCP adapters.

The native run and FunctionCall identify one durable effect. Neither an unknown
acknowledgement nor a repeated native call may dispatch that effect again.
"""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import asdict, replace

from agno.exceptions import RunCancelledException
from agno.tools.function import Function, FunctionCall

from .personal_remote_provider import SecretLease
from .personal_tool_contract import PersonalToolAdapter, ToolInvocation, ToolInvocationError, validate_tool_arguments, bounded_tool_json
from .store import canonical, digest
from .tool_output import output_preview, DEFAULT_OUTPUT_TOKENS


def _unknown(**facts):
    return {'outcome': 'unknown', 'stopped': None, 'code': 'PERSONAL_TOOL_OUTCOME_UNKNOWN',
            'message': 'The original operation is unconfirmed. Do not replay it. '
                       'Inspect its original result if possible; other work can continue.', **facts}


def _receipt(receipt, **identity):
    if not isinstance(receipt, dict):
        return _unknown(**identity)
    if receipt.get('outcome') == 'completed' and 'output' in receipt:
        output = receipt['output']
        text = json.dumps(output, ensure_ascii=False, allow_nan=False)
        if len(text.encode()) > DEFAULT_OUTPUT_TOKENS * 4:
            return {'preview': output_preview(text), 'truncated': True,
                    'fullOutput': receipt.get('outputArtifact')}
        return output
    if receipt.get('outcome') == 'failed':
        if receipt.get('stopped') is True:
            detail = ': ' + json.dumps(receipt['output'], ensure_ascii=False) if 'output' in receipt else ''
            raise ToolInvocationError('PERSONAL_TOOL_FAILED' + detail, outcome='failed', stopped=True)
        return _unknown(**identity, outcome='failed', stopped=False,
            code='PERSONAL_TOOL_FAILED_CLEANUP_UNCONFIRMED', output=receipt.get('output'),
            message='The operation failed, but cleanup is unconfirmed. Do not replay it. Other work can continue.')
    if (receipt.get('outcome') == 'cancelled' and receipt.get('cancelled') is True
            and receipt.get('stopped') is True):
        raise RunCancelledException('PERSONAL_TOOL_CANCELLED')
    return _unknown(**identity)


def personal_tool_function(adapter: PersonalToolAdapter, store, handle, context):
    descriptor = replace(adapter.descriptor, input_schema=copy.deepcopy(dict(adapter.descriptor.input_schema)))
    fingerprint = digest(asdict(descriptor))
    service = store.personal_tools
    expected = (context.user_id, context.session_id, context.run_id)
    connection = {'ref': handle.configuration['registrationRef'], 'revision': handle.configuration['revision']}
    async def invoke(*, run_context, fc, **arguments):
        # Agno injects both values, removing framework arguments supplied by
        # a model. Never infer or manufacture a replacement call identity.
        call_id = fc.call_id if isinstance(fc, FunctionCall) else None
        if (type(call_id) is not str or not call_id
                or any(ord(char) < 32 for char in call_id)):
            raise PermissionError('PERSONAL_TOOL_CONTEXT_DENIED')

        def check_execution():
            try:
                if ((run_context.user_id, run_context.session_id, run_context.run_id) != expected
                        or fc.call_id != call_id or fc.function.name != descriptor.tool_name
                        or fc.function._run_context is not run_context
                        or service.adapters.get(descriptor.adapter_id) is not adapter
                        or handle.adapter is not adapter or handle.service is not service
                        or handle.requesting_actor != expected[0] or digest(asdict(adapter.descriptor)) != fingerprint):
                    raise PermissionError()
                task = store.task(expected[1], expected[0])
                if task['run_id'] != expected[2]:
                    raise PermissionError('Tool run differs from its task')
                if store.cancellation_requested(expected[2]):
                    raise RunCancelledException('PERSONAL_TOOL_CANCELLED')
            except RunCancelledException:
                raise RunCancelledException('PERSONAL_TOOL_CANCELLED') from None
            except Exception:
                raise PermissionError('PERSONAL_TOOL_AUTHORIZATION_DENIED') from None

        def check_authorized():
            check_execution()
            try:
                handle.check_authorized()
            except RunCancelledException:
                raise RunCancelledException('PERSONAL_TOOL_CANCELLED') from None
            except Exception:
                raise PermissionError('PERSONAL_TOOL_AUTHORIZATION_DENIED') from None

        await asyncio.to_thread(check_authorized)
        try:
            values = validate_tool_arguments(descriptor.input_schema, arguments)
        except Exception:
            raise ValueError('PERSONAL_TOOL_INPUT_INVALID') from None
        effect_key = 'personal-tool:' + call_id
        identity = {'callId': call_id, 'effectKey': expected[2] + ':' + effect_key}
        def unknown(**facts):
            check_execution()
            return _unknown(**identity, **facts)

        request = {'ownerId': expected[0], 'taskId': expected[1],
            'adapterId': descriptor.adapter_id, 'descriptor': fingerprint, 'connection': connection,
            'callId': call_id, 'arguments': values}
        try:
            reservation = await asyncio.to_thread(store.effect_reserve, expected[2], effect_key, request)
        except Exception:
            return unknown()
        if reservation.get('status') == 'done':
            return _receipt(reservation.get('result'), **identity)
        if reservation.get('status') != 'new':
            previous = reservation.get('result')
            if (reservation.get('status') == 'unknown' and isinstance(previous, dict)
                    and previous.get('outcome') == 'failed' and previous.get('stopped') is False):
                return _receipt(previous, **identity)
            return unknown()

        def resolve_credential():
            try:
                lease = handle.resolve_credential(check_execution=check_execution)
                if lease is not None and not isinstance(lease, SecretLease):
                    raise ValueError()
            except RunCancelledException:
                raise RunCancelledException('PERSONAL_TOOL_CANCELLED') from None
            except Exception:
                raise PermissionError('PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE') from None
            return lease

        invocation = ToolInvocation(owner_id=expected[0], connection_ref=connection['ref'],
            connection_revision=connection['revision'], call_id=call_id, arguments=values,
            run_context=run_context, check_authorized=check_authorized, resolve_credential=resolve_credential)
        event = {'toolName': descriptor.tool_name, 'callId': call_id, 'arguments': values}
        await asyncio.to_thread(store.event, expected[1], 'tool_started', '开始执行工具', event)
        try:
            # Adapters own finally cleanup and positive stop evidence. A
            # naked cancellation exception is not proof of remote stop.
            output = await adapter.invoke(invocation)
            output = bounded_tool_json(output, maximum=None)
            receipt = {'outcome': 'completed', 'output': output}
            text = json.dumps(output, ensure_ascii=False, allow_nan=False)
            if len(text.encode()) > DEFAULT_OUTPUT_TOKENS * 4:
                artifact = await asyncio.to_thread(store.artifact_write, expected[2],
                    'tool-' + digest(call_id)[:24] + '.json', text, 'application/json')
                receipt['outputArtifact'] = artifact
        except ToolInvocationError as error:
            if error.outcome == 'cancelled' and error.stopped is True:
                receipt = {'outcome': 'cancelled', 'cancelled': True, 'stopped': True}
            elif error.outcome == 'failed':
                receipt = {'outcome': 'failed', 'stopped': error.stopped is True}
                if error.output is not None:
                    receipt['output'] = error.output
            else:
                await asyncio.to_thread(store.event, expected[1], 'tool_finished', '工具结果待核对',
                    {**event, 'outcome': 'unknown'})
                return unknown(stopped=error.stopped, code=error.code)
        except RunCancelledException:
            raise RunCancelledException('PERSONAL_TOOL_CANCELLED') from None
        except asyncio.CancelledError:
            raise asyncio.CancelledError() from None
        except Exception:
            await asyncio.to_thread(store.event, expected[1], 'tool_finished', '工具结果待核对',
                {**event, 'outcome': 'unknown'})
            return unknown()
        if receipt.get('outcome') == 'failed' and receipt.get('stopped') is False:
            # Business failure is known, but local process custody is not
            # settled. Retain UNKNOWN evidence and never overwrite a receipt.
            try:
                rows = await asyncio.to_thread(store.sql, """
                    UPDATE af_effects SET result=CAST(:result AS JSONB)
                    WHERE effect_key=:effect_key AND run_id=:run_id AND task_id=:task_id
                      AND fingerprint=:fingerprint AND status='UNKNOWN' AND result IS NULL
                    RETURNING effect_key
                    """, effect_key=expected[2] + ':' + effect_key, run_id=expected[2],
                    task_id=expected[1], fingerprint=digest(request), result=canonical(receipt))
                if len(rows) != 1:
                    raise ValueError('Effect receipt was not recorded')
            except Exception:
                return unknown()
            await asyncio.to_thread(check_authorized)
            return _receipt(receipt, **identity)
        try:
            await asyncio.to_thread(store.effect_complete, expected[2], effect_key, receipt)
        except Exception:
            return unknown()
        # Preserve a known completion even if authority was revoked during
        # execution, but do not disclose its result without current access.
        await asyncio.to_thread(check_authorized)
        await asyncio.to_thread(store.event, expected[1], 'tool_finished', '工具执行记录', {**event, **receipt})
        return _receipt(receipt, **identity)

    return Function(name=descriptor.tool_name, description=descriptor.description,
        parameters=copy.deepcopy(dict(descriptor.input_schema)), entrypoint=invoke,
        skip_entrypoint_processing=True)
