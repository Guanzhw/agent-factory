// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../web/api.js';
import { ControlRecovery } from '../web/ControlRecovery.js';
import { persistCommandPointer } from '../web/controlCommandStorage.js';
import { TaskDetail, TaskWorkspace } from '../web/TaskWorkspace.js';
import { WorkflowPanel } from '../web/WorkflowPanel.js';
import type { WorkspaceContext } from '../web/App.js';
import type { ControlReceipt, JobDetail } from '../web/models.js';
import type { WorkflowSnapshot } from '../web/workflowState.js';

let host: HTMLDivElement;
let root: Root;
const run = async (_name: string, work: () => Promise<void>) => work();
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.localStorage.clear(); window.sessionStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'controlCommands').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api.workflows, 'get').mockResolvedValue({ available: false });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });
const proof = (owner: string, task: string): ControlReceipt => ({ commandId: `command-${task}`, ownerId: owner, taskId: task,
  action: 'cancel', state: 'UNKNOWN', decisionRecorded: false, stopConfirmed: false, canDispatch: false,
  acknowledged: false, createdAt: '2026-10-29T00:00:00Z' } as ControlReceipt);
const base = (): WorkspaceContext => ({ user: { id: 'alice', name: 'Alice', role: 'user' }, route: { tab: 'tasks', task: '' },
  jobs: [], jobsLoaded: true, jobsError: '', historyError: '', historyLoading: false, nextCursor: null,
  busy: '', act: run, notice: vi.fn(), onTask: vi.fn(), loadEarlier: vi.fn(), retry: vi.fn(),
  navigate: vi.fn(), drafts: new Map() } as unknown as WorkspaceContext);
const detail = (status: string, allowedActions: string[] = []): JobDetail => ({ job: { id: 'task-one', ownerId: 'alice',
  status, input: { topic: '修复解析错误', mode: 'fixture', scenario: 'normal' }, allowedActions,
  createdAt: '2026-10-29T00:00:00Z', updatedAt: '2026-10-29T00:00:00Z' }, events: [], artifacts: [] } as unknown as JobDetail);
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find(element => element.textContent === text);
  expect(button).toBeDefined(); await act(async () => button!.click());
}

it('opens applications from a true empty task list but does not call a failed read empty', async () => {
  const context = base();
  await act(async () => root.render(createElement(TaskWorkspace, { context })));
  expect(host.querySelector('h1')?.textContent).toBe('我的任务');
  await click('去应用开始任务');
  expect(context.navigate).toHaveBeenCalledWith({ tab: 'catalog', task: '' });
  await act(async () => root.render(createElement(TaskWorkspace, { context: { ...context, jobsError: '离线' } })));
  expect(host.textContent).not.toContain('还没有任务');
  expect(host.textContent).not.toContain('尚无任务。');
  expect(host.textContent).not.toContain('去应用开始任务');
  expect(host.textContent).toContain('任务列表更新失败：离线');
});

it('keeps exact-task command recovery available even when task detail cannot be read', async () => {
  vi.mocked(api.controlCommands).mockResolvedValue({ items: [proof('alice', 'task-one')], nextCursor: null });
  const context = { ...base(), route: { tab: 'tasks', task: 'task-one' }, detailError: '记录暂不可读' };
  const onBack = vi.fn();
  await act(async () => root.render(createElement(TaskWorkspace, { context, returnToSource: { label: '原研究会话', onBack } })));
  expect(api.controlCommands).toHaveBeenCalledWith('alice', 'task-one', undefined, expect.any(AbortSignal));
  expect(host.textContent).toContain('记录暂不可读'); expect(host.textContent).toContain('本任务待核对操作');
  expect(host.textContent).toContain('提交结果未知');
  await click('返回原研究会话'); expect(onBack).toHaveBeenCalledOnce();
  await click('查看全部待核对操作'); expect(context.onTask).toHaveBeenCalledWith('');
});

