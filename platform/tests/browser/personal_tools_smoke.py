"""Real Chromium personal-tool UI regression with wholly synthetic API state.

Run npm run build, then python platform/tests/browser/personal_tools_smoke.py.
Requires existing Playwright/Chromium; never installs dependencies, starts tools,
contacts a provider, or serves an actual Factory API. Lost acknowledgements are
injected only after the synthetic backend has retained the original request.
"""
from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
STORAGE = 'factory-personal-tool-command:alice'
DESCRIPTOR = {
    'adapterId': 'fixture-cli-v1', 'revision': 'descriptor-v1', 'toolName': 'fixture_lookup',
    'description': 'Synthetic installed tool; no command is executed.',
    'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    'transport': 'cli', 'credentialProviderId': 'fixture-tool-token',
    'credentialDestination': 'https://fixture.example.org', 'capabilities': ['tool:lookup'],
    'permission': 'tool:lookup', 'readOnly': True,
}
CREDENTIAL = {'credentialRef': 'credential-fixture', 'credentialRevision': 'credential-r1',
    'providerId': DESCRIPTOR['credentialProviderId'], 'destination': DESCRIPTOR['credentialDestination'],
    'status': 'active'}
CONFIGURED = {'ownerId': 'alice', 'registrationRef': 'owner-tool-fixture',
    'adapterId': DESCRIPTOR['adapterId'], 'revision': 'owner-config-r1',
    'descriptorRevision': DESCRIPTOR['revision'], 'kind': 'tool', 'toolName': DESCRIPTOR['toolName'],
    'transport': DESCRIPTOR['transport'], 'credentialRef': CREDENTIAL['credentialRef'],
    'credentialRevision': CREDENTIAL['credentialRevision'], 'status': 'configured', 'available': True,
    'capabilities': DESCRIPTOR['capabilities'], 'createdAt': '2026-10-13T00:00:00Z', 'expiresAt': None,
    'allowedActions': ['inspect', 'bind', 'revoke']}
BOUND = {'ref': 'bound-tool-fixture', 'ownerId': 'alice', 'version': 1, 'fingerprint': 'a' * 64,
    'kind': 'tool', 'revision': CONFIGURED['revision'], 'capabilities': DESCRIPTOR['capabilities'],
    'taskId': None, 'registrationRef': CONFIGURED['registrationRef'], 'expiresAt': None,
    'createdAt': CONFIGURED['createdAt'], 'revokedAt': None, 'status': 'active', 'available': True,
    'allowedActions': ['inspect', 'revoke']}


