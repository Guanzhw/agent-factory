"""Real loopback application HTTP/browser; synthetic model transport and local tool only.

No browser API interception, provider/GPU access, HAR or credential evidence.
Uses an isolated PostgreSQL database, private scratch TLS, existing auth fixtures.
"""
import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
import ssl
import tempfile
import sys
from threading import Event
from io import BytesIO
from zipfile import ZipFile
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from accept_browser_auth import listener, serve
from agent_factory.application_content import ContentPublication
from agent_factory.personal_tools import OperationAccountRequest
from test_research_delivery_postgres import PROGRAM
from test_research_workflow_postgres import objects
from agent_factory.browser_oidc import BrowserCodeExchanger
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from browser_identity_fixture import BrowserIdentityFixture, private_tls_files
from pg_fixture import IsolatedPostgres
from test_research_workflow_postgres import ResearchModel, settings_for


hold_child = Event()
child_entered = Event()
association_calls = []

def model_response(request):
    body = json.loads(request.content)
    context = next((value for value in objects([SimpleNamespace(**message) for message in body['messages']]) if value.get('purpose') == 'association'), None)
    if context:
        assert not body.get('tools')
        association_calls.append([source['id'] for source in context['sources']])
        answer = {'answer': 'Measurements have related conditions; this is controlled agent analysis.', 'citations': association_calls[-1], 'evidenceLevel': 'agent_analysis', 'relation': 'related'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': json.dumps(answer)}}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})
    names = {tool['function']['name'] for tool in body.get('tools', [])}
    mode = 'experiment' if 'research_fixture_compute' in names else 'research'
    model = ResearchModel(SimpleNamespace(plan={'mode': mode}))
    result = model._response([SimpleNamespace(**message) for message in body['messages']])
    if mode == 'research' and result.content and result.content.startswith('{'):
        inputs = next((item for item in objects([SimpleNamespace(**message) for message in body['messages']]) if 'peerEvidence' in item), None)
        if inputs:
            value = json.loads(result.content)
            value['sourceAssessments'] = [{'contentId': source['id'], 'disposition': 'reproduce', 'reason': 'Compare the actual prior condition with this original run'} for entry in inputs['peerEvidence'] for source in entry['sources']]
            result.content = json.dumps(value)
    message = {'role': 'assistant', 'content': result.content}
    if result.tool_calls:
        message['tool_calls'] = result.tool_calls
    return httpx.Response(200, json={'id': 'synthetic-' + uuid4().hex, 'object': 'chat.completion',
        'model': 'controlled-research', 'choices': [{'index': 0,
        'finish_reason': 'tool_calls' if result.tool_calls else 'stop', 'message': message}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}})


async def model_wire(request):
    try:
        body = json.loads(request.content)
        names = {tool['function']['name'] for tool in body.get('tools', [])}
        if 'research_fixture_compute' in names and not child_entered.is_set():
            child_entered.set()
            if not await asyncio.to_thread(hold_child.wait, 30):
                raise AssertionError('Browser did not complete its bounded goal revision')
        return model_response(request)
    except Exception as error:
        # Only fixture exception type and frame locations, never request headers/body.
        import traceback
        print('SYNTHETIC_MODEL_FIXTURE_ERROR', type(error).__name__, flush=True)
        traceback.print_tb(error.__traceback__)
        raise


def scenario(browser, origin, output, mode, identity, viewport, state, material):
    context = browser.new_context(ignore_https_errors=True, viewport=viewport, service_workers='block')
    page = context.new_page()
    errors, console_errors, expected_unauthorized, api_responses = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: api_responses.append({'path': response.url.split('?', 1)[0].removeprefix(origin), 'status': response.status}) if response.url.startswith(origin + '/api/factory/') else None)
    def console(message):
        if message.type != 'error':
            return
        url = message.location.get('url', '').split('?', 1)[0]
        if ('401' in message.text and url.endswith(('/api/factory/session', '/api/factory/auth/session'))) or ('404' in message.text and ('/research/deliveries/' in url or '/research/associations/' in url)):
            expected_unauthorized.append({'path': url.removeprefix(origin), 'status': 404 if '404' in message.text else 401})
        else:
            console_errors.append({'text': message.text, 'url': url.removeprefix(origin)})
    page.on('console', console)
    login_name = '使用企业账号登录'
    def login(owner):
        identity.subject = 'subject-' + owner
        page.get_by_role('button', name=login_name, exact=True).click()
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
        page.get_by_label('Selected actual CLI · v1', exact=True).check()
        page.get_by_role('combobox', name=re.compile('^工具连接 · experiment_cli')).select_option(material['connectionRef'])
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
        page.get_by_role('button', name='修改目标', exact=True).click()
        page.get_by_role('button', name='读取已发布实验材料', exact=True).click()
        page.get_by_role('combobox', name=re.compile('^证据CLI材料')).select_option(f"{material['id']}:{material['version']}:{material['sha256']}")
        page.get_by_label('指标输出字段', exact=True).fill('metrics')
        page.get_by_label('源码输出字段', exact=True).fill('source')
        page.get_by_label('运行配方输出字段', exact=True).fill('recipe')
        page.get_by_role('button', name='保存研究约定', exact=True).click()
        page.get_by_role('button', name='确认当前约定', exact=True).click()
        page.get_by_role('button', name='按当前约定启动或续接研究', exact=True).click()
        project_id = page.evaluate("new URL(location.href).searchParams.get('project')")
        endpoint = origin + '/api/factory/research/projects/' + project_id
        # Hold only the controlled model transport while a real UI revision is saved.
        assert child_entered.wait(15), 'Original child did not reach model transport'
        page.get_by_role('button', name='修改目标', exact=True).click()
        page.get_by_role('textbox', name=re.compile('^研究目标')).fill('Measure actual bytes with a revised interpretation')
        page.get_by_role('button', name='保存研究约定', exact=True).click()
        page.get_by_role('button', name='确认当前约定', exact=True).click()
        revised = context.request.get(endpoint).json()
        assert revised['currentGoalVersion'] == 4
        assert revised['goals'][-1]['agreement']['evidence']['fields'] == {'metrics': 'metrics', 'source': 'source', 'run_recipe': 'recipe'}
        assert revised['goals'][-1]['agreement']['budget'] == revised['goals'][-2]['agreement']['budget']
        hold_child.set()
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
        assert round_record['decision']['outcome'] == 'not_met', round_record
        assert round_record['decision']['evidenceIds'], round_record
        assert len(round_record['terminal']['runtime']) == 2, round_record
        assert all(task['status'] == 'completed' for task in round_record['terminal']['runtime']), round_record
        assert round_record['terminalRecordId'], records
        page.get_by_role('tab', name='成果', exact=True).click()
        page.get_by_role('button', name='生成成果清单', exact=True).click()
        expect(page.get_by_role('heading', name='已收集选中证据 · 尚未独立验证', exact=True)).to_be_visible()
        delivery_id = page.evaluate("new URL(location.href).searchParams.get('researchDelivery')")
        manifest = context.request.get(origin + '/api/factory/research/deliveries/' + delivery_id).json()
        assert manifest['missingEvidence'] == []
        assert 'UNSELECTED_PRIVATE_CANARY' not in json.dumps(manifest)
        page.screenshot(path=str(output / 'owner-delivery.png'), full_page=True)
        page.reload()
        expect(page.get_by_role('heading', name='研究成果清单', exact=True)).to_be_visible()
        page.get_by_role('button', name='返回平台', exact=True).click()
        page.go_back()
        expect(page.get_by_role('heading', name='研究成果清单', exact=True)).to_be_visible()
        page.locator('.rw-identity > button').click()
        page.get_by_role('button', name='退出登录', exact=True).click()
        expect(page.get_by_role('button', name=login_name, exact=True)).to_be_enabled()
        page.goto(origin + '/?tab=research&researchView=team')
        login('bob')
        page.get_by_role('button', name=delivery_id, exact=True).click()
        expect(page.get_by_role('heading', name='研究成果清单', exact=True)).to_be_visible()
        with page.expect_download() as downloaded:
            page.get_by_role('button', name='下载当前授权成果包', exact=True).click()
        raw = Path(downloaded.value.path()).read_bytes()
        assert b'UNSELECTED_PRIVATE_CANARY' not in raw
        with ZipFile(BytesIO(raw)) as bundle:
            actual_manifest = json.loads(bundle.read('manifest.json'))
            selected = [json.loads(bundle.read(name)) for name in bundle.namelist() if name.startswith('evidence/')]
        assert actual_manifest['missingEvidence'] == []
        values = {item['role']: item['value'] for item in selected}
        assert values['metrics'] == {'value': 3, 'target': 4} and values['source'] == PROGRAM
        assert values['run_recipe']['expected'] == values['metrics']
        assert context.request.get(endpoint).status == 404
        page.screenshot(path=str(output / 'team-delivery.png'), full_page=True)
        state['application_content'].set_visibility('alice', manifest['recordIds'][0], 'personal', 'browser-withdraw-delivery')
        page.get_by_role('button', name='核对成果与当前来源', exact=True).click()
        expect(page.get_by_role('alert')).to_be_visible()
        expect(page.get_by_role('button', name='下载当前授权成果包', exact=True)).to_have_count(0)
        assert context.request.get(origin + '/api/factory/research/deliveries/' + delivery_id + '/download').status == 404
        page.screenshot(path=str(output / 'withdrawn-delivery.png'), full_page=True)
        association_evidence = None
        if mode == 'mobile':
            state['application_content'].set_visibility('alice', manifest['recordIds'][0], 'team', 'browser-restore-terminal')
            page.locator('.rw-identity > button').click()
            page.get_by_role('button', name='退出登录', exact=True).click()
            expect(page.get_by_role('button', name=login_name, exact=True)).to_be_enabled()
            page.goto(origin + '/?tab=research&researchView=team')
            login('alice')
            until = time.monotonic() + 30
            associated = []
            while time.monotonic() < until:
                associated = context.request.get(origin + '/api/factory/research/associations').json()['items']
                if associated: break
                page.wait_for_timeout(100)
            assert associated, 'No real event-driven association was completed'
            association = associated[0]
            page.get_by_role('button', name='刷新相关研究关联', exact=True).click()
            page.get_by_role('button', name=association['id'], exact=True).click()
            expect(page.get_by_text('Measurements have related conditions; this is controlled agent analysis.', exact=True)).to_be_visible()
            page.get_by_role('button', name=material['peerSourceId'], exact=True).click()
            expect(page.get_by_role('heading', name='原研究依据 · 尚未独立验证', exact=True)).to_be_visible()
            page.screenshot(path=str(output / 'association-source.png'), full_page=True)
            page.reload()
            expect(page.get_by_text('Measurements have related conditions; this is controlled agent analysis.', exact=True)).to_be_visible()
            state['application_content'].set_visibility('bob', material['peerSourceId'], 'personal', 'browser-withdraw-peer-source')
            page.get_by_role('button', name='核对关联与当前来源', exact=True).click()
            expect(page.get_by_role('alert')).to_be_visible()
            expect(page.get_by_text('Measurements have related conditions; this is controlled agent analysis.', exact=True)).to_have_count(0)
            page.goto(origin + '/?tab=research&project=' + project_id)
            expect(page.get_by_text('来源不可用，目标、分析及派生成果已隐藏。', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='修改目标', exact=True)).to_have_count(0)
            expect(page.get_by_role('heading', name='实验来源不可用', exact=True)).to_be_visible()
            hidden = context.request.get(endpoint).json()
            assert hidden['sourceUnavailable'] and 'agreement' not in hidden['goals'][0]
            assert context.request.get(origin + '/api/factory/research/deliveries/' + delivery_id).status == 404
            page.screenshot(path=str(output / 'protected-project.png'), full_page=True)
            association_evidence = {'associationId': association['id'], 'peerSourceId': material['peerSourceId'], 'nativeAssociationCalls': len(association_calls), 'projectSourceUnavailable': True, 'assistantConfigurationVia': 'real backend HTTP fixture; no browser form claim', 'priorEvidenceVia': 'actual content service fixture; actual research publication triggers native association'}
        assert not errors and not console_errors, (errors, console_errors)
        return {'associations': association_evidence, 'projectId': project_id, 'deliveryId': delivery_id, 'goalVersion': revised['currentGoalVersion'],
            'originalRound': round_record, 'selectedRoles': sorted(values), 'missingEvidence': manifest['missingEvidence'],
            'downloadedBytes': len(raw), 'pageErrors': errors, 'consoleErrors': console_errors,
            'expectedUnauthorized': expected_unauthorized, 'apiResponses': api_responses,
            'privateProjectDenied': True, 'withdrawnDownloadStatus': 404, 'realProviderOrGPU': False,
            'modelAndToolConfiguredVia': 'real core fixture prerequisite; selection/publication/evidence/goal/delivery via browser'}
    except BaseException:
        hold_child.set()
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
        idp_socket = listener(); stack.callback(idp_socket.close)
        identity = BrowserIdentityFixture(issuer='https://127.0.0.1:' + str(idp_socket.getsockname()[1]), redirect_uri=origin + '/api/factory/auth/callback')
        settings = settings_for(database.url, scratch / 'workspace',
            jwt_key='synthetic-research-browser-signing-key-at-least-32bytes', web_directory=args.dist.resolve(),
            owner_model_transport_factory=lambda: httpx.MockTransport(model_wire), browser_oidc=identity.config())
        app = create_app(settings); state = factory_state(app); store = state['store']
        stack.callback(store.engine.dispose); stack.callback(store.native_db.db_engine.dispose)
        stack.callback(store.dispose_root_locks)
        state['browser_auth'].exchanger = BrowserCodeExchanger(identity.config(),
            transport=httpx.AsyncHTTPTransport(verify=ssl.create_default_context(cafile=str(certificate)), retries=0))
        for owner in ('alice', 'bob'):
            state['auth'].directory.upsert(owner, name='Synthetic ' + owner)
        serve(stack, identity.app, idp_socket, certificate, key)
        serve(stack, app, app_socket, certificate, key)
        script = scratch / 'experiment.py'; script.write_text(PROGRAM)
        (scratch / 'private.txt').write_text('UNSELECTED_PRIVATE_CANARY')
        personal = store.personal_tools
        operation = personal.operations.create('alice', {'transport': 'cli', 'toolName': 'research_fixture_compute', 'executable': sys.executable, 'arguments': [str(script), '--evidence'], 'workingDirectory': str(scratch), 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, 'browser-cli')
        resource = personal.configure_operation('alice', operation['operationRef']['id'], OperationAccountRequest(requestId='browser-cli-account', **{key: operation['operationRef'][key] for key in ('version', 'sha256')}))
        connection = state['connections'].bind('alice', resource['registrationRef'], 'browser-cli-binding')
        governance = state['material_governance']
        tool = governance.create_draft('alice', {'id': 'browser-selected-cli', 'kind': 'tool', 'name': 'Selected actual CLI',
            'content': 'research_fixture_compute', 'permissions': [operation['descriptor']['permission']],
            'runtimeBinding': {**operation['runtimeBinding'], 'config': {**operation['runtimeBinding']['config'], 'connectionName': 'experiment_cli'}}}, 'browser-tool-draft')
        governance.publish('alice', tool['id'], tool['version'], 'browser-tool-publish')
        material = {**{key: tool[key] for key in ('id', 'version', 'sha256')}, 'connectionRef': connection['ref']}
        child_entered.clear(); hold_child.clear(); association_calls.clear()
        if mode == 'mobile':
            with browser.new_context(ignore_https_errors=True) as setup_context:
                for owner in ('alice', 'bob'):
                    model = store.personal_models.configure(owner, {'provider': 'openai-compatible', 'baseURL': 'http://localhost:9/v1', 'model': 'synthetic-association'}, 'browser-association-model')
                    identity.subject = 'subject-' + owner
                    setup_page = setup_context.new_page()
                    setup_page.goto(origin + '/?tab=research')
                    setup_page.get_by_role('button', name='使用企业账号登录', exact=True).click()
                    expect(setup_page.locator('.rw-identity')).to_be_visible()
                    assert setup_context.request.get(origin + '/api/factory/session').json()['id'] == owner
                    def post_qa(path, body):
                        csrf = setup_context.request.get(origin + '/api/factory/auth/session').json()['csrfToken']
                        response = setup_context.request.post(origin + '/api/factory/research' + path, data=body, headers={'X-Factory-CSRF': csrf, 'Origin': origin})
                        assert response.status == 200, (path, response.status)
                        return response.json()
                    draft = post_qa('/setup/qa/drafts', {'requestId': 'qa-draft', 'name': 'Synthetic browser association fixture', 'modelConnectionRef': model['connectionRef'], 'budget': {'toolCalls': 4}})
                    published = post_qa('/setup/' + draft['id'] + '/publish', {'requestId': 'qa-publish'})
                    post_qa('/assistants', {'requestId': 'qa-identity'})
                    caps = {'rounds': 4, 'toolCalls': 16, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
                    post_qa('/assistants/me/configurations', {'requestId': 'qa-config', 'expectedRevision': 0, 'applicationRef': published['applicationRef'], 'connectionRefs': published['connectionRefs'], 'budget': {'caps': caps, 'perQuestionCaps': {**caps, 'rounds': 1, 'toolCalls': 4}, 'deadline': time.time() + 300}, 'associations': {'enabled': True, 'maxRecipients': 2}})
                    setup_context.clear_cookies()
                    setup_page.close()
            prior = state['application_content'].publish('bob', ContentPublication(source={'application': 'research', 'record': 'prior-measurement', 'revision': '1'}, content={'kind': 'research.experiment.start', 'hypothesis': 'Measure the specified actual bytes', 'conditions': {'comparison': 'Measure actual bytes once; previous measurement'}}, visibility='team'), 'browser-prior-source')
            material['peerSourceId'] = prior['id']
        viewport = {'width': 1487, 'height': 1058} if mode == 'desktop' else {'width': 390, 'height': 844}
        result = scenario(browser, origin, output, mode, identity, viewport, state, material)
        return {'mode': mode, 'database': database.name, 'businessAPIsMocked': False,
            'identity': 'local-synthetic-oidc', 'result': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--viewport', choices=('desktop', 'mobile', 'both'), default='both')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        try:
            reports = []
            for mode in (('desktop', 'mobile') if args.viewport == 'both' else (args.viewport,)):
                result = run_mode(browser, args, mode)
                (args.output / mode / 'evidence.json').write_text(json.dumps(result, indent=2))
                reports.append(f'{mode}/evidence.json')
            (args.output / 'evidence.json').write_text(json.dumps({'ok': True, 'reports': reports}, indent=2))
        finally:
            browser.close()


if __name__ == '__main__':
    main()
