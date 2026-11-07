"""Chat acceptance through real HTTPS, PostgreSQL, Agno and local processes.

Only identity and model responses are synthetic. No browser API interception,
external model calls, provider credentials, HAR or browser traces are used.
Run with PYTHONPATH=platform:deployment:platform/tests:applications:applications/tests.
"""
import argparse
import ast
from contextlib import ExitStack, suppress
import json
import os
import re
from pathlib import Path
import ssl
import sys
import tempfile
import time
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from accept_browser_auth import listener, serve
from agent_factory.browser_oidc import BrowserCodeExchanger
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from browser_identity_fixture import BrowserIdentityFixture, private_tls_files
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.session_tools import ResearchSessionTools


class ScriptedProvider:
    """A deterministic model fixture; actual tools and queue remain unmodified."""
    def __init__(self, delegations=5):
        self.delegations = delegations
        self.mode = 'command'
        self.calls = 0

    def __call__(self, request):
        assert str(request.url) == 'http://127.0.0.1:1/v1/chat/completions'
        self.calls += 1
        body = json.loads(request.content)
        messages = body['messages']
        tool_names = {call['id']: call.get('function', {}).get('name')
            for item in messages for call in item.get('tool_calls', [])}
        tool_results = [{**item, 'name': tool_names.get(item.get('tool_call_id'))}
            for item in messages if item.get('role') == 'tool']
        # Children receive a distinct input context, not the parent's transcript.
        child = any('\\"subtask\\"' in str(item.get('content', '')) for item in messages)
        call = None
        content = '验收完成：已读取实际工具结果。'
        if child:
            content = '子助手已完成独立检查。'
        elif not tool_results:
            if self.mode == 'delegate':
                call = ('research_delegate', {'goal': '独立检查：直接回复子助手完成，不调用工具。'})
            else:
                code = ('import time, os; from pathlib import Path; Path("stop-probe.pid").write_text(str(os.getpid())); print("STOP_PROBE_STARTED", flush=True); time.sleep(120)'
                        if self.mode == 'stop' else
                        'import sys, time; time.sleep(1); print("EXPECTED_FAILURE", flush=True); sys.exit(7)'
                        if self.mode == 'failure' else
                        'from pathlib import Path; p=Path("acceptance.txt"); '
                        'p.write_text("actual local result", encoding="utf-8"); '
                        'print("ACTUAL_TOOL_SUCCESS", p.read_text())')
                call = ('research_run', {'argv': [sys.executable, '-I', '-c', code], **({'yield_time_ms': 250} if self.mode == 'failure' else {})})
        elif self.mode == 'delegate':
            def find_child(value):
                if isinstance(value, dict):
                    if isinstance(value.get('childTaskId'), str):
                        return value['childTaskId']
                    for nested in value.values():
                        found = find_child(nested)
                        if found:
                            return found
                if isinstance(value, list):
                    for nested in value:
                        found = find_child(nested)
                        if found:
                            return found
                return None
            delegated = [item for item in tool_results if item.get('name') == 'research_delegate']
            waited = [item for item in tool_results if item.get('name') == 'research_wait_child']
            if len(delegated) == len(waited) and len(delegated) < self.delegations:
                call = ('research_delegate', {'goal': f'独立检查 {len(delegated) + 1}：直接回复子助手完成，不调用工具。'})
            for result in reversed(delegated if len(delegated) > len(waited) else []):
                try:
                    try:
                        decoded = json.loads(result.get('content', '{}'))
                    except (ValueError, TypeError):
                        decoded = ast.literal_eval(result.get('content', '{}'))
                    identifier = find_child(decoded)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if identifier:
                    call = ('research_wait_child', {'childTaskId': identifier})
                    break
        if self.mode in {'command', 'failure', 'stop'} and tool_results:
            try:
                latest = json.loads(tool_results[-1].get('content', '{}'))
            except (ValueError, TypeError):
                latest = ast.literal_eval(tool_results[-1].get('content', '{}'))
            if isinstance(latest, dict) and latest.get('status') in {'queued', 'running'}:
                call = ('research_wait_child', {'childTaskId': latest['childTaskId']})
            elif self.mode != 'failure' and tool_results[-1].get('name') == 'research_wait_child':
                original = next(item for item in reversed(tool_results) if item.get('name') == 'research_run')
                try:
                    receipt = json.loads(original.get('content', '{}'))
                except (ValueError, TypeError):
                    receipt = ast.literal_eval(original.get('content', '{}'))
                call = ('research_read_process', {'processId': receipt['processId']})
        if self.mode == 'failure' and tool_results:
            content = '命令退出码为 7，任务未成功；错误输出已保留。'
        message = {'role': 'assistant', 'content': content if call is None else None}
        if call:
            message['tool_calls'] = [{'id': 'fixture-' + uuid4().hex, 'type': 'function',
                'function': {'name': call[0], 'arguments': json.dumps(call[1])}}]
        finish = 'tool_calls' if call else 'stop'
        if body.get('stream'):
            chunks = []
            if call:
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, **message['tool_calls'][0]}]}
                chunks.append({'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]})
            else:
                for index, fragment in enumerate((content[:6], content[6:])):
                    delta = {'content': fragment}
                    if index == 0:
                        delta['role'] = 'assistant'
                    chunks.append({'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]})
            chunks.append({'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130}})
            payload = ''.join('data: ' + json.dumps({'id': 'synthetic-chat', 'object': 'chat.completion.chunk', 'created': 1794000000, 'model': body['model'], **chunk}) + '\n\n' for chunk in chunks)
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=payload + 'data: [DONE]\n\n')
        return httpx.Response(200, json={'id': 'synthetic-chat', 'model': body['model'],
            'object': 'chat.completion', 'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130}})


def run_mode(browser, args, mode):
    output = args.output / mode
    output.mkdir()
    with ExitStack() as stack:
        database = stack.enter_context(IsolatedPostgres(args.database_url))
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='chat-browser-')))
        coding = scratch / 'coding'
        coding.mkdir()
        certificate, key = private_tls_files(scratch / 'tls')
        app_socket, idp_socket = listener(), listener()
        stack.callback(app_socket.close)
        stack.callback(idp_socket.close)
        origin = 'https://127.0.0.1:' + str(app_socket.getsockname()[1])
        identity = BrowserIdentityFixture(issuer='https://127.0.0.1:' + str(idp_socket.getsockname()[1]),
            redirect_uri=origin + '/api/factory/auth/callback')
        provider = ScriptedProvider(args.delegations)
        settings = Settings(db_url=database.url, workspace=scratch / 'factory', web_directory=args.dist.resolve(),
            browser_oidc=identity.config(), owner_model_transport_factory=lambda: httpx.MockTransport(provider),
            storage_task_reserve_bytes=1024 * 1024)
        app = create_app(settings, session_tools=ResearchSessionTools(workspace_root=coding,
            host_commands=True, command_path=str(Path(sys.executable).parent)))
        state = factory_state(app)
        store = state['store']
        stack.callback(store.engine.dispose)
        stack.callback(store.native_db.db_engine.dispose)
        stack.callback(store.dispose_root_locks)
        state['browser_auth'].exchanger = BrowserCodeExchanger(identity.config(),
            transport=httpx.AsyncHTTPTransport(verify=ssl.create_default_context(cafile=str(certificate)), retries=0))
        state['auth'].directory.upsert('alice', name='验收用户')
        serve(stack, identity.app, idp_socket, certificate, key)
        serve(stack, app, app_socket, certificate, key)
        context = browser.new_context(ignore_https_errors=True, viewport={
            'width': 1440 if mode == 'desktop' else 390, 'height': 1000 if mode == 'desktop' else 844})
        stack.callback(context.close)
        page = context.new_page()
        errors, mutations, streams, steps = [], [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: mutations.append({'path': request.url.split('?', 1)[0].removeprefix(origin),
            'body': request.post_data_json}) if request.method == 'POST' and '/research/sessions' in request.url else None)
        page.on('response', lambda response: streams.append(response.status) if '/research/sessions/' in response.url
            and response.url.endswith('/events') else None)

        def capture(name):
            assert page.locator('body').evaluate('(element) => element.scrollWidth <= innerWidth'), name
            filename = f'{len(steps) + 1:02d}-{name}.png'
            page.screenshot(path=str(output / filename), full_page=False)
            page.screenshot(path=str(output / ('fullpage-' + filename)), full_page=True)
            steps.append({'name': name, 'screenshot': filename})

        def post(path, body, status=200):
            csrf = context.request.get(origin + '/api/factory/auth/session').json()['csrfToken']
            response = context.request.post(origin + '/api/factory' + path, data=body,
                headers={'X-Factory-CSRF': csrf, 'Origin': origin})
            assert response.status == status, (path, response.status, response.text())
            return response.json()

        def focus_activity():
            target = page.locator('.rs-turn').last.locator('.rs-activity')
            target.scroll_into_view_if_needed()
            if mode == 'mobile':
                target.evaluate('(element) => window.scrollBy(0, element.getBoundingClientRect().top - 175)')
            else:
                target.evaluate('(element) => { const scroller = element.closest(".rs-content"); if (scroller) scroller.scrollTop += element.getBoundingClientRect().top - 100; }')

        def read(identifier):
            response = context.request.get(origin + '/api/factory/research/sessions/' + identifier)
            assert response.ok, response.status
            return response.json()

        def wait_for(identifier, predicate, seconds=90):
            deadline = time.monotonic() + seconds
            value = None
            while time.monotonic() < deadline:
                value = read(identifier)
                if predicate(value):
                    return value
                if value.get('turns') and value['turns'][-1]['status'] == 'failed':
                    raise AssertionError(('native task failed', value['turns'][-1]['failure']))
                page.wait_for_timeout(100)
            (output / 'last-session.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))
            raise AssertionError(('session did not reach expected state', value))

        try:
            page.goto(origin)
            page.get_by_role('button', name='使用企业账号登录', exact=True).click()
            expect(page.get_by_placeholder('向 Agent Factory 发送消息…')).to_be_visible()
            capture('chat-empty')
            prompt = page.get_by_placeholder('向 Agent Factory 发送消息…')
            prompt.fill('创建文件并运行检查，返回实际结果。')
            page.get_by_role('button', name='配置我的模型', exact=True).click()
            expect(page.get_by_role('heading', name='我的模型/API', exact=True)).to_be_visible()
            capture('model-settings')
            page.get_by_label('模型提供方', exact=True).select_option('openai-compatible')
            page.get_by_label('模型名称', exact=True).fill('SCRIPTED-chat-acceptance')
            page.get_by_label('API 端点', exact=True).fill('http://127.0.0.1:1/v1')
            page.get_by_label('模型凭据来源', exact=True).select_option('none')
            page.get_by_role('button', name='保存并设为默认', exact=True).click()
            expect(page.get_by_text('默认模型', exact=True)).to_be_visible()
            capture('model-saved')
            page.get_by_role('button', name='返回对话', exact=True).click()
            expect(prompt).to_have_value('创建文件并运行检查，返回实际结果。')
            expect(page.get_by_role('button', name='发送消息', exact=True)).to_be_enabled()
            capture('draft-restored')
            navigation = page.locator('details.rs-navigation')
            if mode == 'mobile':
                navigation.locator('summary').first.click()
            page.get_by_role('button', name='设置', exact=True).click()
            expect(page.get_by_role('heading', name='设置', exact=True)).to_be_visible()
            capture('settings')
            page.get_by_role('button', name=re.compile(r'^返回\s*(?:对话|应用)$')).click()
            expect(prompt).to_have_value('创建文件并运行检查，返回实际结果。')
            if mode == 'mobile' and navigation.get_attribute('open') is not None:
                navigation.locator('summary').first.click()
            page.get_by_role('button', name='发送消息', exact=True).click()
            page.wait_for_function("new URL(location.href).searchParams.get('researchSession')")
            identifier = page.evaluate("new URL(location.href).searchParams.get('researchSession')")
            value = wait_for(identifier, lambda value: value['turns'] and value['turns'][-1]['status'] == 'completed')
            expect(page.get_by_text('验收完成：已读取实际工具结果。', exact=True)).to_be_visible()
            assert 'ACTUAL_TOOL_SUCCESS' in json.dumps(value, ensure_ascii=False)
            assert any(path.read_text() == 'actual local result' for path in coding.rglob('acceptance.txt'))
            expect(page.locator('.rs-turn').last.locator('header')).to_contain_text('本轮已完成')
            focus_activity()
            page.locator('.rs-turn').last.get_by_text('查看命令输出', exact=True).click()
            capture('tool-completed')
            original = next(item for item in mutations if item['path'].endswith('/turns'))
            repeated = post(original['path'].removeprefix('/api/factory'), original['body'])
            assert len(repeated['turns']) == 1
            previous_calls = provider.calls
            page.reload()
            expect(page.get_by_text('验收完成：已读取实际工具结果。', exact=True)).to_be_visible()
            assert len(read(identifier)['turns']) == 1 and provider.calls == previous_calls
            expect(page.locator('.rs-turn').last.locator('header')).to_contain_text('本轮已完成')
            focus_activity()
            capture('reload-original')
            if mode == 'desktop':
                page.locator('.rs-content').evaluate('(element) => element.scrollTop = element.scrollHeight')
                page.wait_for_timeout(100)
            provider.mode = 'failure'
            post('/research/sessions/' + identifier + '/turns', {'requestId': str(uuid4()), 'text': '验证失败反馈。'})
            value = wait_for(identifier, lambda value: len(value['turns']) == 2 and value['turns'][-1]['status'] == 'completed')
            assert 'EXPECTED_FAILURE' in json.dumps(value) and '7' in json.dumps(value['turns'][-1]['toolResults'])
            expect(page.get_by_text('命令退出码为 7，任务未成功；错误输出已保留。', exact=True)).to_be_visible()
            if mode == 'desktop':
                expect(page.get_by_text('命令退出码为 7，任务未成功；错误输出已保留。', exact=True)).to_be_in_viewport()
            expect(page.locator('.rs-turn')).to_have_count(2)
            expect(page.locator('.rs-turn').last.locator('header')).to_contain_text('本轮已完成')
            focus_activity()
            expect(page.locator('.rs-turn').last.get_by_text('命令退出码：7', exact=False)).to_be_in_viewport()
            page.locator('.rs-turn').last.get_by_text('查看命令输出', exact=True).click()
            capture('command-failure')
            provider.mode = 'delegate'
            post('/research/sessions/' + identifier + '/turns', {'requestId': str(uuid4()), 'text': '委托独立检查。'})
            value = wait_for(identifier, lambda value: len(value['turns']) == 3 and value['turns'][-1]['status'] == 'completed')
            children = value['turns'][-1].get('children', [])
            assert len(children) >= args.delegations and all(child['status'] == 'completed' for child in children), value
            expect(page.locator('.rs-turn')).to_have_count(3)
            expect(page.locator('.rs-turn').last.locator('header')).to_contain_text('本轮已完成')
            execution = page.locator('.rs-turn').last.locator('details.rs-execution')
            execution.evaluate('(element) => element.open = true')
            child_region = page.get_by_role('region', name='第 3 轮临时子助手', exact=True)
            child_region.scroll_into_view_if_needed()
            expect(child_region).to_be_in_viewport()
            capture('delegation')
            provider.mode = 'stop'
            post('/research/sessions/' + identifier + '/turns', {'requestId': str(uuid4()), 'text': '开始可停止的本地进程。'})
            wait_for(identifier, lambda value: len(value['turns']) == 4 and any(
                event['type'] == 'research_tool_started' for event in value['turns'][-1]['events']))
            deadline = time.monotonic() + 30
            while not list(coding.rglob('stop-probe.pid')) and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            pid_files = list(coding.rglob('stop-probe.pid'))
            assert pid_files, 'Stop probe must actually start its owned process'
            stopped_pid = int(pid_files[0].read_text())
            expect(page.locator('.rs-turn')).to_have_count(4)
            expect(page.locator('.rs-turn').last.locator('.rs-activity')).to_contain_text('运行命令')
            focus_activity()
            capture('running')
            if mode == 'mobile':
                page.evaluate('window.scrollTo(0, 0)')
                page.wait_for_timeout(1200)
                assert page.evaluate('window.scrollY') < 50, 'Progress must not pull a reader away from history'
                page.locator('.rs-detail-heading').scroll_into_view_if_needed()
            page.get_by_role('button', name='请求停止', exact=True).click()
            value = wait_for(identifier, lambda value: value['state'] == 'stopped')
            assert value['turns'][-1]['status'] in {'cancelled', 'canceled'}
            expect(page.locator('.rs-state')).to_contain_text('已停止')
            focus_activity()
            if os.name == 'posix':
                with suppress(ProcessLookupError):
                    os.kill(stopped_pid, 0)
                    raise AssertionError('Owned process is still alive after stopped state')
            capture('stopped')
            calls_after_stop = provider.calls
            page.reload()
            expect(page.locator('.rs-state')).to_contain_text('已停止')
            assert read(identifier)['state'] == 'stopped' and provider.calls == calls_after_stop
            focus_activity()
            capture('stopped-reloaded')
            if mode == 'mobile':
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.reload()
                expect(page.locator('.rs-state')).to_contain_text('已停止')
                page.locator('.rs-turn').last.locator('.rs-activity').scroll_into_view_if_needed()
                capture('same-session-desktop-stopped')
            (output / 'session.json').write_text(json.dumps(value, ensure_ascii=False, indent=2))
            assert not errors, errors
            assert streams and all(status == 200 for status in streams), streams
            return {'viewport': mode, 'steps': steps, 'modelCalls': provider.calls,
                'sessionStreams': len(streams), 'realBusinessHTTP': True, 'realPostgres': True,
                'realNativeQueue': True, 'realLocalProcess': True, 'externalModelCalls': 0,
                'identity': 'synthetic-loopback-oidc', 'browserAPIsIntercepted': False,
                'duplicateTurnCreated': False, 'delegatedChildren': args.delegations, 'stoppedState': value['state']}
        except BaseException:
            page.screenshot(path=str(output / 'failure.png'), full_page=True)
            (output / 'failure-page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--delegations', type=int, default=5)
    parser.add_argument('--viewport', choices=('desktop', 'mobile', 'both'), default='both')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            results = [run_mode(browser, args, mode) for mode in
                (('desktop', 'mobile') if args.viewport == 'both' else (args.viewport,))]
            (args.output / 'evidence.json').write_text(json.dumps({'passed': True, 'results': results}, ensure_ascii=False, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
