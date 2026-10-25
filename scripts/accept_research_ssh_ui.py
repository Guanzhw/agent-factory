"""Narrow actual-API SSH consent/evidence browser acceptance; test OIDC only.

Reuses the native SSH fixture for isolated PG/resources and existing HTTPS
server helpers. No task/model/SSH execution, real credentials or public listener.
"""
import argparse
from contextlib import ExitStack
from dataclasses import replace
import json
import re
from pathlib import Path
import ssl

import httpx
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from accept_browser_auth import listener, serve
from agent_factory.browser_oidc import BrowserCodeExchanger
from agent_factory.ssh_process_contract import LAUNCH_TOOL
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from browser_identity_fixture import BrowserIdentityFixture, private_tls_files
from fixture_auth import initialize_members
import test_ssh_native_postgres as native


def run(browser, dist, output, *, windows_diagnostic_only=False):
    fixture = native.SSHNativePostgresTests('runTest')
    servers = ExitStack()
    identity = None
    origin = None

    def start():
        nonlocal identity, origin
        certificate, key = private_tls_files(fixture.folder / 'tls')
        app_socket, idp_socket = listener(), listener()
        servers.callback(app_socket.close)
        servers.callback(idp_socket.close)
        origin = 'https://127.0.0.1:' + str(app_socket.getsockname()[1])
        identity = BrowserIdentityFixture(issuer='https://127.0.0.1:' + str(idp_socket.getsockname()[1]),
            redirect_uri=origin + '/api/factory/auth/callback')
        settings = replace(fixture.settings, web_directory=dist.resolve(), browser_oidc=identity.config())
        fixture.app = create_app(settings)
        fixture.state = factory_state(fixture.app)
        fixture.store, fixture.auth = fixture.state['store'], fixture.state['auth']
        initialize_members(fixture.auth)
        fixture.state['browser_auth'].exchanger = BrowserCodeExchanger(identity.config(),
            transport=httpx.AsyncHTTPTransport(verify=ssl.create_default_context(cafile=str(certificate)), retries=0))
        serve(servers, identity.app, idp_socket, certificate, key)
        serve(servers, fixture.app, app_socket, certificate, key)
        # Uvicorn owns the one application lifespan; this client is only the
        # existing native fixture's setup transport, with no second lifespan.
        fixture.client = TestClient(fixture.app, base_url='https://testserver')

    def stop():
        servers.close()
        if fixture.client is not None:
            fixture.client.close()
            fixture.client = None
        fixture.store.dispose_root_locks()
        fixture.store.engine.dispose()
        fixture.store.native_db.db_engine.dispose()

    fixture.start, fixture.stop = start, stop
    context = None
    errors, console_errors, expected_console, binds = [], [], [], []
    try:
        fixture.setUp()
        fixture.store.connections.revoke('alice', fixture.connection, 'browser-revoke-fixture-execute')
        server = fixture.request('GET', '/personal-ssh')[0]
        assert server['enabled'] and not server['executionEnabled'], server
        context = browser.new_context(ignore_https_errors=True, viewport={'width': 1487, 'height': 1058}, service_workers='block')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        logged_in = False
        def console(message):
            if message.type != 'error':
                return
            url = message.location.get('url', '').split('?', 1)[0]
            value = {'text': message.text, 'path': url.removeprefix(origin)}
            if (not logged_in and '401' in message.text and url.endswith(('/api/factory/session', '/api/factory/auth/session'))) or ('ERR_FAILED' in message.text and url.endswith('/bind-execution')):
                expected_console.append(value)
            else:
                console_errors.append(value)
        page.on('console', console)
        capability_projections = []
        if windows_diagnostic_only:
            def project_windows_diagnostic(route):
                actual = route.fetch()
                assert actual.status == 200
                body = actual.json()
                assert body['controllerDiagnostic'] is None
                body['controllerDiagnostic'] = 'SSH_CONTROLLER_PLATFORM_UNSUPPORTED'
                capability_projections.append(body['controllerDiagnostic'])
                route.fulfill(response=actual, json=body)
            page.route('**/personal-ssh/capabilities', project_windows_diagnostic)
        page.goto(origin + '/?tab=connections')
        page.get_by_role('button', name='使用企业账号登录', exact=True).click()
        expect(page.get_by_role('heading', name='我的凭据与连接', exact=True)).to_be_visible()
        logged_in = True
        expect(page.get_by_text('尚未允许训练执行', exact=True)).to_be_visible()
        assert fixture.store.tasks('alice') == [] and not fixture.started.exists()
        if windows_diagnostic_only:
            diagnostic = '当前原生 Windows 控制端尚不支持 SSH 连接检查或执行。已有服务器配置仍可查看和撤销。'
            expect(page.get_by_text(diagnostic, exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name=server['name'], exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='撤销授权', exact=True)).to_be_enabled()
            page.screenshot(path=str(output / 'windows-diagnostic-existing-resource.png'), full_page=True)
            page.get_by_role('button', name='撤销授权', exact=True).click()
            page.get_by_role('button', name='确认撤销服务器授权', exact=True).click()
            expect(page.get_by_text('连接授权已撤销', exact=True)).to_be_visible()
            current = fixture.request('GET', '/personal-ssh/' + server['reference'])
            assert current['status'] == 'revoked' and not current['enabled'] and not current['executionEnabled']
            assert fixture.store.tasks('alice') == [] and fixture.processes == [] and not fixture.started.exists()
            assert errors == [] and console_errors == [], (errors, console_errors)
            page.screenshot(path=str(output / 'windows-diagnostic-revoked.png'), full_page=True)
            return {'ok': True, 'scenario': 'windows-diagnostic-only', 'actualHost': 'Linux Chromium',
                'capabilityProjection': capability_projections, 'nativeWindowsRuntimeTested': False,
                'resourceStatusAfterActualRevoke': current['status'], 'tasks': 0, 'helperLaunches': 0,
                'pageErrors': errors, 'consoleErrors': console_errors, 'expectedConsole': expected_console,
                'businessMutationAPIsMocked': False, 'identity': 'synthetic local HTTPS OIDC'}

        def lose_reply(route):
            binds.append(route.request.post_data_json['requestId'])
            actual = route.fetch()
            assert actual.status == 200
            route.abort('failed')
        page.route('**/personal-ssh/*/bind-execution', lose_reply)
        page.get_by_role('button', name='允许执行已配置训练', exact=True).click()
        expect(page.get_by_role('heading', name='上次操作待确认', exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role('heading', name='上次操作待确认', exact=True)).to_be_visible()
        page.get_by_role('button', name='核对原操作', exact=True).click()
        expect(page.get_by_role('heading', name='上次操作待确认', exact=True)).to_have_count(0)
        expect(page.get_by_text('已允许执行已配置训练', exact=True)).to_be_visible()
        assert len(binds) == 1
        assert set(fixture.store.connections.request_result('alice', binds[0])['connection']['capabilities']) == {'ssh:prepare', 'ssh:execute'}
        assert fixture.store.tasks('alice') == [] and not fixture.started.exists()
        page.screenshot(path=str(output / 'ssh-execution-consent.png'), full_page=True)

        page.goto(origin + '/?tab=research')
        page.get_by_role('button', name='新建项目', exact=True).click()
        page.get_by_label('项目名称', exact=True).fill('SSH 精选证据配置验收')
        page.get_by_role('button', name='创建项目', exact=True).click()
        expect(page.get_by_text('尚未配置精选证据，不能据此获得可复现成果。', exact=True)).to_be_visible()
        page.get_by_label('研究目标', exact=True).fill('Inspect selected SSH evidence')
        page.get_by_label('评价与达标标准', exact=True).fill('Use original selected metrics')
        page.get_by_label('停止与放弃条件', exact=True).fill('No execution in this browser fixture')
        page.get_by_label('最多实验轮数', exact=True).fill('1')
        page.get_by_label('最多工具调用', exact=True).fill('32')
        page.get_by_role('button', name='读取已发布实验材料', exact=True).click()
        candidates = fixture.request('GET', '/research/setup')['experimentMaterials']
        launch = next(item for item in candidates if item['id'] == 'ssh-native-launch')
        pin = ':'.join(str(launch[key]) for key in ('id', 'version', 'sha256'))
        page.get_by_role('combobox', name=re.compile('^证据来源')).select_option('ssh-process')
        page.get_by_role('combobox', name=re.compile('^证据SSH启动材料')).select_option(pin)
        page.get_by_label('指标输出字段', exact=True).fill('metrics')
        page.get_by_role('combobox', name=re.compile('^证据来源')).select_option('cli')
        expect(page.get_by_role('combobox', name=re.compile('^证据CLI材料'))).to_have_value('')
        expect(page.get_by_label('指标输出字段', exact=True)).to_have_count(0)
        page.get_by_role('combobox', name=re.compile('^证据来源')).select_option('ssh-process')
        page.get_by_role('combobox', name=re.compile('^证据SSH启动材料')).select_option(pin)
        for label, value in (('指标', 'metrics'), ('源码', 'source'), ('运行配方', 'recipe')):
            page.get_by_label(label + '输出字段', exact=True).fill(value)
        page.get_by_role('button', name='保存研究约定', exact=True).click()
        expect(page.get_by_role('button', name='修改目标', exact=True)).to_be_visible()
        project_id = page.evaluate("new URL(location.href).searchParams.get('project')")
        project = fixture.request('GET', '/research/projects/' + project_id)
        evidence = project['goals'][-1]['agreement']['evidence']
        assert evidence == {'kind': 'ssh-process', 'toolMaterial': {key: launch[key] for key in ('id', 'version', 'sha256')},
            'fields': {'metrics': 'metrics', 'source': 'source', 'run_recipe': 'recipe'}}
        page.reload()
        page.get_by_role('button', name='修改目标', exact=True).click()
        expect(page.get_by_role('combobox', name=re.compile('^证据来源'))).to_have_value('ssh-process')
        expect(page.get_by_label('指标输出字段', exact=True)).to_have_value('metrics')
        page.screenshot(path=str(output / 'ssh-selected-evidence.png'), full_page=True)

        model = fixture.request('POST', '/personal-models', {'requestId': 'browser-qa-model', 'provider': 'openai-compatible',
            'baseURL': 'http://localhost:9/v1', 'model': 'not-invoked'}, expected=201)
        draft = fixture.request('POST', '/research/setup/qa/drafts', {'requestId': 'browser-qa-draft', 'name': 'QA without SSH',
            'modelConnectionRef': model['connectionRef'], 'budget': {'toolCalls': 4}})
        qa = fixture.request('POST', '/research/setup/' + draft['id'] + '/publish', {'requestId': 'browser-qa-publish'})
        tools = fixture.state['applications'].require_current(qa['applicationRef'])['modes']['qa']['toolOrder']
        assert set(tools) == {'research_qa_context', 'research_qa_record'} and LAUNCH_TOOL not in tools
        assert fixture.store.tasks('alice') == [] and fixture.store.sql('SELECT * FROM af_delegation_links') == []
        assert not fixture.started.exists() and fixture.processes == []
        assert errors == [] and console_errors == [], (errors, console_errors)
        return {'ok': True, 'bindRequests': binds, 'projectId': project_id, 'evidence': evidence,
            'qaToolsWithSSHRegistered': tools, 'tasks': 0, 'helperLaunches': 0, 'pageErrors': errors,
            'consoleErrors': console_errors, 'expectedConsole': expected_console,
            'businessAPIsMocked': False, 'faultInjection': 'drop one actual successful bind-execution response',
            'identity': 'synthetic local HTTPS OIDC', 'runtimeUnknownTested': False, 'externalProviderOrGPU': False}
    except Exception:
        if context is not None:
            page.screenshot(path=str(output / 'first-failure.png'), full_page=True)
        (output / 'browser-errors.json').write_text(json.dumps({'pageErrors': errors, 'consoleErrors': console_errors, 'expectedConsole': expected_console}, indent=2))
        raise
    finally:
        if context is not None:
            context.close()
        fixture.doCleanups()
        servers.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--windows-diagnostic-only', action='store_true', help='Project only the unsupported-controller capability diagnostic; actual Linux fixture APIs remain')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        try:
            result = run(browser, args.dist, args.output, windows_diagnostic_only=args.windows_diagnostic_only)
            (args.output / 'evidence.json').write_text(json.dumps(result, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