it('changes command scope without showing old receipts or polling another task local pointer', async () => {
  vi.mocked(api.controlCommands).mockResolvedValue({ items: [proof('alice', 'task-one')], nextCursor: null });
  const props = { ownerId: 'alice', taskId: 'task-one', onSelect: vi.fn(), busy: '', act: run };
  await act(async () => root.render(createElement(ControlRecovery, props)));
  expect(host.textContent).toContain('command-task-one');
  await persistCommandPointer('alice', 'task-one', { action: 'cancel' });
  let resolve!: (value: { items: ControlReceipt[]; nextCursor: null }) => void;
  vi.mocked(api.controlCommands).mockImplementation(() => new Promise(done => { resolve = done; }));
  const receipt = vi.spyOn(api, 'controlReceipt');
  await act(async () => root.render(createElement(ControlRecovery, { ...props, taskId: 'task-two' })));
  expect(host.textContent).not.toContain('command-task-one');
  await act(async () => resolve({ items: [], nextCursor: null }));
  expect(receipt).not.toHaveBeenCalled();
  vi.mocked(api.controlCommands).mockResolvedValue({ items: [], nextCursor: null });
  await act(async () => root.render(createElement(ControlRecovery, { ...props, ownerId: 'bob', taskId: undefined })));
  expect(api.controlCommands).toHaveBeenLastCalledWith('bob', undefined, undefined, expect.any(AbortSignal));
  expect(receipt).not.toHaveBeenCalled();
});

it('retains a missing original receipt as unknown and never dispatches it automatically', async () => {
  const pointer = await persistCommandPointer('alice', 'task-one', { action: 'cancel' });
  vi.spyOn(api, 'controlReceipt').mockRejectedValue(new ApiError('missing', 404));
  const dispatch = vi.spyOn(api, 'dispatchControl');
  await act(async () => root.render(createElement(ControlRecovery, { ownerId: 'alice', taskId: 'task-one', onSelect: vi.fn(), busy: '', act: run })));
  expect(host.textContent).toContain('尚无服务端回执');
  expect(host.textContent).not.toContain('继续未派发请求'); expect(dispatch).not.toHaveBeenCalled();
  expect(await persistCommandPointer('alice', 'task-one', { action: 'cancel' })).toEqual(pointer);
});

it('shows failure and outcome before technical history without inventing retry, and preserves descendant stop scope', async () => {
  const value = detail('failed'); value.job.error = '测试命令退出 1';
  await act(async () => root.render(createElement(TaskDetail, { ownerId: 'alice', detail: value, busy: '', act: run,
    onNotice: vi.fn(), onSelect: vi.fn(), jobs: [], drafts: new Map() })));
  const text = host.textContent!;
  expect(text.indexOf('测试命令退出 1')).toBeLessThan(text.indexOf('证据与产物'));
  expect(text.indexOf('证据与产物')).toBeLessThan(text.indexOf('执行时间线与完整历史'));
  expect(text).toContain('尚无产物');
  expect([...host.querySelectorAll('button')].some(button => /重跑|重新执行/.test(button.textContent ?? ''))).toBe(false);
  const running = detail('running', ['cancel']);
  await act(async () => root.render(createElement(TaskDetail, { ownerId: 'alice', detail: running, busy: '', act: run,
    onNotice: vi.fn(), onSelect: vi.fn(), jobs: [], drafts: new Map() })));
  expect(host.textContent).toContain('针对本任务及其后代，不会暂停后续计划');
  expect(host.querySelector('.delegation-panel')?.closest('details')?.open).toBe(false);
});

it('keeps workflow decisions and unknown physical operations visible even after native completion', async () => {
  const workflow: WorkflowSnapshot = { schema: 2, id: 'workflow', ownerId: 'alice', taskId: 'task-one', nativeRunId: 'run',
    planId: 'plan', planSha256: 'a'.repeat(64), version: 'b'.repeat(64), status: 'completed', steps: [],
    requirements: [{ id: 'question', stepName: '输入修正', kind: 'input', fields: [] }],
    operations: [{ id: 'operation', stepId: 'step', state: 'UNKNOWN', allStopped: false }] };
  const workflowApi = { get: vi.fn().mockResolvedValue({ available: true, workflow, allowedActions: [{ action: 'decide', requirementId: 'question' }] }), command: vi.fn(), commandStatus: vi.fn() };
  await act(async () => root.render(createElement(WorkflowPanel, { ownerId: 'alice', taskId: 'task-one', api: workflowApi })));
  expect(host.querySelector('details')?.open).toBe(true);
  const input = host.querySelector('textarea'); expect(input).not.toBeNull(); expect(input?.closest('details')).toBeNull();
  expect(host.textContent).toContain('尚未确认停止');
  expect(workflowApi.command).not.toHaveBeenCalled();
});
