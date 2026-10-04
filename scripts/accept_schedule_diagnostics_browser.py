"""Read-only schedule diagnostics acceptance against isolated mock-login HTTPS.

Fixture preparation may call the real native scheduling admission service with
controlled claims. Those actions are never represented as a production timer or
UI trigger. Diagnostics must come from persisted admission records; this harness
never fabricates API responses or stores browser credentials/traces.
"""
import argparse
from collections import Counter
from pathlib import Path
import traceback
from urllib.parse import urlsplit
from uuid import uuid4
import json

from playwright.sync_api import expect, sync_playwright

from accept_app_recovery_browser import capture, json_get, origin
from accept_schedule_management_browser import (
    CREATE_CRON, TIMEZONE, approved_plan, change, contexts_for, preview,
)

PREFIX = '/api/factory'


def create_paused_schedule(page, reviewer, label):
    """Only normal UI controls create the reviewed immutable-plan schedule."""
    plan, _goal = approved_plan(page, reviewer, label)
    page.get_by_role('button', name='用此已批准方案设置计划任务', exact=True).click()
    panel = page.get_by_role('region', name='计划任务', exact=True)
    schedule_name = '计划拒绝诊断 ' + label + ' ' + uuid4().hex[:10]
    panel.get_by_label('计划任务名称', exact=True).fill(schedule_name)
    panel.get_by_label('Cron表达式', exact=True).fill(CREATE_CRON)
    panel.get_by_label('IANA时区', exact=True).fill(TIMEZONE)
    preview(panel)
    schedule = change(page, '/schedule-management',
                      panel.get_by_role('button', name='保存计划任务', exact=True).click)
    assert schedule['enabled'] is False
    assert schedule['planId'] == plan['id']
    assert schedule['planFingerprint'] == plan['fingerprint']
    return schedule


def read_phase_mutations(page):
    """Observe every mutation after preparation, including unexpected replay."""
    counts = Counter()
    def observe(request):
        path = urlsplit(request.url).path
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and path.startswith(PREFIX + '/'):
            # Only finite categories enter evidence; no URL/query/body is saved.
            if path == PREFIX + '/instances':
                category = 'instances'
            elif path.startswith(PREFIX + '/schedules/') and path.endswith('/trigger'):
                category = 'trigger'
            elif path.startswith(PREFIX + '/schedule-management'):
                category = 'schedule-write'
            else:
                category = 'other-write'
            counts[category] += 1
    page.on('request', observe)
    return counts, observe


def read_only_history(context, base, schedule_id):
    result = json_get(context, base, '/schedule-management/' + schedule_id + '/occurrences')
    assert result['items'] == []
    return result


def safe_failure(output, name, stage, error, counts):
    """Keep only finite stages and source locations, never exception messages."""
    (Path(output) / (name + '-failure.json')).write_text(json.dumps({
        'stage': stage, 'mutations': dict(counts),
        'frames': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                   for frame in traceback.extract_tb(error.__traceback__)],
    }) + '\n')


REASON_LABELS = {'CLOCK_BUSY': '执行时间变更或调度锁正在占用',
    'AUTHORIZATION_DENIED': '当前执行权限未通过检查', 'CLAIM_CHANGED': '原调度领取状态已变化',
    'BINDING_UNAVAILABLE': '原计划绑定无法核对', 'PAUSED': '计划已暂停',
    'DEFINITION_CHANGED': '计划定义已变化', 'PLAN_UNAVAILABLE': '原不可变方案无法使用',
    'CHECK_UNAVAILABLE': '前置检查暂时无法完成'}


REASONS = frozenset({'CLOCK_BUSY', 'AUTHORIZATION_DENIED', 'CLAIM_CHANGED',
    'BINDING_UNAVAILABLE', 'PAUSED', 'DEFINITION_CHANGED', 'PLAN_UNAVAILABLE',
    'CHECK_UNAVAILABLE'})


def diagnostics(context, base, schedule_id):
    result = json_get(context, base, '/schedule-management/' + schedule_id + '/diagnostics')
    assert set(result) == {'schema', 'ownerId', 'scheduleId', 'items', 'nextCursor',
                           'retention', 'coverage', 'snapshot'}
    assert result['schema'] == 1 and result['ownerId'] == 'manager'
    assert result['scheduleId'] == schedule_id and result['snapshot'] is False
    assert result['coverage'] == 'retained-rejections-only'
    assert result['retention'] == {'days': 30, 'maxRecords': 100}
    for item in result['items']:
        assert set(item) == {'id', 'ownerId', 'scheduleId', 'reasonCode', 'source', 'observedAt'}
        assert item['ownerId'] == 'manager' and item['scheduleId'] == schedule_id
        assert item['reasonCode'] in REASONS and item['source'] in {'native', 'manual'}
        assert isinstance(item['observedAt'], str) and item['observedAt']
    assert len({item['id'] for item in result['items']}) == len(result['items'])
    return result


