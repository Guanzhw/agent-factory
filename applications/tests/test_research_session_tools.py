"""Native Agno Function calls, real temporary files/processes; synthetic authority only."""
import asyncio
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agno.agent import Agent
from agno.exceptions import RunCancelledException, StopAgentRun
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools.function import FunctionCall
from fastapi import HTTPException

from agent_factory.execution_bindings import BindingContext
from agent_factory.store import digest
from research.session_tools import EFFECT_PREFIX, ResearchSessionTools


CONTENT_ID = 'abcdefab-1111-2222-3333-abcdefabcdef'


class Store:
    """The production effect fingerprint contract, without claiming PG evidence."""
    def __init__(self):
        self.receipts = {}
        self.events = []

    def effect_reserve(self, run, key, request):
        identifier = run + ':' + key
        previous = self.receipts.get(identifier)
        if previous:
            if previous['fingerprint'] != digest(request):
                raise ValueError('conflict')
            return {'status': 'done' if previous['status'] in {'DONE', 'CANCELLED'} else 'unknown',
                'result': deepcopy(previous['result'])}
        self.receipts[identifier] = {'effect_key': identifier, 'taskId': request['taskId'],
            'fingerprint': digest(request), 'status': 'UNKNOWN', 'result': None}
        return {'status': 'new'}

    def effect_complete(self, run, key, receipt):
        self.receipts[run + ':' + key].update(status='CANCELLED' if receipt.get('cancelled') else 'DONE',
            result=deepcopy(receipt))

    def effects(self, task):
        return [deepcopy(item) for item in self.receipts.values() if item['taskId'] == task]

    def event(self, task, kind, message, data):
        self.events.append({'taskId': task, 'type': kind, 'data': deepcopy(data)})


class Sessions:
    def __init__(self):
        self.cancelled = False
        self.active = True
        self.sources = []
        self.seconds = 3

    def authorize_tool(self, ctx, name):
        if self.cancelled:
            raise RunCancelledException('synthetic owner stop')
        if not self.active or ctx.session_id not in {'task-' + ctx.user_id, 'task-' + ctx.user_id + '-second'}:
            raise PermissionError('synthetic ownership rejected')
        return {'id': 'session-' + ctx.user_id, 'ownerId': ctx.user_id, 'turnId': 'turn-' + ctx.user_id,
            'workspaceRef': 'session-' + ctx.user_id, 'limits': {'operationSeconds': self.seconds}}

    def record_source(self, ctx, identifier):
        self.authorize_tool(ctx, 'research_read_shared_evidence')
        self.sources.append(identifier)


class Content:
    def __init__(self):
        self.shared = True
        self.reads = []

    def read(self, actor, identifier):
        self.reads.append((actor, identifier))
        if not self.shared or identifier != CONTENT_ID:
            raise HTTPException(404, 'RESOURCE_NOT_FOUND')
        return {'id': CONTENT_ID, 'ownerId': 'bob', 'visibility': 'team',
            'source': {'application': 'research', 'record': 'experiment', 'revision': '1'},
            'content': {'observation': 'synthetic evidence'}, 'verificationStatus': 'unverified'}


