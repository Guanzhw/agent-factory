"""Built composer target-capability UI smoke with synthetic GET-only API fixtures.

Requires existing dist assets, Playwright and Chromium. Does not install/build,
probe remote receivers, start tasks or prove live remote execution compatibility.
--list-cases collects cases without importing Playwright or launching a browser.
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

ROOT = Path(__file__).resolve().parents[3]
CASES = ('v1-default', 'v2-capabilities')
PROPOSAL = '11111111-1111-4111-8111-111111111111'
OWNER = {'id': 'alice', 'name': 'Synthetic Alice', 'role': 'user'}


class SyntheticAPI:
    def __init__(self, base, version):
        self.base, self.version = base, version
        self.requests, self.violations, self.assets = [], [], []
        self.targets = [
            {'id': 'legacy', 'name': 'Synthetic legacy receiver', 'kind': 'remote-factory',
             'connectivityVerified': False},  # Omitted declaration preserves v1 compatibility.
            {'id': 'current', 'name': 'Synthetic v2 receiver', 'kind': 'remote-factory',
             'supportedApplicationContracts': [1, 2], 'connectivityVerified': False},
        ]
        ref = {'id': 'synthetic-neutral', 'version': 1, 'sha256': 'a' * 64}
        version_fields = {'contractVersion': 2} if version == 2 else {}
        budget = {'toolCalls': 1, 'maxDepth': 0, 'maxChildren': 0, 'outputBytes': 1024,
                  'operationSeconds' if version == 2 else 'experimentSeconds': 1}
        mode = {'materialRefs': [], 'materialChoices': {}, 'capabilities': [], 'budget': budget,
                'config': {}, 'toolOrder': [], 'connectionRequirements': []}
        self.application = {**version_fields, **ref, 'name': 'Synthetic neutral fixture',
            'description': 'Browser presentation only', 'discoveryKeywords': [], 'defaultForDiscovery': False,
            'defaultMode': 'fixture', 'modes': {'fixture': mode}}
        candidate = {**version_fields, 'application': ref['id'], 'applicationRef': ref,
            'mode': 'fixture', 'normalizedGoal': 'Inspect static receiver declarations',
            'materialRefs': [], 'materials': [], 'tools': [], 'capabilities': [], 'budget': budget,
            'config': {}, 'instructions': 'Synthetic fixture only', 'status': 'ready', 'missing': [],
            'policy': {}, 'syntheticFixture': True, 'executionBindings': None, 'bindingManifest': {},
            'fingerprint': 'b' * 64}
        self.plan = {**version_fields, 'id': 'synthetic-plan', 'ownerId': OWNER['id'],
            'fingerprint': 'c' * 64, 'normalizedGoal': candidate['normalizedGoal'], 'applicationRef': ref,
            'materialRefs': [], 'capabilities': [], 'missing': [], 'status': 'ready',
            'createdAt': '2026-10-24T00:00:00Z', 'bindingManifest': {}}
        proposal = {'id': PROPOSAL, 'ownerId': OWNER['id'], 'createdAt': self.plan['createdAt'],
            'parentId': None, 'input': {'goal': candidate['normalizedGoal'], 'application': ref['id']},
            'candidate': candidate, 'selection': {'method': 'explicit-application', 'matchedKeywords': []},
            'fingerprint': 'd' * 64, 'state': 'accepted', 'planId': self.plan['id'], 'allowedActions': []}
        self.recovery = {'proposal': proposal, 'plan': self.plan, 'historical': True, 'executionAuthorized': False}
        self.authorization = {'ownerId': OWNER['id'], 'planId': self.plan['id'],
            'planFingerprint': self.plan['fingerprint'], 'executionAllowed': True,
            'reviewRequired': False, 'reviewRequestSupported': False, 'nativeToolConfirmationRequired': False,
            'policy': {'name': 'member-self-service', 'revision': 'fixture', 'fingerprint': 'e' * 64,
                       'review_ttl_seconds': 300, 'nativeToolConfirmationSeparate': True}}

    def reject(self, route, message):
        self.violations.append(message)
        route.abort()

    def intercept(self, route):
        request = route.request
        url = urlsplit(request.url)
        if f'{url.scheme}://{url.netloc}' != self.base:
            self.reject(route, 'External request: ' + request.url)
            return
        if request.method != 'GET':
            self.reject(route, 'Unexpected mutation: ' + request.url)
            return
        if not url.path.startswith('/api/'):
            if url.path == '/' or url.path.startswith('/assets/'):
                self.assets.append(url.path)
                route.continue_()
            else:
                self.reject(route, 'Unexpected static request: ' + request.url)
            return
        path = url.path.removeprefix('/api/factory')
        self.requests.append({'method': request.method, 'path': path})
        values = {
            '/auth/config': {'enabled': False, 'oidcEnabled': False, 'localLoginEnabled': False, 'loginPath': '/api/factory/auth/login',
                             'logoutPath': '/api/factory/auth/logout'},
            '/session': OWNER,
            '/status': {'mode': 'demo', 'activeWorkers': 0, 'queuedJobs': 0, 'maxWorkers': 2,
                        'integration': 'Synthetic browser fixture'},
            '/jobs': {'items': [], 'nextCursor': None}, '/materials': [],
            '/execution-targets': self.targets, '/applications': [self.application], '/user-connections': [],
            '/compositions/proposals': {'schema': 1, 'ownerId': OWNER['id'], 'snapshot': False,
                                       'items': [], 'nextCursor': None},
            f'/compositions/proposals/{PROPOSAL}/recovery': self.recovery,
            '/plans/synthetic-plan/authorization': self.authorization,
        }
        if path not in values:
            self.reject(route, 'Unconfigured API read: ' + path)
            return
        route.fulfill(status=200, json=values[path])


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def scenario(browser, base, output, name):
    from playwright.sync_api import expect
    expect.set_options(timeout=12000)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
    api = SyntheticAPI(base, 1 if name == 'v1-default' else 2)
    context.route('**/*', api.intercept)
    def websocket(socket):
        api.violations.append('Unexpected WebSocket: ' + socket.url)
        socket.close()
    context.route_web_socket('**/*', websocket)
    context.add_init_script('sessionStorage.setItem("factory-proposal-v1:alice", ' + json.dumps(PROPOSAL) + ');')
    page = context.new_page()
    page.set_default_timeout(12000)
    errors, console_errors = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
    try:
        page.goto(base + '/?tab=developer', wait_until='networkidle')
        page.get_by_text('继续之前的任务 · 提案与方案历史', exact=True).click()
        page.get_by_role('button', name='继续上次保存的任务', exact=True).click()
        select = page.get_by_role('combobox', name='执行位置', exact=True)
        start = page.get_by_role('button', name='开始任务', exact=True)
        expect(start).to_be_enabled()
        legacy = select.locator('option[value="legacy"]')
        current = select.locator('option[value="current"]')
        expect(legacy).to_contain_text('声明契约 v1')
        expect(current).to_contain_text('声明契约 v1、v2')
        expect(page.get_by_text('目标版本为静态声明', exact=False)).to_be_visible()
        expect(page.get_by_text('连接验证不代表任务可执行', exact=False)).to_be_visible()
        if name == 'v1-default':
            expect(legacy).to_have_js_property("disabled", False)
            select.select_option('legacy')
            expect(start).to_be_enabled()
            expect(page.get_by_text('Synthetic legacy receiver：连接未验证。', exact=True)).to_be_visible()
        else:
            expect(legacy).to_have_js_property("disabled", True)
            expect(legacy).to_contain_text('不支持当前 v2')
            expect(current).to_have_js_property("disabled", False)
            select.select_option('current')
            expect(start).to_be_enabled()
            expect(page.get_by_text('Synthetic v2 receiver：连接未验证。', exact=True)).to_be_visible()
            page.screenshot(path=str(output / (name + '-supported.png')), full_page=True)
            # Only the fixture changes; real five-second workspace polling must update this UI.
            api.targets[1] = {**api.targets[1], 'supportedApplicationContracts': [1], 'connectivityVerified': True}
            expect(start).to_be_disabled()
            expect(select).to_have_value('current')
            expect(current).to_have_js_property("disabled", True)
            expect(page.get_by_text('所选目标未声明支持方案契约 v2', exact=False)).to_be_visible()
            expect(page.get_by_text('Synthetic v2 receiver：连接已验证。', exact=True)).to_be_visible()
            assert api.plan['contractVersion'] == 2
            api.targets = []
            expect(page.get_by_text('所选目标当前不可用，请重新选择执行位置。', exact=True)).to_be_visible()
            expect(select).to_have_value('current')
            expect(start).to_be_disabled()
        page.screenshot(path=str(output / (name + '-result.png')), full_page=True)
        assert any(path.startswith('/assets/') and path.endswith('.js') for path in api.assets), api.assets
        assert not api.violations, api.violations
        assert not errors, errors
        assert not console_errors, console_errors
        return {'case': name, 'result': 'passed', 'fixtureKind': 'synthetic GET-only API',
                'builtAssetsRequested': api.assets, 'apiRequests': api.requests,
                'pageErrors': errors, 'externalRequests': 0, 'mutations': 0,
                'liveRemoteExecutionVerified': False}
    except Exception:
        page.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
        (output / (name + '-failure.json')).write_text(json.dumps({'violations': api.violations,
            'requests': api.requests, 'pageErrors': errors, 'consoleErrors': console_errors,
            'body': page.locator('body').inner_text()}, ensure_ascii=False, indent=2))
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist')
    parser.add_argument('--browser', help='Existing Chromium executable')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--case', action='append', choices=CASES)
    parser.add_argument('--list-cases', action='store_true')
    args = parser.parse_args()
    cases = args.case or list(CASES)
    if args.list_cases:
        print(json.dumps({'cases': cases, 'requires': ['existing built dist', 'Playwright', 'Chromium']}))
        return
    if not (args.dist / 'index.html').is_file():
        parser.error('Requires existing dist/index.html; build separately before running')
    from playwright.sync_api import sync_playwright
    output = args.output or Path(tempfile.mkdtemp(prefix='af-remote-v2-targets-'))
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(args.dist)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            try:
                results = [scenario(browser, f'http://127.0.0.1:{server.server_port}', output, case) for case in cases]
                (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
                print(json.dumps({'casesPassed': len(results), 'output': str(output), 'liveRemoteExecutionVerified': False}))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
