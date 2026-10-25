"""Built Chromium public-operation UI smoke with synthetic API responses only.

Requires an existing dist build and installed Playwright/Chromium. No installs,
CLI/MCP execution, provider requests, or real native integration are performed.
Run: python platform/tests/browser/reusable_tool_operations_smoke.py --dist dist
"""
from __future__ import annotations

import argparse
import functools
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
from personal_tools_smoke import ROOT, QuietHandler, SyntheticAPI, CONFIGURED

STORAGE = 'factory-public-tool-request:alice'
RECIPE = {'transport': 'cli', 'toolName': 'public_fixture', 'description': 'Public synthetic recipe',
          'inputSchema': {'type': 'object', 'properties': {}}, 'executable': '/synthetic/public-tool',
          'arguments': ['--public-demo'], 'environment': {'PUBLIC_MODE': 'demo'},
          'readOnly': True, 'timeoutSeconds': 30, 'maxOutputBytes': 65536}
# Same public normalized fields as normalize_operation; no real executable is used.
CANONICAL = {**RECIPE, 'url': None, 'remoteToolName': None, 'workingDirectory': None,
             'argumentOptions': {}, 'stdinJson': True, 'credentialEnvironmentVariable': None,
             'outputFormat': 'json', 'credentialProviderId': 'member-cli',
             'credentialDestination': RECIPE['executable'], 'permission': 'tool:invoke',
             'capabilities': ['tool:invoke']}
SHA = hashlib.sha256(json.dumps(CANONICAL, sort_keys=True, separators=(',', ':'),
                                ensure_ascii=False).encode()).hexdigest()
PIN = {'id': 'public-fixture-operation', 'version': 1, 'sha256': SHA}
DESCRIPTOR = {key: CANONICAL[key] for key in ('toolName', 'description', 'inputSchema', 'transport',
              'credentialProviderId', 'credentialDestination', 'permission', 'capabilities',
              'readOnly', 'timeoutSeconds', 'maxOutputBytes')}
DESCRIPTOR.update(adapterId='operation-fixture-adapter', revision='1')
RUNTIME = {'adapterId': DESCRIPTOR['adapterId'], 'revision': '1', 'config': {'operationSha256': SHA}}
OPERATION = {'operationRef': PIN, 'ownerId': 'alice', 'configuration': CANONICAL,
             'descriptor': DESCRIPTOR, 'runtimeBinding': RUNTIME}
CREDENTIAL = {'credentialRef': 'alice-operation-key', 'credentialRevision': 'alice-key-v1',
              'providerId': 'member-cli', 'destination': RECIPE['executable'], 'status': 'active'}
ACCOUNT = {**CONFIGURED, 'registrationRef': 'alice-independent-account',
           'adapterId': DESCRIPTOR['adapterId'], 'descriptorRevision': '1',
           'toolName': RECIPE['toolName'], 'capabilities': ['tool:invoke'],
           'credentialRef': CREDENTIAL['credentialRef'], 'credentialRevision': CREDENTIAL['credentialRevision'],
           'operationRef': PIN, 'runtimeBinding': RUNTIME}


