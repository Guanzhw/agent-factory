"""Actual local core/PG/OIDC, synthetic Research UI only; no API interception."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
import core_workspace_smoke as fixture


def scenario(browser, origin, output, mode, viewport):
    context = browser.new_context(viewport=viewport, ignore_https_errors=True)
    page = context.new_page()
    errors, business_writes, console_errors, expected_auth_console = [], [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def console(message):
        if message.type == 'error':
            item = {'text': message.text, 'url': message.location.get('url', '').split('?')[0]}
            if '401' in item['text'] and item['url'] in (origin + '/api/factory/session', origin + '/api/factory/auth/session'):
                expected_auth_console.append(item)
            else:
                console_errors.append(item)
    page.on('console', console)
    def request(req):
        if req.method not in ('GET', 'HEAD', 'OPTIONS') and '/api/' in req.url:
            if '/api/factory/auth/' not in req.url and '/api/factory/dev-identity/' not in req.url and not req.url.endswith('/api/factory/logout'):
                business_writes.append(req.url.split('?')[0])
    page.on('request', request)
    login_label = '选择开发测试身份' if mode == 'demo' else '使用企业账号登录'
    target = '/?tab=research&project=inference&researchTab=evidence#observation'
    screenshots = []
    def capture(name):
        page.screenshot(path=str(output / (name + '.png')), full_page=True)
        screenshots.append(name + '.png')
    def login():
        page.get_by_role('button', name=login_label, exact=True).click()
        if mode == 'demo':
            page.locator('button[name="persona"][value="alice"]').click()
        expect(page.get_by_role('heading', name='项目详情', exact=True)).to_be_visible()
        expect(page.get_by_role('tab', name='证据', exact=True)).to_have_attribute('aria-selected', 'true')
        expect(page).to_have_url(origin + target)
        session = context.request.get(origin + '/api/factory/session')
        assert session.ok and session.json()['id'] == 'alice'
    try:
        page.goto(origin + target)
        expect(page.get_by_role('button', name=login_label, exact=True)).to_be_visible()
        capture('login-interrupted-project')
        login()
        capture('project-return')
        page.reload()
        expect(page.get_by_role('heading', name='项目详情', exact=True)).to_be_visible()
        page.get_by_role('button', name='返回平台', exact=True).click()
        expect(page.get_by_role('heading', name='应用目录', exact=True)).to_be_visible()
        capture('platform-home')
        page.get_by_role('button', name='进入 AutoResearch', exact=True).click()
        expect(page.get_by_role('heading', name='我的研究', exact=True)).to_be_visible()
        assert 'project=' not in page.url
        capture('workbench')
        page.locator('.rd-project-row').filter(has_text='小模型推理加速').click()
        expect(page.get_by_role('heading', name='项目详情', exact=True)).to_be_visible()
        page.go_back()
        expect(page.get_by_role('heading', name='我的研究', exact=True)).to_be_visible()
        page.go_forward()
        expect(page.get_by_role('heading', name='项目详情', exact=True)).to_be_visible()
        page.goto(origin + target)
        page.locator('.rd-identity > button').click()
        page.get_by_role('button', name='退出登录', exact=True).click()
        expect(page.get_by_role('button', name=login_label, exact=True)).to_be_visible()
        assert context.request.get(origin + '/api/factory/session').status == 401
        login()
        assert not business_writes, business_writes
        assert not errors, errors
        assert not console_errors, console_errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        return dict(result='passed', loginInterruptedProject=True, platformEntryAndReturn=True,
                    backForward=True, refresh=True, logoutRelogin=True, researchUI='synthetic',
                    businessAPIsMocked=False, businessWrites=business_writes, pageErrors=errors, consoleErrors=console_errors, expectedAuthConsole=expected_auth_console, screenshots=screenshots)
    except BaseException:
        capture('failure')
        raise
    finally:
        context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    fixture.scenario = scenario
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        try:
            results = [fixture.run_mode(browser, args, mode) for mode in ('demo', 'production-local')]
            (args.output / 'evidence.json').write_text(json.dumps({'ok': True, 'results': results}, indent=2) + '\n')
        finally:
            browser.close()
