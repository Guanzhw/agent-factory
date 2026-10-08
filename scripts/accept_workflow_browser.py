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
  workflow: { schema: 2, id: `workflow-${scenario}`, ownerId: 'controlled-owner', taskId,
    nativeRunId: `native-${scenario}`, planId: `plan-${scenario}`, planSha256: 'a'.repeat(64),
    version: '4'.repeat(64), status: 'paused',
    steps: [{id:'human',name:'human',status:'paused'},{id:'later',name:'later',status:'pending'}],
    requirements: [{id:'requirement-human',stepName:'human',kind:scenario==='input'?'input':'confirmation',fields:scenario==='input'?[{name:'answer',type:'str',required:true}]:[]},
      {id:'requirement-later',stepName:'later',kind:'confirmation'}], operations: [] },
  calls: [], receipts: {}, primaryId: null, unrecordedAttempted: false,
});
let data = JSON.parse(sessionStorage.getItem(key) || 'null') || fresh();
const save = () => sessionStorage.setItem(key, JSON.stringify(data));
const copy = value => structuredClone(value);
const record = (method, body = null) => { data.calls.push({ method, body: copy(body) }); save(); };
const snapshot = () => ({available:true,workflow:copy(data.workflow),allowedActions:[{action:'cancel'},
  ...data.workflow.requirements.map(item=>({action:'decide',requirementId:item.id})),
  ...data.workflow.operations.map(item=>({action:'reconcile',operationId:item.id}))]});
