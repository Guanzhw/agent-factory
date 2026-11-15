"""A native retry without saved model history must not register the trigger twice."""
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch

from agno.agent import Agent
import test_chat_journey as journey
from test_native_model import Endpoint, chunk, reply


class TriggerRetry(unittest.TestCase):
    setUpClass = classmethod(journey.ChatJourney.setUpClass.__func__)
    setUp = journey.ChatJourney.setUp
    post = journey.ChatJourney.post
    session = journey.ChatJourney.session
    wait_for = journey.ChatJourney.wait_for
    send = journey.ChatJourney.send

    def test_actual_retry_with_missing_model_history(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        server.requests, server.hold = [], None
        def answer(body):
            number = len(server.requests)
            if number == 2:
                return 503, {'error': {'message': 'one model outage', 'type': 'server_error'}}
            if not any(message.get('role') == 'tool' for message in body['messages']):
                return 200, [chunk({'role': 'assistant', 'tool_calls': [{
                    'index': 0, 'id': 'set_' + str(number), 'type': 'function',
                    'function': {'name': 'research_set_trigger', 'arguments': json.dumps({
                        'title': 'Watch result', 'instruction': 'Summarize new results',
                        'source': 'external', 'eventType': 'new_result'})}}]}), chunk({}, 'tool_calls')]
            return 200, reply('Standing instruction set.')
        server.answer = answer
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'trigger-retry',
            'baseURL': f'http://127.0.0.1:{server.server_port}/v1'})
        self.page.reload()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='trigger-retry', exact=True).click()
        arun, interrupted = Agent.arun, False
        # A streamed RunError normally ends cleanly. Interrupt delivery to
        # exercise the native worker retry after the trigger was committed.
        def fail_delivery(agent, *args, **kwargs):
            nonlocal interrupted
            result = arun(agent, *args, **kwargs)
            if not kwargs.get('stream'):
                return result
            async def events():
                nonlocal interrupted
                try:
                    async for event in result:
                        yield event
                        if getattr(event, 'event', None) == 'RunError' and not interrupted:
                            interrupted = True
                            raise RuntimeError('fixture: temporary worker delivery failure')
                finally:
                    await result.aclose()
            return events()
        with patch.object(Agent, 'arun', fail_delivery), patch.object(Agent, 'get_run_output', return_value=None):
            self.send('Watch new research results and continue after failure')
            snapshot = self.wait_for(lambda value: value['turns'][-1]['completedAt'] is not None)
        task = self.state['store'].task(snapshot['turns'][-1]['taskId'], self.owner)
        ticket = self.state['store'].native_db.get_job(task['run_id'])
        items = self.state['research_sessions'].triggers.listing(self.owner, snapshot['id'])['items']
        self.assertEqual(ticket['attempt'], 2)
        self.assertEqual(len(items), 1)
        self.assertEqual(snapshot['turns'][-1]['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
