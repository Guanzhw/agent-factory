"""Production subagent protocol: real PG/Agno, explicitly scripted HTTP model.
"""
import asyncio
import ast
from contextvars import ContextVar
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine

from agent_factory.delegation import DelegationService
from agent_factory.byok_model import OwnerChatModel
from agent_factory.runtime import CONTEXT_MARKER
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_identity import access_token
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.session_subagents import SPAWN, WAIT, ResearchSubagents
from research.session_tools import ResearchSessionTools
from research.sessions import ResearchSessions


class ResearchChildCancellationContracts(unittest.TestCase):
    """Actual application/delegation guards with synthetic metadata and SQLite."""

    def setUp(self):
        self.root = {'id': 'root', 'run_id': 'root-run', 'plan_id': 'root-plan', 'owner_id': 'alice',
            'cancel_requested': False, 'admission': 'accepted', 'request_id': 'application-start:original-turn'}
        self.child = {**self.root, 'id': 'child', 'run_id': 'child-run', 'plan_id': 'child-plan',
            'request_id': 'delegation:original-child'}
        self.link = {'child_id': 'child', 'parent_id': 'root', 'root_id': 'root',
            'owner_id': 'alice', 'plan_id': 'child-plan', 'depth': 1}
        binding = {'parentTaskId': 'root', 'rootTaskId': 'root', 'depth': 1}
        self.plans = {name: {'id': name, 'status': 'ready', 'capabilities': [], 'tools': [],
            'applicationRef': {'id': 'research'}, 'mode': 'autonomous',
            'inputValues': {'sessionId': 'session', 'turnId': 'turn'}} for name in ('root-plan', 'child-plan')}
        self.plans['child-plan']['delegation'] = binding
        self.turn = {'id': 'turn', 'owner_id': 'alice', 'session_id': 'session',
            'application_request_id': 'original-turn', 'body': {'startFingerprint': 'original'}}
        self.row = {'id': 'session', 'body': {'configuration': {'applicationRef': {'id': 'research'}},
            'stopped': False}}

        def task(identifier, owner=None):
            item = next(value for value in (self.root, self.child) if identifier in (value['id'], value['run_id']))
            if owner is not None and item['owner_id'] != owner:
                raise HTTPException(404, 'Task not found')
            return item

        def sql(query, **values):
            if 'af_delegation_roots' in query:
                return []
            if 'af_delegation_links' in query:
                return [self.link] if values.get('id', values.get('child')) == 'child' else []
            if 'af_plan_requests' in query:
                self.assertEqual((values['owner'], values['request'], values['plan']),
                    ('alice', self.root['request_id'], self.root['plan_id']))
                return [{'fingerprint': 'original'}]
            raise AssertionError(query)

        store = SimpleNamespace(task=task, plan=lambda identifier, *args: self.plans[identifier], sql=sql,
            has_failures=lambda *_: False, material_governance=None, event=lambda *_: None)
        store.delegation = DelegationService(None, store, SimpleNamespace(require_member=lambda *_: None), None)
        store.delegation._native = lambda *_: {'status': 'running'}
        self.service = object.__new__(ResearchSessions)
        self.service.store = store
        self.service.runs = SimpleNamespace(factory=SimpleNamespace(commands=None))
        self.service.subagents = ResearchSubagents(self.service)
        self.service._row = lambda conn, owner, identifier: self.row
        self.service._turns = lambda conn, identifier: [self.turn]
        metadata = MetaData()
        self.service.turns = Table('turns', metadata, *(Column(name, String) for name in
            ('id', 'owner_id', 'session_id', 'application_request_id')), Column('body', JSON))
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        metadata.create_all(engine)
        self.conn = self.enterContext(engine.begin())
        self.conn.execute(self.service.turns.insert().values(**self.turn))
        self.context = RunContext(user_id='alice', session_id='child', run_id='child-run')

    def test_recorded_root_or_session_stop_before_child_cascade_is_cancellation(self):
        for signal in (self.root, self.row['body']):
            field = 'cancel_requested' if signal is self.root else 'stopped'
            signal[field] = True
            with self.assertRaises(RunCancelledException):
                self.service._execution(self.conn, self.context)
            self.assertFalse(self.child['cancel_requested'])
            signal[field] = False

    def test_unavailable_mandate_is_still_permission_error(self):
        self.root['admission'] = 'rejected'
        with self.assertRaises(PermissionError):
            self.service._execution(self.conn, self.context)

    def test_forged_child_identity_or_link_is_denied_even_when_root_stopped(self):
        self.root['cancel_requested'] = True
        with self.assertRaises(HTTPException):
            self.service._execution(self.conn, RunContext(user_id='bob', session_id='child', run_id='child-run'))
        with self.assertRaises(PermissionError):
            self.service._execution(self.conn, RunContext(user_id='alice', session_id='child', run_id='root-run'))
        self.plans['child-plan']['delegation'] = {'parentTaskId': 'forged', 'rootTaskId': 'root', 'depth': 1}
        with self.assertRaises(PermissionError):
            self.service._execution(self.conn, self.context)

    def test_active_child_keeps_own_execution_identity(self):
        row, turn, task = self.service._execution(self.conn, self.context)
        self.assertEqual((row['id'], turn['id'], task['id'], task['run_id']),
            ('session', 'turn', 'child', 'child-run'))


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchSubagentProbe(unittest.TestCase):
    def boot(self, owners=('alice',), *, hold_children=False, command_child=False,
             same_call_memory=False, lose_child_receipt=False):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        scratch = Path(self.enterContext(TemporaryDirectory()))
        workspace = scratch / 'workspace'
        workspace.mkdir()
        self.calls, self.wire_errors, phases, parent_arrivals = [], [], {}, set()
        provider_plan = ContextVar('probe_provider_plan')
        original_request = OwnerChatModel._request

        async def traced_request(model, messages, **kwargs):
            token = provider_plan.set(model._session_id.removeprefix('af-plan-'))
            try:
                return await original_request(model, messages, **kwargs)
            finally:
                provider_plan.reset(token)

        self.enterContext(patch.object(OwnerChatModel, '_request', traced_request))
        self.release = asyncio.Event()
        both_parents = asyncio.Event()
        if not hold_children:
            self.release.set()

        async def scripted_wire(request):
            body = json.loads(request.content)
            context = next(json.loads(line.split(CONTEXT_MARKER, 1)[1])
                for item in body['messages'] if item['role'] == 'system'
                for line in item['content'].splitlines() if CONTEXT_MARKER in line)
            owner = body['model'].removeprefix('scripted-')
            child = context['normalizedGoal'].startswith('child-')
            key = owner, child
            phase = phases.get(key, 0)
            phases[key] = phase + 1
            actual_task = self.store.sql('SELECT * FROM af_tasks WHERE plan_id=:plan', plan=provider_plan.get())[0]
            self.calls.append({'owner': owner, 'child': child, 'phase': phase,
                'goal': context['normalizedGoal'], 'plan': context['id'], 'providerPlan': provider_plan.get(),
                'task': actual_task['id'], 'run': actual_task['run_id'],
                'attempt': self.ticket(actual_task)['attempt'], 'effects': len(self.store.effects(actual_task['id'])),
                'body': body})
            self.assertEqual(context['id'], provider_plan.get(), 'Provider binding and instruction plan must agree')
            name, arguments, message = None, {}, None
            memory_call = same_call_memory and phase == 0
            if same_call_memory:
                phase -= 1
            if memory_call:
                name, arguments = 'research_remember', {'memory': 'Use unittest.'}
            elif child:
                if phase == 0:
                    await self.release.wait()
                    name = 'research_run' if command_child else 'research_read_file'
                    arguments = {'argv': ['python3', 'sleeper.py']} if command_child else {'path': 'evidence.txt'}
                else:
                    message = {'role': 'assistant', 'content': 'child-evidence-' + owner}
            elif phase == 0:
                parent_arrivals.add(owner)
                if len(parent_arrivals) == len(owners):
                    both_parents.set()
                await both_parents.wait()
                name, arguments = 'research_edit_file', {'path': 'parent-note.txt', 'old': '', 'new': 'investigation-' + owner}
            elif phase == 1:
                name, arguments = SPAWN, {'goal': 'child-' + owner}
            elif phase == 2:
                child_result = next(ast.literal_eval(item['content']) for item in body['messages']
                    if item['role'] == 'tool' and 'childTaskId' in item.get('content', ''))
                name, arguments = WAIT, {'childTaskId': child_result['childTaskId']}
            else:
                if lose_child_receipt:
                    result = next(json.loads(item['content']) for item in body['messages']
                        if item['role'] == 'tool' and item.get('tool_call_id') == f'{owner}-0-2')
                    self.assertIsNone(result['result'], 'A lost child answer must not become the root answer')
                    self.assertEqual(result['status'], 'failed')
                else:
                    self.assertIn('child-evidence-' + owner, json.dumps(body))
                message = {'role': 'assistant', 'content': 'integrated-' + owner}
            if name:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'same-memory-call' if memory_call else f'{owner}-{int(child)}-{phase}', 'type': 'function', 'function': {
                        'name': name, 'arguments': json.dumps(arguments)}}]}
            return httpx.Response(200, json={'choices': [{'finish_reason': 'tool_calls' if name else 'stop',
                'message': message}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18}})

        async def wire(request):
            try:
                return await scripted_wire(request)
            except Exception as error:
                self.wire_errors.append(repr(error))
                raise

        self.tools = ResearchSessionTools(workspace_root=workspace, host_commands=True)
        self.app_settings = Settings(db_url=isolated.url, workspace=scratch / 'factory',
            owner_model_transport_factory=lambda: httpx.MockTransport(wire))
        self.app = create_app(self.app_settings, session_tools=self.tools)
        self.state = factory_state(self.app)
        initialize_members(self.state['auth'])
        self.store, self.sessions = self.state['store'], self.state['research_sessions']
        self.child_receipt_losses = []
        complete = self.store.effect_complete

        def record_completion(run_id, key, receipt):
            task = self.store.sql('SELECT * FROM af_tasks WHERE run_id=:run', run=run_id)[0]
            if (lose_child_receipt and key.endswith(':same-memory-call') and not self.child_receipt_losses
                    and self.store.plan(task['plan_id']).get('delegation')):
                self.child_receipt_losses.append((task['id'], run_id))
                raise ConnectionError('Synthetic response loss after real child memory write')
            return complete(run_id, key, receipt)

        if lose_child_receipt:
            self.enterContext(patch.object(self.store, 'effect_complete', side_effect=record_completion))
        self.life = self.enterContext(ExitStack())
        self.life.callback(self.store.engine.dispose)
        self.life.callback(self.store.native_db.db_engine.dispose)
        self.life.callback(self.store.dispose_root_locks)
        self.client = self.life.enter_context(TestClient(self.app, base_url='https://testserver'))
        self.headers = {owner: {'Authorization': 'Bearer ' + access_token(owner)} for owner in owners}
        self.identifiers, self.workspaces = {}, {}
        for owner in owners:
            model = self.store.personal_models.configure(owner, {'provider': 'openai-compatible',
                'baseURL': 'http://localhost:8899/v1', 'model': 'scripted-' + owner}, 'probe-model-' + owner)
            session = self.post(owner, '/sessions', {'requestId': 'probe-session-' + owner,
                'title': 'Synthetic subagent protocol probe', 'goal': 'parent-' + owner,
                'boundaries': 'Only inspect this temporary fixture.', 'modelConnectionRef': model['connectionRef'],
                'limits': {'maxTurns': 2, 'toolCallsPerTurn': 8, 'operationSeconds': 5}})
            self.identifiers[owner] = session['id']
            path = workspace.joinpath(*(hashlib.sha256(value.encode()).hexdigest() for value in (owner, session['id'])))
            path.mkdir(parents=True)
            (path / 'evidence.txt').write_text('private-evidence-' + owner)
            (path / 'sleeper.py').write_text('import os,subprocess,sys,time\n'
                'from pathlib import Path\n'
                'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"])\n'
                'Path("pids.txt").write_text(str(os.getpid())+" "+str(child.pid))\n'
                'time.sleep(120)\n')
            self.workspaces[owner] = path
        self.assertEqual(self.store.settings.max_workers, 2)
        self.assertEqual(self.store.settings.max_user_tasks, 2)
        for owner in owners:
            self.post(owner, '/sessions/' + self.identifiers[owner] + '/turns', {
                'requestId': 'probe-turn-' + owner, 'text': 'Investigate with one child, then integrate.'})

    def post(self, owner, path, body):
        response = self.client.post('/api/factory/research' + path, json=body, headers=self.headers[owner])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait(self, predicate, label, seconds=20):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.05)
        self.fail(label + ': ' + json.dumps({'tasks': self.store.sql('SELECT id,owner_id,body FROM af_tasks'),
            'events': self.store.sql('SELECT type,message,data FROM af_events ORDER BY id DESC LIMIT 12'),
            'calls': [{key: value for key, value in item.items() if key != 'body'} for item in self.calls],
            'wireErrors': self.wire_errors}, default=str))

    def roots(self):
        return self.store.sql("SELECT * FROM af_tasks WHERE request_id LIKE 'application-start:%'")

    def ticket(self, task):
        return self.store.native_db.get_job(task['run_id']) if task.get('run_id') else {}

    def test_original_child_and_native_continuation(self):
        self.boot()
        self.wait(lambda: len(self.roots()) == 1 and self.ticket(self.roots()[0]).get('status') == 'completed',
                  'Parent did not resume with original child')
        root = self.roots()[0]
        links = self.store.sql('SELECT * FROM af_delegation_links')
        self.assertEqual(len(links), 1)
        child = self.store.task(links[0]['child_id'], 'alice')
        self.assertNotEqual(root['id'], child['id'])
        self.assertNotEqual(root['run_id'], child['run_id'])
        self.assertEqual(self.ticket(root)['attempt'], 2)
        self.assertEqual(self.ticket(child)['attempt'], 1)
        self.assertEqual(len(self.store.effects(root['id'])), 1)
        self.assertEqual(len(self.store.effects(child['id'])), 0)
        self.assertEqual((self.workspaces['alice'] / 'parent-note.txt').read_text(), 'investigation-alice')
        self.assertEqual(self.store.plan(root['plan_id'])['budget']['maxChildren'], 1)
        self.assertEqual(self.store.plan(child['plan_id'])['inputValues']['sessionId'], self.identifiers['alice'])
        child_requests = [item['body'] for item in self.calls if item['child']]
        self.assertIn('private-evidence-alice', json.dumps(child_requests))
        self.assertEqual(len(self.calls), 6)
        ticket = self.ticket(root)
        self.assertTrue(self.sessions.subagents.permits_continuation(root, ticket))
        retry = deepcopy(ticket)
        retry['attempt'] += 1
        self.assertFalse(self.sessions.subagents.permits_continuation(root, retry),
                         'A requeue retaining the original continuation payload is not a new continuation')
        tampered = deepcopy(ticket)
        tampered['payload']['continue']['kwargs']['metadata']['factoryControlCommand']['fingerprint'] = 'forged'
        self.assertFalse(self.sessions.subagents.permits_continuation(root, tampered))

    def test_parent_and_child_same_memory_call_id_use_their_own_native_receipts(self):
        self.boot(same_call_memory=True)
        self.wait(lambda: len(self.roots()) == 1 and self.ticket(self.roots()[0]).get('status') == 'completed',
                  'Parent must integrate after the distinct original memory calls')
        root = self.roots()[0]
        child = self.store.task(self.store.sql('SELECT * FROM af_delegation_links')[0]['child_id'])
        memories = self.store.native_db.get_user_memories(user_id='alice')
        self.assertEqual(len(memories), 2)
        self.assertNotEqual(memories[0].memory_id, memories[1].memory_id)
        for task in (root, child):
            effects = [item for item in self.store.effects(task['id']) if item['effect_key'].endswith(':same-memory-call')]
            self.assertEqual(len(effects), 1)
            self.assertEqual(effects[0]['status'], 'DONE')
            self.assertTrue(effects[0]['effect_key'].startswith(task['run_id'] + ':'))
        self.wait(lambda: self.store.task(root['id'])['terminal'], 'Original root lifecycle must finish before final projection')
        view = self.client.get('/api/factory/research/sessions/' + self.identifiers['alice'],
            headers=self.headers['alice']).json()
        self.assertEqual(view['turns'][0]['result'], 'integrated-alice')
        self.assertEqual(view['turns'][0]['children'][0]['result'], 'child-evidence-alice')
        self.assertEqual(len(self.calls), 8)

    def test_child_memory_lost_receipt_observed_without_rewriting_or_root_result(self):
        self.boot(same_call_memory=True, lose_child_receipt=True)
        self.wait(lambda: len(self.roots()) == 1 and self.ticket(self.roots()[0]).get('status') == 'completed',
                  'Original parent must receive the stopped child without replaying its memory')
        root = self.roots()[0]
        child_id, child_run = self.child_receipt_losses[0]
        child = self.store.task(child_id)
        self.assertEqual(child['run_id'], child_run)
        effects = self.store.effects(child_id)
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]['status'], 'DONE')
        self.assertTrue(effects[0]['result']['reconciled'])
        self.assertEqual(len(self.store.native_db.get_user_memories(user_id='alice')), 2)
        self.assertEqual(len([item for item in self.calls if item['child']]), 1)
        self.assertEqual(self.ticket(child)['attempt'], 1)
        parent_memory = next(item for item in self.store.effects(root['id']) if item['effect_key'].endswith(':same-memory-call'))
        self.assertNotIn('reconciled', parent_memory['result'])
        for _ in range(3):
            self.client.portal.call(self.sessions.observe_waits, self.store.lifecycle_observer, child)
        self.assertEqual(len(self.store.sql('SELECT * FROM af_delegation_links')), 1)
        self.wait(lambda: self.store.task(root['id'])['terminal'], 'Original failed child must remain visible in root lifecycle')
        view = self.client.get('/api/factory/research/sessions/' + self.identifiers['alice'],
            headers=self.headers['alice']).json()
        self.assertEqual(view['turns'][0]['status'], 'failed')
        self.assertIsNone(view['turns'][0]['result'])
        self.assertEqual(view['turns'][0]['children'][0]['status'], 'failed')
        self.assertIsNone(view['turns'][0]['children'][0]['result'])

    def test_two_owners_pause_without_extra_capacity(self):
        self.boot(('alice', 'bob'), hold_children=True)
        self.wait(lambda: len(self.roots()) == 2 and all(self.ticket(root).get('status') == 'paused'
            for root in self.roots()), 'Both parents must pause')
        links = self.store.sql('SELECT * FROM af_delegation_links')
        self.assertEqual(len(links), 2)
        self.wait(lambda: all(self.ticket(self.store.task(link['child_id'])).get('status') == 'running'
            for link in links), 'Both children must run with their parents paused')
        for link in links:
            child = self.store.task(link['child_id'])
            context = RunContext(user_id=child['owner_id'], session_id=child['id'], run_id=child['run_id'])
            self.assertEqual(self.sessions.authorize_tool(context, 'research_read_file')['id'],
                             self.identifiers[child['owner_id']])
        self.client.portal.call(self.release.set)
        self.wait(lambda: all(self.ticket(root).get('status') == 'completed' for root in self.roots()),
                  'Both original parents must resume')
        for item in self.calls:
            other = 'bob' if item['owner'] == 'alice' else 'alice'
            self.assertNotIn('private-evidence-' + other, json.dumps(item['body']))
        self.assertEqual(len(self.calls), 12)

    def test_service_restart_observes_original_wait_and_reuses_child(self):
        self.boot(hold_children=True)
        async def defer_result(*_):
            return None

        self.sessions.subagents.observe_waits = defer_result
        self.wait(lambda: self.roots() and self.ticket(self.roots()[0]).get('status') == 'paused',
                  'Parent must be durably paused before restart')
        root = self.roots()[0]
        link = self.store.sql('SELECT * FROM af_delegation_links')[0]
        child = self.store.task(link['child_id'])
        context = RunContext(user_id='alice', session_id=root['id'], run_id=root['run_id'])
        duplicate = self.client.portal.call(self.sessions.subagents.start, context, 'alice-0-1', 'child-alice')
        self.assertEqual((duplicate['childTaskId'], duplicate['runId']), (child['id'], child['run_id']))
        self.assertEqual(duplicate['childTaskId'], child['id'])
        with self.assertRaises(HTTPException) as changed:
            self.client.portal.call(self.sessions.subagents.start, context, 'alice-0-1', 'changed goal')
        self.assertEqual(changed.exception.status_code, 409)
        self.client.portal.call(self.release.set)
        self.wait(lambda: self.ticket(child).get('status') == 'completed', 'Original child must finish')
        self.assertEqual(self.ticket(root)['status'], 'paused')
        self.life.close()
        self.tools = ResearchSessionTools(workspace_root=self.tools.workspace_root, host_commands=True)
        self.app = create_app(self.app_settings, session_tools=self.tools)
        self.state = factory_state(self.app)
        self.store, self.sessions = self.state['store'], self.state['research_sessions']
        self.life.callback(self.store.engine.dispose)
        self.life.callback(self.store.native_db.db_engine.dispose)
        self.life.callback(self.store.dispose_root_locks)
        self.client = self.life.enter_context(TestClient(self.app, base_url='https://testserver'))
        self.wait(lambda: self.ticket(root).get('status') == 'completed', 'Original run must resume after service restart')
        for _ in range(3):
            self.client.portal.call(self.sessions.subagents.observe_waits, self.store.lifecycle_observer,
                                    self.store.task(root['id']))
        self.assertEqual(len(self.store.sql('SELECT * FROM af_delegation_links')), 1)
        self.assertEqual(self.store.task(child['id'])['run_id'], child['run_id'])
        self.assertEqual(self.store.task(root['id'])['run_id'], root['run_id'])
        self.assertEqual(len(self.calls), 6)

    def test_stop_reaches_actual_child_command_and_descendant_process(self):
        self.boot(command_child=True)
        path = self.workspaces['alice'] / 'pids.txt'
        self.wait(path.exists, 'Child command must write its actual parent and child PIDs')
        pids = [int(value) for value in path.read_text().split()]
        self.assertEqual(len(pids), 2)
        self.post('alice', '/sessions/' + self.identifiers['alice'] + '/stop', {'requestId': 'probe-stop-original'})

        def exited(pid):
            status = Path(f'/proc/{pid}/stat')
            try:
                return status.read_text().split()[2] == 'Z'
            except FileNotFoundError:
                return True

        self.wait(lambda: all(exited(pid) for pid in pids), 'Both actual processes must exit after stop')
        root = self.roots()[0]
        self.wait(lambda: self.client.portal.call(self.store.delegation.inspect_group, 'alice', root['id'])['allStopped'],
                  'Stopping must be confirmed for the original task tree')
        self.assertTrue(self.store.task(root['id'])['cancel_requested'])
        self.assertNotEqual(self.ticket(root)['status'], 'completed')
        self.assertEqual(len(self.store.sql('SELECT * FROM af_delegation_links')), 1)
