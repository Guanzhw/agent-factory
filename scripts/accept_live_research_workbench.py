"""Real loopback application HTTP/browser; synthetic model transport and local tool only.

No browser API interception, provider/GPU access, HAR or credential evidence.
Uses an isolated PostgreSQL database, private scratch TLS, existing auth fixtures.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
import ssl
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from accept_browser_auth import listener, serve
from agent_factory.browser_oidc import BrowserCodeExchanger
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from browser_identity_fixture import BrowserIdentityFixture, private_tls_files
from pg_fixture import IsolatedPostgres
from test_research_workflow_postgres import DIGEST, ResearchModel, settings_for, PERMISSION


def model_response(request):
    body = json.loads(request.content)
    names = {tool['function']['name'] for tool in body.get('tools', [])}
    mode = 'experiment' if 'research_fixture_compute' in names else 'research'
    model = ResearchModel(SimpleNamespace(plan={'mode': mode}))
    result = model._response([SimpleNamespace(**message) for message in body['messages']])
    message = {'role': 'assistant', 'content': result.content}
    if result.tool_calls:
        message['tool_calls'] = result.tool_calls
    return httpx.Response(200, json={'id': 'synthetic-' + uuid4().hex, 'object': 'chat.completion',
        'model': 'controlled-research', 'choices': [{'index': 0,
        'finish_reason': 'tool_calls' if result.tool_calls else 'stop', 'message': message}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}})


def model_wire(request):
    try:
        return model_response(request)
    except Exception as error:
        # Only fixture exception type and frame locations, never request headers/body.
        import traceback
        print('SYNTHETIC_MODEL_FIXTURE_ERROR', type(error).__name__, flush=True)
        traceback.print_tb(error.__traceback__)
        raise


def scenario(browser, origin, output, mode, identity, viewport):
    context = browser.new_context(ignore_https_errors=True, viewport=viewport, service_workers='block')
    page = context.new_page()
    errors, console_errors, expected_unauthorized, api_responses = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: api_responses.append({'path': response.url.split('?', 1)[0].removeprefix(origin), 'status': response.status}) if response.url.startswith(origin + '/api/factory/') else None)
    def console(message):
        if message.type != 'error':
            return
        url = message.location.get('url', '').split('?', 1)[0]
        if '401' in message.text and url.endswith(('/api/factory/session', '/api/factory/auth/session')):
            expected_unauthorized.append({'path': url.removeprefix(origin), 'status': 401})
        else:
            console_errors.append({'text': message.text, 'url': url.removeprefix(origin)})
    page.on('console', console)
    login_name = '选择开发测试身份' if mode == 'demo' else '使用企业账号登录'
    def login(owner):
        if identity:
            identity.subject = 'subject-' + owner
        page.get_by_role('button', name=login_name, exact=True).click()
        if mode == 'demo':
            page.locator(f'button[name="persona"][value="{owner}"]').click()
        expect(page.locator('.rw-identity')).to_be_visible()
        assert context.request.get(origin + '/api/factory/session').json()['id'] == owner
    def post(path, value, expected):
        csrf = context.request.get(origin + '/api/factory/auth/session').json()['csrfToken']
        response = context.request.post(origin + '/api/factory' + path, data=value,
            headers={'X-Factory-CSRF': csrf, 'Origin': origin})
        assert response.status == expected, (path, response.status, response.text())
        return response.json()
    try:
        page.goto(origin + '/?tab=research#workspace')
        login('alice')
        expect(page).to_have_url(origin + '/?tab=research#workspace')
        page.get_by_role('button', name='返回平台', exact=True).click()
        page.screenshot(path=str(output / 'platform-home.png'), full_page=True)
        page.get_by_role('button', name='进入 AutoResearch', exact=True).click()
        expect(page.get_by_role('heading', name='我的研究', exact=True)).to_be_visible()
        assert context.request.get(origin + '/api/factory/research/projects').json()['items'] == []
        model = post('/personal-models', {'requestId': str(uuid4()), 'provider': 'openai-compatible',
            'baseURL': 'http://localhost:9/v1', 'model': 'controlled-research'}, 201)
        page.get_by_role('button', name='新建项目', exact=True).click()
        page.get_by_label('项目名称', exact=True).fill('真实接口校验 · 合成模型')
        page.get_by_role('button', name='创建项目', exact=True).click()
        page.get_by_label('研究目标', exact=True).fill('Measure the specified actual bytes')
        page.get_by_label('评价与达标标准', exact=True).fill('Compare actual UTF-8 checksum evidence')
        page.get_by_label('停止与放弃条件', exact=True).fill('Stop on evidenced result or original budget exhaustion')
        page.get_by_label('最多实验轮数', exact=True).fill('1')
        page.get_by_label('最多工具调用', exact=True).fill('32')
        page.get_by_role('button', name='保存研究约定', exact=True).click()
        page.get_by_role('button', name='配置研究执行', exact=True).click()
        page.get_by_role('button', name='准备新的研究执行配置', exact=True).click()
        page.get_by_label('配置名称', exact=True).fill('浏览器显式发布的研究配置')
        page.get_by_role('combobox', name=re.compile('^已保存模型连接')).select_option(model['connectionRef'])
        page.get_by_role('combobox', name=re.compile('^运行环境')).select_option('research-fixture-environment-v1:1')
        page.get_by_label('research_fixture_compute · v1', exact=True).check()
        page.get_by_text('单次执行上限', exact=True).click()
        page.get_by_label('工具调用次数', exact=True).fill('32')
        page.get_by_label('单操作秒数', exact=True).fill('30')
        page.get_by_role('button', name='保存私人配置草稿', exact=True).click()
        expect(page.get_by_role('heading', name='私人草稿 · 尚未发布', exact=True)).to_be_visible()
        page.get_by_role('button', name='发布研究执行配置', exact=True).click()
        expect(page.get_by_role('heading', name='配置已发布', exact=True)).to_be_visible()
        page.get_by_role('button', name='用于当前研究约定', exact=True).click()
        page.get_by_label('研究截止时间（本地时间）', exact=True).fill((datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M'))
        page.get_by_label('每轮工具调用上限', exact=True).fill('32')
        page.get_by_role('button', name='保存配置并生成待确认版本', exact=True).click()
        page.get_by_role('button', name='确认当前约定', exact=True).click()
        page.get_by_role('button', name='按当前约定启动或续接研究', exact=True).click()
        project_id = page.evaluate("new URL(location.href).searchParams.get('project')")
        endpoint = origin + '/api/factory/research/projects/' + project_id
        deadline = time.monotonic() + 45
        records = {}
        while time.monotonic() < deadline:
            response = context.request.get(endpoint + '/experiments')
            assert response.ok, response.text()
            records = response.json()
            if any(item.get('decision') and item.get('terminal') for item in records.get('rounds', [])):
                break
            page.wait_for_timeout(250)
        round_record = next((item for item in records.get('rounds', []) if item.get('decision') and item.get('terminal')), None)
        assert round_record is not None, records
        assert round_record['decision']['outcome'] == 'met', round_record
        assert round_record['decision']['evidenceIds'], round_record
        assert len(round_record['terminal']['runtime']) == 2, round_record
        assert all(task['status'] == 'completed' for task in round_record['terminal']['runtime']), round_record
        assert DIGEST in json.dumps(records['items']), records
        assert any(attempt['operation']['observation']['output']['artifacts'] for item in records['items'] for attempt in item['attempts']), records
        page.get_by_role('tab', name='证据', exact=True).click()
        expect(page.get_by_text('Agent 分析 · 尚未独立验证', exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_text('Agent 分析 · 尚未独立验证', exact=True)).to_be_visible()
        page.screenshot(path=str(output / 'workbench-evidence.png'), full_page=True)
        deep_link = page.url
        page.get_by_role('button', name='返回平台', exact=True).click()
        page.go_back()
        expect(page.get_by_text('Agent 分析 · 尚未独立验证', exact=True)).to_be_visible()
        page.go_forward()
        page.goto(deep_link)
        page.locator('.rw-identity > button').click()
        page.get_by_role('button', name='退出登录', exact=True).click()
        login('alice')
        expect(page.get_by_text('Agent 分析 · 尚未独立验证', exact=True)).to_be_visible()
        page.locator('.rw-identity > button').click()
        page.get_by_role('button', name='退出登录', exact=True).click()
        page.goto(origin + '/?tab=research')
        login('bob')
        assert context.request.get(origin + '/api/factory/research/projects').json()['items'] == []
        denied = context.request.get(endpoint)
        assert denied.status in (403, 404)
        post('/research/projects/' + project_id + '/end', {'requestId': str(uuid4()),
            'expectedVersion': 2, 'outcome': 'cancelled', 'reason': 'Cross-owner denial probe'}, 404)
        assert not errors, errors
        assert not console_errors, console_errors
        return {'projectId': project_id, 'rounds': records['rounds'], 'experiments': records['items'], 'pageErrors': errors,
            'consoleErrors': console_errors, 'expectedUnauthorized': expected_unauthorized, 'apiResponses': api_responses,
            'crossOwnerReadStatus': denied.status, 'crossOwnerWriteStatus': 404,
            'modelConfiguredVia': 'real core HTTP fixture prerequisite, no saved secret',
            'researchTeamReading': 'NOTDONE: P7 API absent', 'realProviderOrGPU': False}
    except BaseException:
        page.screenshot(path=str(output / 'first-failure.png'), full_page=True)
        (output / 'failure-page.txt').write_text(page.locator('body').inner_text())
        (output / 'errors.json').write_text(json.dumps({'pageErrors': errors, 'consoleErrors': console_errors, 'apiResponses': api_responses}, indent=2))
        raise
    finally:
        context.close()


def run_mode(browser, args, mode):
    output = args.output / mode
    output.mkdir()
    with ExitStack() as stack:
        database = stack.enter_context(IsolatedPostgres(args.database_url))
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='research-live-browser-')))
        certificate, key = private_tls_files(scratch / 'tls')
        app_socket = listener()
        stack.callback(app_socket.close)
        origin = 'https://127.0.0.1:' + str(app_socket.getsockname()[1])
        identity = None
        options = {'development_mock_login': True, 'development_public_origin': origin} if mode == 'demo' else {}
        if mode != 'demo':
            idp_socket = listener(); stack.callback(idp_socket.close)
            identity = BrowserIdentityFixture(issuer='https://127.0.0.1:' + str(idp_socket.getsockname()[1]), redirect_uri=origin + '/api/factory/auth/callback')
            options['browser_oidc'] = identity.config()
        settings = settings_for(database.url, scratch / 'workspace', demo=mode == 'demo',
            jwt_key='synthetic-research-browser-signing-key-at-least-32bytes', web_directory=args.dist.resolve(),
            owner_model_transport_factory=lambda: httpx.MockTransport(model_wire), **options)
        app = create_app(settings); state = factory_state(app); store = state['store']
        stack.callback(store.engine.dispose); stack.callback(store.native_db.db_engine.dispose)
        stack.callback(store.dispose_root_locks)
        if identity:
            state['browser_auth'].exchanger = BrowserCodeExchanger(identity.config(),
                transport=httpx.AsyncHTTPTransport(verify=ssl.create_default_context(cafile=str(certificate)), retries=0))
            for owner in ('alice', 'bob'):
                state['auth'].directory.upsert(owner, name='Synthetic ' + owner)
            serve(stack, identity.app, idp_socket, certificate, key)
        serve(stack, app, app_socket, certificate, key)
        governance = state['material_governance']
        tool = governance.create_draft('alice', {'id': 'browser-synthetic-compute', 'kind': 'tool',
            'name': 'research_fixture_compute', 'content': 'research_fixture_compute',
            'permissions': [PERMISSION], 'runtimeBinding': {'adapterId': 'research-fixture-compute-v1', 'revision': '1', 'config': {}}}, 'browser-tool-draft')
        governance.publish('alice', tool['id'], tool['version'], 'browser-tool-publish')
        viewport = {'width': 1487, 'height': 1058} if mode == 'demo' else {'width': 390, 'height': 844}
        result = scenario(browser, origin, output, mode, identity, viewport)
        return {'mode': mode, 'database': database.name, 'businessAPIsMocked': False,
            'identity': 'development-selector' if mode == 'demo' else 'local-synthetic-oidc', 'result': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('demo', 'production-local', 'both'), default='both')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        try:
            results = [run_mode(browser, args, mode) for mode in (('demo', 'production-local') if args.mode == 'both' else (args.mode,))]
            (args.output / 'evidence.json').write_text(json.dumps({'ok': True, 'results': results}, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