def scenario(browser, base, output, name, viewport, *, prepare=None, schedule_id=None):
    """prepare is an isolated-fixture callback, never a production API endpoint.

    It receives the UI-created schedule and returns evidence of real persisted
    admission refusals; it must never submit a successful native occurrence.
    Without it, the CLI verifies a previously prepared synthetic schedule only.
    """
    contexts = contexts_for(browser, base, viewport)
    owner, reviewer, foreign = contexts
    page, review_page, bob = [context.pages[0] for context in contexts]
    stage, counts, observer = 'fixture-preparation', Counter(), None
    page_errors, console_errors = [], []
    page.on('pageerror', lambda _error: page_errors.append('PAGE_ERROR'))
    def console(message):
        if message.type == 'error':
            console_errors.append('CONSOLE_ERROR')
    page.on('console', console)
    try:
        fixture_evidence = None
        if prepare is not None:
            schedule = create_paused_schedule(page, review_page, name)
            schedule_id = schedule['id']
            fixture_evidence = prepare(schedule)
            assert fixture_evidence['method'] == 'controlled-native-admission-not-ui-timer'
            assert fixture_evidence['tasksCreated'] == 0
        assert schedule_id
        stage = 'read-only-diagnostics'
        before = diagnostics(owner, base, schedule_id)
        assert before['items'], 'Prepared fixture must contain actual persisted refusals'
        if fixture_evidence is not None:
            assert {item['reasonCode'] for item in before['items']} == set(fixture_evidence['reasonCodes'])
        history = read_only_history(owner, base, schedule_id)
        counts, observer = read_phase_mutations(page)
        page.get_by_role('button', name='计划任务', exact=True).click()
        panel = page.get_by_role('region', name='计划触发拒绝诊断', exact=True)
        expect(panel).to_be_visible()
        select_diagnostic_schedule(panel, schedule_id)
        expect(panel.get_by_label('诊断保留范围', exact=True)).to_contain_text('不是完整触发历史或实时快照')
        expect(panel.locator('article')).to_have_count(len(before['items']))
        for item in before['items']:
            expect(panel.get_by_role('heading', name=REASON_LABELS[item['reasonCode']], exact=True)).to_be_visible()
        expect(panel).not_to_contain_text('UNTRUSTED_PROVIDER_DETAIL_TEST_ONLY')
        assert panel.get_by_role('button', name='重新执行', exact=True).count() == 0
        for _ in range(3):
            with page.expect_response(lambda response: response.request.method == 'GET'
                and urlsplit(response.url).path == PREFIX + '/schedule-management/' + schedule_id + '/diagnostics'):
                panel.get_by_role('button', name='刷新拒绝诊断', exact=True).click()
            assert diagnostics(owner, base, schedule_id) == before
            assert read_only_history(owner, base, schedule_id) == history
        capture(page, output, name + '-retained-diagnostics')
        stage = 'reload-and-isolation'
        page.reload(wait_until='domcontentloaded')
        page.get_by_role('button', name='计划任务', exact=True).click()
        select_diagnostic_schedule(panel, schedule_id)
        expect(panel.get_by_label('诊断保留范围', exact=True)).to_be_visible()
        assert diagnostics(owner, base, schedule_id) == before
        assert read_only_history(owner, base, schedule_id) == history
        response = foreign.request.get(base + PREFIX + '/schedule-management/' + schedule_id + '/diagnostics')
        assert response.status == 404
        foreign_catalog = json_get(foreign, base, '/schedule-management/diagnostic-schedules')
        assert all(item['id'] != schedule_id for item in foreign_catalog['items'])
        capture(page, output, name + '-reloaded-diagnostics')
        assert not counts and not page_errors and not console_errors
        return {'viewport': name, 'scheduleId': schedule_id, 'evidenceMode': 'controlled-fixture',
            'diagnosticIds': [item['id'] for item in before['items']],
            'reasonCodes': sorted({item['reasonCode'] for item in before['items']}),
            'preparation': fixture_evidence, 'readOnlyRefreshCount': 3, 'reloadPreservedIds': True,
            'historyEmpty': True, 'mutationsAfterPreparation': 0, 'crossOwnerDenied': True,
            'retention': before['retention'], 'snapshot': False, 'pageErrors': 0,
            'unexpectedConsoleErrors': 0}
    except Exception as error:
        page.screenshot(path=str(Path(output) / (name + '-failure.png')), full_page=True)
        safe_failure(output, name, stage, error, counts)
        raise RuntimeError('SCHEDULE_DIAGNOSTICS_BROWSER_FAILED') from None
    finally:
        if observer is not None:
            page.remove_listener('request', observer)
        for context in reversed(contexts):
            context.close()


def select_diagnostic_schedule(panel, schedule_id):
    refresh = panel.get_by_role('button', name='刷新诊断计划', exact=True)
    expect(refresh).to_be_enabled()
    with panel.page.expect_response(lambda response: response.request.method == 'GET'
        and urlsplit(response.url).path == PREFIX + '/schedule-management/diagnostic-schedules'):
        refresh.click()
    panel.get_by_label('选择诊断计划', exact=True).select_option(schedule_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=origin, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--schedule-id', required=True,
                        help='Existing controlled fixture schedule with real retained refusals')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evidence = {'evidenceMode': 'controlled-fixture', 'productionSchedule': False, 'screens': []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for name, viewport in (('desktop', {'width': 1440, 'height': 1000}),
                                       ('mobile', {'width': 390, 'height': 844})):
                    evidence['screens'].append(scenario(browser, args.base_url, args.output_dir,
                        name, viewport, schedule_id=args.schedule_id))
            finally:
                browser.close()
        evidence['ok'] = True
    except Exception:
        evidence['ok'] = False
    (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'ok': evidence['ok'], 'screens': len(evidence['screens'])}))
    if not evidence['ok']:
        raise SystemExit('SCHEDULE_DIAGNOSTICS_BROWSER_FAILED')


if __name__ == '__main__':
    main()
