"""Mock-transport browser interaction checks for real workflow UI components.

Starts a temporary loopback Vite harness with WorkflowPanel and ApplicationInputs.
All API responses and execution records are synthetic; this does not verify a live
Factory, PostgreSQL, native continuation, an adapter, or a ConvertD workflow.
Only the process group created by this script is stopped. Screenshots and evidence
are written to --output-dir, never to tracked application files.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright  # type: ignore[reportMissingImports]


HARNESS = r'''
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { WorkflowPanel } from '../web/WorkflowPanel.tsx';
import { ApplicationInputs } from '../web/ApplicationInputs.tsx';
import { ApiError } from '../web/api.ts';
import '../web/styles.css';

const scenario = new URLSearchParams(location.search).get('case') || 'normal';
const taskId = `controlled-${scenario}`;
const key = `controlled-browser-harness:${scenario}`;
const fresh = () => ({
  workflow: { schema: 1, id: `workflow-${scenario}`, ownerId: 'controlled-owner', taskId,
    nativeRunId: `native-${scenario}`, planId: `plan-${scenario}`, planSha256: 'a'.repeat(64),
    definitionSha256: 'b'.repeat(64), version: 4, status: 'ACTIVE', cancelRequested: false,
    definition: { id: 'synthetic-review', revision: '1', stages: [
      { id: 'human', adapterId: 'controlled', revision: '1', dependencies: [], failureRoutes: {}, humanGate: true },
      { id: 'later', adapterId: 'controlled', revision: '1', dependencies: ['human'], failureRoutes: {}, humanGate: true },
    ] }, stages: {
      human: { state: 'HUMAN_WAIT', approved: false, operationId: null, handle: null, observation: null },
      later: { state: 'HUMAN_WAIT', approved: false, operationId: null, handle: null, observation: null },
    } }, calls: [], receipts: {}, primaryId: null, unrecordedAttempted: false,
});
let data = JSON.parse(sessionStorage.getItem(key) || 'null') || fresh();
const save = () => sessionStorage.setItem(key, JSON.stringify(data));
const copy = value => structuredClone(value);
const record = (method, body = null) => { data.calls.push({ method, body: copy(body) }); save(); };
const snapshot = () => {
  const actions = [{ action: 'cancel' }];
  for (const [id, stage] of Object.entries(data.workflow.stages)) {
    if (stage.state === 'HUMAN_WAIT') actions.push({ action: 'decide', stageId: id });
    if (stage.state === 'PENDING') actions.push({ action: 'resume', stageId: id });
    if (stage.operationId) actions.push({ action: 'reconcile', stageId: id });
  }
  return { available: true, workflow: copy(data.workflow), allowedActions: actions };
};
const api = {
  async get(task) { if (task !== taskId) throw Error('WRONG_TASK'); record('GET'); return snapshot(); },
  async commandStatus(task, id) {
    if (task !== taskId) throw Error('WRONG_TASK'); record('GET_RECEIPT', { commandId: id });
    if (!data.receipts[id]) throw new ApiError('Controlled command not recorded', 404);
    return copy(data.receipts[id]);
  },
  async command(task, command) {
    if (task !== taskId) throw Error('WRONG_TASK'); record('POST', command);
    if (data.receipts[command.commandId]) return copy(data.receipts[command.commandId]);
    if (command.action !== 'cancel' && command.version !== data.workflow.version) throw new ApiError('Controlled stale version', 409);
    const stage = data.workflow.stages[command.stageId];
    if (command.action === 'decide') {
      if (command.approved !== true) throw Error('EXPECTED_EXPLICIT_APPROVAL');
      stage.approved = true; stage.state = 'PENDING'; data.workflow.version++;
    } else if (command.action === 'resume') {
      if (scenario === 'unrecorded' && !data.unrecordedAttempted) {
        data.unrecordedAttempted = true; save(); throw new ApiError('Controlled lost transport before record', 0);
      }
      stage.state = 'UNKNOWN'; stage.operationId = 'original-controlled-operation';
      data.workflow.version++; data.primaryId = command.commandId;
      data.receipts[command.commandId] = { commandId: command.commandId, status: 'unknown', workflow: copy(data.workflow) };
      save(); return copy(data.receipts[command.commandId]);
    } else if (command.action === 'reconcile') {
      if (stage.operationId !== 'original-controlled-operation') throw Error('ORIGINAL_IDENTITY_CHANGED');
      stage.state = 'WAITING'; stage.handle = { adapterId: 'controlled', revision: '1', id: 'original-controlled-handle' };
      stage.observation = { operationId: stage.operationId, handle: copy(stage.handle), state: 'WAITING', allStopped: false, failure: null };
      // Retain the older original receipt snapshot deliberately: the UI must not
      // roll back the newer WAITING observation when reading its completed receipt.
      data.receipts[data.primaryId].status = 'completed'; data.workflow.version++;
    } else if (command.action === 'cancel') {
      if (Object.keys(command).some(k => !['commandId', 'action'].includes(k))) throw Error('CANCEL_PAYLOAD_CHANGED');
      data.workflow.cancelRequested = true; data.workflow.version++;
      data.receipts[command.commandId] = { commandId: command.commandId, status: 'recorded', workflow: copy(data.workflow) };
      save(); return copy(data.receipts[command.commandId]);
    }
    data.receipts[command.commandId] = { commandId: command.commandId, status: 'completed', workflow: copy(data.workflow) };
    save(); return copy(data.receipts[command.commandId]);
  },
};
window.__workflowFixture = { read: () => copy(data) };
const schema = { type: 'object', additionalProperties: false, required: ['question', 'count', 'confirmed'],
  title: '受控任务输入', properties: {
    question: { type: 'string', title: '研究问题', minLength: 1, maxLength: 100 },
    count: { type: 'integer', title: '样本数', minimum: 1, maximum: 4 },
    confirmed: { type: 'boolean', title: '已核对范围' },
    tags: { type: 'array', title: '标签', maxItems: 2, items: { type: 'string', maxLength: 20 } },
  } };
function Harness() {
  const [values, setValues] = useState({});
  return <main className="workspace-main"><div className="workspace-content">
    <h1>工作流组件浏览器验收</h1><p>合成 API 传输；不验证真实后端、原生执行或科研结论。</p>
    <section className="composer"><ApplicationInputs schema={schema} values={values} onChange={setValues}/>
      <output data-testid="input-values">{JSON.stringify(values)}</output></section>
    <section className="task-panel"><div className="detail-sections"><WorkflowPanel ownerId="controlled-owner" taskId={taskId} api={api}/></div></section>
  </div></main>;
}
createRoot(document.getElementById('root')).render(<Harness/>);
'''


def fixture(page):
    return page.evaluate('window.__workflowFixture.read()')


def posts(page, action=None):
    return [item['body'] for item in fixture(page)['calls']
            if item['method'] == 'POST' and (action is None or item['body']['action'] == action)]


def decision(page, stage='human'):
    return page.locator('.button-row > div').filter(has_text='决定阶段 ' + stage).get_by_role('button', name='同意本阶段', exact=True)


def wait_ready(page):
    expect(page.get_by_role('button', name='请求取消工作流', exact=True)).to_be_enabled()


def uncertain_resume(page):
    expect(decision(page)).to_be_enabled()
    decision(page).click()
    resume = page.get_by_role('button', name='继续阶段 human', exact=True)
    expect(resume).to_be_enabled(); resume.click()
    expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_be_visible()
    wait_ready(page)
    expect(decision(page, 'later')).to_be_disabled()
    approved, resumed = posts(page, 'decide')[0], posts(page, 'resume')[0]
    assert approved['version'] == 4 and approved['stageId'] == 'human' and approved['approved'] is True
    assert resumed['version'] == 5 and resumed['stageId'] == 'human'
    return resumed


def capture(page, output, name):
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'HORIZONTAL_OVERFLOW'
    page.screenshot(path=str(output / (name + '.png')), full_page=True)


def browser_checks(browser, base, output):
    context = browser.new_context(viewport={'width': 1280, 'height': 960})
    failures = []
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
    page = context.new_page(); page.on('pageerror', lambda error: failures.append(str(error)))
    try:
        page.goto(base + '/?case=normal')
        page.get_by_label('研究问题（必需）', exact=True).fill('公开合成输入')
        page.get_by_label('样本数（必需）', exact=True).fill('3')
        page.get_by_label('已核对范围（必需）', exact=True).select_option('false')
        page.get_by_label('标签（可选） JSON', exact=True).fill('["alpha","beta"]')
        values = json.loads(page.get_by_test_id('input-values').inner_text())
        assert values == {'question': '公开合成输入', 'count': 3, 'confirmed': False, 'tags': ['alpha', 'beta']}
        original = uncertain_resume(page)
        assert len(posts(page, 'resume')) == 1
        page.reload(); wait_ready(page)
        expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_be_visible()
        expect(decision(page, 'later')).to_be_disabled()
        count = len(posts(page))
        page.get_by_role('button', name='读取原命令回执', exact=True).click(); wait_ready(page)
        assert len(posts(page)) == count, 'RECEIPT_LOOKUP_REPOSTED'
        assert fixture(page)['calls'][-1]['method'] == 'GET'
        assert any(item['method'] == 'GET_RECEIPT' and item['body']['commandId'] == original['commandId'] for item in fixture(page)['calls'])
        page.get_by_role('button', name='核对原执行 human', exact=True).click(); wait_ready(page)
        reconciled = posts(page, 'reconcile')[-1]
        assert reconciled['version'] == 6 and reconciled['stageId'] == 'human'
        expect(page.get_by_text('等待外部事件', exact=True)).to_be_visible()
        page.get_by_role('button', name='读取原命令回执', exact=True).click(); wait_ready(page)
        expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_have_count(0)
        expect(decision(page, 'later')).to_be_enabled()
        expect(page.get_by_text('等待外部事件', exact=True)).to_be_visible()
        assert len(posts(page, 'resume')) == 1, 'UNKNOWN_EXECUTION_REPLAYED'
        capture(page, output, 'desktop-recovered')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_text('输入结构与范围（JSON）', exact=True).click()
        capture(page, output, 'mobile-recovered')
        normal_calls = fixture(page)['calls']

        page.goto(base + '/?case=cancel')
        uncertain_resume(page)
        page.get_by_role('button', name='请求取消工作流', exact=True).click(); wait_ready(page)
        assert len(posts(page, 'cancel')) == 1
        assert set(posts(page, 'cancel')[0]) == {'commandId', 'action'}
        expect(page.get_by_text('已记录取消请求。', exact=False)).to_be_visible()
        expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_be_visible()
        expect(page.get_by_text('本阶段执行已确认停止。', exact=True)).to_have_count(0)
        expect(page.get_by_text('工作流已取消', exact=True)).to_have_count(0)
        capture(page, output, 'mobile-pending-cancel')
        cancel_calls = fixture(page)['calls']

        page.goto(base + '/?case=unrecorded')
        unrecorded = uncertain_resume(page)
        expect(page.get_by_role('button', name='提交同一原命令', exact=True)).to_have_count(0)
        page.get_by_role('button', name='读取原命令回执', exact=True).click(); wait_ready(page)
        replay = page.get_by_role('button', name='提交同一原命令', exact=True)
        expect(replay).to_be_enabled(); assert len(posts(page, 'resume')) == 1
        replay.click(); wait_ready(page)
        assert posts(page, 'resume') == [unrecorded, unrecorded], 'RETRY_CHANGED_ORIGINAL_INTENT'
        assert not failures, failures
        return {'ok': True, 'inputValuesPreserved': values, 'humanVersionVerified': True,
                'reconcileVersionVerified': True, 'unknownReceiptGetRecovery': True,
                'pendingSurvivedReload': True, 'pendingCancelAllowed': True,
                'cancelNotPromotedToStopped': True, 'explicit404RetrySameIntent': True,
                'olderReceiptDidNotRegressSnapshot': True, 'mobileHorizontalOverflow': False,
                'normalCalls': normal_calls, 'cancelCalls': cancel_calls,
                'unrecordedCalls': fixture(page)['calls'], 'pageErrors': failures}
    except Exception:
        page.screenshot(path=str(output / 'failure.png'), full_page=True)
        (output / 'failure-state.json').write_text(json.dumps({'fixture': fixture(page), 'pageErrors': failures,
            'overflow': page.evaluate('document.documentElement.scrollWidth > window.innerWidth')}, indent=2) + '\n')
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    if (output / 'evidence.json').exists():
        raise ValueError('Use a fresh evidence directory')
    repo = Path(__file__).resolve().parents[1]
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    base = 'http://127.0.0.1:' + str(port)
    evidence = {'evidenceMode': 'mock-transport-browser-interaction', 'liveBackendVerified': False,
                'nativeExecutionVerified': False, 'realConvertDVerified': False}
    with tempfile.TemporaryDirectory(prefix='.workflow-browser-', dir=repo) as temporary:
        root = Path(temporary)
        (root / 'index.html').write_text('<!doctype html><html lang="zh"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script type="module" src="/harness.tsx"></script></html>')
        (root / 'harness.tsx').write_text(HARNESS)
        (root / 'vite.config.mjs').write_text("import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\nexport default defineConfig({plugins:[react()],root:" + json.dumps(str(root)) + ",server:{host:'127.0.0.1',strictPort:true,fs:{allow:[" + json.dumps(str(repo)) + "]}}});\n")
        with (output / 'vite.log').open('w') as log:
            server = subprocess.Popen(['node', str(repo / 'node_modules/vite/bin/vite.js'), '--config', str(root / 'vite.config.mjs'), '--port', str(port)],
                                      cwd=repo, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 20
                while True:
                    if server.poll() is not None:
                        raise RuntimeError('Temporary Vite harness exited')
                    try:
                        with urlopen(base, timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Temporary Vite harness did not become ready')
                    time.sleep(0.1)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        evidence.update(browser_checks(browser, base, output))
                    finally:
                        browser.close()
            except Exception as error:
                evidence.update(ok=False, failureType=type(error).__name__, failure=str(error)[:2000])
            finally:
                if server.poll() is None:
                    if os.name == 'posix':
                        os.killpg(server.pid, signal.SIGTERM)
                    else:
                        server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == 'posix':
                            os.killpg(server.pid, signal.SIGKILL)
                        else:
                            server.kill()
                        server.wait(timeout=5)
    evidence['temporaryServerStopped'] = server.poll() is not None
    (output / 'evidence.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: evidence[key] for key in ('ok', 'evidenceMode', 'temporaryServerStopped')}))
    if not evidence['ok']:
        raise SystemExit('WORKFLOW_BROWSER_INTERACTION_FAILED')


if __name__ == '__main__':
    main()
