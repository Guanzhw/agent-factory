"""Real Chromium over synthetic API responses; not identity/provider acceptance."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', default='http://127.0.0.1:4175')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for mobile in (False, True):
            size = {'width': 390, 'height': 844} if mobile else {'width': 1487, 'height': 1058}
            context = browser.new_context(viewport=size, device_scale_factor=1)
            page = context.new_page()
            errors, writes, console_errors = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
            user = {'id': 'alice', 'name': '张予阳', 'role': 'user'}
            signed_in = True

            def fixture(route):
                nonlocal signed_in, user
                path = urlparse(route.request.url).path
                if route.request.method != 'GET':
                    writes.append(path)
                if path == '/api/factory/logout':
                    signed_in = False
                    route.fulfill(status=204)
                    return
                if path == '/api/factory/demo/login':
                    signed_in = True
                    persona = route.request.post_data_json['persona']
                    user = {'id': persona, 'name': '张予阳' if persona == 'alice' else '演示 Bob', 'role': 'user'}
                    route.fulfill(json=user)
                    return
                if path == '/api/factory/session' and not signed_in:
                    route.fulfill(status=401, json={'detail': 'SIGN_IN_REQUIRED'})
                    return
                data = {
                    '/api/factory/auth/config': {'enabled': False, 'loginPath': '/api/factory/auth/login', 'logoutPath': '/api/factory/auth/logout'},
                    '/api/factory/status': {'mode': 'demo', 'maxWorkers': 1, 'activeWorkers': 0, 'queuedJobs': 0, 'integration': 'Synthetic UI fixture', 'liveEnabled': False},
                    '/api/factory/session': user, '/api/factory/materials': [],
                    '/api/factory/jobs': {'items': [], 'nextCursor': None}, '/api/factory/execution-targets': [],
                    '/api/factory/personal-models/capabilities': {'enabled': False, 'providers': [], 'liveCompatibilityVerified': False},
                    '/api/factory/personal-models': [], '/api/factory/user-connections': [],
                    '/api/factory/user-connections/registrations': [], '/api/factory/resources/leases': {'leases': [], 'nextCursor': None},
                    '/api/factory/personal-credentials/capabilities': {'enabled': False, 'providerIds': []},
                    '/api/factory/personal-ssh/capabilities': {'enabled': False}, '/api/factory/personal-tools/descriptors': [],
                    '/api/factory/personal-tools': [], '/api/factory/personal-remotes/providers': [], '/api/factory/personal-remotes': [],
                }
                assert path in data, f'Unexpected API request: {path}'
                route.fulfill(json=data[path])

            page.route('**/api/**', fixture)
            page.goto(args.origin)
            expect(page.get_by_role('heading', name='应用目录', exact=True)).to_be_visible()
            page.screenshot(path=str(args.output / f'platform-{size["width"]}.png'))
            page.get_by_role('button', name='进入 AutoResearch', exact=True).click()
            expect(page.get_by_role('heading', name='我的研究', exact=True)).to_be_visible()
            page.screenshot(path=str(args.output / f'workbench-{size["width"]}.png'))
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
            page.locator('.rd-project-row').filter(has_text='小模型推理加速').click()
            expect(page.get_by_role('heading', name='项目详情', exact=True)).to_be_visible()
            project_url = page.url
            page.get_by_role('tab', name='实验', exact=True).click()
            page.get_by_role('button', name='实验 12 · 候选方案评估', exact=False).click()
            expect(page.get_by_role('dialog', name='实验 12 · 运行与观察')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.get_by_role('dialog')).to_have_count(0)
            assert page.locator('.rd-experiments > button').first.evaluate('(el)=>el===document.activeElement'), 'Dialog focus did not return'
            page.get_by_role('tab', name='证据', exact=True).click()
            page.locator('.rd-evidence').get_by_role('button', name='团队记录 08', exact=False).click()
            page.get_by_role('button', name='关联到当前讨论').click()
            if mobile:
                expect(page.get_by_role('dialog', name='研究助手 · 演示')).to_be_visible()
                page.keyboard.press('Escape')
            page.reload()
            expect(page.get_by_role('tab', name='证据', exact=True)).to_have_attribute('aria-selected', 'true')
            page.get_by_role('button', name='返回工作台', exact=True).click()
            page.go_back()
            expect(page.get_by_role('heading', name='项目详情', exact=True)).to_be_visible()
            page.go_forward()
            expect(page.get_by_role('heading', name='我的研究', exact=True)).to_be_visible()
            page.get_by_role('button', name='新建项目', exact=True).click()
            page.get_by_label('项目名称', exact=True).fill('合成新项目')
            page.get_by_label('研究目标', exact=True).fill('演示创建与空状态，不调用模型')
            page.get_by_role('button', name='创建演示项目', exact=True).click()
            expect(page.get_by_role('heading', name='还没有实验或证据')).to_be_visible()
            created_url = page.url
            page.reload()
            expect(page.get_by_role('heading', name='合成新项目', exact=True)).to_be_visible()
            if mobile:
                page.get_by_role('button', name='研究助手', exact=True).click()
            page.get_by_role('button', name='助手选项', exact=True).click()
            page.get_by_role('button', name='重置演示对话', exact=True).click()
            expect(page.locator('.rd-messages')).not_to_contain_text('实验12已运行完成')
            expect(page.locator('.rd-messages')).to_contain_text('当前项目的演示讨论')
            if mobile:
                page.keyboard.press('Escape')
            page.get_by_role('button', name='返回平台', exact=True).click()
            expect(page.get_by_role('heading', name='应用目录', exact=True)).to_be_visible()
            page.get_by_role('button', name='进入 AutoResearch', exact=True).click()
            assert 'project=' not in page.url, 'Platform entry retained old project'
            page.get_by_role('button', name='团队经验', exact=True).click()
            page.get_by_label('搜索团队经验').fill('没有此记录')
            expect(page.get_by_text('没有匹配的团队记录。试试其他关键词。')).to_be_visible()
            page.get_by_label('搜索团队经验').fill('')
            page.get_by_label('只看与推理加速相关').check()
            expect(page.locator('.rd-records article')).to_have_count(2)
            page.get_by_role('button', name='工作台', exact=True).click()
            if mobile:
                page.get_by_role('button', name='研究助手', exact=True).click()
            page.get_by_label('给研究助手发送演示消息').fill('怎样核对评估条件？')
            page.get_by_role('button', name='发送演示消息', exact=True).click()
            expect(page.get_by_text('演示回复：建议先核对实验条件与团队记录中的数据划分，再判断当前结果是否可以比较。此处没有调用模型，也没有启动实验。')).to_be_visible()
            if mobile:
                page.keyboard.press('Escape')
            page.get_by_role('button', name='资源', exact=True).click()
            expect(page.get_by_role('heading', name='我的资源', exact=True)).to_be_visible()
            page.get_by_role('navigation', name='工作区').get_by_role('button', name='应用', exact=True).click()
            page.get_by_role('navigation', name='工作区').get_by_role('button', name='资源', exact=True).click()
            expect(page.get_by_role('button', name='返回 AutoResearch', exact=True)).to_have_count(0)
            page.get_by_role('button', name='返回 应用', exact=True).click()
            expect(page.get_by_role('heading', name='应用目录', exact=True)).to_be_visible()
            page.get_by_role('button', name='进入 AutoResearch', exact=True).click()
            page.get_by_role('button', name='资源', exact=True).click()
            page.get_by_role('button', name='设置我的模型/API', exact=True).click()
            expect(page.get_by_role('heading', name='我的模型/API', exact=True)).to_be_visible()
            page.get_by_role('button', name='管理我的凭据与连接', exact=True).click()
            expect(page.get_by_role('heading', name='我的凭据与连接', exact=True)).to_be_visible()
            page.get_by_role('button', name='管理模型/API 设置', exact=True).click()
            page.get_by_role('button', name='返回工作区', exact=True).click()
            expect(page.get_by_role('heading', name='我的研究', exact=True)).to_be_visible()

            page.goto(project_url)
            page.locator('.rd-identity > button').click()
            page.get_by_role('button', name='退出登录', exact=True).click()
            page.get_by_role('button', name='成员 Bob', exact=True).click()
            page.goto(created_url)
            expect(page.get_by_role('heading', name='未找到演示项目')).to_be_visible()
            assert not errors, errors
            assert not console_errors, console_errors
            assert set(writes) <= {'/api/factory/demo/login', '/api/factory/logout'}, writes
            results.append({'viewport': size, 'browser': 'Chromium', 'identity': 'synthetic HTTP fixture, not real authentication', 'core_and_research_write_calls': [path for path in writes if path not in {'/api/factory/demo/login', '/api/factory/logout'}], 'page_errors': errors, 'console_errors': console_errors, 'result': 'passed'})
            context.close()
        browser.close()
    (args.output / 'browser.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
