"""Actual cookie/SQL development-login UI acceptance on an existing HTTPS demo.

Use only the explicit loopback development mock profile. Normal responses are
never mocked. One logout response is discarded after the server commits it.
Creates only synthetic proposals; no tasks, models, real IdP or new services.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from accept_app_recovery_browser import LOGIN_NAME, PREFIX, capture, json_get, login, origin


def signed_out(page, base):
    assert json_get(page.context, base, '/auth/session')['authenticated'] is False
    response = page.context.request.get(base + PREFIX + '/session')
    assert response.status == 401
    assert 'no-store' in response.headers.get('cache-control', '')


def persona_ui(page, base, persona):
    current = json_get(page.context, base, '/session')
    assert current['id'] == persona
    manager = persona == 'manager'
    assert current['role'] == ('manager' if manager else 'user')
    for label in ('共享材料管理', '应用定义治理', '方案审查'):
        button = page.get_by_role('button', name=label, exact=True)
        if manager:
            expect(button).to_be_visible()
        else:
            expect(button).to_have_count(0)


def navigate(page, base, persona):
    for _ in range(2):
        page.get_by_role('button', name='我的资源连接', exact=False).click()
        page.get_by_role('heading', name='我的连接引用', exact=True).wait_for()
        persona_ui(page, base, persona)
        if persona == 'manager':
            for label in ('共享材料管理', '应用定义治理', '方案审查'):
                page.get_by_role('button', name=label, exact=True).click()
                persona_ui(page, base, persona)
        page.get_by_role('button', name='研究工作台', exact=False).click()
        page.get_by_role('region', name='我的装配提案', exact=True).wait_for()
        page.reload()
        page.get_by_role('button', name='退出', exact=True).wait_for()
        persona_ui(page, base, persona)


def logout_lost_reply(page, base):
    committed = []
    def handler(route):
        if route.request.method != 'POST':
            route.continue_(); return
        response = route.fetch(max_redirects=0, max_retries=0)
        assert response.ok
        committed.append(True)
        route.abort('failed')
    path = base + PREFIX + '/logout'
    page.route(path, handler)
    try:
        with page.expect_event('requestfailed', predicate=lambda request:
                               request.method == 'POST' and request.url == path):
            page.get_by_role('button', name='退出', exact=True).click()
        assert committed == [True]
    finally:
        page.unroute(path, handler)
    # The cookie might remain client-side after lost Set-Cookie. SQL invalidation
    # must nevertheless deny authenticated reads, then UI must re-enter login.
    signed_out(page, base)
    page.reload()
    page.get_by_role('button', name=LOGIN_NAME).wait_for()
    expect(page.get_by_role('region', name='我的装配提案', exact=True)).to_have_count(0)


def scenario(browser, base, output, name, viewport):
    context = browser.new_context(ignore_https_errors=True, viewport=viewport)
    try:
        page = context.new_page()
        errors, unexpected_console, posts = [], [], Counter()
        page.on('pageerror', lambda _error: errors.append('pageerror'))
        def request(request):
            if request.method == 'POST':
                posts[urlsplit(request.url).path] += 1
        page.on('request', request)
        def console(message):
            if message.type != 'error':
                return
            path = urlsplit(message.location.get('url', '')).path
            expected = (path == PREFIX + '/logout' and 'ERR_FAILED' in message.text
                        or path.startswith(PREFIX + '/') and '401' in message.text)
            if not expected:
                unexpected_console.append('console-error')
        page.on('console', console)
        page.goto(base)
        entry = page.get_by_role('button', name=LOGIN_NAME)
        entry.click()
        page.get_by_role('button', name='取消登录', exact=True).click()
        entry.wait_for()
        signed_out(page, base)
        assert 'auth_error=' not in page.url
        capture(page, output, name + '-cancelled-login')
        # Refresh the real authorization document, abandon it without selecting
        # any identity, then start a fresh flow from the application.
        entry.click()
        page.locator('button[name="persona"][value="alice"]').wait_for()
        page.reload()
        page.locator('button[name="persona"][value="alice"]').wait_for()
        page.goto(base)
        entry.wait_for()
        signed_out(page, base)
        login(page, base, 'alice')
        persona_ui(page, base, 'alice')
        navigate(page, base, 'alice')
        goal = '合成登录身份隔离验收 ' + name + ' ' + uuid4().hex[:12]
        selector = page.get_by_label('已批准的应用', exact=True)
        expect(selector).to_be_enabled()
        selector.select_option('research')
        page.get_by_label('任务目标', exact=True).fill(goal)
        with page.expect_response(lambda response: response.request.method == 'POST'
                                  and urlsplit(response.url).path == PREFIX + '/compositions/proposals') as result:
            page.get_by_role('button', name='生成装配提案', exact=True).click()
        response = result.value
        assert response.ok
        proposal = response.json()
        assert proposal['ownerId'] == 'alice' and proposal['candidate']['syntheticFixture'] is True
        capture(page, output, name + '-alice')
        logout_lost_reply(page, base)
        # Same browser, different user: no stale proposal or manager controls.
        login(page, base, 'bob')
        navigate(page, base, 'bob')
        expect(page.get_by_text(goal, exact=True)).to_have_count(0)
        assert context.request.get(base + PREFIX + '/compositions/proposals/' + proposal['id'] + '/recovery').status == 404
        inbox = json_get(context, base, '/compositions/proposals')
        assert inbox['ownerId'] == 'bob' and all(item['ownerId'] == 'bob' for item in inbox['items'])
        capture(page, output, name + '-bob-isolated')
        page.get_by_role('button', name='退出', exact=True).click()
        entry.wait_for()
        signed_out(page, base)
        login(page, base, 'manager')
        navigate(page, base, 'manager')
        assert context.request.get(base + PREFIX + '/compositions/proposals/' + proposal['id'] + '/recovery').status == 404
        capture(page, output, name + '-manager')
        page.get_by_role('button', name='退出', exact=True).click()
        entry.wait_for()
        signed_out(page, base)
        login(page, base, 'alice')
        persona_ui(page, base, 'alice')
        recovered = json_get(context, base, '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert recovered['proposal']['id'] == proposal['id'] and recovered['plan'] is None
        capture(page, output, name + '-alice-relogin')
        assert not any('/instances' in path for path in posts)
        assert not errors and not unexpected_console
        return {'viewport': name, 'proposalId': proposal['id'], 'normalLogin': True,
                'cancelledLogin': True, 'authorizationRefreshAndAbandon': True, 'freshLoginAfterInterruption': True,
                'logoutLostAckServerRevoked': True, 'normalLogoutAndRelogin': True,
                'roles': ['alice', 'bob', 'manager'], 'sameBrowserOwnerIsolation': True,
                'crossOwnerRecordDenied': True, 'repeatedNavigationAndRefresh': True,
                'instancePosts': 0, 'pageErrors': 0, 'unexpectedConsoleErrors': 0, 'horizontalOverflow': False}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=origin, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evidence = {'evidenceMode': 'controlled-fixture', 'realIdentityProviderVerified': False,
                'normalResponsesMocked': False, 'servicesStarted': False, 'screens': []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for name, viewport in (('desktop', {'width': 1440, 'height': 1000}),
                                       ('mobile', {'width': 390, 'height': 844})):
                    evidence['screens'].append(scenario(browser, args.base_url, args.output_dir, name, viewport))
            finally:
                browser.close()
    except Exception:
        evidence['ok'] = False
        (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        raise SystemExit('DEVELOPMENT_LOGIN_BROWSER_FAILED') from None
    evidence['ok'] = True
    (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'ok': True, 'evidenceMode': 'controlled-fixture', 'screens': len(evidence['screens'])}))


if __name__ == '__main__':
    main()
