"""Recover original synthetic proposals and plans through local HTTPS OIDC.

The isolated test host installs explicit core fixture materials. Actual browser
HTTP verifies lost acknowledgements and owner isolation without native tasks.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import json
from pathlib import Path
import ssl
import tempfile
import httpx
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


from accept_browser_auth import listener, serve
from agent_factory.browser_oidc import BrowserCodeExchanger
from agent_factory.config import Settings
from browser_identity_fixture import BrowserIdentityFixture, private_tls_files
from core_native_fixture import create_fixture_app
from pg_fixture import IsolatedPostgres

PREFIX = '/api/factory'


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or not parsed.port
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise argparse.ArgumentTypeError('Use an explicit loopback HTTPS origin')
    return value.rstrip('/')


def login(page, base, owner, identity):
    identity.subject = 'subject-' + owner
    page.goto(base)
    page.get_by_role('button', name='使用企业账号登录', exact=True).click()
    page.get_by_role('button', name='退出', exact=True).wait_for()
    response = page.context.request.get(base + PREFIX + '/session')
    assert response.ok and response.json()['id'] == owner
    assert 'no-store' in response.headers.get('cache-control', '')


def json_get(context, base, path):
    response = context.request.get(base + PREFIX + path)
    assert response.ok
    assert 'no-store' in response.headers.get('cache-control', '')
    return response.json()


def lost_reply(page, base, path, action):
    """Deliver one real POST to server, then discard its successful response."""
    captured = []
    def handler(route):
        if route.request.method != 'POST':
            route.continue_()
            return
        assert not captured
        response = route.fetch(max_redirects=0, max_retries=0)
        assert response.ok
        captured.append(response.json())
        route.abort('failed')
    page.route(base + PREFIX + path, handler)
    try:
        with page.expect_event('requestfailed', predicate=lambda request:
                               request.method == 'POST' and urlsplit(request.url).path == PREFIX + path):
            action()
        assert len(captured) == 1
        return captured[0]
    finally:
        page.unroute(base + PREFIX + path, handler)


def restore(page, goal, accepted=False):
    # Lose all browser command keys and proposal pointer, retain HttpOnly session.
    page.evaluate('localStorage.clear(); sessionStorage.clear()')
    page.reload()
    inbox = page.get_by_role('region', name='我的装配提案', exact=True)
    for _ in range(20):
        expect(inbox.get_by_role('button', name='重新读取第一页', exact=True)).to_be_enabled()
        item = inbox.locator('article').filter(has=page.get_by_role('heading', name=goal, exact=True))
        if item.count():
            item.get_by_role('button', name='查看原方案' if accepted else '恢复此提案', exact=True).click()
            break
        next_page = inbox.get_by_role('button', name='查看下一页', exact=True)
        assert next_page.count() == 1, 'Recovery item absent'
        next_page.click()
    else:
        raise AssertionError('Fixture inbox exceeded bounded page limit')
    expect(page.get_by_label('2. 描述任务', exact=True)).to_have_value(goal)
    if accepted:
        page.get_by_role('heading', name='4. 开始任务', exact=True).wait_for()


def capture(page, output, name):
    assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
    page.screenshot(path=str(output / (name + '.png')), full_page=True)


def scenario(browser, base, output, name, viewport, identity):
    context = browser.new_context(ignore_https_errors=True, viewport=viewport)
    foreign = browser.new_context(ignore_https_errors=True, viewport=viewport)
    try:
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda _error: errors.append('pageerror'))
        console_errors = []
        def console(message):
            if message.type != 'error':
                return
            path = urlsplit(message.location.get('url', '')).path
            injected = path == PREFIX + '/compositions/proposals' or path.endswith('/accept')
            expected_failure = injected and 'Failed to load resource' in message.text and 'ERR_FAILED' in message.text
            initial_signed_out = path == PREFIX + '/session' and '401' in message.text
            if not (expected_failure or initial_signed_out):
                console_errors.append('console-error')
        page.on('console', console)
        posts = Counter()
        def count(request):
            if request.method == 'POST':
                posts[urlsplit(request.url).path] += 1
        page.on('request', count)
        login(page, base, 'alice', identity)
        goal = '合成研究提案恢复验收 ' + name + ' ' + uuid4().hex[:12]
        selector = page.get_by_label('1. 选择应用', exact=True)
        expect(selector).to_be_enabled()
        selector.select_option('fixture-text')
        page.get_by_label('应用执行方式', exact=True).select_option('literature')
        page.get_by_label('2. 描述任务', exact=True).fill(goal)
        proposal = lost_reply(page, base, '/compositions/proposals', lambda:
            page.get_by_role('button', name='预览任务方案', exact=True).click())
        assert proposal['ownerId'] == 'alice' and proposal['state'] == 'pending'
        assert proposal['candidate']['syntheticFixture'] is True
        restore(page, goal)
        stored = json_get(context, base, '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert stored['proposal']['id'] == proposal['id'] and stored['plan'] is None
        capture(page, output, name + '-proposal-recovered')
        # Also lose acceptance ACK: restoration must GET the original sealed plan.
        plan = lost_reply(page, base, '/compositions/proposals/' + proposal['id'] + '/accept', lambda:
            page.get_by_role('button', name='确认范围并保存方案', exact=True).click())
        restore(page, goal, accepted=True)
        recovered = json_get(context, base, '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert recovered['plan'] == plan
        expect(page.get_by_role('button', name='开始任务', exact=True)).to_be_enabled()
        capture(page, output, name + '-direct-admission-ready')
        # A separate session cannot read the first owner's original record.
        foreign_page = foreign.new_page()
        login(foreign_page, base, 'bob', identity)
        denied = foreign.request.get(base + PREFIX + '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert denied.status == 404
        assert posts[PREFIX + '/compositions/proposals'] == 1
        assert posts[PREFIX + '/compositions/proposals/' + proposal['id'] + '/accept'] == 1
        assert not any('/instances' in path for path in posts)
        assert not errors and not console_errors
        return {'viewport': name, 'proposalId': proposal['id'], 'planId': plan['id'],
                'proposalLostReplyRecovered': True, 'acceptLostReplyRecoveredReadOnly': True,
                'directMemberAdmissionReady': True, 'foreignOwnerDenied': True,
                'browserStorageLoss': True, 'duplicateCreateAcceptPosts': 0,
                'instancePosts': 0, 'pageErrors': 0, 'unexpectedConsoleErrors': 0, 'horizontalOverflow': False}
    except Exception:
        page.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
        raise
    finally:
        foreign.close(); context.close()


@contextmanager
def recovery_fixture(database_url, dist):
    """Owned loopback OIDC and explicit test catalog for browser consumers."""
    with ExitStack() as stack:
        database = stack.enter_context(IsolatedPostgres(database_url))
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='app-recovery-oidc-')))
        certificate, key = private_tls_files(scratch / 'tls')
        app_socket, idp_socket = listener(), listener()
        stack.callback(app_socket.close); stack.callback(idp_socket.close)
        base = 'https://127.0.0.1:' + str(app_socket.getsockname()[1])
        identity = BrowserIdentityFixture(issuer='https://127.0.0.1:' + str(idp_socket.getsockname()[1]),
            redirect_uri=base + '/api/factory/auth/callback')
        config = identity.config()
        config = replace(config, subject_owners={**config.subject_owners, (identity.issuer, 'subject-manager'): 'manager'})
        app = create_fixture_app(Settings(db_url=database.url, workspace=scratch / 'workspace',
            jwt_key='synthetic-recovery-browser-signing-key-at-least-32bytes',
            browser_oidc=config, web_directory=dist.resolve(), max_workers=1))
        state = app.app.state.factory
        store = state['store']
        stack.callback(store.engine.dispose); stack.callback(store.native_db.db_engine.dispose)
        stack.callback(store.dispose_root_locks)
        state['browser_auth'].exchanger = BrowserCodeExchanger(config,
            transport=httpx.AsyncHTTPTransport(verify=ssl.create_default_context(cafile=str(certificate)), retries=0))
        serve(stack, identity.app, idp_socket, certificate, key)
        serve(stack, app, app_socket, certificate, key)
        yield base, identity, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evidence = {'evidenceMode': 'controlled-fixture', 'realIdentityProviderVerified': False,
                'servicesStarted': True, 'identity': 'local-synthetic-oidc', 'modelCalls': 0, 'screens': []}
    try:
        with recovery_fixture(args.database_url, args.dist) as (base, identity, _state), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for name, viewport in (('desktop', {'width': 1440, 'height': 1000}),
                                       ('mobile', {'width': 390, 'height': 844})):
                    evidence['screens'].append(scenario(browser, base, args.output_dir, name, viewport, identity))
            finally:
                browser.close()
    except Exception:
        # Never serialize browser/server exception details or authentication URLs.
        evidence['ok'] = False
        (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        raise SystemExit('APP_RECOVERY_BROWSER_FAILED') from None
    evidence['ok'] = True
    (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'ok': True, 'evidenceMode': 'controlled-fixture', 'screens': len(evidence['screens'])}))


if __name__ == '__main__':
    main()