const api = {
  async get(task) { if (task !== taskId) throw Error('WRONG_TASK'); record('GET'); return snapshot(); },
  async commandStatus(task,id) {
    if(task!==taskId)throw Error('WRONG_TASK'); record('GET_RECEIPT',{commandId:id});
    if(!data.receipts[id])throw new ApiError('Controlled command not recorded',404);
    return copy(data.receipts[id]);
  },
  async command(task,command) {
    if(task!==taskId)throw Error('WRONG_TASK'); record('POST',command);
    if(data.receipts[command.commandId])return copy(data.receipts[command.commandId]);
    if(command.action!=='cancel'&&command.version!==data.workflow.version)throw new ApiError('Controlled stale version',409);
    if(command.action==='decide') {
      if(command.requirementId!=='requirement-human'||(scenario==='input'?command.values?.answer!=='公开合成答复':command.approved!==true))throw Error('EXPECTED_ORIGINAL_DECISION');
      if(scenario==='unrecorded'&&!data.unrecordedAttempted){data.unrecordedAttempted=true;save();throw new ApiError('Controlled lost transport before record',0);}
      data.workflow.requirements=data.workflow.requirements.filter(item=>item.id!==command.requirementId);
      data.workflow.operations=[{id:'original-controlled-operation',stepId:'human',state:'UNKNOWN',allStopped:false}];
      data.workflow.version='5'.repeat(64);data.primaryId=command.commandId;
      data.receipts[command.commandId]={commandId:command.commandId,status:'unknown',workflow:copy(data.workflow)};
      save();return copy(data.receipts[command.commandId]);
    } else if(command.action==='reconcile') {
      if(command.operationId!=='original-controlled-operation')throw Error('ORIGINAL_IDENTITY_CHANGED');
      data.workflow.operations[0].state='WAITING';data.workflow.version='6'.repeat(64);
      // Deliberately retain the historical UNKNOWN snapshot in the receipt.
      data.receipts[data.primaryId].status='completed';
    } else if(command.action==='cancel') {
      if(Object.keys(command).some(k=>!['commandId','action'].includes(k)))throw Error('CANCEL_PAYLOAD_CHANGED');
      data.workflow.status='cancelled';data.workflow.version='7'.repeat(64);
      data.receipts[command.commandId]={commandId:command.commandId,status:'recorded',workflow:copy(data.workflow)};
      save();return copy(data.receipts[command.commandId]);
    }
    data.receipts[command.commandId]={commandId:command.commandId,status:'completed',workflow:copy(data.workflow)};
    save();return copy(data.receipts[command.commandId]);
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


def decision(page, step='human'):
    return page.locator('.button-row > div').filter(has_text='确认：' + step).get_by_role('button', name='同意', exact=True)


def wait_ready(page):
    expect(page.get_by_role('button', name='请求取消原工作流', exact=True)).to_be_enabled()


def uncertain_decision(page):
    expect(decision(page)).to_be_enabled()
    decision(page).click()
    expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_be_visible()
    wait_ready(page)
    expect(decision(page, 'later')).to_be_disabled()
    command = posts(page, 'decide')[0]
    assert command['version'] == '4' * 64 and command['requirementId'] == 'requirement-human' and command['approved'] is True
    return command


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
        original = uncertain_decision(page)
        assert len(posts(page, 'decide')) == 1
        page.reload(); wait_ready(page)
        expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_be_visible()
        expect(decision(page, 'later')).to_be_disabled()
        count = len(posts(page))
        page.get_by_role('button', name='读取原命令回执', exact=True).click(); wait_ready(page)
        assert len(posts(page)) == count, 'RECEIPT_LOOKUP_REPOSTED'
        assert fixture(page)['calls'][-1]['method'] == 'GET'
        assert any(item['method'] == 'GET_RECEIPT' and item['body']['commandId'] == original['commandId'] for item in fixture(page)['calls'])
        page.get_by_role('button', name='核对原操作 original-controlled-operation', exact=True).click(); wait_ready(page)
        reconciled = posts(page, 'reconcile')[-1]
        assert reconciled['version'] == '5' * 64 and reconciled['operationId'] == 'original-controlled-operation'
        expect(page.get_by_text('human：等待中；尚未确认停止', exact=True)).to_be_visible()
        page.get_by_role('button', name='读取原命令回执', exact=True).click(); wait_ready(page)
        expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_have_count(0)
        expect(decision(page, 'later')).to_be_enabled()
        expect(page.get_by_text('human：等待中；尚未确认停止', exact=True)).to_be_visible()
        assert len(posts(page, 'decide')) == 1, 'UNKNOWN_EXECUTION_REPLAYED'
        capture(page, output, 'desktop-recovered')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_text('输入结构与范围（JSON）', exact=True).click()
        capture(page, output, 'mobile-recovered')
        normal_calls = fixture(page)['calls']

        page.goto(base + '/?case=cancel')
        uncertain_decision(page)
        page.get_by_role('button', name='请求取消原工作流', exact=True).click(); wait_ready(page)
        assert len(posts(page, 'cancel')) == 1
        assert set(posts(page, 'cancel')[0]) == {'commandId', 'action'}
        expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_have_count(2)
        expect(page.get_by_text('human：状态待核对；尚未确认停止', exact=True)).to_be_visible()
        expect(page.get_by_text('运行状态：已取消', exact=True)).to_be_visible()
        page.reload(); wait_ready(page)
        expect(page.get_by_role('button', name='读取原命令回执', exact=True)).to_have_count(2)
        capture(page, output, 'mobile-pending-cancel')
        cancel_calls = fixture(page)['calls']

        page.goto(base + '/?case=unrecorded')
        unrecorded = uncertain_decision(page)
        expect(page.get_by_role('button', name='提交同一原命令', exact=True)).to_have_count(0)
        page.get_by_role('button', name='读取原命令回执', exact=True).click(); wait_ready(page)
        replay = page.get_by_role('button', name='提交同一原命令', exact=True)
        expect(replay).to_be_enabled(); assert len(posts(page, 'decide')) == 1
        replay.click(); wait_ready(page)
        assert posts(page, 'decide') == [unrecorded, unrecorded], 'RETRY_CHANGED_ORIGINAL_INTENT'
        unrecorded_calls = fixture(page)['calls']
        page.goto(base + '/?case=input')
        page.get_by_label('human 输入（JSON）', exact=True).fill('{"answer":"公开合成答复","confirmed":false}')
        page.get_by_role('button', name='提交原要求的输入', exact=True).click(); wait_ready(page)
        input_command = posts(page, 'decide')[0]
        assert input_command['requirementId'] == 'requirement-human'
        assert input_command['values'] == {'answer': '公开合成答复', 'confirmed': False}
        assert 'approved' not in input_command
        assert not failures, failures
        return {'ok': True, 'inputValuesPreserved': values, 'humanVersionVerified': True,
                'reconcileVersionVerified': True, 'unknownReceiptGetRecovery': True,
                'pendingSurvivedReload': True, 'pendingCancelAllowed': True, 'nativeRequirementInputsPreserved': True,
                'cancelNotPromotedToStopped': True, 'explicit404RetrySameIntent': True,
                'olderReceiptDidNotRegressSnapshot': True, 'mobileHorizontalOverflow': False,
                'normalCalls': normal_calls, 'cancelCalls': cancel_calls,
                'unrecordedCalls': unrecorded_calls, 'inputCalls': fixture(page)['calls'], 'pageErrors': failures}
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
    parser.add_argument('--chromium-executable', type=Path, help='Existing operator-selected Chromium binary; never downloaded.')
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
                    browser = playwright.chromium.launch(headless=True,
                        executable_path=str(args.chromium_executable.resolve(strict=True)) if args.chromium_executable else None)
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
