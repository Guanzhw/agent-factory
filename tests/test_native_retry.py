"""A reclaimed native stream continues saved observations without replaying tools."""
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import secrets
from uuid import uuid4
import sys
import threading
import unittest
from unittest.mock import patch

from agno.agent import Agent
from agno.models.message import Message
from agno.run import RunContext
from agno.tools.function import Function
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

    def exercise(self, *, unknown=False, stop=False, completed=False, missing_result=False, native=False, history=False, revoked=False, compact=False, ssh_missing=False, ssh_not_started=False):
        prior = None
        if revoked:
            from agent_factory.application_content import ContentPublication, ContentSource
            content = self.state['application_content']
            publisher = 'publisher-' + uuid4().hex
            self.state['browser_auth'].local_passwords.create(publisher, secrets.token_urlsafe(20))
            source = content.publish(publisher, ContentPublication(
                source=ContentSource(application='research', record='retry-source', revision='1'),
                content={'observation': 'source-secret-marker'}, visibility='team'), str(uuid4()))
            self.send('共享资料验收:' + source['id'])
            prior = self.wait_for(lambda value: value['turns'][-1]['status'] == 'completed')
            content.set_visibility(publisher, source['id'], 'personal', str(uuid4()))
            self.assertIn('旧共享来源', self.session()['context']['notice'])
        marker = Path(self.folder.name) / (self.owner + '-executions.txt')
        self.post('/personal-tools/resources', {'transport': 'cli', 'toolName': 'append_once',
            'description': 'Append one marker', 'executable': sys.executable,
            'arguments': ['-c', f'from pathlib import Path; Path({str(marker)!r}).open("a").write("once\\n"); print("appended")'],
            'readOnly': False, 'inputSchema': {'type': 'object', 'properties': {}}})
        if ssh_missing:
            calls = 0
            def ssh_run(run_context: RunContext):
                nonlocal calls
                calls += 1
                if ssh_not_started and calls == 1:
                    return {'outcome': 'failed', 'code': 'SSH_PREPARATION_FAILED', 'stopped': True}
                with marker.open('a') as handle:
                    handle.write('once\n')
                return {'outcome': 'unknown', 'code': 'SSH_RESULT_LOST', 'stopped': False}
            ssh = patch.object(self.state['store'].personal_ssh, 'functions',
                return_value=[Function.from_callable(ssh_run)])
            ssh.start()
            self.addCleanup(ssh.stop)
            missing = patch.object(Agent, 'get_run_output', return_value=None)
            missing.start()
            self.addCleanup(missing.stop)
        if native:
            tools = self.state['store'].research_tools
            functions = tools.functions
            def append_native_once():
                with marker.open('a') as handle:
                    handle.write('once\n')
                return 'appended'
            def with_native_tool(context):
                return [*functions(context), Function.from_callable(append_native_once)]
            patched = patch.object(tools, 'functions', with_native_tool)
            patched.start()
            self.addCleanup(patched.stop)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        server.requests, server.hold = [], None
        resumed, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        preparing_history, offset = history, 0
        def answer(body):
            if not body.get('tools'):
                if body['messages'][-1].get('content') != 'Provide the summary of the conversation.':
                    return 200, reply('appended')
                summary = 'new-summary-retained-marker history-target-0 history-target-4 correction-retained-marker'
                if 'Append once, then analyze' in json.dumps(body):
                    summary += ' Append once, then analyze the observation without repeating the operation.'
                return 200, reply(json.dumps({'summary': summary, 'topics': []}))
            number = sum(bool(request.get('tools')) for request, _ in server.requests) - offset
            if preparing_history:
                return 200, reply('History observed.')
            if number == 1 or ssh_missing and number == 3:
                return 200, [chunk({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'append_1',
                    'type': 'function', 'function': {'name': 'ssh_run' if ssh_missing else 'append_native_once' if native else 'append_once',
                    'arguments': '{}' if native or ssh_missing else '{"arguments":{}}'}}]}),
                    chunk({}, 'tool_calls')]
            if number == 2 and not completed:
                return 503, {'error': {'message': 'Provider outage', 'type': 'server_error'}}
            resumed.set()
            if stop:
                release.wait(15)
            return 200, reply('Finished independent analysis from the saved observation.')
        server.answer = answer
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        model = self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'stream-retry',
            'baseURL': f'http://127.0.0.1:{server.server_port}/v1'})
        self.page.reload()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='stream-retry', exact=True).click()
        if history:
            self.send('history-target-0 ' + ('preserve context. ' * 500 if compact else ''))
            prior = self.wait_for(lambda value: value['turns'][-1]['status'] == 'completed')
            for index in range(1, 5):
                self.post('/research/sessions/' + prior['id'] + '/turns', {'text': f'history-target-{index}'})
                prior = self.wait_for(lambda value: len(value['turns']) == index + 1
                    and value['turns'][-1]['status'] == 'completed')
            service = self.state['research_sessions']
            # Existing checkpoint/correction records exercise native recovery without invoking a summarizer.
            with service._write() as conn:
                row = service._row(conn, self.owner, prior['id'])
                turns = service._turns(conn, row['id'])
                turn = turns[-1]
                service._save_turn(conn, turn, {**turn['body'], 'messages': [*turn['body']['messages'],
                    service._message('correction', 'correction-retained-marker')]})
                if not compact:
                    service._save_session(conn, row, {**row['body'], 'contextCheckpoint': {
                        'throughSequence': turns[1]['sequence'], 'projectionVersion': 3,
                        'summary': {'summary': 'history-target-0 history-target-1 summary-retained-marker', 'topics': []}}})
            preparing_history, offset = False, len(server.requests)
            if compact:
                model = self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'retry-compact',
                    'baseURL': f'http://127.0.0.1:{server.server_port}/v1', 'autoCompactTokenLimit': 1000})
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
        if missing_result:
            get_run = Agent.get_run_output
            def missing_current_result(agent, *args, **kwargs):
                previous = get_run(agent, *args, **kwargs)
                if previous is not None:
                    previous.messages = [message for message in previous.messages or [] if message.role != 'tool']
                    previous.messages.insert(1, Message(role='assistant', from_history=True,
                        tool_calls=[{'id': 'append_1', 'type': 'function',
                            'function': {'name': 'older_tool', 'arguments': '{}'}}]))
                    previous.messages.insert(2, Message(role='tool', tool_call_id='append_1',
                        content='Older result with the same call ID', from_history=True))
                return previous
            missing = patch.object(Agent, 'get_run_output', missing_current_result)
            missing.start()
            self.addCleanup(missing.stop)
        with patch.object(db, 'complete_job', side_effect=fail_settlement):
            goal = 'Append once, then analyze the observation without repeating the operation.'
            if prior:
                self.post('/research/sessions/' + prior['id'] + '/turns',
                    {'text': goal, 'modelConnectionRef': model['connectionRef']})
            else:
                self.send(goal)
            self.assertTrue(settled.wait(20))
            current = self.session()
            store = self.state['store']
            task = store.task(current['turns'][-1]['taskId'], self.owner)
            ticket = db.get_job(task['run_id'])
            self.assertTrue(ticket['payload']['stream'])
            self.assertEqual((ticket['status'], ticket['attempt']), ('running', 1))
            if ssh_not_started:
                self.assertFalse(marker.exists())
            else:
                self.assertEqual(marker.read_text(), 'once\n')
            # Advance only this disposable ticket's stopped heartbeat clock.
            table = db._get_table(table_type='jobs')
            with db.Session() as conn, conn.begin():
                conn.execute(table.update().where(table.c.id == task['run_id']).values(locked_at=0))
            if not ssh_missing or ssh_not_started:
                self.assertTrue(resumed.wait(15))
            if stop:
                self.post('/research/sessions/' + current['id'] + '/stop', {})
                release.set()
            final = self.wait_for(lambda value: value['turns'][-1]['completedAt'] is not None)
            self.assertEqual(final['turns'][-1]['status'], 'canceled' if stop else 'failed' if ssh_missing and not ssh_not_started else 'completed', final)
            self.assertEqual(final['turns'][-1]['taskId'], task['id'])
            self.assertEqual(db.get_job(task['run_id'])['attempt'], 2)
            self.assertEqual(marker.read_text(), 'once\n')
            requests = [request for request in server.requests if request[0].get('tools')]
            self.assertEqual(len(requests) - offset, 4 if ssh_not_started else 2 if completed or ssh_missing else 3)
            if not completed and not compact and not ssh_missing:
                self.assertTrue(any(message.get('role') == 'tool'
                    and ('unknown' if unknown or missing_result else 'appended') in str(message.get('content')).lower()
                    for message in requests[offset + 2][0]['messages']))
            if native or ssh_missing:
                self.assertEqual(store.effects(task['id']), [])
            else:
                self.assertEqual(store.effects(task['id'])[0]['status'], 'UNKNOWN' if unknown else 'DONE')
            sent = json.dumps(server.requests[offset:], ensure_ascii=False)
            if revoked:
                self.assertNotIn('source-secret-marker', sent)
                self.assertNotIn('derived-source-marker', sent)
            if history:
                resumed_input = json.dumps(requests[offset + 2][0]['messages'])
                for text in ('history-target-0', 'history-target-4', 'summary-retained-marker', 'correction-retained-marker'):
                    self.assertIn(text, resumed_input)
            if compact:
                summary = next(request for request, _ in server.requests
                    if request['messages'][-1].get('content') == 'Provide the summary of the conversation.')
                self.assertIn('history-target-0', json.dumps(summary))
                self.assertIn('correction-retained-marker', json.dumps(summary))
                self.assertIn('new-summary-retained-marker', resumed_input)
            self.assertTrue(self.state['executor'].add_history_to_context)
            self.page.reload()
            self.assertEqual(self.session()['turns'][-1]['status'], final['turns'][-1]['status'])
        if ssh_missing and not ssh_not_started:
            ssh_missing = False
            self.post('/research/sessions/' + current['id'] + '/turns', {'text': 'Independent analysis after unknown SSH.'})
            self.wait_for(lambda value: len(value['turns']) == len(final['turns']) + 1
                and value['turns'][-1]['status'] == 'completed')
            self.assertEqual(marker.read_text(), 'once\n')
        if history or revoked:
            self.post('/research/sessions/' + current['id'] + '/turns', {'text': 'followup-confirm-marker'})
            self.wait_for(lambda value: len(value['turns']) == len(final['turns']) + 1
                and value['turns'][-1]['status'] == 'completed')
            followup = json.dumps(server.requests[-1][0]['messages'])
            self.assertIn(goal, followup)
            if history:
                self.assertIn('history-target-4', followup)
            else:
                self.assertNotIn('source-secret-marker', followup)

    def test_completed_operation_is_not_replayed(self):
        self.exercise()

    def test_unknown_observation_allows_independent_continuation(self):
        self.exercise(unknown=True)

    def test_stop_during_native_continuation(self):
        self.exercise(stop=True)

    def test_completed_native_run_needs_no_new_model_request(self):
        self.exercise(completed=True)

    def test_history_result_does_not_hide_current_unknown(self):
        self.exercise(missing_result=True)

    def test_native_tool_without_effect_record_does_not_repeat_missing_result(self):
        self.exercise(native=True, missing_result=True)

    def test_recovery_retains_valid_history_summary_and_correction(self):
        self.exercise(history=True)

    def test_recovery_does_not_restore_withdrawn_source(self):
        self.exercise(revoked=True)

    def test_recovery_preserves_summary_generated_in_failed_attempt(self):
        self.exercise(history=True, compact=True)

    def test_ssh_without_any_saved_messages_does_not_replay(self):
        self.exercise(ssh_missing=True)

    def test_ssh_confirmed_not_started_can_retry_then_continue(self):
        self.exercise(ssh_missing=True, ssh_not_started=True)
