"""Native summary requests use JSON mode and retain the auxiliary request guards."""
from http.server import ThreadingHTTPServer
import json
from threading import Event, Thread
from types import SimpleNamespace
import unittest

from agno.exceptions import RunCancelledException, StopAgentRun
from agno.run import RunContext

from agent_factory.byok_model import OwnerChatModel
from agent_factory.model_dispatch import DelegatingModel
from research.session_context import summarize
from test_native_model import Endpoint, reply


class NativeSummary(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        self.server.requests, self.server.hold, self.server.started = [], None, Event()
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def check_summary(self, protocol):
        content = json.dumps({'summary': 'result was 42', 'topics': ['result']})
        self.server.answer = lambda _: (200, reply(content) if protocol == 'chat-completions' else {
            'status': 'completed', 'output': [{'id': 'summary', 'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': content}]}]})
        configuration = {'provider': 'openai-compatible', 'model': 'deepseek-v4.1-flash', 'protocol': protocol,
            'baseURL': f'http://127.0.0.1:{self.server.server_port}/v1'}
        context = RunContext(run_id='run', session_id='task', user_id='owner')
        state, selected = {}, []
        def current():
            if state.get('stop'):
                raise RunCancelledException('stopped')
        def authorize(_):
            if state.get('withdrawn'):
                raise StopAgentRun('source unavailable')
        dispatcher = DelegatingModel(SimpleNamespace(research_sessions=SimpleNamespace(authorize_model=authorize)))
        def auxiliary():
            model = OwnerChatModel(configuration, lambda: None)
            dispatcher._provider_hooks(model, context, current, auxiliary,
                {'inputValues': {'sessionId': 'conversation', 'turnId': 'turn'}}, auxiliary_request=True)
            selected.append(model)
            return model
        main = OwnerChatModel(configuration, lambda: None)
        original_flags = (main.supports_native_structured_outputs, main.supports_json_schema_outputs)
        result = summarize({'confirmedReplies': ['result was 42']}, context, auxiliary)
        self.assertEqual(result, {'summary': 'result was 42', 'topics': ['result']})
        request = self.server.requests[-1][0]
        self.assertEqual(request.get('response_format', request.get('text', {}).get('format')), {'type': 'json_object'})
        self.assertEqual((main.supports_native_structured_outputs, main.supports_json_schema_outputs), original_flags)
        self.assertFalse(selected[-1].supports_native_structured_outputs)
        for cause, exception in [('stop', RunCancelledException), ('withdrawn', StopAgentRun)]:
            state.clear()
            state[cause] = True
            with self.assertRaises(exception):
                summarize({'confirmedReplies': ['do not send this']}, context, auxiliary)
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(len({id(model) for model in selected}), 3)

    def test_chat_summary_uses_native_json_mode_and_guards(self):
        self.check_summary('chat-completions')

    def test_responses_summary_uses_native_json_mode_and_guards(self):
        self.check_summary('responses')
