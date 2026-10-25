"""Real browser acceptance of governed synthetic application templates.

Run only against an isolated loopback development-mock Factory with approved
explicit core native fixture materials. All mutations use UI; API reads corroborate
immutable records and owner isolation. No services, credentials or live providers
are configured here. Browser TLS exception applies only to this test context.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import traceback
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from accept_app_recovery_browser import capture, json_get, login, origin

PREFIX = '/api/factory'


def safe_path(url):
    path = urlsplit(url).path
    for pattern, label in (
        (r'/api/factory/applications/[^/]+/versions/[0-9]+/publish', '/applications/:id/versions/:version/publish'),
        (r'/api/factory/compositions/proposals/[^/]+/accept', '/compositions/proposals/:id/accept'),
        (r'/api/factory/jobs/[^/]+/artifacts/[^/]+', '/jobs/:id/artifacts/:id'),
        (r'/api/factory/jobs/[^/]+', '/jobs/:id'),
    ):
        if re.fullmatch(pattern, path):
            return label
    return path.removeprefix(PREFIX) if path in {
        PREFIX + '/applications/drafts', PREFIX + '/applications/definitions',
        PREFIX + '/applications', PREFIX + '/session',
        PREFIX + '/compositions/proposals', PREFIX + '/instances',
    } else '/other'


def mutation(page, path, action):
    with page.expect_response(lambda response: response.request.method == 'POST'
                              and urlsplit(response.url).path == PREFIX + path) as pending:
        action()
    response = pending.value
    assert response.ok, 'UI_MUTATION_REJECTED'
    return response.json()


def uncertain_draft(page, base, editor, save):
    original = []
    def drop(route):
        if route.request.method != 'POST':
            route.continue_()
            return
        response = route.fetch(max_redirects=0, max_retries=0)
        assert response.ok and not original
        original.append((route.request.post_data_json, response.json()))
        route.abort('failed')
    endpoint = base + PREFIX + '/applications/drafts'
    page.route(endpoint, drop)
    try:
        with page.expect_event('requestfailed', predicate=lambda request:
                               request.method == 'POST' and request.url == endpoint):
            save.click()
    finally:
        page.unroute(endpoint, drop)
    expect(editor.get_by_label('应用名称', exact=True)).to_be_disabled()
    retry = page.get_by_role('button', name='核对并重试原保存', exact=True)
    expect(retry).to_be_enabled()
    with page.expect_request(lambda request: request.method == 'POST' and request.url == endpoint) as request:
        saved = mutation(page, '/applications/drafts', retry.click)
    assert request.value.post_data_json == original[0][0], 'RETRY_SCOPE_CHANGED'
    assert saved == original[0][1], 'DUPLICATE_DRAFT'
    return saved


def governance(page):
    page.get_by_role('button', name='应用定义治理', exact=True).click()
    page.get_by_role('heading', name='应用定义治理', exact=True).wait_for()


def application_row(page, name, button):
    return page.locator('article').filter(
        has=page.get_by_role('heading', name=name + ' · v1', exact=True)
    ).filter(has=page.get_by_role('button', name=button, exact=True))


def scenario(browser, base, output, name, viewport):
    contexts = [browser.new_context(ignore_https_errors=True, viewport=viewport, accept_downloads=True)
                for _ in range(3)]
    author, owner, foreign = contexts
    pages = [context.new_page() for context in contexts]
    manager, alice, bob = pages
    posts = Counter()
    diagnostics = []
    page_errors = []
    console_errors = []
    stage = 'login'
    for page in pages:
        page.set_default_timeout(20000)
        page.on('pageerror', lambda _error: page_errors.append('PAGE_ERROR'))
        def console(message):
            if message.type != 'error':
                return
            path = safe_path(message.location.get('url', ''))
            if path == '/session' and '401' in message.text:
                return
            if path == '/applications/drafts' and 'ERR_FAILED' in message.text:
                return
            console_errors.append('CONSOLE_ERROR')
        page.on('console', console)
        page.on('request', lambda request: posts.update([safe_path(request.url)])
                if request.method == 'POST' and safe_path(request.url) != '/other' else None)
        page.on('response', lambda response: diagnostics.append(
            {'path': safe_path(response.url), 'status': response.status})
            if response.status >= 400 and len(diagnostics) < 50 else None)
    try:
        for page, persona in zip(pages, ('manager', 'alice', 'bob'), strict=True):
            login(page, base, persona)
        stage = 'template'
        governance(manager)
        apps = json_get(author, base, '/applications')
        source = next(item for item in apps if item['id'] == 'fixture-text')
        reference = f"{source['id']}@{source['version']}:{source['sha256']}"
        manager.get_by_label('复制应用定义', exact=True).select_option(reference)
        editor = manager.get_by_role('region', name='应用模板编辑', exact=True)
        expect(editor).to_be_visible()
        app_name = '合成模板验收 ' + name + ' ' + uuid4().hex[:10]
        editor.get_by_label('应用名称', exact=True).fill(app_name)
        editor.get_by_label('应用说明', exact=True).fill('受控合成文献任务；不调用真实模型或研究数据源。')
        editor.get_by_label('默认执行方式', exact=True).select_option('literature')
        editor.get_by_label('编辑执行方式', exact=True).select_option('literature')
        save = manager.get_by_role('button', name='保存应用草稿', exact=True)
        stage = 'invalid-budget'
        budget = editor.get_by_label('预算 工具调用次数', exact=True)
        original_budget = budget.input_value()
        budget.fill('-1')
        expect(save).to_be_disabled()
        expect(editor.get_by_role('alert')).to_be_visible()
        assert posts['/applications/drafts'] == 0
        capture(manager, output, name + '-invalid-budget')
        budget.fill(original_budget)
        stage = 'missing-material'
        picker = editor.get_by_role('group', name='固定材料', exact=True)
        selected = picker.get_by_role('region', name='固定材料已选项', exact=True)
        removed_ids = []
        while selected.count():
            remove = selected.get_by_role('button', name=re.compile('^移除 ')).first
            removed_label = remove.get_attribute('aria-label')
            assert removed_label
            removed_ids.append(removed_label.split(' ')[1])
            remove.click()
        expect(save).to_be_disabled()
        expect(editor.get_by_role('alert')).to_be_visible()
        assert posts['/applications/drafts'] == 0
        capture(manager, output, name + '-missing-material')
        for material_id in removed_ids:
            picker.get_by_role('checkbox', name=re.compile(re.escape(material_id) + r' v[0-9]+')).check()
        expect(save).to_be_enabled()
        stage = 'draft'
        draft = uncertain_draft(manager, base, editor, save)
        assert draft['name'] == app_name and draft['version'] == 1 and draft['id'] != source['id']
        manager.reload(wait_until='domcontentloaded'); governance(manager)
        row = application_row(manager, app_name, '发布此版本')
        expect(row).to_contain_text('草稿')
        versions = json_get(author, base, '/applications/definitions?allAuthors=false')
        assert [item['application'] for item in versions if item['application']['id'] == draft['id']] == [draft]
        assert posts['/applications/drafts'] == 2
        stage = 'publish'
        published = mutation(manager, f"/applications/{draft['id']}/versions/1/publish",
                             row.get_by_role('button', name='发布此版本', exact=True).click)
        assert published == draft
        manager.reload(wait_until='domcontentloaded'); governance(manager)
        assert any(item == draft for item in json_get(author, base, '/applications'))
        capture(manager, output, name + '-published')
        stage = 'assemble'
        alice.reload(wait_until='domcontentloaded')
        alice.get_by_label('1. 选择应用', exact=True).select_option(draft['id'])
        alice.get_by_label('应用执行方式', exact=True).select_option('literature')
        goal = '合成文献单次执行 ' + app_name
        alice.get_by_label('2. 描述任务', exact=True).fill(goal)
        proposal = mutation(alice, '/compositions/proposals',
                            alice.get_by_role('button', name='预览任务方案', exact=True).click)
        assert proposal['candidate']['syntheticFixture'] is True
        plan = mutation(alice, f"/compositions/proposals/{proposal['id']}/accept",
                        alice.get_by_role('button', name='确认范围并保存方案', exact=True).click)
        job = mutation(alice, '/instances',
                       alice.get_by_role('button', name='开始任务', exact=True).click)
        assert job['planId'] == plan['id']
        # Browser-visible artifact is the completion condition, never an estimated sleep.
        download = alice.get_by_role('button', name=re.compile('^校验并下载 ')).first
        download.wait_for(timeout=90000)
        expect(alice.get_by_text(re.compile('^执行已完成。研究结论是否通过验证：'))).to_be_visible(timeout=20000)
        detail = json_get(owner, base, '/jobs/' + job['id'])
        assert detail['job']['status'] == 'completed' and detail['artifacts']
        assert detail['snapshot']['run_id'] and detail['snapshot']['queue']['id'] == detail['snapshot']['run_id'], 'NATIVE_RUN_REQUIRED'
        artifact = detail['artifacts'][0]
        with alice.expect_download() as result:
            alice.get_by_role('button', name='校验并下载 ' + artifact['name'], exact=True).click()
        raw = Path(result.value.path()).read_bytes()
        assert len(raw) == artifact['size'] and hashlib.sha256(raw).hexdigest() == artifact['sha256']
        alice.reload(wait_until='domcontentloaded')
        alice.get_by_role('button').filter(has_text=goal).click()
        expect(alice.get_by_role('button', name=re.compile('^校验并下载 ')).first).to_be_visible()
        capture(alice, output, name + '-native-artifact')
        stage = 'isolation'
        assert foreign.request.get(base + PREFIX + '/jobs/' + job['id']).status == 404
        assert foreign.request.get(base + PREFIX + '/jobs/' + job['id'] + '/artifacts/' + artifact['id']).status == 404
        for endpoint in ('/applications/drafts', '/applications/:id/versions/:version/publish', '/compositions/proposals',
                         '/compositions/proposals/:id/accept', '/instances'):
            assert posts[endpoint] == (2 if endpoint == '/applications/drafts' else 1), 'DUPLICATE_MUTATION'
        assert not page_errors and not console_errors
        return {'viewport': name, 'evidenceMode': 'controlled-fixture', 'draftId': draft['id'],
                'publishedVersion': draft['version'], 'planId': plan['id'],
                'taskId': job['id'], 'nativeRunPresent': True, 'artifactIntegrityVerified': True,
                'invalidBudgetAndMissingMaterialRejected': True, 'directOwnerPublication': True,
                'refreshPreservedOriginalRecords': True, 'instancePosts': 1, 'bobIsolation': True,
                'lostDraftAcknowledgementRecovered': True, 'draftRequests': 2, 'uniqueDrafts': 1,
                'liveProviderVerified': False, 'pageErrors': 0, 'unexpectedConsoleErrors': 0}
    except Exception as error:
        failed_page = manager if stage in {'template', 'invalid-budget', 'missing-material', 'draft', 'publish'} else alice
        overflow = failed_page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        overflow_elements = failed_page.evaluate("""() => [...document.querySelectorAll('body *')]
            .filter(element => element.getBoundingClientRect().right > window.innerWidth + 1)
            .slice(0, 20).map(element => ({tag: element.tagName, class: element.className,
                width: Math.round(element.getBoundingClientRect().width),
                right: Math.round(element.getBoundingClientRect().right)}))""")
        if stage != 'login':
            failed_page.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
        (output / (name + '-failure.json')).write_text(json.dumps({
            'stage': stage, 'http': diagnostics, 'horizontalOverflow': overflow,
            'navigationError': next((code for code in ('ERR_ABORTED', 'ERR_CONNECTION_RESET',
                'ERR_CONNECTION_REFUSED', 'Timeout') if code in str(error)), 'OTHER'),
            'overflowElements': overflow_elements,
            'frames': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                       for frame in traceback.extract_tb(error.__traceback__)]}) + '\n')
        raise RuntimeError('MATERIAL_TEMPLATE_BROWSER_FAILED') from None
    finally:
        for context in reversed(contexts):
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=origin, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evidence = {'evidenceMode': 'controlled-fixture', 'liveProviderVerified': False, 'screens': []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for name, viewport in (('desktop', {'width': 1440, 'height': 1000}),
                                       ('mobile', {'width': 390, 'height': 844})):
                    evidence['screens'].append(scenario(browser, args.base_url, args.output_dir, name, viewport))
            finally:
                browser.close()
        evidence['ok'] = True
    except Exception:
        evidence['ok'] = False
    (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'ok': evidence['ok'], 'screens': len(evidence['screens'])}))
    if not evidence['ok']:
        raise SystemExit('MATERIAL_TEMPLATE_BROWSER_FAILED')


if __name__ == '__main__':
    main()
