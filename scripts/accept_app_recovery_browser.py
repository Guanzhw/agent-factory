"""Recover synthetic proposals/reviews against an already running loopback demo.

Requires development_mock_login, admin-review policy, and approved demo research
materials. Creates proposals/plans/reviews, never task instances or model calls.
Start no services and preserve no traces, cookies, tokens, or raw exceptions.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


PREFIX = '/api/factory'
LOGIN_NAME = re.compile(r'^(选择开发测试身份|使用企业账号登录)$')


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or not parsed.port
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise argparse.ArgumentTypeError('Use an explicit loopback HTTPS origin')
    return value.rstrip('/')


def login(page, base, persona):
    page.goto(base)
    page.get_by_role('button', name=LOGIN_NAME).click()
    page.locator('button[name="persona"][value="' + persona + '"]').click()
    page.get_by_role('button', name='退出', exact=True).wait_for()
    response = page.context.request.get(base + PREFIX + '/session')
    assert response.ok and response.json()['id'] == persona
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
    expect(page.get_by_label('任务目标', exact=True)).to_have_value(goal)
    if accepted:
        page.get_by_role('heading', name='已固定的执行方案', exact=True).wait_for()


def capture(page, output, name):
    assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
    page.screenshot(path=str(output / (name + '.png')), full_page=True)


def scenario(browser, base, output, name, viewport):
    context = browser.new_context(ignore_https_errors=True, viewport=viewport)
    manager = browser.new_context(ignore_https_errors=True, viewport=viewport)
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
            injected = path == PREFIX + '/compositions/proposals' or path == PREFIX + '/plan-reviews' or path.endswith('/accept')
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
        login(page, base, 'alice')
        goal = '合成研究提案恢复验收 ' + name + ' ' + uuid4().hex[:12]
        selector = page.get_by_label('已批准的应用', exact=True)
        expect(selector).to_be_enabled()
        selector.select_option('research')
        page.get_by_label('应用执行方式', exact=True).select_option('literature')
        page.get_by_label('任务目标', exact=True).fill(goal)
        proposal = lost_reply(page, base, '/compositions/proposals', lambda:
            page.get_by_role('button', name='生成装配提案', exact=True).click())
        assert proposal['ownerId'] == 'alice' and proposal['state'] == 'pending'
        assert proposal['candidate']['syntheticFixture'] is True
        restore(page, goal)
        stored = json_get(context, base, '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert stored['proposal']['id'] == proposal['id'] and stored['plan'] is None
        capture(page, output, name + '-proposal-recovered')
        # Also lose acceptance ACK: restoration must GET the original sealed plan.
        plan = lost_reply(page, base, '/compositions/proposals/' + proposal['id'] + '/accept', lambda:
            page.get_by_role('button', name='接受提案并固定方案', exact=True).click())
        restore(page, goal, accepted=True)
        recovered = json_get(context, base, '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert recovered['plan'] == plan
        gate = page.get_by_role('region', name='方案执行授权', exact=True)
        expect(gate).to_contain_text('管理员审查')
        review = lost_reply(page, base, '/plan-reviews', lambda:
            gate.get_by_role('button', name='提交方案审查', exact=True).click())
        assert review['planId'] == plan['id'] and review['decision'] == 'pending'
        restore(page, goal, accepted=True)
        expect(gate).to_contain_text('审查状态：等待决定')
        expect(page.get_by_role('button', name='确认方案并创建任务', exact=True)).to_be_disabled()
        reviews = json_get(context, base, '/plan-reviews?allOwners=false&planId=' + plan['id'])
        assert [item['id'] for item in reviews] == [review['id']]
        capture(page, output, name + '-review-pending-recovered')
        # Independent reviewer decides only this exact synthetic plan through UI.
        manager_page = manager.new_page()
        login(manager_page, base, 'manager')
        manager_page.get_by_role('button', name='方案审查', exact=True).click()
        row = manager_page.locator('article').filter(has=manager_page.get_by_role('heading', name=goal, exact=True))
        row.get_by_role('button', name='拒绝方案', exact=True).click()
        expect(row).to_contain_text('已拒绝')
        restore(page, goal, accepted=True)
        expect(gate).to_contain_text('审查状态：已拒绝')
        expect(page.get_by_role('button', name='确认方案并创建任务', exact=True)).to_be_disabled()
        expect(gate.get_by_role('button', name='明确提交新的审查请求', exact=True)).to_be_visible()
        capture(page, output, name + '-review-denied-recovered')
        # A separate session cannot read the first owner's original record.
        foreign_page = foreign.new_page()
        login(foreign_page, base, 'bob')
        denied = foreign.request.get(base + PREFIX + '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert denied.status == 404
        assert posts[PREFIX + '/compositions/proposals'] == 1
        assert posts[PREFIX + '/compositions/proposals/' + proposal['id'] + '/accept'] == 1
        assert posts[PREFIX + '/plan-reviews'] == 1
        assert not any('/instances' in path for path in posts)
        assert not errors and not console_errors
        return {'viewport': name, 'proposalId': proposal['id'], 'planId': plan['id'], 'reviewId': review['id'],
                'proposalLostReplyRecovered': True, 'acceptLostReplyRecoveredReadOnly': True,
                'pendingAndDeniedReviewRecovered': True, 'foreignOwnerDenied': True,
                'browserStorageLoss': True, 'duplicateCreateAcceptReviewPosts': 0,
                'instancePosts': 0, 'pageErrors': 0, 'unexpectedConsoleErrors': 0, 'horizontalOverflow': False}
    except Exception:
        page.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
        raise
    finally:
        foreign.close(); manager.close(); context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=origin, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evidence = {'evidenceMode': 'controlled-fixture', 'realIdentityProviderVerified': False,
                'servicesStarted': False, 'modelCalls': 0, 'screens': []}
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
        # Never serialize browser/server exception details or authentication URLs.
        evidence['ok'] = False
        (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        raise SystemExit('APP_RECOVERY_BROWSER_FAILED') from None
    evidence['ok'] = True
    (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'ok': True, 'evidenceMode': 'controlled-fixture', 'screens': len(evidence['screens'])}))


if __name__ == '__main__':
    main()
