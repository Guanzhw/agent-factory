"""A deterministic, explicitly synthetic Model for native Agno integration."""
from dataclasses import dataclass
import json

from agno.models.base import Model
from agno.models.response import ModelResponse

CONTEXT_MARKER = 'FACTORY_SYNTHETIC_CONTEXT='


@dataclass
class DemoModel(Model):
    """Exercise the native model/tool/HITL loop without provider credentials."""

    id: str = 'factory-synthetic-v1'
    name: str = 'Synthetic integration model'
    provider: str = 'local-synthetic'

    def _response(self, messages):
        system = next((str(m.content) for m in messages if m.role == 'system'), '')
        encoded = next((line.split(CONTEXT_MARKER, 1)[1] for line in reversed(system.splitlines()) if CONTEXT_MARKER in line), '{}')
        plan = json.loads(encoded)
        goal = str(plan.get('normalizedGoal', 'Synthetic integration task'))
        results = {}
        failures = []
        for message in messages:
            if message.role == 'tool':
                if message.tool_call_error:
                    failures.append(str(message.content))
                try:
                    results[message.tool_name] = json.loads(message.content)
                except (TypeError, ValueError):
                    results[message.tool_name] = {'message': str(message.content)}
        if failures:
            status = 'blocked-unknown' if any('UNKNOWN' in e for e in failures) else 'failed'
            return ModelResponse(role='assistant', content=json.dumps({'status': status, 'evidenceKind': 'synthetic', 'errors': failures}))

        def call(name, arguments):
            return ModelResponse(role='assistant', tool_calls=[{'id': 'synthetic-' + name, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}])

        config = plan.get('config', {})
        if config.get('askScope') and 'ask_scope' not in results:
            return call('ask_scope', {'question': 'What specific question or scope should this synthetic research task investigate?'})
        if 'ask_scope' in results:
            goal = str(results['ask_scope'].get('scope', goal))
        if plan.get('application') == 'checksum':
            if 'checksum' not in results:
                return call('checksum', {'text': str(config.get('sample', goal))})
        else:
            if 'literature_search' not in results:
                return call('literature_search', {'query': goal})
            if plan.get('mode') == 'experiment' and 'run_experiment' not in results:
                return call('run_experiment', {'experiment': 'bounded-sort-v1'})
        return ModelResponse(role='assistant', content=json.dumps({'status': 'synthetic-complete', 'evidenceKind': 'synthetic', 'modelId': self.id, 'results': results, 'notice': 'Synthetic integration evidence; no real literature search or research improvement has been established.'}))

    def invoke(self, messages, **kwargs):
        return self._response(messages)

    async def ainvoke(self, messages, **kwargs):
        return self._response(messages)

    def invoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response
