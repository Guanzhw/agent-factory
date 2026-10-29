"""Native Agno Function calls, real temporary files/processes; synthetic authority only."""
import asyncio
import ast
from contextlib import chdir
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agno.agent import Agent
from agno.exceptions import RunCancelledException, StopAgentRun
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools.function import FunctionCall
from fastapi import HTTPException

from agent_factory.execution_bindings import BindingContext, EnvironmentLimits
from agent_factory.store import digest
from research.session_tools import EFFECT_PREFIX, ResearchSessionTools, _directory, _parts


CONTENT_ID = 'abcdefab-1111-2222-3333-abcdefabcdef'


class ResearchSessionConfigurationTests(unittest.TestCase):
    def test_research_plan_can_select_longer_operation_without_changing_environment_default(self):
        limits = ResearchSessionTools._environment(SimpleNamespace(plan={
            'budget': {'operationSeconds': 60, 'outputBytes': 65536}}))
        self.assertEqual(limits.timeout_seconds, 60)
        self.assertEqual(EnvironmentLimits().timeout_seconds, 8)
        self.assertEqual(EnvironmentLimits(timeout_seconds=.15).timeout_seconds, .15)
        with self.assertRaises(ValueError):
            EnvironmentLimits(timeout_seconds=601)

    def test_default_and_disabled_search_path_leave_only_shared_evidence_available(self):
        self.assertEqual(ResearchSessionTools().available_tools, ['research_read_shared_evidence'])
        self.assertEqual(ResearchSessionTools(command_path='.').available_tools, ['research_read_shared_evidence'])

    def test_enabled_commands_still_require_absolute_search_path_and_strict_types(self):
        for options in ({'host_commands': True, 'command_path': '.'}, {'command_path': None},
                {'host_commands': 0}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'RESEARCH_COMMAND_CONFIGURATION_INVALID'):
                ResearchSessionTools(**options)

    def test_unsupported_platform_workspace_is_rejected_before_open(self):
        unavailable = SimpleNamespace(name='java', open=Mock())
        with patch('research.session_tools.os', unavailable), \
                patch('research.session_tools.sys', SimpleNamespace(platform='unsupported')):
            with self.assertRaisesRegex(ValueError, 'RESEARCH_WORKSPACE_CONFIGURATION_INVALID'):
                ResearchSessionTools(workspace_root=Path.cwd())
            with self.assertRaisesRegex(ValueError, 'RESEARCH_WORKSPACE_CONFIGURATION_INVALID'):
                with _directory(Path.cwd()):
                    self.fail('Unsupported directory was opened')
        unavailable.open.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'POSIX flag contract')
    def test_missing_required_posix_flags_never_fall_back_to_unprotected_open(self):
        unavailable = SimpleNamespace(name='posix', O_RDONLY=os.O_RDONLY, open=Mock())
        with patch('research.session_tools.os', unavailable), self.assertRaises(AttributeError):
            with _directory(Path.cwd()):
                self.fail('Directory opened without required flags')
        unavailable.open.assert_not_called()

    def test_windows_path_grammar_rejects_aliases_without_native_io(self):
        with patch('research.session_tools.sys', SimpleNamespace(platform='win32')):
            self.assertEqual(_parts('中文 空格/source.py'), ['中文 空格', 'source.py'])
            for path in ('C:/outside', 'C:outside', '//server/share', r'\\?\C:\outside',
                    'file:stream', 'NUL.txt', 'COM¹', 'LPT1.py', 'trailing.', 'trailing ', 'a*/b', 'a\n'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    _parts(path)


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


@unittest.skipUnless(os.name in {'posix', 'nt'}, 'Requires an implemented host process owner')
class ResearchSessionToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temporary = TemporaryDirectory(prefix='research-tool-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store, self.sessions, self.content = Store(), Sessions(), Content()
        self.tools = ResearchSessionTools(workspace_root=self.root, host_commands=True,
            command_path=str(Path(sys.executable).parent) + (os.pathsep + os.defpath if os.name == 'posix' else ''))
        self.tools.bind(self.sessions, self.content)
        self.sequence = 0

    def call(self, name, arguments, *, owner='alice', call_id=None, run_id=None):
        self.sequence += 1
        ctx = RunContext(user_id=owner, session_id='task-' + owner, run_id=run_id or 'run-' + owner, session_state={})
        binding = BindingContext(None, self.store, {'budget': {'operationSeconds': self.sessions.seconds, 'outputBytes': 65536}},
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

    async def test_utf8_space_paths_exact_hashes_and_real_command_cwd(self):
        workspace = self.workspace()
        (workspace / '中文 空格').mkdir()
        original = '# 注释\r\nvalue = "原值"\r\n'
        path = '中文 空格/源码.py'
        created = await self.invoke('research_edit_file', {'path': path, 'old': '', 'new': original})
        self.assertEqual(created['afterSha256'], hashlib.sha256(original.encode()).hexdigest())
        read = await self.invoke('research_read_file', {'path': path})
        self.assertEqual(read['text'], original)
        found = await self.invoke('research_search', {'query': '原值', 'path': '中文 空格'})
        self.assertEqual(found['matches'], [{'path': path, 'line': 2, 'text': 'value = "原值"'}])
        changed = await self.invoke('research_edit_file', {'path': path, 'old': '原值', 'new': '新值'})
        expected = original.replace('原值', '新值').encode()
        self.assertEqual((workspace / path).read_bytes(), expected)
        self.assertEqual(changed['beforeSha256'], created['afterSha256'])
        self.assertEqual(changed['afterSha256'], hashlib.sha256(expected).hexdigest())
        result = await self.invoke('research_run', {'argv': [Path(sys.executable).name, '-c',
            'import os,sys;from pathlib import Path;assert Path("源码.py").exists();'
            'print("中文输出");print("中文错误",file=sys.stderr);print(os.getcwd())'], 'cwd': '中文 空格'})
        self.assertEqual(result['exitCode'], 0)
        self.assertIn('中文输出', result['stdout'])
        self.assertIn(str(workspace / '中文 空格'), result['stdout'])
        self.assertEqual(result['stderr'].strip(), '中文错误')

    @unittest.skipUnless(sys.platform == 'win32', 'Requires actual Windows junction and file handle APIs')
    async def test_windows_junctions_hardlinks_and_device_aliases_never_change_outside_file(self):
        workspace = self.workspace()
        outside = self.root / 'outside'
        outside.mkdir()
        target = outside / 'private.txt'
        target.write_text('outside-private', encoding='utf-8')
        junction = workspace / 'junction'
        command = str(Path(os.environ['SystemRoot']) / 'System32' / 'cmd.exe')
        subprocess.run([command, '/d', '/c', 'mklink', '/J', str(junction), str(outside)],
            capture_output=True, check=True)
        self.addCleanup(junction.rmdir)
        with self.assertRaises(ValueError):
            ResearchSessionTools(workspace_root=junction)
        (workspace / 'hardlink.txt').hardlink_to(target)
        for path in ('junction/private.txt', 'hardlink.txt', 'NUL.txt', 'file:stream', 'C:/outside', '../outside'):
            with self.subTest(path=path):
                read = await self.invoke('research_read_file', {'path': path})
                self.assertEqual(read['outcome'], 'failed')
                edit = await self.invoke('research_edit_file', {'path': path, 'old': 'outside-private', 'new': 'wrong'})
                self.assertEqual(edit['outcome'], 'failed')
        search = await self.invoke('research_search', {'path': 'junction', 'query': 'outside-private'})
        self.assertEqual(search['outcome'], 'failed')
        command_result = await self.invoke('research_run', {'argv': [Path(sys.executable).name, '-c', 'pass'],
            'cwd': 'junction'})
        self.assertEqual(command_result['outcome'], 'failed')
        self.assertEqual(target.read_text(encoding='utf-8'), 'outside-private')

    @unittest.skipUnless(sys.platform == 'win32', 'Requires actual Windows directory sharing modes')
    async def test_windows_ancestor_handles_block_replacement_and_release_after_operation(self):
        import win32con
        import win32file
        workspace = self.workspace()
        nested = workspace / '中文 nested'
        nested.mkdir()
        with _directory(workspace, ('中文 nested',)):
            with self.assertRaises(OSError):
                workspace.rename(workspace.with_name('moved'))
            with self.assertRaises(OSError):
                nested.rename(workspace / 'replaced')
            with self.assertRaises(OSError):
                handle = win32file.CreateFile(str(nested), win32con.GENERIC_WRITE,
                    win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                    None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_BACKUP_SEMANTICS, None)
                handle.Close()
            created = await self.invoke('research_edit_file', {'path': '中文 nested/source.py',
                'old': '', 'new': 'value = 1\n'})
            self.assertTrue(created['created'])
        nested.rename(workspace / 'released')
        self.assertEqual((workspace / 'released/source.py').read_bytes(), b'value = 1\n')

    @unittest.skipUnless(sys.platform == 'win32', 'Requires actual Windows executable search semantics')
    async def test_windows_command_lookup_does_not_add_service_current_directory(self):
        fake = self.root / 'research-cwd-only.exe'
        shutil.copyfile(sys.executable, fake)
        with chdir(self.root):
            result = await self.invoke('research_run', {'argv': [fake.name]})
        self.assertEqual(result, {'outcome': 'failed', 'code': 'RESEARCH_COMMAND_UNAVAILABLE',
            'message': 'Tool call failed. Check the reported code and tool arguments before correcting this call.'})
        for command in ('C:python.exe', 'NUL.exe', 'python.exe:stream'):
            rejected = await self.invoke('research_run', {'argv': [command]})
            self.assertEqual(rejected['code'], 'RESEARCH_COMMAND_INVALID')

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows configured long operation acceptance')
    async def test_windows_command_can_run_beyond_thirty_seconds_within_selected_budget(self):
        self.sessions.seconds = 40
        result = await self.invoke('research_run', {'argv': [Path(sys.executable).name, '-c',
            'import time;time.sleep(30.1);print("long-test-completed")']})
        self.assertEqual(result['exitCode'], 0)
        self.assertEqual(result['stdout'].strip(), 'long-test-completed')
        self.assertTrue(result['stopped'])

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

    async def test_normal_source_larger_than_12kb_can_be_read_found_and_edited(self):
        original = '# ordinary unchanged source line\n' * 1400 + 'answer = 40 + 1\n'
        source = self.workspace() / 'module.py'
        source.write_text(original)
        self.assertGreater(source.stat().st_size, 12000)
        read = await self.invoke('research_read_file', {'path': 'module.py'})
        self.assertEqual(read['text'], original)
        found = await self.invoke('research_search', {'query': 'answer = 40 + 1'})
        self.assertEqual(found['matches'], [{'path': 'module.py', 'line': 1401, 'text': 'answer = 40 + 1'}])
        self.assertFalse(found['truncated'])
        changed = await self.invoke('research_edit_file', {'path': 'module.py',
            'old': 'answer = 40 + 1', 'new': 'answer = 40 + 2'})
        self.assertEqual(source.read_text(), original.replace('answer = 40 + 1', 'answer = 40 + 2'))
        self.assertNotEqual(changed['beforeSha256'], changed['afterSha256'])
        self.assertEqual(changed['bytes'], source.stat().st_size)

    async def test_single_file_search_matches_directory_search_and_reports_truncation(self):
        folder = self.workspace() / 'project/pytest_asyncio'
        folder.mkdir(parents=True)
        source = folder / 'plugin.py'
        source.write_text('# ordinary source\n' * 1400 + 'loop.shutdown_asyncgens()\n')
        file_result = await self.invoke('research_search', {'path': 'project/pytest_asyncio/plugin.py',
            'query': 'shutdown_asyncgens'})
        directory_result = await self.invoke('research_search', {'path': 'project/pytest_asyncio',
            'query': 'shutdown_asyncgens'})
        self.assertEqual(file_result, directory_result)
        self.assertEqual(file_result['matches'], [{'path': 'project/pytest_asyncio/plugin.py',
            'line': 1401, 'text': 'loop.shutdown_asyncgens()'}])
        self.assertEqual(file_result['entriesScanned'], 1)
        source.write_text('match\n' * 31)
        bounded = await self.invoke('research_search', {'path': 'project/pytest_asyncio/plugin.py', 'query': 'match'})
        self.assertEqual(len(bounded['matches']), 30)
        self.assertTrue(bounded['truncated'])

    async def test_native_agent_corrects_target_and_schema_errors_in_same_run(self):
        (self.workspace() / 'source.py').write_text('answer = 42\n')

        class CorrectingModel(RepairModel):
            def invoke(self, messages, **kwargs):
                step = self.calls
                self.calls += 1
                if step:
                    result = ast.literal_eval(next(message.content for message in reversed(messages)
                        if message.role == 'tool'))
                    if step < 3:
                        assert result['outcome'] == 'failed' and result['message']
                        assert result['code'] == ('RESEARCH_FILE_TARGET_INVALID' if step == 1
                            else 'PERSONAL_TOOL_INPUT_INVALID')
                    else:
                        assert result['matches'][0]['text'] == 'answer = 42'
                        return ModelResponse(role='assistant', content='Corrected the search after reading both errors.')
                arguments = ({'path': 'missing.py', 'query': 'answer'}, {'path': 'source.py'},
                    {'path': 'source.py', 'query': 'answer'})[step]
                return ModelResponse(role='assistant', tool_calls=[{'id': 'correcting-' + str(step),
                    'type': 'function', 'function': {'name': 'research_search', 'arguments': json.dumps(arguments)}}])

        def selected_tools(run_context: RunContext):
            binding = BindingContext(None, self.store, {'budget': {}}, run_context, {})
            return [registration.factory(binding) for registration in self.tools.tool_registrations]

        model = CorrectingModel('', '')
        agent = Agent(id='scripted-error-correction', model=model, tools=selected_tools, telemetry=False, tool_call_limit=4)
        result = await agent.arun('Scripted correction protocol.', user_id='alice',
            session_id='task-alice', run_id='run-alice')
        self.assertEqual(model.calls, 4)
        self.assertIn('Corrected the search', result.content)
        self.assertEqual([event['data']['outcome'] for event in self.store.events
            if event['type'] == 'research_tool_finished'], ['failed', 'failed', 'completed'])
        self.assertEqual(self.store.receipts, {})

    async def test_failed_edit_receipt_is_returned_without_repeating_operation(self):
        source = self.workspace() / 'source.py'
        source.write_text('original\n')
        arguments = {'path': 'source.py', 'old': 'missing', 'new': 'replacement'}
        first = await self.invoke('research_edit_file', arguments, call_id='failed-edit')
        self.assertEqual(first['outcome'], 'failed')
        self.assertEqual(source.read_text(), 'original\n')
        source.write_text('missing\n')
        second = await self.invoke('research_edit_file', arguments, call_id='failed-edit')
        self.assertEqual(first, second)
        self.assertEqual(source.read_text(), 'missing\n')
        self.assertEqual(self.store.effects('task-alice')[0]['status'], 'DONE')
        unavailable = await self.invoke('research_run', {'argv': ['nonexistent-research-test-command']})
        self.assertEqual(unavailable['outcome'], 'failed')
        self.assertEqual(unavailable['code'], 'RESEARCH_COMMAND_UNAVAILABLE')

    async def test_local_file_access_error_is_recoverable_but_owner_revocation_blocks_invalid_arguments(self):
        with patch('research.session_tools._read', side_effect=PermissionError('synthetic OS file access denied')):
            result = await self.invoke('research_read_file', {'path': 'source.py'})
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['code'], 'RESEARCH_FILE_TARGET_INVALID')
        self.sessions.active = False
        call = self.call('research_search', {'path': 'source.py'})
        self.assertEqual((await call.aexecute()).status, 'failure')
        self.assertIsNone(call.result)

    async def test_native_agent_completes_both_commands_from_one_model_response(self):
        commands = (['pwd'], ['ls', '-la']) if os.name == 'posix' else (
            [Path(sys.executable).name, '-c', 'import os;print(os.getcwd())'],
            [Path(sys.executable).name, '-c', 'import os;print(os.listdir())'])
        class ParallelResponse(RepairModel):
            def invoke(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return ModelResponse(role='assistant', tool_calls=[
                        {'id': 'parallel-' + str(index), 'type': 'function', 'function': {
                            'name': 'research_run', 'arguments': json.dumps({'argv': argv})}}
                        for index, argv in enumerate(commands)])
                return ModelResponse(role='assistant', content='Scripted model received both tool results.')

        def selected_tools(run_context: RunContext):
            binding = BindingContext(None, self.store, {'budget': {}}, run_context, {})
            return [registration.factory(binding) for registration in self.tools.tool_registrations]

        model = ParallelResponse('', '')
        agent = Agent(id='scripted-parallel-tools', model=model, tools=selected_tools, telemetry=False)
        await agent.arun('Scripted replay: inspect this temporary directory.', user_id='alice',
                         session_id='task-alice', run_id='run-alice')
        self.assertEqual(model.calls, 2)
        effects = self.store.effects('task-alice')
        self.assertEqual([item['status'] for item in effects], ['DONE', 'DONE'])
        self.assertEqual([item['result']['output']['argv'] for item in effects], list(commands))
        self.assertTrue(all(item['result']['output']['exitCode'] == 0 for item in effects))

    async def test_different_runs_start_processes_without_waiting_for_each_other(self):
        release = self.root / 'release-synthetic-processes'
        script = ('from pathlib import Path;import time;Path("started").write_text("ready");'
                  f'\nwhile not Path({str(release)!r}).exists(): time.sleep(.01)')
        calls = [self.call('research_run', {'argv': [Path(sys.executable).name, '-c', script]}, owner=owner)
                 for owner in ('alice', 'bob')]
        pending = [asyncio.create_task(call.aexecute()) for call in calls]
        try:
            for _ in range(100):
                if all((self.workspace(owner) / 'started').exists() for owner in ('alice', 'bob')):
                    break
                await asyncio.sleep(.02)
            self.assertTrue(all((self.workspace(owner) / 'started').exists() for owner in ('alice', 'bob')))
        finally:
            release.touch()
            results = await asyncio.gather(*pending, return_exceptions=True)
        self.assertEqual([result.status for result in results], ['success', 'success'])

    async def test_read_above_return_budget_reports_reason_without_changing_file(self):
        original = '# unchanged source\n' * 4000
        source = self.workspace() / 'oversized-result.py'
        source.write_text(original)
        call = self.call('research_read_file', {'path': 'oversized-result.py'})
        result = await call.aexecute()
        self.assertEqual(result.status, 'success')
        self.assertEqual(call.result['outcome'], 'failed')
        self.assertEqual(call.result['code'], 'RESEARCH_TOOL_OUTPUT_TOO_LARGE')
        self.assertEqual(source.read_text(), original)
        self.assertEqual(self.store.effects('task-alice'), [])
        self.assertEqual(self.store.events[-1]['data']['code'], 'RESEARCH_TOOL_OUTPUT_TOO_LARGE')

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink fixture; Windows junctions tested separately')
    async def test_owner_paths_symlinks_traversal_and_exact_edit_failure(self):
        await self.invoke('research_edit_file', {'path': 'private.txt', 'old': '', 'new': 'alice-private'})
        bob = self.call('research_read_file', {'path': 'private.txt'}, owner='bob')
        self.assertEqual((await bob.aexecute()).status, 'success')
        self.assertEqual(bob.result['outcome'], 'failed')
        outside = self.root / 'outside.txt'
        outside.write_text('outside-private')
        (self.workspace() / 'link').symlink_to(outside)
        (self.workspace() / 'directory-link').symlink_to(self.root, target_is_directory=True)
        for path in ('../outside.txt', '/etc/passwd', 'link', 'directory-link/outside.txt'):
            with self.subTest(path=path):
                call = self.call('research_read_file', {'path': path})
                self.assertEqual((await call.aexecute()).status, 'success')
                self.assertEqual(call.result['outcome'], 'failed')
                self.assertNotIn('outside-private', str(call.result))
        bad_edit = self.call('research_edit_file', {'path': 'private.txt', 'old': 'missing', 'new': 'wrong'})
        self.assertEqual((await bad_edit.aexecute()).status, 'success')
        self.assertEqual(bad_edit.result['outcome'], 'failed')
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
        self.tools = ResearchSessionTools(workspace_root=self.root, host_commands=True,
            command_path=str(Path(sys.executable).parent) + (os.pathsep + os.defpath if os.name == 'posix' else ''))
        self.tools.bind(self.sessions, self.content)
        new = self.call('research_run', {'argv': [Path(sys.executable).name, '-c',
            'from pathlib import Path;Path("replayed").write_text("bad")']}, run_id='run-after-reopen')
        with self.assertRaises(StopAgentRun):
            await new.aexecute()
        invalid = self.call('research_search', {'path': 'missing.py'}, run_id='run-after-reopen')
        with self.assertRaises(StopAgentRun):
            await invalid.aexecute()
        self.assertFalse((self.workspace() / 'replayed').exists())
        same_call = self.call('research_run', {}, call_id=call.call_id)
        with self.assertRaises(StopAgentRun):
            await same_call.aexecute()
        self.assertEqual(len(self.store.receipts), 1)
        self.assertEqual(self.store.events[-1]['data']['outcome'], 'unknown')
        self.assertTrue(self.store.events[-1]['data']['stopped'])

    @unittest.skipUnless(sys.platform == 'linux', 'Linux /proc group evidence; Windows uses original Job tests')
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
        waiting = self.call('research_edit_file', {'path': 'after-stop', 'old': '', 'new': 'must not run'})
        waiter = asyncio.create_task(waiting.aexecute())
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        self.sessions.cancelled = True
        with self.assertRaises(RunCancelledException):
            await asyncio.wait_for(pending, 4)
        with self.assertRaises(RunCancelledException):
            await asyncio.wait_for(waiter, 4)
        self.assertFalse((marker.parent / 'after-stop').exists())
        for pid in pids:
            proc = Path('/proc') / str(pid) / 'stat'
            if proc.exists():
                self.assertIn(proc.read_text().split(') ')[1].split()[0], {'Z', 'X'})
        effect = self.store.effects('task-alice')[0]
        self.assertEqual(effect['status'], 'CANCELLED')
        self.assertEqual(effect['result']['stopped'], True)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux /proc evidence; Windows uses original Job tests')
    async def test_revocation_stops_running_command_and_rejects_waiting_tool(self):
        workspace = self.workspace()
        call = self.call('research_run', {'argv': [Path(sys.executable).name, '-c',
            'from pathlib import Path;import os,time;Path("started").write_text(str(os.getpid()));time.sleep(30)']})
        pending = asyncio.create_task(call.aexecute())
        marker = workspace / 'started'
        for _ in range(100):
            if marker.exists():
                break
            await asyncio.sleep(.02)
        self.assertTrue(marker.exists())
        waiting = self.call('research_edit_file', {'path': 'after-revocation', 'old': '', 'new': 'must not run'})
        waiter = asyncio.create_task(waiting.aexecute())
        await asyncio.sleep(0)
        self.assertFalse(waiter.done())
        self.sessions.active = False
        with self.assertRaises(StopAgentRun):
            await asyncio.wait_for(pending, 4)
        self.assertEqual((await asyncio.wait_for(waiter, 4)).status, 'failure')
        self.assertFalse((workspace / 'after-revocation').exists())
        self.assertEqual(len(self.store.effects('task-alice')), 1)
        proc = Path('/proc') / marker.read_text() / 'stat'
        if proc.exists():
            self.assertIn(proc.read_text().split(') ')[1].split()[0], {'Z', 'X'})

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