class OperationAPI(SyntheticAPI):
    def __init__(self, base):
        super().__init__(base, 'operations')
        self.operations = []
        self.credentials = [CREDENTIAL]
        self.operation_body = self.account_body = None
        self.account_creations = 0

    def values(self):
        return {**super().values(), '/personal-tools/operations': self.operations,
                '/personal-credentials/capabilities': {'enabled': True, 'providerIds': ['member-cli']},
                '/user-connections/registrations': []}

    def intercept(self, route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path.removeprefix('/api/factory')
        if f'{url.scheme}://{url.netloc}' != self.base or request.method != 'POST' or path not in {
            '/personal-tools/operations', '/personal-tools/operations/' + PIN['id'] + '/accounts',
        }:
            # Inherited interceptor rejects every unconfigured mutation and all external traffic.
            return super().intercept(route)
        body = request.post_data_json
        self.requests.append({'method': request.method, 'path': path, 'body': body,
                              'expectedOwner': request.headers.get('x-factory-expected-owner')})
        if request.headers.get('x-factory-expected-owner') != 'alice' or not body.get('requestId'):
            return self.reject(route, 'Missing owner scope or request identity')
        if path == '/personal-tools/operations':
            if self.operation_body is not None or body != {'configuration': RECIPE, 'requestId': body['requestId']}:
                return self.reject(route, 'Unexpected public operation mutation')
            self.operation_body = body
            self.operations = [OPERATION]
            return route.fulfill(status=201, json=OPERATION)
        expected = {'version': 1, 'sha256': SHA, 'credentialRef': CREDENTIAL['credentialRef'],
                    'credentialRevision': CREDENTIAL['credentialRevision'], 'requestId': body['requestId']}
        if body != expected or self.account_body is not None and body != self.account_body:
            return self.reject(route, 'Account retry changed the original operation or credentials')
        if self.account_body is None:
            self.account_body = body
            self.configured = ACCOUNT
            self.account_creations += 1
            self.aborted.append(request.url)
            return route.abort('failed')
        return route.fulfill(status=200, json=ACCOUNT)


def scenario(browser, base, output):
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
    api = OperationAPI(base)
    errors, console_errors = [], []
    context.route('**/*', api.intercept)

    def websocket(socket):
        api.violations.append('Unexpected WebSocket: ' + socket.url)
        socket.close()
    context.route_web_socket('**/*', websocket)
    page = context.new_page()
    page.set_default_timeout(10000)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: console_errors.append({'text': message.text, 'location': message.location})
            if message.type == 'error' else None)
    try:
        page.goto(base + '/', wait_until='networkidle')
        page.get_by_role('button', name='资源', exact=True).click()
        page.get_by_role('button', name='管理服务器与连接', exact=True).click()
        page.get_by_role('button', name='可复用工具操作', exact=True).click()
        panel = page.get_by_role('region', name='可复用工具操作', exact=True)
        expect(panel.get_by_label('公开操作配方', exact=True)).not_to_have_value(json.dumps(RECIPE))
        panel.get_by_label('公开操作配方', exact=True).fill(json.dumps(RECIPE))
        preview = panel.get_by_label('即将公开的完整配方', exact=True)
        expect(preview).to_contain_text('--public-demo')
        expect(preview).to_contain_text('PUBLIC_MODE')
        expect(panel.get_by_role('button', name='保存公开操作版本', exact=True)).to_be_disabled()
        assert not [r for r in api.requests if r['method'] != 'GET']
        page.screenshot(path=str(output / 'public-preview.png'), full_page=True)
        panel.get_by_label('确认公开操作配方', exact=True).check()
        panel.get_by_role('button', name='保存公开操作版本', exact=True).click()
        expect(panel.get_by_role('status')).to_contain_text('尚未创建账号、发布工具材料或执行工具')
        selection = panel.get_by_label('选择公开工具操作', exact=True)
        selection.select_option(PIN['id'] + ':1:' + SHA)
        expect(panel.get_by_label('所选操作公开配方')).to_contain_text('credentialDestination')
        panel.get_by_label('公开操作本人凭据', exact=True).select_option(CREDENTIAL['credentialRef'])
        panel.get_by_role('button', name='创建本人的独立账号', exact=True).click()
        expect(panel.get_by_role('alert')).to_contain_text('请求尚未确认')
        expect(panel.get_by_label('公开操作本人凭据', exact=True)).to_be_disabled()
        pending = json.loads(page.evaluate('(key) => localStorage.getItem(key)', STORAGE))
        assert pending['operationId'] == PIN['id'] and pending['input'] == api.account_body
        writes_before = [r for r in api.requests if r['method'] == 'POST']
        page.reload(wait_until='networkidle')
        expect(panel.get_by_label('待确认原请求')).to_contain_text(CREDENTIAL['credentialRef'])
        assert [r for r in api.requests if r['method'] == 'POST'] == writes_before
        panel.get_by_role('button', name='核对原操作请求', exact=True).click()
        expect(panel.get_by_role('status').filter(has_text='本人的独立账号')).to_be_visible()
        assert page.evaluate('(key) => localStorage.getItem(key)', STORAGE) is None
        writes = [r for r in api.requests if r['method'] == 'POST']
        assert [r['path'] for r in writes] == ['/personal-tools/operations'] + [
            '/personal-tools/operations/' + PIN['id'] + '/accounts'] * 2
        assert writes[1]['body'] == writes[2]['body']
        assert writes[0]['body']['requestId'] != writes[1]['body']['requestId']
        assert api.account_creations == 1 and not api.violations and not errors
        expected_errors = [item for item in console_errors if item['location'].get('url') in api.aborted
                           and item['text'] == 'Failed to load resource: net::ERR_FAILED']
        assert len(expected_errors) == len(console_errors) and len(expected_errors) <= len(api.aborted)
        page.screenshot(path=str(output / 'independent-account-recovered.png'), full_page=True)
        return {'result': 'passed', 'apiRequests': api.requests, 'accountCreations': api.account_creations,
                'lostAcknowledgements': len(api.aborted), 'externalRequests': 0, 'unexpectedMutations': 0,
                'pageErrors': errors, 'unexpectedConsoleErrors': [], 'syntheticAPI': True,
                'realNativeIntegrationVerified': False}
    except Exception:
        page.screenshot(path=str(output / 'failure.png'), full_page=True)
        (output / 'failure.json').write_text(json.dumps({'requests': api.requests, 'violations': api.violations,
            'pageErrors': errors, 'consoleErrors': console_errors, 'body': page.locator('body').inner_text()},
            ensure_ascii=False, indent=2))
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist')
    parser.add_argument('--browser', help='Existing Chromium executable; defaults to installed Playwright browser')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not (args.dist / 'index.html').is_file():
        parser.error('Requires already built dist/index.html')
    output = args.output or Path(tempfile.mkdtemp(prefix='af-operation-browser-'))
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(args.dist)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            try:
                result = scenario(browser, f'http://127.0.0.1:{server.server_port}', output)
                (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
                print(json.dumps({'scenariosPassed': 1, 'output': str(output), 'realNativeIntegrationVerified': False}))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
