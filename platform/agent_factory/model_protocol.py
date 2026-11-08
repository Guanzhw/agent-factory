"""Agno Responses formatting with lossless stateless continuation replay."""
from copy import deepcopy

from agno.exceptions import ModelProviderError
from agno.models.openai.responses import OpenAIResponses
from agno.tools.function import Function


def protocol_name(configuration):
    value = configuration.get('protocol', 'chat-completions')
    if not isinstance(value, str) or value not in {'chat-completions', 'responses'}:
        raise ValueError('MODEL_PROTOCOL_UNSUPPORTED')
    return value


class OwnerResponses(OpenAIResponses):
    def __init__(self, configuration, scope, session_id):
        super().__init__(id=configuration['model'], provider=configuration['provider'],
            store=False, use_previous_response_id=False, retries=0, max_retries=0,
            max_output_tokens=configuration.get('maxOutputTokens'),
            reasoning_effort=configuration.get('reasoningEffort'),
            reasoning_summary='auto' if configuration.get('reasoningEffort') else None,
            include=['reasoning.encrypted_content'],
            role_map={'system': 'system', 'user': 'user', 'assistant': 'assistant', 'tool': 'tool'})
        self._scope, self._session_id = scope, session_id

    def _format_tool_params(self, messages, tools=None):
        # Agno 3.1.0 mutates nullable property types into their first alternative.
        # Preserve the schema and the existing non-strict function default.
        formatted = []
        for tool in tools or []:
            if isinstance(tool, Function):
                tool = {'type': 'function', 'function': tool.to_dict()}
            if tool.get('type') != 'function':
                formatted.append(deepcopy(tool))
                continue
            formatted.append({**{key: deepcopy(value) for key, value in tool['function'].items()
                if key not in {'external_execution', 'requires_confirmation', 'approval_type'}},
                'type': 'function', 'strict': tool['function'].get('strict', False)})
        return formatted

    def _format_messages(self, messages, compress_tool_results=False, tools=None):
        inputs = []
        call_ids = self._build_fc_id_to_call_id_map(messages)
        for message in messages:
            private = message.provider_data or {}
            saved = private.get('owner_model_continuation', private.get('owner_responses'))
            if (message.role == 'assistant' and saved and saved.get('scope') == self._scope
                    and saved.get('session') == self._session_id):
                # Replay every original item in order, including encrypted reasoning and phase.
                inputs.extend(deepcopy(saved['continuation']['output']))
                continue
            message = message.model_copy(update={'provider_data': None})
            if message.role == 'tool' and message.tool_call_id is not None:
                message.tool_call_id = call_ids.get(message.tool_call_id, message.tool_call_id)
            inputs.extend(super()._format_messages([message], compress_tool_results, tools))
        return inputs

    def _parse_provider_response(self, response, **kwargs):
        if response.error or response.status != 'completed':
            raise ModelProviderError(message='PERSONAL_MODEL_STREAM_INCOMPLETE', model_name='Owner Model')
        result = super()._parse_provider_response(response, **kwargs)
        output = [item.model_dump(exclude_none=True) for item in response.output]
        # Native parsing keeps only the last reasoning item and formatting drops phase.
        result.provider_data = {'owner_model_continuation': {'scope': self._scope,
            'session': self._session_id, 'continuation': {'output': output}}}
        result.reasoning_content = ''.join(part['text'] for item in output if item['type'] == 'reasoning'
            for part in item.get('summary', []) + item.get('content', []) if 'text' in part) or None
        if not result.content and not result.tool_calls:
            refusal = any(part.get('type') == 'refusal' for item in output if item['type'] == 'message'
                for part in item.get('content', []))
            raise ModelProviderError(message='PERSONAL_MODEL_REFUSAL' if refusal else 'PERSONAL_MODEL_EMPTY_OUTPUT',
                model_name='Owner Model')
        return result
