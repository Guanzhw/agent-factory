"""Actual browser acceptance for fixed synthetic comparison workflows.

Use an isolated mock-login HTTPS Factory and real task-owned native process
fixtures. An offline comparison assessment alone is not execution proof. Failed,
cancelled and unknown runs must remain inconclusive, with original identities
preserved; no route response fakes or production providers are used here.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import traceback
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from accept_app_recovery_browser import capture, json_get, login, lost_reply, restore, origin
from accept_material_template_browser import mutation

PREFIX = '/api/factory'


def contexts_for(browser, base, viewport):
    contexts = []
    try:
        for persona in ('alice', 'manager2', 'bob'):
            context = browser.new_context(ignore_https_errors=True, viewport=viewport, accept_downloads=True)
            contexts.append(context)
            page = context.new_page()
            page.set_default_timeout(20000)
            login(page, base, persona)
        return contexts
    except Exception:
        for context in reversed(contexts):
            context.close()
        raise RuntimeError('COMPARISON_BROWSER_LOGIN_FAILED') from None


def observe_mutations(page):
    counts = Counter()
    def observe(request):
        if request.method != 'POST':
            return
        path = urlsplit(request.url).path
        for pattern, category in (
            (r'/api/factory/compositions/proposals', 'proposal'),
            (r'/api/factory/compositions/proposals/[^/]+/accept', 'accept'),
            (r'/api/factory/plan-reviews', 'review'),
            (r'/api/factory/instances', 'instance'),
        ):
            if re.fullmatch(pattern, path):
                counts[category] += 1
    page.on('request', observe)
    return counts


def reviewed_plan(page, reviewer, context, base, goal):
    """Lose proposal ACK, recover it read-only, then review its immutable plan."""
    proposal = lost_reply(page, base, '/compositions/proposals',
                          page.get_by_role('button', name='生成装配提案', exact=True).dblclick)
    restore(page, goal)
    original = json_get(context, base, '/compositions/proposals/' + proposal['id'] + '/recovery')
    assert original['proposal']['id'] == proposal['id'] and original['plan'] is None
    plan = mutation(page, '/compositions/proposals/' + proposal['id'] + '/accept',
                    page.get_by_role('button', name='接受提案并固定方案', exact=True).click)
    mutation(page, '/plan-reviews', page.get_by_role('button', name='提交方案审查', exact=True).click)
    reviewer.get_by_role('button', name='方案审查', exact=True).click()
    row = reviewer.locator('article').filter(has_text=plan['id'])
    row.get_by_role('button', name='同意方案', exact=True).click()
    expect(row).to_contain_text('已同意')
    page.get_by_role('button', name='刷新授权与审查状态', exact=True).click()
    expect(page.get_by_role('button', name='确认方案并创建任务', exact=True)).to_be_enabled()
    return plan


def verify_original_identity(detail, task, plan):
    """Native run identity is necessary, but never sufficient for result success."""
    assert detail['job']['id'] == task['id'] and detail['job']['ownerId'] == 'alice'
    assert detail['job']['planId'] == plan['id']
    snapshot = detail['snapshot']
    assert snapshot['run_id'] and snapshot['queue']['id'] == snapshot['run_id']
    assert snapshot['planFingerprint'] == plan['fingerprint']


def download_verified(page, artifact):
    with page.expect_download() as pending:
        page.get_by_role('button', name='校验并下载 ' + artifact['name'], exact=True).click()
    content = Path(pending.value.path()).read_bytes()
    assert len(content) == artifact['size']
    assert hashlib.sha256(content).hexdigest() == artifact['sha256']
    return content


def cross_owner_denied(foreign, base, task_id, artifact_ids):
    assert foreign.request.get(base + PREFIX + '/jobs/' + task_id).status == 404
    for identifier in artifact_ids:
        assert foreign.request.get(base + PREFIX + '/jobs/' + task_id + '/artifacts/' + identifier).status == 404


def original_task_after_refresh(page, goal):
    page.reload(wait_until='domcontentloaded')
    page.locator('button.task-row').filter(has_text=goal).first.click()
    expect(page.get_by_role('region', name='任务详情', exact=True).get_by_role('heading', name=goal, exact=True)).to_be_visible()


def scenario(browser, base, output, name, viewport, *, choice='linear-v1', original_check=None):
    contexts = contexts_for(browser, base, viewport)
    owner, reviewer, foreign = contexts
    alice, manager, bob = [context.pages[0] for context in contexts]
    counts = observe_mutations(alice)
    stage = 'fixed-selection'
    page_errors, console_errors = [], []
    for page in (alice, manager, bob):
        page.on('pageerror', lambda _error: page_errors.append('PAGE_ERROR'))
        def console(message):
            if message.type != 'error':
                return
            path = urlsplit(message.location.get('url', '')).path
            if path == PREFIX + '/session' and '401' in message.text:
                return
            if path in {PREFIX + '/compositions/proposals', PREFIX + '/instances'} and 'ERR_FAILED' in message.text:
                return
            console_errors.append('CONSOLE_ERROR')
        page.on('console', console)
    try:
        alice.get_by_role('button', name='基线候选比较', exact=True).click()
        panel = alice.get_by_role('region', name='受控基线候选比较', exact=True)
        catalog = json_get(owner, base, '/comparisons/catalog')
        item = next(item for item in catalog['items'] if item['mode'] == choice)
        ref = item['applicationRef']
        key = f"{ref['id']}@{ref['version']}:{ref['sha256']}:{choice}"
        panel.get_by_label('比较候选', exact=True).select_option(key)
        for text in ('合成开发数据', '固定数据集', '固定评估器', '允许修改的文件', '固定运行边界'):
            expect(panel).to_contain_text(text)
        capture(alice, output, name + '-fixed-inputs')
        panel.get_by_role('button', name='用此比较准备方案', exact=True).click()
        goal = alice.get_by_label('任务目标', exact=True).input_value()
        assert goal == item['goal']
        expect(alice.get_by_label('任务目标', exact=True)).to_be_disabled()
        stage = 'proposal-and-independent-review'
        plan = reviewed_plan(alice, manager, owner, base, goal)
        assert plan['applicationRef'] == ref and plan['mode'] == choice
        stage = 'native-instance'
        create = alice.get_by_role('button', name='确认方案并创建任务', exact=True)
        # Existing instantiate recovery reads /requests/<original key>; no second POST.
        task = lost_reply(alice, base, '/instances', create.dblclick)
        expect(alice.get_by_role('region', name='任务详情', exact=True)).to_contain_text(task['id'])
        report = alice.get_by_role('region', name='基线候选比较证据', exact=True)
        expect(report).to_contain_text('原执行与产物已核对', timeout=90000)
        expect(alice.get_by_text(re.compile('^执行已完成。研究结论是否通过验证：'))).to_be_visible(timeout=20000)
        detail = json_get(owner, base, '/jobs/' + task['id'])
        verify_original_identity(detail, task, plan)
        evidence = detail['comparisonEvidence']
        assert evidence['status'] == 'ready' and evidence['executionVerified'] is True
        assert evidence['scientificConclusionVerified'] is False
        assert evidence['taskId'] == task['id'] and evidence['planId'] == plan['id']
        assert evidence['nativeRunId'] == detail['snapshot']['run_id']
        process = evidence['process']
        assert process['allStopped'] is True and process['capacityHeld'] is False
        assert process['executionStatus'] == 'COMPLETED' and process['exitCode'] == 0
        if choice == 'failure-v1':
            assert evidence['assessment']['status'] == 'inconclusive'
            assert evidence['candidate']['status'] == 'failed' and evidence['candidate']['value'] is None
            expect(report).to_contain_text('工作流产物已核对不代表双方评估成功')
            expect(report.get_by_role('heading', name='候选指标改善', exact=True)).to_have_count(0)
        else:
            assert evidence['assessment']['status'] == 'improved'
            assert evidence['baseline']['value'] > evidence['candidate']['value']
            expect(report.get_by_role('heading', name='候选指标改善', exact=True)).to_be_visible()
        if original_check is not None:
            original_check(task, plan, evidence)
        artifact_ids = []
        for artifact in detail['artifacts']:
            if artifact['name'] in {'comparison-output.json', 'comparison-report.json'}:
                content = download_verified(alice, artifact)
                artifact_ids.append(artifact['id'])
                if artifact['name'] == 'comparison-report.json':
                    document = json.loads(content)
                    assert document['taskId'] == task['id'] and document['planId'] == plan['id']
                    assert document['process']['providerJobId'] == process['providerJobId']
                    assert document['assessment'] == evidence['assessment']
        assert len(artifact_ids) == 2
        capture(alice, output, name + '-comparison-report')
        stage = 'refresh-and-isolation'
        original_task_after_refresh(alice, goal)
        expect(alice.get_by_role('region', name='任务详情', exact=True)).to_contain_text(task['id'])
        current = json_get(owner, base, '/jobs/' + task['id'])
        assert current['comparisonEvidence'] == evidence
        cross_owner_denied(foreign, base, task['id'], artifact_ids)
        assert counts == {'proposal': 1, 'accept': 1, 'review': 1, 'instance': 1}
        assert not page_errors and not console_errors
        return {'scenario': name, 'choice': choice, 'evidenceMode': 'controlled-fixture',
                'taskId': task['id'], 'planId': plan['id'], 'nativeRunId': evidence['nativeRunId'],
                'leaseId': process['leaseId'], 'providerJobId': process['providerJobId'],
                'assessment': evidence['assessment']['status'], 'executionVerified': True,
                'scientificConclusionVerified': False, 'proposalLostAckReadOnlyRecovered': True,
                'instanceLostAckReadOnlyRecovered': True, 'instancePosts': 1,
                'originalProcessIdentityVerified': original_check is not None,
                'reportBytesAndHashesVerified': True, 'reloadPreservedIdentity': True,
                'crossOwnerDenied': True, 'pageErrors': 0, 'unexpectedConsoleErrors': 0,
                'cancelUnknownCoverage': 'separate native PostgreSQL and pure UI tests'}
    except Exception as error:
        alice.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
        (output / (name + '-failure.json')).write_text(json.dumps({'stage': stage,
            'mutations': dict(counts), 'pageErrors': len(page_errors), 'consoleErrors': len(console_errors),
            'frames': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                       for frame in traceback.extract_tb(error.__traceback__)]}) + '\n')
        raise RuntimeError('COMPARISON_BROWSER_FAILED') from None
    finally:
        for context in reversed(contexts):
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=origin, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evidence = {'evidenceMode': 'controlled-fixture', 'liveProviderVerified': False, 'scenarios': []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for screen, viewport in (('desktop', {'width': 1440, 'height': 1000}),
                                         ('mobile', {'width': 390, 'height': 844})):
                    for choice in ('linear-v1', 'failure-v1'):
                        evidence['scenarios'].append(scenario(browser, args.base_url, args.output_dir,
                            screen + '-' + choice, viewport, choice=choice))
            finally:
                browser.close()
        evidence['ok'] = True
    except Exception:
        evidence['ok'] = False
    (args.output_dir / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'ok': evidence['ok'], 'scenarios': len(evidence['scenarios'])}))
    if not evidence['ok']:
        raise SystemExit('COMPARISON_BROWSER_FAILED')


if __name__ == '__main__':
    main()
