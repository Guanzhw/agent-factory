"""A reclaimed native stream continues saved observations without replaying tools."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

from agent_factory.personal_cli import MemberCliAdapter
import test_chat_journey as journey
from test_native_model import Endpoint, chunk, reply


class NativeRetryJourney(unittest.TestCase):
    setUpClass = classmethod(journey.ChatJourney.setUpClass.__func__)
    setUp = journey.ChatJourney.setUp
    post = journey.ChatJourney.post
    session = journey.ChatJourney.session
    wait_for = journey.ChatJourney.wait_for
    send = journey.ChatJourney.send

    def exercise(self, *, unknown=False, stop=False, completed=False):
        marker = Path(self.folder.name) / (self.owner + '-executions.txt')
        self.post('/personal-tools/resources', {'transport': 'cli', 'toolName': 'append_once',
            'description': 'Append one marker', 'executable': sys.executable,
            'arguments': ['-c', f'from pathlib import Path; Path({str(marker)!r}).open("a").write("once\\n"); print("appended")'],
            'readOnly': False, 'inputSchema': {'type': 'object', 'properties': {}}})
        server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        server.requests, server.hold = [], None
        resumed, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def answer(body):
            if len(server.requests) == 1:
                return 200, [chunk({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'append_1',
                    'type': 'function', 'function': {'name': 'append_once', 'arguments': '{"arguments":{}}'}}]}),
                    chunk({}, 'tool_calls')]
            if len(server.requests) == 2 and not completed:
                return 503, {'error': {'message': 'Provider outage', 'type': 'server_error'}}
            resumed.set()
            if stop:
                release.wait(15)
            return 200, reply('Finished independent analysis from the saved observation.')
        server.answer = answer
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'stream-retry',
            'baseURL': f'http://127.0.0.1:{server.server_port}/v1'})
        self.page.reload()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='stream-retry', exact=True).click()
        db = self.state['store'].native_db
        complete = db.complete_job
        settled = threading.Event()
        def fail_settlement(job_id, worker, attempt, status, error=None):
            if attempt == 1 and status == 'completed':
                settled.set()
                raise ConnectionError('Transient queue settlement database failure')
            return complete(job_id, worker, attempt, status, error)
        if unknown:
            invoke = MemberCliAdapter.invoke
            async def lost_result(adapter, invocation):
                await invoke(adapter, invocation)
                raise ConnectionError('CLI result lost after the process actually exited')
            lost = patch.object(MemberCliAdapter, 'invoke', lost_result)
            lost.start()
            self.addCleanup(lost.stop)
        with patch.object(db, 'complete_job', side_effect=fail_settlement):
            self.send('Append once, then analyze the observation without repeating the operation.')
            self.assertTrue(settled.wait(20))
            current = self.session()
            store = self.state['store']
            task = store.task(current['turns'][-1]['taskId'], self.owner)
            ticket = db.get_job(task['run_id'])
            self.assertTrue(ticket['payload']['stream'])
            self.assertEqual((ticket['status'], ticket['attempt']), ('running', 1))
            self.assertEqual(marker.read_text(), 'once\n')
            # Advance only this disposable ticket's stopped heartbeat clock.
            table = db._get_table(table_type='jobs')
            with db.Session() as conn, conn.begin():
                conn.execute(table.update().where(table.c.id == task['run_id']).values(locked_at=0))
            self.assertTrue(resumed.wait(15))
            if stop:
                self.post('/research/sessions/' + current['id'] + '/stop', {})
                release.set()
            final = self.wait_for(lambda value: value['turns'][-1]['completedAt'] is not None)
            self.assertEqual(final['turns'][-1]['status'], 'canceled' if stop else 'completed', final)
            self.assertEqual(final['turns'][-1]['taskId'], task['id'])
            self.assertEqual(db.get_job(task['run_id'])['attempt'], 2)
            self.assertEqual(marker.read_text(), 'once\n')
            self.assertEqual(len(server.requests), 2 if completed else 3)
            if not completed:
                self.assertTrue(any(message.get('role') == 'tool'
                    and ('unknown' if unknown else 'appended') in str(message.get('content')).lower()
                    for message in server.requests[2][0]['messages']))
            self.assertEqual(store.effects(task['id'])[0]['status'], 'UNKNOWN' if unknown else 'DONE')
            self.page.reload()
            self.assertEqual(self.session()['turns'][-1]['status'], final['turns'][-1]['status'])

    def test_completed_operation_is_not_replayed(self):
        self.exercise()

    def test_unknown_observation_allows_independent_continuation(self):
        self.exercise(unknown=True)

    def test_stop_during_native_continuation(self):
        self.exercise(stop=True)

    def test_completed_native_run_needs_no_new_model_request(self):
        self.exercise(completed=True)