class SyntheticAPI:
    def __init__(self, base, mode):
        self.base, self.mode, self.owner = base, mode, 'alice'
        self.configured = self.bound = None
        self.requests, self.violations, self.aborted = [], [], []
        self.commands = {}

    def values(self):
        own = self.owner == 'alice'
        return {
            '/auth/config': {'enabled': False, 'loginPath': '/api/factory/auth/login',
                             'logoutPath': '/api/factory/auth/logout'},
            '/session': {'id': self.owner, 'name': 'Synthetic ' + self.owner.title(), 'role': 'user'},
            '/status': {'mode': 'demo', 'activeWorkers': 0, 'queuedJobs': 0, 'maxWorkers': 1},
            '/materials': [], '/jobs': [], '/execution-targets': [], '/applications': [],
            '/commands': {'items': [], 'nextCursor': None},
            '/personal-agent/capabilities': {
                'executionContract': 'personal-external-v1', 'nativeQueue': True,
                'ownerSubmit': '/api/factory/personal-agent/commands/submit',
                'modelConfiguration': 'remote-configured-model', 'factoryBYOKForwarded': False,
            },
            '/personal-agent/sessions': [],
            '/compositions/proposals': {'schema': 1, 'ownerId': self.owner, 'items': [],
                                       'nextCursor': None, 'snapshot': False},
            '/personal-tools/descriptors': [DESCRIPTOR],
            '/personal-tools': [self.configured] if own and self.configured else [],
            '/user-connections': [self.bound] if own and self.bound else [],
            '/user-connections/registrations': [{
                'registrationRef': CONFIGURED['registrationRef'], 'kind': 'tool',
                'revision': CONFIGURED['revision'], 'capabilities': DESCRIPTOR['capabilities'],
                'expiresAt': None, 'available': self.configured['available'],
                'status': 'available' if self.configured['available'] else 'unavailable',
                'allowedActions': ['bind'] if self.configured['available'] else [],
            }] if own and self.configured else [],
            '/personal-credentials': [CREDENTIAL] if own else [],
            '/personal-credentials/capabilities': {'enabled': True,
                                                 'providerIds': [DESCRIPTOR['credentialProviderId']]},
            '/personal-remotes': [], '/personal-remotes/providers': [],
            '/personal-models': [], '/personal-ssh': [], '/personal-ssh/capabilities': {'enabled': False},
            '/resources/leases': {'leases': [], 'nextCursor': None},
            '/application-environments': [], '/application-environments/servers': [],
            '/application-environments/capabilities': {'locations': [], 'applications': []},
        }

    def reject(self, route, message):
        self.violations.append(message)
        route.abort()

    def intercept(self, route):
        request = route.request
        url = urlsplit(request.url)
        if f'{url.scheme}://{url.netloc}' != self.base:
            self.reject(route, 'External request: ' + request.url)
            return
        if not url.path.startswith('/api/'):
            if request.method == 'GET' and (url.path == '/' or url.path.startswith('/assets/')):
                route.continue_()
            else:
                self.reject(route, 'Unexpected static request: ' + request.url)
            return
        path = url.path.removeprefix('/api/factory')
        row = {'method': request.method, 'path': path, 'expectedOwner': request.headers.get('x-factory-expected-owner')}
        self.requests.append(row)
        if request.method == 'GET':
            if path in self.commands:
                receipt = self.commands[path]
                if self.mode == 'revoked-recovery' and receipt['action'] == 'tool.configure':
                    self.configured = {**CONFIGURED, 'status': 'revoked', 'available': False,
                                       'allowedActions': ['inspect']}
                    receipt = {**receipt, 'tool': self.configured}
                route.fulfill(status=200, json=receipt)
            elif path in self.values():
                route.fulfill(status=200, json=self.values()[path])
            else:
                self.reject(route, 'Unconfigured API read: ' + path)
            return
        body = request.post_data_json
        row['body'] = body
        previous = [r for r in self.requests if r['method'] == 'POST' and r['path'] == path]
        if request.method != 'POST' or self.owner != 'alice' or row['expectedOwner'] != 'alice' or len(previous) != 1:
            self.reject(route, 'Unexpected owner, method, or repeated dispatch: ' + path)
            return
        request_id = body.get('requestId') if isinstance(body, dict) else None
        if not isinstance(request_id, str) or not request_id:
            self.reject(route, 'Missing original request ID')
            return
        if path == '/personal-tools' and body == {
            'adapterId': DESCRIPTOR['adapterId'], 'credentialRef': CREDENTIAL['credentialRef'],
            'credentialRevision': CREDENTIAL['credentialRevision'], 'requestId': request_id,
        }:
            self.configured = dict(CONFIGURED)
            self.commands['/personal-tools/requests/' + request_id] = {
                'requestId': request_id, 'action': 'tool.configure', 'tool': self.configured}
            result = self.configured
            lose = self.mode in {'configure-loss', 'revoked-recovery'}
        elif path == '/user-connections' and self.configured and body == {
            'registrationRef': CONFIGURED['registrationRef'], 'requestId': request_id,
            'capabilities': DESCRIPTOR['capabilities'],
        }:
            self.bound = dict(BOUND)
            self.commands['/user-connections/requests/' + request_id] = {
                'requestId': request_id, 'action': 'bind', 'connection': self.bound}
            result = self.bound
            lose = self.mode == 'bind-loss'
        else:
            self.reject(route, 'Unconfigured synthetic mutation: ' + path)
            return
        if lose:
            self.aborted.append(request.url)
            route.abort('failed')
        else:
            route.fulfill(status=201, json=result)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def scenario(browser, base, output, name, mode, viewport):
    context = browser.new_context(viewport=viewport, service_workers='block')
    api = SyntheticAPI(base, mode)
    errors, console_errors, widths = [], [], {}
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

    def capture(stage):
        width = page.evaluate('({viewport: innerWidth, document: document.documentElement.scrollWidth})')
        assert width['document'] <= width['viewport'] + 1, f'{stage} horizontal overflow: {width}'
        widths[stage] = width
        page.screenshot(path=str(output / f'{name}-{stage}.png'), full_page=True)

    try:
        page.goto(base + '/', wait_until='networkidle')
        page.get_by_role('button', name='资源', exact=True).click()
        expect(page.get_by_role('heading', name='我的资源', exact=True)).to_be_visible()
        page.get_by_role('button', name='管理服务器与连接', exact=True).click()
        expect(page.get_by_role('heading', name='我的工具连接', exact=True)).to_be_visible()
        panel = page.get_by_role('region', name='我的工具连接', exact=True)
        panel.get_by_label('个人工具', exact=True).select_option(DESCRIPTOR['adapterId'])
        panel.get_by_label('工具已有凭据', exact=True).select_option(CREDENTIAL['credentialRef'])
        capture('selected')
        if mode == 'owner-change':
            # Another browser tab changed the authenticated account. A fresh
            # session read must stop submission before any credential/tool POST.
            api.owner = 'bob'
        panel.get_by_role('button', name='保存并绑定工具', exact=True).click()
        if mode == 'owner-change':
            expect(panel.get_by_role('alert')).to_contain_text('当前登录账户已改变')
            expect(panel.get_by_label('工具已有凭据', exact=True)).to_have_count(0)
        elif mode in {'configure-loss', 'bind-loss', 'revoked-recovery'}:
            expect(panel.get_by_role('alert')).to_contain_text('操作尚未确认')
            pending = json.loads(page.evaluate('(key) => localStorage.getItem(key)', STORAGE))
            expected_stage = 'bind' if mode == 'bind-loss' else 'configure'
            assert pending['stage'] == expected_stage and pending['dispatched'] is True
            writes_before = [r for r in api.requests if r['method'] == 'POST']
            page.reload(wait_until='networkidle')
            assert [r for r in api.requests if r['method'] == 'POST'] == writes_before
            expect(panel.get_by_role('button', name='保存并绑定工具', exact=True)).to_be_disabled()
            panel.get_by_role('button', name='核对原工具请求', exact=True).click()
            expected_read = ('/user-connections/requests/' + pending['bindRequestId'] if mode == 'bind-loss'
                             else '/personal-tools/requests/' + pending['requestId'])
            if mode == 'revoked-recovery':
                expect(panel.get_by_role('status')).to_contain_text('没有继续绑定')
                expect(panel.get_by_role('button', name='工具已撤销', exact=True)).to_be_disabled()
            else:
                expect(panel.get_by_role('status')).to_contain_text('工具已保存并绑定')
            assert len([r for r in api.requests if r['method'] == 'GET' and r['path'] == expected_read]) == 1
        else:
            expect(panel.get_by_role('status')).to_contain_text('工具已保存并绑定')
            page.reload(wait_until='networkidle')
            expect(panel.get_by_role('heading', name='fixture_lookup · CLI', exact=True)).to_be_visible()
        capture('result')
        assert page.evaluate('(key) => localStorage.getItem(key)', STORAGE) is None
        writes = [r for r in api.requests if r['method'] == 'POST']
        expected_writes = [] if mode == 'owner-change' else ['/personal-tools'] + (
            [] if mode == 'revoked-recovery' else ['/user-connections'])
        assert [r['path'] for r in writes] == expected_writes, writes
        assert len({r['body']['requestId'] for r in writes}) == len(writes), writes
        assert not api.violations, api.violations
        expected_console = [e for e in console_errors if e['location'].get('url') in api.aborted
                            and e['text'] == 'Failed to load resource: net::ERR_FAILED']
        assert len(expected_console) == len(console_errors) <= len(api.aborted), console_errors
        assert not errors, errors
        return {'scenario': name, 'result': 'passed', 'viewport': viewport, 'horizontalWidths': widths,
                'apiRequests': api.requests, 'injectedLostAcknowledgements': len(api.aborted),
                'expectedNetworkConsoleErrors': expected_console, 'unexpectedConsoleErrors': [],
                'pageErrors': errors, 'externalRequests': 0, 'toolInvocations': 0, 'modelCalls': 0}
    except Exception:
        page.screenshot(path=str(output / f'{name}-failure.png'), full_page=True)
        (output / f'{name}-failure.json').write_text(json.dumps({
            'violations': api.violations, 'pageErrors': errors, 'consoleErrors': console_errors,
            'requests': api.requests, 'body': page.locator('body').inner_text()}, ensure_ascii=False, indent=2))
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist')
    parser.add_argument('--browser', default=shutil.which('chromium') or shutil.which('google-chrome'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not (args.dist / 'index.html').is_file() or not args.browser:
        parser.error('Requires existing built dist and Chromium; this script does not install either')
    output = args.output or Path(tempfile.mkdtemp(prefix='af-personal-tool-browser-'))
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(args.dist)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            try:
                cases = [('desktop-configured', 'configured', 1440), ('mobile-configured', 'configured', 390),
                         ('desktop-configure-loss', 'configure-loss', 1440), ('mobile-bind-loss', 'bind-loss', 390),
                         ('desktop-revoked-recovery', 'revoked-recovery', 1440), ('mobile-owner-change', 'owner-change', 390)]
                results = [scenario(browser, f'http://127.0.0.1:{server.server_port}', output, name, mode,
                                    {'width': width, 'height': 1000 if width > 400 else 844})
                           for name, mode, width in cases]
                (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
                print(json.dumps({'scenariosPassed': len(results), 'output': str(output),
                                  'realCLIOrMCPIntegrationVerified': False}))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
