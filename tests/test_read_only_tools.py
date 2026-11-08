"""Configured read-only CLI calls survive native queue retries after model failure."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
import sys
import threading
import unittest
from unittest.mock import patch

from playwright.sync_api import expect

import test_chat_journey as journey
from test_native_model import Endpoint, chunk, reply


class ReadOnlyQueueJourney(unittest.TestCase):
    setUpClass = classmethod(journey.ChatJourney.setUpClass.__func__)
    setUp = journey.ChatJourney.setUp
    post = journey.ChatJourney.post
    session = journey.ChatJourney.session
    wait_for = journey.ChatJourney.wait_for
    send = journey.ChatJourney.send

    def exercise_retry(self, read_only, *, stop=False):
        # Keep the held attempt's retry from being claimed by a second worker slot.
        worker = self.state['lifecycle_observer'].worker_getter()
        single_slot = patch.object(worker.config, 'max_concurrency', 1)
        single_slot.start()
        self.addCleanup(single_slot.stop)
        self.post('/personal-tools/resources', {'transport': 'cli', 'toolName': 'read_python_version',
            'description': 'Read the Python interpreter version', 'executable': sys.executable,
            'arguments': ['-c', 'import json,sys; print(json.dumps({"version":sys.version_info.major}))'],
            'readOnly': read_only, 'inputSchema': {'type': 'object', 'properties': {}}})
        server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        server.requests, server.hold = [], None
        def answer(body):
            number = len(server.requests)
            if number == 2:
                return 503, {'error': {'message': 'one model outage', 'type': 'server_error'}}
            if number in {1, 3}:
                return 200, [chunk({'role': 'assistant', 'tool_calls': [{
                    'index': 0, 'id': 'read_version_' + str(number), 'type': 'function',
                    'function': {'name': 'read_python_version', 'arguments': json.dumps({'arguments': {}})}}]}),
                    chunk({}, 'tool_calls')]
            return 200, reply('读取完成，模型故障后继续。')
        server.answer = answer
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'retry-regression',
            'baseURL': f'http://127.0.0.1:{server.server_port}/v1'})
        self.page.reload()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='retry-regression', exact=True).click()
        # Hold the SDK after persisting its queued retry while the old run still says error.
        db = self.state['store'].native_db
        retry = db.retry_or_fail_job
        queued, release = threading.Event(), threading.Event()
        def delayed_retry(job, worker, attempt, error, delay):
            result = retry(job, worker, attempt, error, 2)
            if attempt == 1:
                queued.set()
                if not release.wait(15):
                    raise RuntimeError('Test did not release the queued retry')
            return result
        delayed = patch.object(db, 'retry_or_fail_job', side_effect=delayed_retry)
        delayed.start()
        self.addCleanup(delayed.stop)
        self.addCleanup(release.set)
        self.send('读取 Python 版本并在模型故障后继续')
        self.assertTrue(queued.wait(15), 'Provider failure did not reach native retry')
        try:
            current = self.session()
            task = self.state['store'].task(current['turns'][-1]['taskId'], self.owner)
            observer = self.state['lifecycle_observer']
            binding = observer._binding(task)
            self.assertEqual((binding['status'], binding['persistedRunStatus']), ('queued', 'error'))
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(lambda: asyncio.run(observer.observe_root(task['id']))).result(timeout=10)
            self.assertFalse(self.state['store'].task(task['id'], self.owner)['cancel_requested'])
            if stop:
                self.post('/research/sessions/' + current['id'] + '/stop', {})
        finally:
            release.set()
        def ended(value):
            turn = value['turns'][-1]
            task = self.state['store'].task(turn['taskId'], self.owner)
            ticket = self.state['store'].native_db.get_job(task['run_id'])
            return ticket['status'] in {'completed', 'failed', 'cancelled'} and turn['completedAt'] is not None
        snapshot = self.wait_for(ended)
        turn = snapshot['turns'][-1]
        store = self.state['store']
        task = store.task(turn['taskId'], self.owner)
        if stop:
            self.assertEqual(turn['status'], 'canceled', snapshot)
            self.assertEqual(store.native_db.get_job(task['run_id'])['attempt'], 1)
            self.assertEqual(len(server.requests), 2)
            return
        self.assertEqual(store.native_db.get_job(task['run_id'])['attempt'], 2, snapshot)
        outputs = [e['data']['output'] for e in turn['events'] if e['type'] == 'tool_finished']
        self.assertEqual(outputs, [{'version': sys.version_info.major}] * (2 if read_only else 1))
        # The failed request reached the provider with the actual subprocess result.
        self.assertTrue(any(m.get('role') == 'tool' and 'version' in str(m.get('content'))
                            for m in server.requests[1][0]['messages']))
        if read_only:
            self.assertEqual(turn['status'], 'completed', snapshot)
            self.assertEqual(store.effects(task['id']), [])
            self.assertEqual(len(server.requests), 4)
            expect(self.page.locator('.rs-turn')).to_contain_text('读取完成，模型故障后继续。')
        else:
            self.assertEqual(turn['status'], 'failed', snapshot)
            self.assertTrue(store.effects(task['id']))
            self.assertEqual(len(server.requests), 2)
            self.assertTrue(any(e['type'] == 'research_reconciliation_required' for e in turn['events']))
        self.page.reload()
        expect(self.page.locator('.rs-turn')).to_have_count(1)
        self.assertEqual(len(server.requests), 4 if read_only else 2)
        if not read_only:
            self.assertTrue(any(e['type'] == 'research_reconciliation_required'
                                for e in self.session()['turns'][-1]['events']))

    def test_read_only_cli_recovers_after_model_failure(self):
        self.exercise_retry(True)

    def test_unmarked_cli_is_not_replayed_after_model_failure(self):
        self.exercise_retry(False)

    def test_stop_during_read_only_native_retry(self):
        self.exercise_retry(True, stop=True)
