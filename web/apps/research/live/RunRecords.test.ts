// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RunRecords } from './RunRecords.js';
import * as runs from './runs.js';
let host: HTMLDivElement; let root: Root;
const onTask = vi.fn();
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); onTask.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('keeps UNKNOWN operation and missing decision distinct from runtime completion', async () => {
  vi.spyOn(runs, 'readResearchRuns').mockResolvedValue({ items: [{ id: 'experiment', projectId: 'p', goalVersion: 1, hypothesis: '比较两种采样', conditions: { seed: 11 }, attempts: [{ id: 'attempt', operationId: 'operation-original', operation: { id: 'operation-original', closed: false, observation: { state: 'UNKNOWN' } } }] }], rounds: [{ id: 'round', goalVersion: 1, taskId: 'task-original', terminalRecordId: null, decision: null, terminal: { verificationStatus: 'unverified', runtime: [{ taskId: 'task-original', runId: null, status: 'completed' }], continuationBlocked: null, sharing: 'published' } }] });
  await act(async () => root.render(createElement(RunRecords, { ownerId: 'alice', projectId: 'p', evidence: true, onTask })));
  expect(host.textContent).toContain('UNKNOWN'); expect(host.textContent).toContain('尚无助手研究决策'); expect(host.textContent).not.toContain('助手判断达标');
  const button = [...host.querySelectorAll('button')].find(item => item.textContent === '查看原任务与产物')!;
  await act(async () => button.click()); expect(onTask).toHaveBeenCalledWith('task-original');
  expect(host.textContent).not.toContain('重新启动');
});
it('shows a met decision as agent analysis with original evidence references', async () => {
  vi.spyOn(runs, 'readResearchRuns').mockResolvedValue({ items: [], rounds: [{ id: 'r', goalVersion: 2, taskId: null, terminalRecordId: 'record-1', terminal: null, decision: { action: 'stop', outcome: 'met', reason: '根据原始观察提出判断', evidenceIds: ['operation-2'], sourceAssessments: [{ contentId: 'peer-source', disposition: 'reproduce', reason: '核对不同实验条件' }] } }] });
  await act(async () => root.render(createElement(RunRecords, { ownerId: 'alice', projectId: 'p', evidence: true, onTask })));
  expect(host.textContent).toContain('Agent 分析 · 尚未独立验证'); expect(host.textContent).toContain('operation-2'); expect(host.textContent).toContain('独立复现：核对不同实验条件'); expect(host.textContent).toContain('record-1'); expect(host.textContent).toContain('尚未取得终态记录');
});

it('preserves the original operation when its observation is null', async () => {
  vi.spyOn(runs, 'readResearchRuns').mockResolvedValue({ items: [{ id: 'experiment', projectId: 'p', goalVersion: 1, hypothesis: '等待原观察', conditions: {}, attempts: [{ id: 'attempt', operationId: 'operation-unobserved', operation: { id: 'operation-unobserved', closed: false, observation: null } }] }], rounds: [] });
  await act(async () => root.render(createElement(RunRecords, { ownerId: 'alice', projectId: 'p', evidence: true, onTask })));
  expect(host.textContent).toContain('operation-unobserved');
  expect(host.textContent).toContain('UNKNOWN');
  expect(host.textContent).toContain('尚未确认');
  expect([...host.querySelectorAll('button')].map(button => button.textContent)).toEqual(['核对原运行记录']);
  expect(onTask).not.toHaveBeenCalled();
});
it('renders protected source projections without rich fields or artifact entry points', async () => {
  vi.spyOn(runs, 'readResearchRuns').mockResolvedValue({ items: [{ id: 'experiment', projectId: 'p', goalVersion: 1, sourceUnavailable: true, attempts: [{ id: 'attempt', operationId: 'original-operation' }] }], rounds: [{ id: 'round', goalVersion: 1, taskId: 'original-task', terminalRecordId: 'record', sourceUnavailable: true, decision: null, terminal: { state: 'ended' } }] });
  await act(async () => root.render(createElement(RunRecords, { ownerId: 'alice', projectId: 'p', evidence: true, onTask })));
  expect(host.textContent).toContain('来源不可用'); expect(host.textContent).toContain('original-operation'); expect(host.textContent).toContain('不是新的资源停止证明'); expect(host.textContent).not.toContain('查看原任务与产物'); expect(onTask).not.toHaveBeenCalled();
});