class RepairModel(Model):
    """Explicit scripted provider: edits only after observing an actual failed test."""
    def __init__(self, old, new):
        super().__init__(id='scripted-repair-protocol', provider='synthetic')
        self.old, self.new, self.calls = old, new, 0

    def invoke(self, messages, **kwargs):
        step = self.calls
        self.calls += 1
        if step == 0:
            name, arguments = 'research_read_file', {'path': 'calc.py'}
        elif step in {1, 3}:
            name, arguments = 'research_run', {'argv': [Path(sys.executable).name, '-B', 'test_calc.py']}
        elif step == 2:
            result = ast.literal_eval(next(message.content for message in reversed(messages) if message.role == 'tool'))
            assert result['exitCode'] == 1, 'Scripted provider must see the real failed test before editing'
            name, arguments = 'research_edit_file', {'path': 'calc.py', 'old': self.old, 'new': self.new}
        elif step == 4:
            result = ast.literal_eval(next(message.content for message in reversed(messages) if message.role == 'tool'))
            assert result['exitCode'] == 0 and 'ACTUAL_TEST_PASSED' in result['stdout']
            return ModelResponse(role='assistant', content='Scripted protocol observed actual tests passing.')
        else:
            raise AssertionError('Unexpected extra model invocation')
        return ModelResponse(role='assistant', tool_calls=[{'id': 'scripted-' + str(step), 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}])

    async def ainvoke(self, messages, **kwargs):
        return self.invoke(messages, **kwargs)

    def invoke_stream(self, messages, **kwargs):
        yield self.invoke(messages, **kwargs)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self.invoke(messages, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@unittest.skipUnless(os.name == 'posix', 'Host command custody requires POSIX process groups')
class ResearchSessionToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temporary = TemporaryDirectory(prefix='research-tool-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store, self.sessions, self.content = Store(), Sessions(), Content()
        self.tools = ResearchSessionTools(workspace_root=self.root, host_commands=True,
            command_path=str(Path(sys.executable).parent) + os.pathsep + os.defpath)
        self.tools.bind(self.sessions, self.content)
        self.sequence = 0

    def call(self, name, arguments, *, owner='alice', call_id=None):
        self.sequence += 1
        ctx = RunContext(user_id=owner, session_id='task-' + owner, run_id='run-' + owner, session_state={})
        binding = BindingContext(None, self.store, {'budget': {'operationSeconds': 3, 'outputBytes': 65536}},
            ctx, {})
        registration = next(item for item in self.tools.tool_registrations if item.tool_name == name)
        function = registration.factory(binding)
        function._run_context = ctx
        return FunctionCall(function=function, arguments=arguments, call_id=call_id or 'call-' + str(self.sequence))

    async def invoke(self, name, arguments, **kwargs):
        call = self.call(name, arguments, **kwargs)
        result = await call.aexecute()
        self.assertEqual(result.status, 'success', result.error)
        return call.result

    def workspace(self, owner='alice'):
        ctx = RunContext(user_id=owner, session_id='task-' + owner, run_id='run-' + owner)
        return self.tools._workspace(self.sessions.authorize_tool(ctx, 'research_read_file'))

    async def test_real_create_read_search_failed_test_exact_edit_and_success(self):
        original = 'def total(values):\n    return sum(values)\n'
        created = await self.invoke('research_edit_file', {'path': 'calc.py', 'old': '', 'new': original})
        self.assertTrue(created['created'])
        await self.invoke('research_edit_file', {'path': 'test_calc.py', 'old': '',
            'new': 'from calc import total\nassert total([2, -3]) == 2\nprint("ACTUAL_TEST_PASSED")\n'})
        read = await self.invoke('research_read_file', {'path': 'calc.py'})
        self.assertEqual(read['text'], original)
        found = await self.invoke('research_search', {'query': 'sum(values)'})
        self.assertEqual(found['matches'][0]['path'], 'calc.py')
        argv = [Path(sys.executable).name, '-B', 'test_calc.py']
        failed = await self.invoke('research_run', {'argv': argv})
        self.assertEqual(failed['exitCode'], 1)
        self.assertIn('AssertionError', failed['stderr'])
        changed = await self.invoke('research_edit_file', {'path': 'calc.py', 'old': 'sum(values)',
            'new': 'sum(value for value in values if value >= 0)'})
        self.assertEqual(changed['beforeSha256'], created['afterSha256'])
        self.assertNotEqual(changed['beforeSha256'], changed['afterSha256'])
        passed = await self.invoke('research_run', {'argv': argv})
        self.assertEqual(passed['exitCode'], 0)
        self.assertEqual(passed['stdout'].strip(), 'ACTUAL_TEST_PASSED')
        self.assertTrue(passed['stopped'])
        self.assertTrue(any(event['data'].get('exitCode') == 1 for event in self.store.events))

    async def test_native_agent_two_turns_use_actual_failure_edit_and_test_results(self):
        workspace = self.workspace()
        (workspace / 'calc.py').write_text('def total(values):\n    return sum(values)\n')
        test_path = workspace / 'test_calc.py'
        test_path.write_text('from calc import total\nassert total([2,-3]) == 2\nprint("ACTUAL_TEST_PASSED")\n')

        def selected_tools(run_context: RunContext):
            binding = BindingContext(None, self.store, {'budget': {}}, run_context, {})
            return [registration.factory(binding) for registration in self.tools.tool_registrations]

        first = RepairModel('sum(values)', 'sum(v for v in values if isinstance(v, int) and v >= 0)')
        agent = Agent(id='scripted-tool-test', model=first, tools=selected_tools, telemetry=False, tool_call_limit=8)
        result = await agent.arun('Synthetic protocol: repair negative values.', user_id='alice',
            session_id='task-alice', run_id='run-alice')
        self.assertEqual(first.calls, 5)
        self.assertIn('actual tests passing', result.content)
        test_path.write_text('from calc import total\nassert total([2,-3,True]) == 2\nprint("ACTUAL_TEST_PASSED")\n')
        second = RepairModel('isinstance(v, int)', 'isinstance(v, int) and not isinstance(v, bool)')
        agent = Agent(id='scripted-tool-test', model=second, tools=selected_tools, telemetry=False, tool_call_limit=8)
        result = await agent.arun('Synthetic next-turn correction: ignore bools too.', user_id='alice',
            session_id='task-alice-second', run_id='run-alice-second')
        self.assertEqual(second.calls, 5)
        self.assertIn('actual tests passing', result.content)
        self.assertIn('not isinstance(v, bool)', (workspace / 'calc.py').read_text())
        codes = [event['data']['exitCode'] for event in self.store.events if 'exitCode' in event['data']]
        self.assertEqual(codes, [1, 0, 1, 0])

    async def test_owner_paths_symlinks_traversal_and_exact_edit_failure(self):
        await self.invoke('research_edit_file', {'path': 'private.txt', 'old': '', 'new': 'alice-private'})
        bob = self.call('research_read_file', {'path': 'private.txt'}, owner='bob')
        self.assertEqual((await bob.aexecute()).status, 'failure')
        outside = self.root / 'outside.txt'
        outside.write_text('outside-private')
        (self.workspace() / 'link').symlink_to(outside)
        (self.workspace() / 'directory-link').symlink_to(self.root, target_is_directory=True)
        for path in ('../outside.txt', '/etc/passwd', 'link', 'directory-link/outside.txt'):
            with self.subTest(path=path):
                call = self.call('research_read_file', {'path': path})
                self.assertEqual((await call.aexecute()).status, 'failure')
                self.assertNotIn('outside-private', str(call.result))
        bad_edit = self.call('research_edit_file', {'path': 'private.txt', 'old': 'missing', 'new': 'wrong'})
        self.assertEqual((await bad_edit.aexecute()).status, 'failure')
        self.assertEqual(self.store.effects('task-alice')[-1]['status'], 'DONE')
        self.assertEqual((self.workspace() / 'private.txt').read_text(), 'alice-private')
        await self.invoke('research_edit_file', {'path': 'private.txt', 'old': 'alice-private', 'new': 'corrected'})
        self.assertNotEqual(self.workspace(), self.workspace('bob'))

    async def test_clean_environment_and_command_opt_in(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-server-secret',
                'RESEARCH_TEST_SECRET': 'synthetic-do-not-inherit', 'PYTHONPATH': '/synthetic/injected'}):
            result = await self.invoke('research_run', {'argv': [Path(sys.executable).name, '-c',
                'import json,os;print(json.dumps(dict(os.environ)))']})
        environment = json.loads(result['stdout'])
        self.assertNotIn('OPENAI_API_KEY', environment)
        self.assertNotIn('RESEARCH_TEST_SECRET', environment)
        self.assertNotIn('PYTHONPATH', environment)
        self.assertNotEqual(environment['HOME'], os.environ.get('HOME'))
        self.assertFalse(Path(environment['HOME']).exists())
        disabled = ResearchSessionTools(workspace_root=self.root)
        self.assertNotIn('research_run', disabled.available_tools)
        self.assertIn('research_edit_file', disabled.available_tools)
        self.assertEqual(ResearchSessionTools().available_tools, ['research_read_shared_evidence'])

    async def test_receipt_replay_does_not_repeat_file_write_or_command(self):
        arguments = {'argv': [Path(sys.executable).name, '-c',
            'from pathlib import Path;p=Path("effects");p.write_text(p.read_text()+"x" if p.exists() else "x")']}
        first = await self.invoke('research_run', arguments, call_id='original-command')
        second = await self.invoke('research_run', arguments, call_id='original-command')
        self.assertEqual(first, second)
        self.assertEqual((self.workspace() / 'effects').read_text(), 'x')
        self.assertEqual(len(self.store.receipts), 1)
        self.assertEqual(len(self.store.events), 2)

    async def test_output_limit_and_stale_native_identity_do_not_dispatch_replacement(self):
        call = self.call('research_run', {'argv': [Path(sys.executable).name, '-c',
            'import sys;sys.stdout.write("x"*50000);sys.stdout.flush()']})
        with self.assertRaises(StopAgentRun):
            await call.aexecute()
        self.assertEqual(self.store.events[-1]['data']['code'], 'PERSONAL_CLI_OUTPUT_LIMIT')
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'UNKNOWN')
        self.assertTrue(self.store.events[-1]['data']['stopped'])
        other = self.call('research_edit_file', {'path': 'wrong-owner', 'old': '', 'new': 'no'}, owner='bob')
        other.function._run_context.user_id = 'alice'
        self.assertEqual((await other.aexecute()).status, 'failure')
        self.assertEqual(len(self.store.receipts), 1)

    async def test_unknown_effect_stops_new_call_instead_of_replaying(self):
        self.sessions.seconds = .1
        call = self.call('research_run', {'argv': [Path(sys.executable).name, '-c',
            'from pathlib import Path;import time;Path("effect").write_text("once");time.sleep(30)']})
        with self.assertRaises(StopAgentRun):
            await call.aexecute()
        effect = self.store.effects('task-alice')[0]
        self.assertEqual(effect['status'], 'UNKNOWN')
        self.assertEqual((self.workspace() / 'effect').read_text(), 'once')
        new = self.call('research_run', {'argv': [Path(sys.executable).name, '-c',
            'from pathlib import Path;Path("replayed").write_text("bad")']})
        with self.assertRaises(StopAgentRun):
            await new.aexecute()
        self.assertFalse((self.workspace() / 'replayed').exists())
        self.assertEqual(len(self.store.receipts), 1)
        self.assertEqual(self.store.events[-1]['data']['outcome'], 'unknown')
        self.assertTrue(self.store.events[-1]['data']['stopped'])

    async def test_cancel_waits_for_real_parent_and_child_group_stop(self):
        script = ('import os,subprocess,sys,time;from pathlib import Path;'
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
            'Path("pids").write_text(str(os.getpid())+","+str(child.pid));time.sleep(30)')
        call = self.call('research_run', {'argv': [Path(sys.executable).name, '-c', script]})
        pending = asyncio.create_task(call.aexecute())
        marker = self.workspace() / 'pids'
        for _ in range(100):
            if marker.exists():
                break
            await asyncio.sleep(.02)
        self.assertTrue(marker.exists(), 'actual parent never started')
        pids = [int(value) for value in marker.read_text().split(',')]
        self.sessions.cancelled = True
        with self.assertRaises(RunCancelledException):
            await asyncio.wait_for(pending, 4)
        for pid in pids:
            proc = Path('/proc') / str(pid) / 'stat'
            if proc.exists():
                self.assertIn(proc.read_text().split(') ')[1].split()[0], {'Z', 'X'})
        effect = self.store.effects('task-alice')[0]
        self.assertEqual(effect['status'], 'CANCELLED')
        self.assertEqual(effect['result']['stopped'], True)

    async def test_shared_evidence_always_rechecks_and_records_source(self):
        result = await self.invoke('research_read_shared_evidence', {'content_id': CONTENT_ID}, call_id='shared-read')
        self.assertEqual(result['source']['application'], 'research')
        self.assertEqual(self.sessions.sources, [CONTENT_ID])
        self.content.shared = False
        call = self.call('research_read_shared_evidence', {'content_id': CONTENT_ID}, call_id='shared-read')
        self.assertEqual((await call.aexecute()).status, 'failure')
        self.assertEqual(len(self.content.reads), 2)
        self.assertEqual(len(self.sessions.sources), 1)
        self.assertEqual(self.store.effects('task-alice'), [])
        self.assertEqual(self.store.events[-1]['type'], 'research_tool_finished')
        self.assertEqual(self.store.events[-1]['data']['outcome'], 'failed')

    async def test_ambiguous_completion_freezes_original_effect(self):
        original = self.store.effect_complete
        self.store.effect_complete = lambda *args: (_ for _ in ()).throw(ConnectionError('synthetic lost ack'))
        call = self.call('research_edit_file', {'path': 'created.txt', 'old': '', 'new': 'original'})
        with self.assertRaises(StopAgentRun):
            await call.aexecute()
        self.store.effect_complete = original
        self.assertEqual((self.workspace() / 'created.txt').read_text(), 'original')
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'UNKNOWN')
        self.assertTrue(self.store.effects('task-alice')[0]['effect_key'].startswith('run-alice:' + EFFECT_PREFIX))
