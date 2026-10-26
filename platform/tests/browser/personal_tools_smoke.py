"""Real Chromium personal-tool UI regression with wholly synthetic API state.

Run npm run build, then python platform/tests/browser/personal_tools_smoke.py.
Use --desktop-only to exercise every flow without launching narrow viewports;
--scenario can select individual flows while retaining the default full suite.
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
import tempfile
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
STORAGE = 'factory-personal-tool-command:alice'
CSRF = 'synthetic-personal-tools-browser-csrf'
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
REPLACEMENT_CREDENTIAL = {**CREDENTIAL, 'credentialRef': 'credential-replacement',
                          'credentialRevision': 'credential-r2'}
CONFIGURED = {'ownerId': 'alice', 'registrationRef': 'owner-tool-fixture',
    'adapterId': DESCRIPTOR['adapterId'], 'revision': 'owner-config-r1',
    'descriptorRevision': DESCRIPTOR['revision'], 'kind': 'tool', 'toolName': DESCRIPTOR['toolName'],
    'transport': DESCRIPTOR['transport'], 'credentialRef': CREDENTIAL['credentialRef'],
    'credentialRevision': CREDENTIAL['credentialRevision'], 'status': 'configured', 'available': True,
    'capabilities': DESCRIPTOR['capabilities'], 'createdAt': '2026-10-13T00:00:00Z', 'expiresAt': None,
    'visibility': 'personal', 'isOwner': True,
    'allowedActions': ['inspect', 'revoke', 'sharing', 'bind'],
    'runtimeBinding': {'adapterId': DESCRIPTOR['adapterId'], 'revision': DESCRIPTOR['revision'], 'config': {}}}
BOUND = {'ref': 'bound-tool-fixture', 'ownerId': 'alice', 'version': 1, 'fingerprint': 'a' * 64,
    'kind': 'tool', 'revision': CONFIGURED['revision'], 'capabilities': DESCRIPTOR['capabilities'],
    'taskId': None, 'registrationRef': CONFIGURED['registrationRef'], 'expiresAt': None,
    'createdAt': CONFIGURED['createdAt'], 'revokedAt': None, 'status': 'active', 'available': True,
    'allowedActions': ['inspect', 'revoke']}


class SyntheticAPI:
    def __init__(self, base, mode):
        self.base, self.mode, self.owner = base, mode, 'alice'
        self.configured = self.bound = None
        self.descriptors, self.credentials = [DESCRIPTOR], [CREDENTIAL]
        self.requests, self.violations, self.aborted, self.rejected = [], [], [], []
        self.commands = {}

    def values(self):
        own = self.owner == 'alice'
        return {
            '/auth/config': {'enabled': True, 'oidcEnabled': True, 'localLoginEnabled': False, 'loginPath': '/api/factory/auth/login',
                             'logoutPath': '/api/factory/auth/logout'},
            '/auth/session': {'authenticated': True, 'csrfToken': CSRF},
            '/session': {'id': self.owner, 'name': 'Synthetic ' + self.owner.title(), 'role': 'user'},
            '/status': {'mode': 'production', 'activeWorkers': 0, 'queuedJobs': 0, 'maxWorkers': 1},
            '/materials': [], '/jobs': {'items': [], 'nextCursor': None}, '/execution-targets': [], '/applications': [],
            '/commands': {'items': [], 'nextCursor': None},
            '/personal-agent/capabilities': {
                'executionContract': 'personal-external-v1', 'nativeQueue': True,
                'ownerSubmit': '/api/factory/personal-agent/commands/submit',
                'modelConfiguration': 'remote-configured-model', 'factoryBYOKForwarded': False,
            },
            '/personal-agent/sessions': [],
            '/compositions/proposals': {'schema': 1, 'ownerId': self.owner, 'items': [],
                                       'nextCursor': None, 'snapshot': False},
            '/personal-tools/descriptors': self.descriptors,
            '/personal-tools/operations': [],
            '/personal-tools': [self.configured] if own and self.configured else [],
            '/user-connections': [self.bound] if own and self.bound else [],
            '/user-connections/registrations': [{
                'registrationRef': CONFIGURED['registrationRef'], 'kind': 'tool',
                'revision': CONFIGURED['revision'], 'capabilities': DESCRIPTOR['capabilities'],
                'expiresAt': None, 'available': self.configured['available'],
                'status': 'available' if self.configured['available'] else 'unavailable',
                'allowedActions': ['inspect', 'bind'] if self.configured['available'] else ['inspect'],
            }] if own and self.configured else [],
            '/personal-credentials': self.credentials if own else [],
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
                if self.mode == 'configure-loss' and len([
                    r for r in self.requests if r['method'] == 'GET' and r['path'] == path
                ]) == 1:
                    # A missing receipt is still an uncertain sent command.
                    # Match the core HTTPException envelope, not a mock-only
                    # exception object that bypasses the actual API parser.
                    code = 'PERSONAL_TOOL_REQUEST_NOT_FOUND'
                    row.update(responseStatus=404, responseCode='REQUEST_REJECTED')
                    self.rejected.append({'url': request.url, 'status': 404,
                                          'code': 'REQUEST_REJECTED', 'message': code})
                    route.fulfill(status=404, json={'message': code, 'code': 'REQUEST_REJECTED'})
                    return
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
        if request.headers.get('x-factory-csrf') != CSRF:
            self.reject(route, 'Missing configured browser-session CSRF header')
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
            if self.mode == 'descriptor-withdrawn':
                # The configure response was valid. Before the unsent bind's
                # descriptor check, the operator withdraws the installed tool.
                self.descriptors = []
                self.configured = {**CONFIGURED, 'status': 'unavailable', 'available': False,
                                   'allowedActions': ['inspect', 'revoke', 'sharing']}
        elif path == '/user-connections' and self.configured and body == {
            'registrationRef': CONFIGURED['registrationRef'], 'requestId': request_id,
            'capabilities': DESCRIPTOR['capabilities'],
        }:
            if self.mode == 'bind-credential-rejected':
                # This is a definitive rejection of this POST, not a missing
                # receipt or an ambiguous 409. No connection was created.
                self.configured = {**CONFIGURED, 'status': 'credential_unavailable', 'available': False,
                                   'allowedActions': ['inspect', 'revoke', 'sharing']}
                self.credentials = [{**CREDENTIAL, 'status': 'revoked'}, REPLACEMENT_CREDENTIAL]
                code = 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE'
                row.update(responseStatus=409, responseCode=code)
                self.rejected.append({'url': request.url, 'status': 409,
                                      'code': code, 'message': code})
                route.fulfill(status=409, json={'message': code, 'code': code})
                return
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
        elif mode == 'descriptor-withdrawn':
            expect(panel.get_by_role('button', name='结束未发送步骤', exact=True)).to_be_enabled()
            pending = json.loads(page.evaluate('(key) => localStorage.getItem(key)', STORAGE))
            original = next(r for r in api.requests if r['method'] == 'POST' and r['path'] == '/personal-tools')
            assert pending['requestId'] == original['body']['requestId']
            assert pending['stage'] == 'bind' and pending['dispatched'] is False
            assert pending['registrationRef'] == CONFIGURED['registrationRef']
            capture('unsent-bind')
            panel.get_by_role('button', name='结束未发送步骤', exact=True).click()
            expect(panel.get_by_role('status')).to_contain_text('已结束未发送步骤')
            expect(panel.get_by_role('button', name='核对原工具请求', exact=True)).to_have_count(0)
            expect(panel.get_by_role('heading', name='fixture_lookup · CLI', exact=True)).to_be_visible()
            expect(panel.get_by_role('button', name='撤销工具配置', exact=True)).to_be_enabled()
            assert api.configured['registrationRef'] == CONFIGURED['registrationRef']
            assert api.bound is None
            # A later installed revision can be chosen explicitly. Ending an
            # unsent step must not leave this new form or old revoke disabled.
            api.descriptors = [{**DESCRIPTOR, 'revision': 'descriptor-v2'}]
            panel.get_by_role('button', name='重新读取工具连接', exact=True).click()
            panel.get_by_label('个人工具', exact=True).select_option(DESCRIPTOR['adapterId'])
            panel.get_by_label('工具已有凭据', exact=True).select_option(CREDENTIAL['credentialRef'])
            expect(panel.get_by_role('button', name='保存并绑定工具', exact=True)).to_be_enabled()
        elif mode == 'bind-credential-rejected':
            expect(panel.get_by_role('status')).to_contain_text('绑定请求已被明确拒绝')
            expect(panel.get_by_role('heading', name='fixture_lookup · CLI', exact=True)).to_be_visible()
            expect(panel.get_by_role('button', name='撤销工具配置', exact=True)).to_be_enabled()
            expect(panel.get_by_role('button', name='核对原工具请求', exact=True)).to_have_count(0)
            assert api.bound is None
            assert api.configured['registrationRef'] == CONFIGURED['registrationRef']
            assert api.configured['credentialRef'] == CREDENTIAL['credentialRef']
            panel.get_by_label('个人工具', exact=True).select_option(DESCRIPTOR['adapterId'])
            panel.get_by_label('工具已有凭据', exact=True).select_option(REPLACEMENT_CREDENTIAL['credentialRef'])
            expect(panel.get_by_label('工具已有凭据', exact=True)).to_have_value(REPLACEMENT_CREDENTIAL['credentialRef'])
            expect(panel.get_by_role('button', name='保存并绑定工具', exact=True)).to_be_enabled()
        elif mode in {'configure-loss', 'bind-loss', 'revoked-recovery'}:
            expect(panel.get_by_role('alert')).to_contain_text('操作尚未确认')
            pending = json.loads(page.evaluate('(key) => localStorage.getItem(key)', STORAGE))
            expected_stage = 'bind' if mode == 'bind-loss' else 'configure'
            assert pending['stage'] == expected_stage and pending['dispatched'] is True
            writes_before = [r for r in api.requests if r['method'] == 'POST']
            page.reload(wait_until='networkidle')
            assert [r for r in api.requests if r['method'] == 'POST'] == writes_before
            expect(panel.get_by_role('button', name='保存并绑定工具', exact=True)).to_be_disabled()
            expect(panel.get_by_role('button', name='结束未发送步骤', exact=True)).to_have_count(0)
            panel.get_by_role('button', name='核对原工具请求', exact=True).click()
            expected_read = ('/user-connections/requests/' + pending['bindRequestId'] if mode == 'bind-loss'
                             else '/personal-tools/requests/' + pending['requestId'])
            if mode == 'configure-loss':
                expect(panel.get_by_role('alert')).to_contain_text('操作尚未确认')
                expect(panel.get_by_role('button', name='核对原工具请求', exact=True)).to_be_enabled()
                expect(panel.get_by_role('button', name='结束未发送步骤', exact=True)).to_have_count(0)
                expect(panel.get_by_role('button', name='保存并绑定工具', exact=True)).to_be_disabled()
                assert json.loads(page.evaluate('(key) => localStorage.getItem(key)', STORAGE)) == pending
                assert [r for r in api.requests if r['method'] == 'POST'] == writes_before
                capture('receipt-missing')
                panel.get_by_role('button', name='核对原工具请求', exact=True).click()
            if mode == 'revoked-recovery':
                expect(panel.get_by_role('status')).to_contain_text('没有继续绑定')
                expect(panel.get_by_role('button', name='工具已撤销', exact=True)).to_be_disabled()
            else:
                expect(panel.get_by_role('status')).to_contain_text('工具已保存并绑定')
            assert len([r for r in api.requests if r['method'] == 'GET' and r['path'] == expected_read]) == (
                2 if mode == 'configure-loss' else 1)
        else:
            expect(panel.get_by_role('status')).to_contain_text('工具已保存并绑定')
            page.reload(wait_until='networkidle')
            expect(panel.get_by_role('heading', name='fixture_lookup · CLI', exact=True)).to_be_visible()
        capture('result')
        assert page.evaluate('(key) => localStorage.getItem(key)', STORAGE) is None
        writes = [r for r in api.requests if r['method'] == 'POST']
        expected_writes = [] if mode == 'owner-change' else ['/personal-tools'] + (
            [] if mode in {'revoked-recovery', 'descriptor-withdrawn'} else ['/user-connections'])
        assert [r['path'] for r in writes] == expected_writes, writes
        assert len({r['body']['requestId'] for r in writes}) == len(writes), writes
        if mode in {'descriptor-withdrawn', 'bind-credential-rejected'}:
            original_receipt = api.commands['/personal-tools/requests/' + writes[0]['body']['requestId']]
            assert original_receipt['tool'] == CONFIGURED
            assert api.configured['registrationRef'] == original_receipt['tool']['registrationRef']
        assert not api.violations, api.violations
        expected_console = [e for e in console_errors if e['location'].get('url') in api.aborted
                            and e['text'] == 'Failed to load resource: net::ERR_FAILED']
        expected_rejections = [e for e in console_errors if any(
            e['location'].get('url') == rejected['url']
            and (rejected['status'], rejected['code'], rejected['message'], e['text']) in {
                (409, 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE', 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE',
                 'Failed to load resource: the server responded with a status of 409 (Conflict)'),
                (404, 'REQUEST_REJECTED', 'PERSONAL_TOOL_REQUEST_NOT_FOUND',
                 'Failed to load resource: the server responded with a status of 404 (Not Found)'),
            }
            for rejected in api.rejected)]
        assert len(expected_console) <= len(api.aborted), console_errors
        assert len(expected_rejections) <= len(api.rejected), console_errors
        assert len(expected_console) + len(expected_rejections) == len(console_errors), console_errors
        assert not errors, errors
        return {'scenario': name, 'result': 'passed', 'viewport': viewport, 'horizontalWidths': widths,
                'apiRequests': api.requests, 'injectedLostAcknowledgements': len(api.aborted),
                'expectedNetworkConsoleErrors': expected_console, 'rejectedResponses': api.rejected,
                'expectedRejectionConsoleErrors': expected_rejections, 'unexpectedConsoleErrors': [],
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
    cases = [('desktop-configured', 'configured', 1440), ('mobile-configured', 'configured', 390),
             ('desktop-configure-loss', 'configure-loss', 1440), ('mobile-bind-loss', 'bind-loss', 390),
             ('desktop-revoked-recovery', 'revoked-recovery', 1440), ('mobile-owner-change', 'owner-change', 390),
             ('desktop-descriptor-withdrawn', 'descriptor-withdrawn', 1440),
             ('desktop-bind-credential-rejected', 'bind-credential-rejected', 1440)]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist')
    parser.add_argument('--browser', help='Explicit Chromium executable; defaults to the locked Playwright browser')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--desktop-only', action='store_true',
                        help='Run each flow once at desktop width; preserve the default narrow coverage')
    parser.add_argument('--scenario', action='append', choices=sorted({mode for _, mode, _ in cases}),
                        help='Run only this flow (repeat to select several)')
    args = parser.parse_args()
    if args.scenario:
        cases = [case for case in cases if case[1] in args.scenario]
    if args.desktop_only:
        modes = dict.fromkeys(mode for _, mode, _ in cases)
        cases = [('desktop-' + mode, mode, 1440) for mode in modes]
    if not (args.dist / 'index.html').is_file():
        parser.error('Requires existing built dist/index.html; run npm run build first')
    output = args.output or Path(tempfile.mkdtemp(prefix='af-personal-tool-browser-'))
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(args.dist)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            try:
                results = [scenario(browser, f'http://127.0.0.1:{server.server_port}', output, name, mode,
                                    {'width': width, 'height': 1000 if width > 400 else 844})
                           for name, mode, width in cases]
                (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
                print(json.dumps({'scenariosPassed': len(results), 'output': str(output),
                                  'desktopOnly': args.desktop_only,
                                  'realCLIOrMCPIntegrationVerified': False}))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
