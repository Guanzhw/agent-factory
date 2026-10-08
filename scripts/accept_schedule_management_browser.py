"""Controlled HTTPS mock-login schedule-management browser acceptance.

Use only an isolated synthetic Factory. Plans are reviewed independently;
creation defaults to paused and cron dates are far from the fixture clock.
Native occurrences are triggered explicitly by the existing API in the test
fixture, never by a production timer or external provider. UI wiring is finalized
against the current schedule management contract before this harness runs.
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

from accept_app_recovery_browser import capture, json_get, login, lost_reply, origin
from accept_material_template_browser import mutation
from accept_synthesis_journey_browser import approve_plan

PREFIX = '/api/factory'
CREATE_CRON = '0 0 1 1 *'
EDIT_CRON = '0 0 2 1 *'
TIMEZONE = 'Etc/UTC'


def approved_plan(owner_page, reviewer_page, label):
    """A manager-owned immutable synthetic plan; another manager approves it."""
    owner_page.get_by_label('已批准的应用', exact=True).select_option('research')
    owner_page.get_by_label('应用执行方式', exact=True).select_option('literature')
    goal = '计划任务合成文献验收 ' + label + ' ' + uuid4().hex[:10]
    owner_page.get_by_label('任务目标', exact=True).fill(goal)
    proposal = mutation(owner_page, '/compositions/proposals',
                        owner_page.get_by_role('button', name='生成装配提案', exact=True).click)
    assert proposal['candidate']['syntheticFixture'] is True
    plan = mutation(owner_page, '/compositions/proposals/' + proposal['id'] + '/accept',
                    owner_page.get_by_role('button', name='接受提案并固定方案', exact=True).click)
    mutation(owner_page, '/plan-reviews', owner_page.get_by_role('button', name='提交方案审查', exact=True).click)
    approve_plan(reviewer_page, owner_page, goal)
    return plan, goal


def contexts_for(browser, base, viewport):
    contexts = []
    try:
        for persona in ('manager', 'manager2', 'bob'):
            context = browser.new_context(ignore_https_errors=True, viewport=viewport, accept_downloads=True)
            contexts.append(context)
            page = context.new_page()
            page.set_default_timeout(20000)
            login(page, base, persona)
        return contexts
    except Exception:
        for context in reversed(contexts):
            context.close()
        raise RuntimeError('SCHEDULE_BROWSER_LOGIN_FAILED') from None


def mutations(page):
    counts = Counter()
    def observe(request):
        if request.method not in {'POST', 'PATCH'}:
            return
        path = urlsplit(request.url).path
        for pattern, label in (
            (r'/api/factory/schedule-management', 'create'),
            (r'/api/factory/schedule-management/[^/]+', 'edit'),
            (r'/api/factory/schedule-management/[^/]+/enabled', 'enabled'),
            (r'/api/factory/schedules/[^/]+/trigger', 'trigger'),
            (r'/api/factory/instances', 'instances'),
        ):
            if re.fullmatch(pattern, path):
                if label == 'edit' and request.method != 'PATCH':
                    continue
                counts[label] += 1
    page.on('request', observe)
    return counts


def verify_task(page, context, base, task_id, goal):
    expect(page.get_by_role('region', name='任务详情', exact=True).get_by_role('heading', name=goal, exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile('^执行已完成。研究结论是否通过验证：'))).to_be_visible(timeout=90000)
    detail = json_get(context, base, '/jobs/' + task_id)
    assert detail['job']['status'] == 'completed' and detail['job']['ownerId'] == 'manager'
    assert detail['snapshot']['queue']['id'] == detail['snapshot']['run_id']
    assert detail['artifacts']
    artifact = detail['artifacts'][0]
    with page.expect_download() as pending:
        page.get_by_role('button', name='校验并下载 ' + artifact['name'], exact=True).click()
    content = Path(pending.value.path()).read_bytes()
    assert len(content) == artifact['size'] and hashlib.sha256(content).hexdigest() == artifact['sha256']
    return detail


def change(page, path, action, method='POST'):
    with page.expect_response(lambda response: response.request.method == method
                              and urlsplit(response.url).path == PREFIX + path) as pending:
        action()
    response = pending.value
    assert response.ok
    return response.json()


def preview(panel):
    panel.get_by_role('button', name='预览下次执行时间', exact=True).click()
    expect(panel.locator('[aria-label="执行时间预览"]')).to_be_visible()


def manual_occurrence(page, schedule_id):
    """Fixture-only authenticated API trigger, explicitly not a UI action."""
    response = page.evaluate("""async ({id, requestId}) => {
        const session = await fetch('/api/factory/auth/session', {cache:'no-store', redirect:'error'});
        if (!session.ok) return {status:session.status};
        const auth = await session.json();
        const response = await fetch('/api/factory/schedules/' + encodeURIComponent(id) + '/trigger', {
            method:'POST', credentials:'same-origin', redirect:'error',
            headers:{'Content-Type':'application/json', 'X-Factory-CSRF':auth.csrfToken},
            body:JSON.stringify({requestId})});
        return {status:response.status, body:response.ok ? await response.json() : null};
    }""", {'id': schedule_id, 'requestId': 'browser-controlled-' + uuid4().hex})
    assert response['status'] == 202 and response['body']['task_id']
    return response['body']


def scenario(browser, base, output, name, viewport):
    contexts = contexts_for(browser, base, viewport)
    owner, reviewer, foreign = contexts
    manager, manager2, bob = [context.pages[0] for context in contexts]
    counts = mutations(manager)
    stage = 'approved-plan'
    page_errors, console_errors = [], []
    for page in (manager, manager2, bob):
        page.on('pageerror', lambda _error: page_errors.append('PAGE_ERROR'))
        def console(message):
            if message.type != 'error':
                return
            path = urlsplit(message.location.get('url', '')).path
            if path == PREFIX + '/session' and '401' in message.text:
                return
            if path == PREFIX + '/schedule-management' and 'ERR_FAILED' in message.text:
                return
            console_errors.append('CONSOLE_ERROR')
        page.on('console', console)
    try:
        plan, goal = approved_plan(manager, manager2, name)
        manager.get_by_role('button', name='用此已批准方案设置计划任务', exact=True).click()
        panel = manager.get_by_role('region', name='计划任务', exact=True)
        expect(panel).to_be_visible()
        schedule_name = '合成计划管理 ' + name + ' ' + uuid4().hex[:10]
        panel.get_by_label('计划任务名称', exact=True).fill(schedule_name)
        panel.get_by_label('Cron表达式', exact=True).fill(CREATE_CRON)
        panel.get_by_label('IANA时区', exact=True).fill(TIMEZONE)
        save = panel.get_by_role('button', name='保存计划任务', exact=True)
        expect(save).to_be_disabled()
        preview(panel)
        stage = 'create-lost-ack'
        schedule = lost_reply(manager, base, '/schedule-management', save.dblclick)
        assert schedule['enabled'] is False and schedule['planId'] == plan['id']
        assert schedule['planFingerprint'] == plan['fingerprint']
        manager.reload(wait_until='domcontentloaded')
        manager.get_by_role('button', name='计划任务', exact=True).click()
        panel.get_by_role('button', name='查看计划任务 ' + schedule_name, exact=True).click()
        stored = json_get(owner, base, '/schedule-management/' + schedule['id'])
        assert stored == schedule
        listing = json_get(owner, base, '/schedule-management')
        assert [item['id'] for item in listing['items'] if item['name'] == schedule_name] == [schedule['id']]
        assert counts['create'] == 1 and counts['instances'] == 0
        capture(manager, output, name + '-paused-recovered')
        stage = 'edit'
        panel.get_by_label('Cron表达式', exact=True).fill(EDIT_CRON)
        preview(panel)
        edited = change(manager, '/schedule-management/' + schedule['id'],
                        panel.get_by_role('button', name='保存执行时间', exact=True).click, 'PATCH')
        assert edited['id'] == schedule['id'] and edited['planId'] == plan['id']
        assert edited['cron'] == EDIT_CRON and edited['enabled'] is False
        assert edited['definitionFingerprint'] != schedule['definitionFingerprint']
        stage = 'resume-pause'
        enabled_path = '/schedule-management/' + schedule['id'] + '/enabled'
        enabled = change(manager, enabled_path, panel.get_by_role('button', name='恢复计划任务', exact=True).click)
        assert enabled['enabled'] is True
        paused = change(manager, enabled_path, panel.get_by_role('button', name='暂停计划任务', exact=True).click)
        assert paused['enabled'] is False
        manager.reload(wait_until='domcontentloaded')
        manager.get_by_role('button', name='计划任务', exact=True).click()
        panel.get_by_role('button', name='查看计划任务 ' + schedule_name, exact=True).click()
        expect(panel.get_by_role('button', name='恢复计划任务', exact=True)).to_be_visible()
        assert json_get(owner, base, '/schedule-management/' + schedule['id']) == paused
        history = json_get(owner, base, '/schedule-management/' + schedule['id'] + '/occurrences')
        assert history['items'] == []
        capture(manager, output, name + '-edited-paused')
        change(manager, enabled_path, panel.get_by_role('button', name='恢复计划任务', exact=True).click)
        stage = 'fixture-manual-occurrence'
        occurrence = manual_occurrence(manager, schedule['id'])
        task_id = occurrence['task_id']
        # Pause before inspection; already admitted native work must remain visible.
        change(manager, enabled_path, panel.get_by_role('button', name='暂停计划任务', exact=True).click)
        panel.get_by_role('button', name='刷新执行历史', exact=True).click()
        panel.get_by_role('button', name='查看原任务', exact=True).click()
        detail = verify_task(manager, owner, base, task_id, goal)
        capture(manager, output, name + '-native-task')
        manager.get_by_role('button', name='计划任务', exact=True).click()
        panel.get_by_role('button', name='查看计划任务 ' + schedule_name, exact=True).click()
        expect(panel.get_by_role('region', name='计划执行历史', exact=True)).to_contain_text('completed')
        history = json_get(owner, base, '/schedule-management/' + schedule['id'] + '/occurrences')
        assert len(history['items']) == 1 and history['items'][0]['taskId'] == task_id
        capture(manager, output, name + '-occurrence-history')
        stage = 'cross-owner'
        for path in ('/schedule-management/' + schedule['id'],
                     '/schedule-management/' + schedule['id'] + '/occurrences', '/jobs/' + task_id):
            assert foreign.request.get(base + PREFIX + path).status == 404
        artifact = detail['artifacts'][0]
        assert foreign.request.get(base + PREFIX + '/jobs/' + task_id + '/artifacts/' + artifact['id']).status == 404
        bob.get_by_role('button', name='计划任务', exact=True).click()
        expect(bob.get_by_role('region', name='计划任务', exact=True)).to_contain_text('管理需要当前管理员权限')
        assert counts == {'create': 1, 'edit': 1, 'enabled': 4, 'trigger': 1}
        assert not page_errors and not console_errors
        return {'viewport': name, 'planId': plan['id'], 'scheduleId': schedule['id'], 'taskId': task_id,
                'defaultPaused': True, 'createLostAckReadOnlyRecovered': True, 'createPosts': 1,
                'timeEditedOriginalPlanPreserved': True, 'pauseResumeRefreshVerified': True,
                'manualOccurrence': {'method': 'fixture-existing-api-not-ui', 'count': 1},
                'nativeTaskAndArtifactVerified': True, 'historyTaskLinkVerified': True,
                'finalSchedulePaused': True, 'crossOwnerDenied': True, 'pageErrors': 0,
                'unexpectedConsoleErrors': 0, 'evidenceMode': 'controlled-fixture'}
    except Exception as error:
        manager.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
        (output / (name + '-failure.json')).write_text(json.dumps({'stage': stage,
            'pageErrors': len(page_errors), 'consoleErrors': len(console_errors), 'mutations': dict(counts),
            'frames': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                       for frame in traceback.extract_tb(error.__traceback__)]}) + '\n')
        raise RuntimeError('SCHEDULE_MANAGEMENT_BROWSER_FAILED') from None
    finally:
        for context in reversed(contexts):
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=origin, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evidence = {'evidenceMode': 'controlled-fixture', 'productionSchedule': False, 'screens': []}
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
        raise SystemExit('SCHEDULE_MANAGEMENT_BROWSER_FAILED')


if __name__ == '__main__':
    main()
