"""HTTPS mock-login acceptance for persisted-source controlled synthesis.

Requires an isolated operator-configured controlled retrieval/synthesis fixture.
Sources must be produced by the native literature application and verified from
persisted report/bundle bytes. No external model, real retrieval, credentials,
component evidence injection or service startup is performed by this script.
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

from accept_app_recovery_browser import capture, json_get, login, lost_reply, origin, restore
from accept_material_template_browser import mutation

PREFIX = '/api/factory'
SOURCE_APPLICATION = 'public-literature-evidence-v2'


def approve_plan(reviewer, owner, goal):
    reviewer.get_by_role('button', name='方案审查', exact=True).click()
    row = reviewer.locator('article').filter(has=reviewer.get_by_role('heading', name=goal, exact=True))
    row.get_by_role('button', name='同意方案', exact=True).click()
    expect(row).to_contain_text('已同意')
    owner.get_by_role('button', name='刷新授权与审查状态', exact=True).click()
    expect(owner.get_by_role('button', name='确认方案并创建任务', exact=True)).to_be_enabled()


def prepare_source(page, reviewer, context, base, connection_ref, label):
    """Create a real native source task through original governed UI."""
    page.get_by_label('已批准的应用', exact=True).select_option(SOURCE_APPLICATION)
    page.get_by_label('应用执行方式', exact=True).select_option('bibliography')
    page.get_by_label('资源连接 publicLiterature', exact=True).select_option(connection_ref)
    goal = '受控来源证据验收，不访问真实文献服务 ' + label + ' ' + uuid4().hex[:10]
    page.get_by_label('任务目标', exact=True).fill(goal)
    proposal = mutation(page, '/compositions/proposals',
                        page.get_by_role('button', name='生成装配提案', exact=True).click)
    plan = mutation(page, '/compositions/proposals/' + proposal['id'] + '/accept',
                    page.get_by_role('button', name='接受提案并固定方案', exact=True).click)
    mutation(page, '/plan-reviews', page.get_by_role('button', name='提交方案审查', exact=True).click)
    approve_plan(reviewer, page, goal)
    task = mutation(page, '/instances', page.get_by_role('button', name='确认方案并创建任务', exact=True).click)
    expect(page.get_by_role('region', name='任务详情', exact=True).get_by_role('heading', name=goal, exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile('^执行已完成。研究结论是否通过验证：'))).to_be_visible(timeout=90000)
    detail = json_get(context, base, '/jobs/' + task['id'])
    evidence = detail['literatureEvidence']
    assert detail['job']['status'] == 'completed' and task['planId'] == plan['id']
    assert detail['snapshot']['run_id'] and detail['snapshot']['queue']['id'] == detail['snapshot']['run_id']
    assert evidence['status'] == 'ready' and evidence['sourceCount'] > 0
    assert evidence['evidenceKind'] == 'controlled_literature_fixture'
    assert evidence['bundleArtifactId'] and evidence['reportArtifactId']
    assert all(not source['fullTextAvailable'] for source in evidence['sources'])
    artifacts = {artifact['id']: artifact for artifact in detail['artifacts']}
    for identifier in (evidence['bundleArtifactId'], evidence['reportArtifactId']):
        artifact = artifacts[identifier]
        response = context.request.get(base + PREFIX + '/jobs/' + task['id'] + '/artifacts/' + identifier)
        assert response.ok
        content = response.body()
        assert len(content) == artifact['size'] and hashlib.sha256(content).hexdigest() == artifact['sha256']
    return task, detail


def verify_downloads(page, detail):
    artifacts = {artifact['name']: artifact for artifact in detail['artifacts']}
    assert {'literature-synthesis.json', 'literature-synthesis.md'} <= set(artifacts)
    for name in ('literature-synthesis.json', 'literature-synthesis.md'):
        artifact = artifacts[name]
        with page.expect_download() as pending:
            page.get_by_role('button', name='校验并下载 ' + name, exact=True).click()
        content = Path(pending.value.path()).read_bytes()
        assert len(content) == artifact['size'] and hashlib.sha256(content).hexdigest() == artifact['sha256']
        if name.endswith('.json'):
            document = json.loads(content)
            assert document['citationIntegrityVerified'] is True
            assert document['scientificConclusionVerified'] is False
            assert document['semanticReview'] == 'required'
            assert document['evidenceKind'] == 'controlled_model_synthesis'
    return [artifacts[name]['id'] for name in ('literature-synthesis.json', 'literature-synthesis.md')]


def begin_contexts(browser, base, viewport):
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
        raise RuntimeError('SYNTHESIS_BROWSER_LOGIN_FAILED') from None


def record_posts(page):
    """Finite categories only; no query, payload, header or authentication data."""
    counts = Counter()
    def observed(request):
        if request.method != 'POST':
            return
        path = urlsplit(request.url).path
        for pattern, category in (
            (r'/api/factory/instances', 'instances'),
            (r'/api/factory/synthesis/snapshots', 'snapshots'),
            (r'/api/factory/compositions/proposals', 'proposals'),
            (r'/api/factory/compositions/proposals/[^/]+/accept', 'accept'),
            (r'/api/factory/plan-reviews', 'plan-reviews'),
        ):
            if re.fullmatch(pattern, path):
                counts[category] += 1
    page.on('request', observed)
    return counts


def scenario(browser, base, output, name, viewport, *, retrieval_connection, synthesis_connection):
    contexts = begin_contexts(browser, base, viewport)
    owner, reviewer, foreign = contexts
    alice, manager, bob = [context.pages[0] for context in contexts]
    counts = record_posts(alice)
    stage = 'native-source'
    errors = []
    console_errors = []
    for page in (alice, manager, bob):
        page.on('pageerror', lambda _error: errors.append('PAGE_ERROR'))
        def console(message):
            if message.type != 'error':
                return
            path = urlsplit(message.location.get('url', '')).path
            if path == PREFIX + '/session' and '401' in message.text:
                return
            if path in {PREFIX + '/synthesis/snapshots', PREFIX + '/compositions/proposals'} and 'ERR_FAILED' in message.text:
                return
            console_errors.append({'site': 'SYNTHESIS_SOURCE_READ' if path.startswith(PREFIX + '/synthesis/sources/') else 'OTHER',
                                   'http409': '409' in message.text})
        page.on('console', console)
    try:
        source_task, source_detail = prepare_source(alice, manager, owner, base, retrieval_connection, name)
        source_goal = source_detail['job']['input']['topic']
        journey = alice.get_by_role('region', name='来源综合工作流', exact=True)
        expect(journey).to_be_visible()
        journey.get_by_role('button', name='重新核对来源与快照', exact=True).click()
        expect(journey).to_contain_text('受控')
        expect(journey).to_contain_text('全文')
        save = journey.get_by_role('button', name='确认来源并保存快照', exact=True)
        expect(save).to_be_disabled()
        selected_ids = [source_detail['literatureEvidence']['sources'][0]['sourceId']]
        for identifier in selected_ids:
            journey.get_by_label('选择来源 ' + identifier, exact=True).check()
        expect(save).to_be_disabled()
        question = '解释所选受控摘录的证据边界，不宣称科研结论 ' + name + ' ' + uuid4().hex[:10]
        journey.get_by_label('综合问题', exact=True).fill(question)
        stage = 'snapshot-lost-ack'
        # Server commits once. The UI must discover the original snapshot by GET,
        # including after refresh, rather than issue a second snapshot POST.
        snapshot = lost_reply(alice, base, '/synthesis/snapshots', save.dblclick)
        assert snapshot['sourceTaskId'] == source_task['id'] and snapshot['sourceIds'] == selected_ids
        original_ref = {'id': snapshot['id'], 'fingerprint': snapshot['fingerprint']}
        alice.reload(wait_until='domcontentloaded')
        alice.locator('button.task-row').filter(has_text=source_goal).click()
        journey = alice.get_by_role('region', name='来源综合工作流', exact=True)
        journey.get_by_role('button', name='查看快照：' + question, exact=True).click()
        sealed = journey.get_by_role('region', name='来源快照', exact=True)
        expect(sealed).to_contain_text(question)
        stored = json_get(owner, base, '/synthesis/snapshots/' + snapshot['id'])
        assert stored == snapshot
        history = json_get(owner, base, '/synthesis/snapshots?sourceTaskId=' + source_task['id'])
        assert [item['id'] for item in history['items']] == [snapshot['id']]
        capture(alice, output, name + '-snapshot-recovered')
        assert foreign.request.get(base + PREFIX + '/synthesis/snapshots/' + snapshot['id']).status == 404
        assert foreign.request.get(base + PREFIX + '/synthesis/sources/' + source_task['id']).status == 404
        stage = 'synthesis-proposal-lost-ack'
        sealed.get_by_role('button', name='用此快照准备合成方案', exact=True).click()
        alice.get_by_label('已批准的应用', exact=True).select_option('source-grounded-synthesis-fixture-v1')
        alice.get_by_label('应用执行方式', exact=True).select_option('controlled-fixture')
        alice.get_by_label('资源连接 scientificFixture', exact=True).select_option(synthesis_connection)
        expect(alice.get_by_label('任务目标', exact=True)).to_have_value(question)
        proposal = lost_reply(alice, base, '/compositions/proposals',
                              alice.get_by_role('button', name='生成装配提案', exact=True).dblclick)
        restore(alice, question)
        recovered = json_get(owner, base, '/compositions/proposals/' + proposal['id'] + '/recovery')
        assert recovered['proposal']['id'] == proposal['id'] and recovered['plan'] is None
        plan = mutation(alice, '/compositions/proposals/' + proposal['id'] + '/accept',
                        alice.get_by_role('button', name='接受提案并固定方案', exact=True).click)
        assert plan['sourceSnapshotRef'] == original_ref
        mutation(alice, '/plan-reviews', alice.get_by_role('button', name='提交方案审查', exact=True).click)
        approve_plan(manager, alice, question)
        stage = 'native-synthesis'
        task = mutation(alice, '/instances', alice.get_by_role('button', name='确认方案并创建任务', exact=True).dblclick)
        expect(alice.get_by_role('region', name='任务详情', exact=True).get_by_role('heading', name=question, exact=True)).to_be_visible()
        expect(alice.get_by_text(re.compile('^执行已完成。研究结论是否通过验证：'))).to_be_visible(timeout=90000)
        report = alice.get_by_role('region', name='来源综合报告', exact=True)
        expect(report).to_contain_text('仍需领域人员进行语义审查')
        detail = json_get(owner, base, '/jobs/' + task['id'])
        assert detail['job']['status'] == 'completed'
        assert detail['snapshot']['run_id'] and detail['snapshot']['queue']['id'] == detail['snapshot']['run_id']
        evidence = detail['synthesisEvidence']
        assert evidence['status'] == 'ready' and evidence['snapshotRef'] == original_ref
        artifact_ids = verify_downloads(alice, detail)
        capture(alice, output, name + '-synthesis-report')
        alice.reload(wait_until='domcontentloaded')
        alice.locator('button.task-row').filter(has_text=question).click()
        expect(alice.get_by_role('region', name='来源综合报告', exact=True)).to_be_visible()
        assert foreign.request.get(base + PREFIX + '/jobs/' + task['id']).status == 404
        for identifier in artifact_ids:
            assert foreign.request.get(base + PREFIX + '/jobs/' + task['id'] + '/artifacts/' + identifier).status == 404
        assert counts == {'instances': 2, 'proposals': 2, 'accept': 2, 'plan-reviews': 2, 'snapshots': 1}
        assert not errors and not console_errors
        return {'viewport': name, 'sourceTaskId': source_task['id'], 'sourceBundleVerified': True,
                'snapshotId': snapshot['id'], 'snapshotPosts': 1, 'snapshotLostAckReadOnlyRecovery': True,
                'proposalLostAckReadOnlyRecovery': True, 'sourceSnapshotPinnedInPlan': True,
                'taskId': task['id'], 'nativeSourceJobs': 1, 'nativeSynthesisJobs': 1,
                'artifactHashesVerified': True, 'crossOwnerDenied': True, 'pageErrors': 0, 'unexpectedConsoleErrors': 0,
                'evidenceMode': 'controlled-fixture', 'scientificConclusionVerified': False,
                'revocationCancelChangedSourceCoverage': 'separate PostgreSQL suite'}
    except Exception as error:
        # Keep only finite phase names. No tokens, input bodies, URLs or browser
        # exception text are written, even if failure occurred during login.
        alice.screenshot(path=str(output / (name + '-failure.png')), full_page=True)
        (output / (name + '-failure.json')).write_text(json.dumps({'stage': stage,
            'pageErrors': len(errors), 'consoleErrors': console_errors[:20], 'postCounts': dict(counts),
            'frames': [{'file': Path(frame.filename).name, 'line': frame.lineno}
                       for frame in traceback.extract_tb(error.__traceback__)]}) + '\n')
        raise RuntimeError('SYNTHESIS_JOURNEY_BROWSER_FAILED') from None
    finally:
        for context in reversed(contexts):
            context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', type=origin, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--retrieval-connection-ref', required=True)
    parser.add_argument('--synthesis-connection-ref', required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result = {'evidenceMode': 'controlled-fixture', 'liveProviderVerified': False, 'screens': []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for name, viewport in (('desktop', {'width': 1440, 'height': 1000}),
                                       ('mobile', {'width': 390, 'height': 844})):
                    result['screens'].append(scenario(browser, args.base_url, args.output_dir, name, viewport,
                        retrieval_connection=args.retrieval_connection_ref, synthesis_connection=args.synthesis_connection_ref))
            finally:
                browser.close()
        result['ok'] = True
    except Exception:
        result['ok'] = False
    (args.output_dir / 'evidence.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'ok': result['ok'], 'screens': len(result['screens'])}))
    if not result['ok']:
        raise SystemExit('SYNTHESIS_JOURNEY_BROWSER_FAILED')


if __name__ == '__main__':
    main()
